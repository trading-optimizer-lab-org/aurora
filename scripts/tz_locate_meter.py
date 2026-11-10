"""TradeZero locate meter: how often TradeZero can lend the stocks the book would short, and at what price.

Twice a trading day (09:45-10:30 and 15:15-15:55 New York) it takes the day's top gainers from Alpaca's free
screener and the prior session's gainers, asks TradeZero for a locate quote on each one, records whether shares
were offered and at what price, and cancels the quote. It never accepts a locate, so it never pays for one.
Records stay in the Actions cache; only aggregates are printed.

  run     measure now (skips outside the windows unless --force)
  report  the aggregates of the stored records
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = "https://webapi.tradezero.com"
DATA = "https://data.alpaca.markets"
NY = ZoneInfo("America/New_York")
WINDOWS = {"open": (9 * 60 + 45, 10 * 60 + 30), "close": (15 * 60 + 15, 15 * 60 + 55)}
NOTIONAL, MIN_PRICE, TOP = float(os.environ.get("TZLOC_NOTIONAL") or 500), 0.50, 50
DONE = {50, 52, 56, 65, 67}  # filled, canceled, rejected, offered, expired
POLLS = 10
BUCKETS = (("prior day gainer", None), ("up 100%+", 100), ("up 50-100%", 50), ("up 20-50%", 20), ("up <20%", -1e9))


class TZ:
    """The few TradeZero calls the meter needs. There is deliberately no accept call."""

    def __init__(self, key: str, secret: str, http=requests, sleep=time.sleep):
        self.h = {"Accept": "application/json", "Content-Type": "application/json",
                  "TZ-API-KEY-ID": key, "TZ-API-SECRET-KEY": secret}
        self.http, self.sleep = http, sleep

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        assert "/accept" not in path, "the meter never accepts a locate"
        for attempt in range(3):
            r = getattr(self.http, method)(BASE + path, headers=self.h, json=body, timeout=15)
            # a quote POST is not retried on 5xx: it may have been created, and a retry would send a second one
            if r.status_code != 429 and (r.status_code < 500 or method == "post"):
                r.raise_for_status()
                return r.json() if r.content else {}
            self.sleep(2.0 * (attempt + 1))
        r.raise_for_status()
        return {}

    def get(self, path: str) -> dict:
        return self._call("get", path)

    def post(self, path: str, body: dict) -> dict:
        return self._call("post", path, body)

    def delete(self, path: str) -> dict:
        return self._call("delete", path)


def live_account(tz: TZ) -> str | None:
    for a in tz.get("/v1/api/accounts").get("accounts", []):
        if tz.get(f"/v1/api/account/{a['account']}").get("accountType") != "Paper":
            return a["account"]
    return None


def outcome(rows: list[dict]) -> str:
    st = [r.get("locateStatus") for r in rows]
    if not rows:
        return "no answer"
    if 50 in st:
        return "FILLED"  # never expected: the meter has no accept call
    if 65 in st or any(r.get("locateStatus") == 67 and r.get("locatePrice") for r in rows):
        return "offered"
    if 56 in st:
        return "rejected"
    if 67 in st:
        return "expired"
    return "no shares"


def measure(tz: TZ, acct: str, sym: str, qty: int) -> dict:
    """Easy-to-borrow check, then a locate quote that is cancelled (or left to expire), never accepted."""
    if tz.get(f"/v1/api/accounts/{acct}/is-easy-to-borrow/symbol/{sym}").get("isEasyToBorrow"):
        return {"outcome": "easy to borrow", "rows": []}
    qid = f"m-{uuid.uuid4().hex[:16]}"
    rows: dict = {}
    try:
        tz.post("/v1/api/accounts/locates/quote", {"account": acct, "symbol": sym, "quantity": qty, "quoteReqID": qid})
        for i in range(POLLS):
            tz.sleep(1.0)
            hist = tz.get(f"/v1/api/accounts/{acct}/locates/history").get("locateHistory", [])
            rows = {r["quoteReqID"]: r for r in hist if r.get("quoteReqID") in (qid, qid + ".SU")}
            # a Single Use row can appear after the regular one is final: wait a few polls for it
            if rows and all(r.get("locateStatus") in DONE for r in rows.values()) and (len(rows) == 2 or i >= 3):
                break
    except requests.RequestException as e:  # the quote may exist without an answer: cancel it blindly
        for q in (qid, qid + ".SU"):
            try:
                tz.delete(f"/v1/api/accounts/locates/cancel/accounts/{acct}/quoteReqID/{q}")
            except requests.RequestException:
                pass
        return {"outcome": "error", "rows": [], "error": type(e).__name__, "qid": qid, "cancel": "blind"}
    keep = [{k: r.get(k) for k in ("quoteReqID", "locateStatus", "locateType", "locatePrice", "locateError", "text")}
            for r in rows.values()]
    out: dict = {"outcome": outcome(keep), "rows": keep, "qid": qid}
    live0 = [q for q, r in rows.items() if r.get("locateStatus") in (54, 65)]
    if live0:
        for q in live0:  # the Single Use offer has its own id: cancelling the regular one leaves it open
            try:
                tz.delete(f"/v1/api/accounts/locates/cancel/accounts/{acct}/quoteReqID/{q}")
            except requests.RequestException as e:
                out.setdefault("cancel_errors", []).append(f"{q[-3:]}:{type(e).__name__}")
        out["cancel"] = "unconfirmed"
        for _ in range(POLLS):  # the cancel is asynchronous: only history confirms it
            tz.sleep(1.0)
            hist = tz.get(f"/v1/api/accounts/{acct}/locates/history").get("locateHistory", [])
            live = [r for r in hist if r.get("quoteReqID") in rows and r.get("locateStatus") in (54, 65)]
            if not live:
                out["cancel"] = "confirmed"
                break
    return out


def check_nothing_filled(tz: TZ, acct: str, qids: set[str]) -> None:
    hist = tz.get(f"/v1/api/accounts/{acct}/locates/history").get("locateHistory", [])
    bad = [r for r in hist if str(r.get("quoteReqID", "")).removesuffix(".SU") in qids and r.get("locateStatus") == 50]
    if bad:
        raise SystemExit(f"{len(bad)} meter quotes show as filled: check the TradeZero portal now")


# ---------------------------------------------------------------- candidates (Alpaca free data)

def shortable(sym: str, price: float) -> bool:
    return price >= MIN_PRICE and sym.isalpha() and not (len(sym) == 5 and sym[-1] in "WRU")


def session_day(movers: dict) -> str:
    """New York date of the screener's last update: Alpaca stamps it in UTC, a day ahead after 19:00 New York."""
    try:
        utc = datetime.fromisoformat(str(movers.get("last_updated", ""))[:19]).replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return f"{utc.astimezone(NY):%Y-%m-%d}"


def candidates(get, today: str, prior: list[str]) -> list[dict] | None:
    """Today's top gainers and the prior session's; None when the screener is not on today's session."""
    m = get(f"{DATA}/v1beta1/screener/stocks/movers", {"top": TOP})
    if session_day(m) != today:
        return None
    out = [{"symbol": g["symbol"], "price": float(g["price"]), "pct": float(g["percent_change"]), "src": "today"}
           for g in m.get("gainers", [])]
    seen = {c["symbol"] for c in out}
    old = [s for s in dict.fromkeys(prior) if s not in seen]
    if old:
        snap = get(f"{DATA}/v2/stocks/snapshots", {"symbols": ",".join(old), "feed": "iex"})
        for s in old:
            p = ((snap.get(s) or {}).get("latestTrade") or {}).get("p")
            if p:
                out.append({"symbol": s, "price": float(p), "pct": None, "src": "prior"})
    return [c for c in out if shortable(c["symbol"], c["price"])]


def quantity(price: float) -> int:
    return max(100, int(math.ceil(NOTIONAL / price / 100.0)) * 100)


# ---------------------------------------------------------------- store and report

def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def bucket(r: dict) -> str:
    if r["src"] == "prior":
        return BUCKETS[0][0]
    return next(name for name, lo in BUCKETS[1:] if r["pct"] >= lo)


def report(recs: list[dict]) -> str:
    other = sum(r.get("notional", 2_000.0) != NOTIONAL for r in recs)  # records before this field were $2,000
    recs = [r for r in recs if r.get("notional", 2_000.0) == NOTIONAL]
    L = ["# TradeZero locate meter", "",
         f"{len({r['date'] for r in recs})} sessions, {len(recs)} quotes. Quote size: about ${NOTIONAL:,.0f} of "
         "stock, at least 100 shares. Price: cost per share of the cheapest offered row, as a share of the stock "
         "price.", "",
         "| window | group | quotes | easy to borrow | offered | no shares | rejected | expired | no answer | errors | "
         "median price |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for slot in WINDOWS:
        for name, _ in BUCKETS:
            g = [r for r in recs if r["slot"] == slot and bucket(r) == name]
            if not g:
                continue
            n = len(g)
            c = {k: sum(r["outcome"] == k for r in g) for k in ("easy to borrow", "offered", "no shares", "rejected",
                                    "expired", "no answer")}
            err = sum(r["outcome"] == "error" for r in g)
            px = [min(x["locatePrice"] for x in r["rows"] if x.get("locateStatus") in (50, 65) and x.get("locatePrice"))
                  / r["price"] for r in g if r["outcome"] == "offered"
                  and any(x.get("locatePrice") for x in r["rows"] if x.get("locateStatus") in (50, 65))]
            med = f"{statistics.median(px):.2%}" if px else "-"
            L.append(f"| {slot} | {name} | {n} | " + " | ".join(f"{c[k] / n:.0%}" for k in c)
                     + f" | {err / n:.0%} | {med} |")
    forced = sum(r["slot"] not in WINDOWS for r in recs)
    open_ = sum(r.get("cancel") == "unconfirmed" for r in recs)
    L += ["", f"Forced quotes outside the windows, left out of the table: {forced}. "
          f"Cancels not confirmed by history, left to expire after 30 s: {open_}. "
          f"Quotes at another size, left out: {other}."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- commands

def slot_of(now: datetime) -> str | None:
    m = now.hour * 60 + now.minute
    return next((k for k, (a, b) in WINDOWS.items() if a <= m < b), None)


def _alpaca_get(url: str, params: dict) -> dict:
    h = {"APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]}
    r = requests.get(url, headers=h, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def cmd_run(args) -> int:
    now = datetime.now(NY)
    slot = slot_of(now) or ("forced" if args.force else None)
    if slot is None or now.weekday() >= 5:
        print(f"outside the measuring windows ({now:%a %H:%M} New York): nothing to do", flush=True)
        return 0
    key, secret = os.environ.get("TZ_API_KEY_ID"), os.environ.get("TZ_API_SECRET_KEY")
    if not key or not secret:
        print("TradeZero keys are not set yet (secrets TZ_API_KEY_ID, TZ_API_SECRET_KEY): nothing to do", flush=True)
        return 0
    today = f"{now:%Y-%m-%d}"
    recs = load(args.store)
    if any(r["date"] == today and r["slot"] == slot for r in recs) and not args.force:
        print(f"{today} {slot} already measured", flush=True)
        return 0
    days = sorted({r["date"] for r in recs if r["date"] < today})
    prior = [r["symbol"] for r in recs if days and r["date"] == days[-1] and r["src"] == "today"]
    cands = candidates(_alpaca_get, today, prior)
    if cands is None:
        print("the market screener is not on today's session (market closed): nothing to do", flush=True)
        return 0
    tz = TZ(key, secret)
    acct = live_account(tz)
    if acct is None:
        raise SystemExit("the keys reach no live account: locates exist only on live accounts")
    new = []
    for c in cands:
        qty = quantity(c["price"])
        try:
            res = measure(tz, acct, c["symbol"], qty)
        except requests.RequestException as e:
            res = {"outcome": "error", "rows": [], "error": type(e).__name__}
        new.append({"date": today, "slot": slot, "time": f"{datetime.now(NY):%H:%M:%S}", **c, "qty": qty, "notional": NOTIONAL, **res})
    check_nothing_filled(tz, acct, {r["qid"] for r in new if r.get("qid")})
    args.store.parent.mkdir(parents=True, exist_ok=True)
    with args.store.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in new)
    (args.store.parent / "changed").write_text(today, encoding="utf-8")
    args.report.write_text(report(recs + new), encoding="utf-8")
    print(f"{today} {slot}: {len(new)} quotes measured", flush=True)
    return 0


def cmd_report(args) -> int:
    text = report(load(args.store))
    args.report.write_text(text, encoding="utf-8")
    print(text, flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run", "report"))
    ap.add_argument("--store", type=Path, default=Path("outputs/tzloc/quotes.jsonl"))
    ap.add_argument("--report", type=Path, default=Path("outputs/tzloc/REPORT.md"))
    ap.add_argument("--force", action="store_true", help="measure now even outside the windows")
    args = ap.parse_args()
    try:
        return {"run": cmd_run, "report": cmd_report}[args.cmd](args)
    except Exception as e:  # the log is public and an error message can hold the account number in a URL
        print(f"failed: {type(e).__name__}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
