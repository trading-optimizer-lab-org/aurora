"""TradeZero paper bot: v58's book DS0.20-NS0.60-RU0.25-N5 on the paper account (docs/research/PAPER_BOT_SPEC.md).

  open    08:00-09:28 New York: DS1/RU signals on the last session's daily bars, a live locate quote per name
          (cancelled, never accepted), sell limits at 1.20 x that close; NS cover limits at 0.70 x entry
  close   15:30-15:57 New York: reconcile the day's fills, NS signals at 15:50 on IEX, at 15:55 market covers that
          are due and market shorts for NS
  report  the ledger
Sized on a virtual $5,000. Orders go only to the paper keys; the live keys only quote locates. State stays in the
Actions cache; the public log shows counts only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tz_locate_meter as M  # noqa: E402

NY = M.NY
DATA = "https://data.alpaca.markets"
ALPACA = ("https://api.alpaca.markets", "https://paper-api.alpaca.markets")
EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "NYSEARCA", "BATS"}
STATE = Path(os.environ.get("TZPAPER_DIR", "outputs/tzpaper")) / "state.json"
EQUITY0 = 5000.0
SIZE = {"DS1": 0.20, "RU": 0.25, "NS": 0.60}
ORDER = ("DS1", "RU", "NS")  # tie-break of the ranking
NEW_MAX, OPEN_MAX, GROSS_MAX, ONCE = 5, 20, 2.0, 20
RISE, LIMIT_UP, HOLD_RUN = 3.0, 1.20, 9  # run-up >= 300%; entry limit; closes after the entry day's close
GAP, DROP, LOW_PART, HOLD_NS, TARGET_NS = 0.30, 0.10, 0.25, 3, 0.70
DV_MIN, DV_CAP, FLOOR = 1e6, 0.01, 2.50
QUOTES_PER_RUN = 5
WINDOWS = {"open": (8 * 60, 9 * 60 + 28), "close": (15 * 60 + 25, 15 * 60 + 57)}
WORKING = {"PendingNew", "New", "Accepted", "PartiallyFilled", "PendingCancel"}


# ---------------------------------------------------------------- state

def empty() -> dict:
    return {"realized": 0.0, "locate_cost": 0.0, "open": [], "pending": [], "fired": {m: {} for m in ORDER},
            "runs": {}, "events": []}


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else empty()


def save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")
    (STATE.parent / "changed").write_text("1", encoding="utf-8")


def event(st: dict, kind: str, **kw) -> None:
    st["events"].append({"at": datetime.now(NY).isoformat(timespec="seconds"), "kind": kind, **kw})


def equity(st: dict, last: dict[str, float]) -> float:
    """Virtual equity: $5,000 plus realized P&L, minus locate costs, plus the shorts' open P&L at ``last``."""
    u = sum((p["entry"] - last.get(p["sym"], p["entry"])) * p["qty"] for p in st["open"])
    return EQUITY0 + st["realized"] - st["locate_cost"] + u


# ---------------------------------------------------------------- sessions and data (Alpaca free)

class Alpaca:
    def __init__(self, http=requests):
        self.h = {"APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
                  "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]}
        self.http = http
        self.base = next((b for b in ALPACA if self._ok(b)), ALPACA[0])

    def _ok(self, b: str) -> bool:
        try:
            return self.http.get(f"{b}/v2/account", headers=self.h, timeout=15).ok
        except requests.RequestException:
            return False

    def get(self, url: str, params: dict) -> dict | list:
        for attempt in range(4):
            r = self.http.get(url, headers=self.h, params=params, timeout=60)
            if r.status_code != 429 and r.status_code < 500:
                r.raise_for_status()
                return r.json()
            time.sleep(3.0 * (attempt + 1))
        r.raise_for_status()
        return {}

    def sessions(self, today: date) -> list[str]:
        cal = self.get(f"{self.base}/v2/calendar", {"start": f"{today - timedelta(days=60)}",
                                                     "end": f"{today + timedelta(days=40)}"})
        return [c["date"] for c in cal]

    def universe(self) -> list[str]:
        a = self.get(f"{self.base}/v2/assets", {"status": "active", "asset_class": "us_equity"})
        return sorted(x["symbol"] for x in a if x.get("tradable") and x.get("exchange") in EXCHANGES
                      and x["symbol"].isalpha() and not (len(x["symbol"]) == 5 and x["symbol"][-1] in "WRU"))

    def daily(self, syms: list[str], start: str, end: str) -> dict[str, list[dict]]:
        """Split-adjusted daily bars (consolidated tape, free when older than 15 minutes)."""
        out: dict[str, list[dict]] = {}
        for i in range(0, len(syms), 500):
            p = {"symbols": ",".join(syms[i:i + 500]), "timeframe": "1Day", "start": start, "end": end,
                 "adjustment": "split", "feed": "sip", "limit": 10000}
            while True:
                d = self.get(f"{DATA}/v2/stocks/bars", p)
                for s, bars in (d.get("bars") or {}).items():
                    out.setdefault(s, []).extend(bars)
                if not d.get("next_page_token"):
                    break
                p["page_token"] = d["next_page_token"]
        return out

    def snapshots(self, syms: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(syms), 200):
            out.update(self.get(f"{DATA}/v2/stocks/snapshots", {"symbols": ",".join(syms[i:i + 200]),
                                                                  "feed": "iex"}) or {})
        return out


# ---------------------------------------------------------------- signals (run_v19/v20 picks for 2026)

def dv20(bars: list[dict]) -> float:
    last = bars[-20:]
    return sum(b["c"] * b["v"] for b in last) / len(last) if last else 0.0


def runup(bars: list[dict], day: str) -> float | None:
    """DS1/RU on the session ``day``: its close over the lowest of the 5 closes before it, minus 1, when >= 3."""
    if not bars or bars[-1]["t"][:10] != day or len(bars) < 3:
        return None
    c = bars[-1]["c"]
    low = min(b["c"] for b in bars[-6:-1])
    if not (1.0 <= c <= 20.0) or c < FLOOR or dv20(bars) < DV_MIN or low <= 0:
        return None
    if bars[-1]["l"] <= 0.9 * bars[-2]["c"]:  # SSR on the entry day
        return None
    rise = c / low - 1
    return rise if rise >= RISE else None


def nightshort(prev_close: float, o: float, h: float, lo: float, px: float, dv: float) -> float | None:
    """NS at 15:50: gap >= 30% at the open, price 10% under the open, in the bottom quarter of the range, $2.50-5."""
    if prev_close <= 0 or dv < DV_MIN or not (FLOOR <= px <= 5.0):
        return None
    if o < prev_close * (1 + GAP) or px > o * (1 - DROP) or (px - lo) > LOW_PART * (h - lo):
        return None
    return o / prev_close - 1


def recent(st: dict, member: str, sym: str, sessions: list[str], today: str) -> bool:
    d = st["fired"][member].get(sym)
    return d is not None and d in sessions and today in sessions and sessions.index(today) - sessions.index(d) < ONCE


def shares(frac: float, eq: float, dv1: float, price: float) -> int:
    return int(math.floor(min(frac * eq, DV_CAP * dv1) / price)) if price > 0 else 0


def room(st: dict, eq: float, last: dict[str, float], today: str) -> tuple[int, float]:
    """(new names left today, gross short notional left)."""
    new_today = sum(1 for e in st["events"] if e["kind"] == "entry" and e.get("day") == today)
    gross = sum(p["qty"] * last.get(p["sym"], p["entry"]) for p in st["open"])
    slots = min(NEW_MAX - new_today, OPEN_MAX - len(st["open"]))
    return max(0, slots), max(0.0, GROSS_MAX * eq - gross)


# ---------------------------------------------------------------- TradeZero

class Broker:
    """Orders on the paper account only."""

    def __init__(self, tz: M.TZ):
        self.tz = tz
        self.acct = next(a["account"] for a in tz.get("/v1/api/accounts")["accounts"]
                         if tz.get(f"/v1/api/account/{a['account']}").get("accountType") == "Paper")

    def order(self, sym: str, side: str, oc: str, qty: int, kind: str, tif: str, limit: float | None = None) -> dict:
        cid = f"pb-{uuid.uuid4().hex[:12]}"
        body = {"securityType": "Stock", "symbol": sym, "side": side, "openClose": oc, "orderType": kind,
                "orderQuantity": int(qty), "timeInForce": tif, "clientOrderId": cid}
        if limit is not None:
            body["limitPrice"] = round(limit, 2 if limit >= 1 else 4)
        r = self.tz.post(f"/v1/api/accounts/{self.acct}/order", body)
        return {"cid": cid, "status": r.get("orderStatus"), "text": r.get("text")}

    def orders(self) -> dict[str, dict]:
        return {o["clientOrderId"]: o for o in self.tz.get(f"/v1/api/accounts/{self.acct}/orders").get("orders", [])}

    def cancel(self, cid: str) -> None:
        self.tz.delete(f"/v1/api/accounts/{self.acct}/orders/{cid}")


def locate(live: M.TZ | None, acct: str | None, sym: str, qty: int) -> tuple[bool, float, dict]:
    """(can short, locate dollars, record). Paper has no locates: the live account quotes and cancels."""
    if live is None or acct is None:
        return False, 0.0, {"outcome": "no live keys"}
    try:
        m = M.measure(live, acct, sym, qty)
    except requests.RequestException as e:
        return False, 0.0, {"outcome": "error", **M.why(e, "etb", acct)}
    if m["outcome"] == "easy to borrow":
        return True, 0.0, m
    if m["outcome"] != "offered":
        return False, 0.0, m
    prices = [float(r["locatePrice"]) for r in m["rows"] if r.get("locatePrice")]
    return True, (min(prices) if prices else 0.0) * qty, m


def reconcile(st: dict, br: Broker, sessions: list[str], today: str) -> None:
    """Apply today's fills of the orders the bot placed; drop orders that are no longer working."""
    book = br.orders()
    keep = []
    for p in st["pending"]:
        o = book.get(p["cid"])
        if o is None:
            if p["day"] == today:
                keep.append(p)  # not visible yet
            continue
        done = int(o.get("executed") or 0) - p.get("applied", 0)
        if done > 0:
            apply_fill(st, p, done, float(o["priceAvg"]), sessions)
            p["applied"] = p.get("applied", 0) + done
        if o.get("orderStatus") in WORKING:
            keep.append(p)
        elif o.get("orderStatus") == "Rejected":
            event(st, "rejected", sym=p["sym"], member=p["member"], what=p["what"], text=o.get("text"))
    st["pending"] = keep


def apply_fill(st: dict, p: dict, qty: int, px: float, sessions: list[str]) -> None:
    if p["what"] == "entry":
        i = sessions.index(p["day"])
        hold = HOLD_NS if p["member"] == "NS" else HOLD_RUN
        due = sessions[min(i + hold, len(sessions) - 1)]
        pos = next((x for x in st["open"] if x["sym"] == p["sym"] and x["day"] == p["day"]), None)
        if pos is None:
            st["open"].append({"sym": p["sym"], "member": p["member"], "qty": qty, "entry": px, "day": p["day"],
                               "due": due})
        else:  # a later part of the same order: priceAvg is the average of all its fills so far
            pos["qty"], pos["entry"] = pos["qty"] + qty, px
        st["locate_cost"] += p.get("loc", 0.0) * qty / max(p["qty"], 1)
        event(st, "entry", day=p["day"], sym=p["sym"], member=p["member"], qty=qty, px=px)
        return
    pos = next((x for x in st["open"] if x["sym"] == p["sym"]), None)
    if pos is None:
        return
    q = min(qty, pos["qty"])
    st["realized"] += (pos["entry"] - px) * q
    pos["qty"] -= q
    event(st, "exit", day=p["day"], sym=p["sym"], member=pos["member"], qty=q, px=px, why=p["what"])
    if pos["qty"] <= 0:
        st["open"].remove(pos)


# ---------------------------------------------------------------- runs

def place_entries(st: dict, br: Broker, live, lacct, cands: list[tuple], today: str, eq: float,
                  last: dict[str, float], kind: str) -> int:
    """cands: (prio, member order, member, sym, price, dv1, limit or None). Returns orders placed."""
    slots, gross_left = room(st, eq, last, today)
    held = {p["sym"] for p in st["open"]} | {p["sym"] for p in st["pending"]}
    placed = quotes = 0
    tried: set[str] = set()
    for prio, _, member, sym, px, dv1, lim in sorted(cands, key=lambda c: (-c[0], c[1])):
        if placed >= slots or quotes >= QUOTES_PER_RUN:
            break
        if sym in held or sym in tried:
            continue
        tried.add(sym)
        q = shares(SIZE[member], eq, dv1, lim or px)
        if q < 1 or q * (lim or px) > gross_left:
            continue
        quotes += 1
        ok, cost, rec = locate(live, lacct, sym, q)
        event(st, "locate", day=today, sym=sym, member=member, qty=q, ok=ok, cost=cost, outcome=rec.get("outcome"))
        if not ok:
            continue
        o = br.order(sym, "Sell", "Open", q, kind, "Day", lim)
        st["fired"][member][sym] = today
        if o["status"] == "Rejected":
            event(st, "rejected", sym=sym, member=member, what="entry", text=o["text"])
            continue
        st["pending"].append({"cid": o["cid"], "sym": sym, "member": member, "what": "entry", "qty": q,
                              "day": today, "loc": cost})
        held.add(sym)
        gross_left -= q * (lim or px)
        placed += 1
    return placed


def run_open(st: dict, al: Alpaca, br: Broker, live, lacct, sessions: list[str], today: str) -> str:
    prev = sessions[sessions.index(today) - 1]
    uni = al.universe()
    bars = al.daily(uni, sessions[sessions.index(today) - 30], prev)
    last = {s: b[-1]["c"] for s, b in bars.items() if b}
    eq = equity(st, last)
    cands = []
    for s, b in bars.items():
        r = runup(b, prev)
        if r is None:
            continue
        dv1 = b[-1]["c"] * b[-1]["v"]
        for k, m in enumerate(("DS1", "RU")):
            if not recent(st, m, s, sessions, today):
                cands.append((r, k, m, s, b[-1]["c"], dv1, b[-1]["c"] * LIMIT_UP))
    n = place_entries(st, br, live, lacct, cands, today, eq, last, "Limit")
    for p in st["open"]:  # NS cover at 0.70 x entry, from the session after the entry
        if p["member"] == "NS" and p["day"] != today:
            o = br.order(p["sym"], "Buy", "Close", p["qty"], "Limit", "Day", p["entry"] * TARGET_NS)
            st["pending"].append({"cid": o["cid"], "sym": p["sym"], "member": "NS", "what": "target",
                                  "qty": p["qty"], "day": today})
    return f"open: {len(cands)} DS1/RU signals, {n} sell limits placed, {len(st['open'])} open positions"


def wait_until(hh: int, mm: int) -> None:
    while (now := datetime.now(NY)).hour * 60 + now.minute < hh * 60 + mm:
        time.sleep(5)


def run_close(st: dict, al: Alpaca, br: Broker, live, lacct, sessions: list[str], today: str) -> str:
    reconcile(st, br, sessions, today)
    prev = sessions[sessions.index(today) - 1]
    uni = al.universe()
    bars = al.daily(uni, sessions[sessions.index(today) - 30], prev)
    pre = [s for s, b in bars.items() if b and b[-1]["t"][:10] == prev and b[-1]["c"] <= 20.0 and dv20(b) >= DV_MIN]
    wait_until(15, 50)
    snap = al.snapshots(sorted(set(pre) | {p["sym"] for p in st["open"]}))
    last = {s: float((v.get("latestTrade") or {}).get("p") or 0) for s, v in snap.items()}
    last = {s: x for s, x in last.items() if x > 0}
    eq = equity(st, last)
    cands = []
    for s in pre:
        d, px = (snap.get(s) or {}).get("dailyBar") or {}, last.get(s, 0.0)
        if not d or (snap[s].get("dailyBar") or {}).get("t", "")[:10] != today:
            continue
        g = nightshort(bars[s][-1]["c"], d["o"], max(d["h"], px), min(d["l"], px), px, dv20(bars[s]))
        if g is not None and not recent(st, "NS", s, sessions, today):
            cands.append((g, 2, "NS", s, px, bars[s][-1]["c"] * bars[s][-1]["v"], None))
    wait_until(15, 55)
    due = [p for p in st["open"] if p["due"] <= today]
    for p in due:  # a working cover limit would block the market cover
        for q in [x for x in st["pending"] if x["sym"] == p["sym"] and x["what"] == "target"]:
            br.cancel(q["cid"])
    if due:
        time.sleep(3)
        reconcile(st, br, sessions, today)
    for p in [p for p in st["open"] if p["due"] <= today]:
        o = br.order(p["sym"], "Buy", "Close", p["qty"], "Market", "Day")
        st["pending"].append({"cid": o["cid"], "sym": p["sym"], "member": p["member"], "what": "time",
                              "qty": p["qty"], "day": today})
    n = place_entries(st, br, live, lacct, cands, today, eq, last, "Market")
    for _ in range(24):  # the market orders fill in seconds; the day's limits stay as they are
        time.sleep(5)
        reconcile(st, br, sessions, today)
        if not any(p["what"] in ("time", "entry") and p["day"] == today and p.get("applied", 0) < p["qty"]
                   and p["sym"] in {c[3] for c in cands} | {d["sym"] for d in due} for p in st["pending"]):
            break
    wait_until(16, 1)  # sell limits from the open can still fill in the last minutes
    reconcile(st, br, sessions, today)
    return f"close: {len(due)} time covers, {len(cands)} NS signals, {n} NS shorts sent, {len(st['open'])} open"


def report(st: dict, money: bool = False) -> str:
    """Counts for the public log; with ``money`` also the dollars (encrypted artifact only)."""
    ev = st["events"]
    n = {k: sum(1 for e in ev if e["kind"] == k) for k in ("locate", "entry", "exit", "rejected")}
    no_loc = sum(1 for e in ev if e["kind"] == "locate" and not e["ok"])
    out = (f"{n['entry']} entries, {n['exit']} exits, {n['locate']} locate checks ({no_loc} not available), "
           f"{n['rejected']} rejected, {len(st['open'])} open")
    if money:
        out += (f"; virtual equity at entry prices ${equity(st, {}):,.0f}, realized ${st['realized']:,.0f}, "
                f"locate cost ${st['locate_cost']:,.0f}")
    return out


class DryBroker:
    def order(self, *a, **k) -> dict:
        raise AssertionError("a dry run places no order")

    def orders(self) -> dict:
        return {}


def dry(mode: str, now: datetime) -> int:
    """Signals of the latest session as if it were today: checks the data path end to end. Prints counts only."""
    global wait_until
    al = Alpaca()
    sessions = al.sessions(now.date())
    today = max(d for d in sessions if d <= f"{now:%Y-%m-%d}")
    wait_until = lambda hh, mm: None  # noqa: E731
    st = empty()
    run = run_open if mode == "open" else run_close  # close: the IEX snapshot is the session's end, not 15:50
    print(run(st, al, DryBroker(), None, None, sessions, today))
    print(report(st))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("open", "close", "report"))
    ap.add_argument("--force", action="store_true", help="run outside the time window (tests)")
    ap.add_argument("--dry", action="store_true", help="last session's signals only: no orders, no quotes, no state")
    a = ap.parse_args()
    st = load()
    if a.mode == "report":
        print(report(st, money=True))
        return 0
    now = datetime.now(NY)
    today = f"{now:%Y-%m-%d}"
    lo, hi = WINDOWS[a.mode]
    if not (a.force or a.dry) and not (lo <= now.hour * 60 + now.minute <= hi):
        print(f"{a.mode}: outside its window at {now:%H:%M} New York")
        return 0
    if a.dry:
        return dry(a.mode, now)
    if st["runs"].get(a.mode) == today:
        print(f"{a.mode}: already ran today")
        return 0
    al = Alpaca()
    sessions = al.sessions(now.date())
    if today not in sessions:
        print("not a trading session")
        return 0
    br = Broker(M.TZ(os.environ["TZ_PAPER_KEY_ID"], os.environ["TZ_PAPER_SECRET_KEY"]))
    live = lacct = None
    if os.environ.get("TZ_API_KEY_ID"):
        live = M.TZ(os.environ["TZ_API_KEY_ID"], os.environ["TZ_API_SECRET_KEY"])
        lacct = M.live_account(live)
    st["runs"][a.mode] = today
    save(st)  # a second cron in the same window must not run the day twice
    try:
        msg = (run_open if a.mode == "open" else run_close)(st, al, br, live, lacct, sessions, today)
    finally:
        save(st)
    print(msg)
    print(report(st))
    return 0


if __name__ == "__main__":
    sys.exit(main())
