"""Borrow logger: keeps a record of everything free that bears on shorting the stocks the book would short.

Runs every 30 minutes of a trading day and once after it. Nothing here can spend money: TradeZero locate quotes
are cancelled and never accepted (tz_locate_meter.TZ refuses any accept call), and no order endpoint is called.

  snap   every run 08:00-16:15 New York: Alpaca movers and snapshots of the candidates, Interactive Brokers' public
         shortable file, TradeZero easy-to-borrow flags, the account (cash, positions, locate inventory) to prove
         nothing was spent, and at the quote slots a TradeZero locate quote per candidate.
  daily  after the session: Reg SHO threshold lists (Nasdaq, NYSE), FINRA daily short volume, Nasdaq symbol
         directories and trading halts, Alpaca's asset flags, the day's TradeZero locate history, daily bars of the
         candidates, and the report over all stored records.

Raw files go to --out (encrypted by the workflow); compact records accumulate in --state (Actions cache).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow_proxy_meter as P  # noqa: E402
import tz_locate_meter as T  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (research logger)"}
SNAP = (8 * 60, 16 * 60 + 15)
QUOTE_SLOTS = {"q0900": (8 * 60 + 45, 9 * 60 + 25), "q1100": (10 * 60 + 45, 11 * 60 + 25),
               "q1300": (12 * 60 + 45, 13 * 60 + 25), "q1430": (14 * 60 + 15, 14 * 60 + 55),
               "q1550": (15 * 60 + 40, 16 * 60)}
KEEP = 60  # sessions of compact records kept in the Actions cache
BUSY = ("14 ", "18 ")  # another quote for the symbol is still pending or offered (the meter's)


def minute(now: datetime) -> int:
    return now.hour * 60 + now.minute


def quote_slot(now: datetime) -> str | None:
    return next((k for k, (a, b) in QUOTE_SLOTS.items() if a <= minute(now) < b), None)


def kinds(rows: list[dict]) -> dict:
    """Which locate pools were offered: regular (1, 2), Pre-Borrow (3), Single Use (4)."""
    off = [r for r in rows if r.get("locateStatus") in (50, 65) and r.get("locatePrice")]
    offer = {k: min((r["locatePrice"] for r in off if r.get("locateType") in t), default=None)
             for k, t in (("regular", (1, 2)), ("pb", (3,)), ("su", (4,)))}
    return {"threshold": any(r.get("locateType") in (3, 4) for r in rows), "offer": offer}


def tz_account(tz: T.TZ, acct: str) -> dict:
    out = {}
    for k, path in (("account", f"/v1/api/account/{acct}"), ("pnl", f"/v1/api/accounts/{acct}/pnl"),
                    ("positions", f"/v1/api/accounts/{acct}/positions"),
                    ("orders", f"/v1/api/accounts/{acct}/orders"),
                    ("inventory", f"/v1/api/accounts/{acct}/locates/inventory")):
        try:
            out[k] = tz.get(path)
        except requests.RequestException as e:
            out[k] = {"error": type(e).__name__}
        tz.sleep(0.6)
    return out


def spent(acc: dict) -> list[str]:
    """Account activity that commits money: open positions, orders today, locate inventory (the owner's or a bug)."""
    def rows(x) -> list:
        return [v for v in (x.values() if isinstance(x, dict) else [x]) if isinstance(v, list) and v]
    ks = ("positions", "orders", "inventory")
    return ([k for k in ks if rows(acc.get(k) or {})]
            + [f"{k} unchecked" for k in ks if not isinstance(acc.get(k), dict) or "error" in acc[k]])


def snap_records(cands: list[dict], ib: dict | None, etb: dict, quotes: dict, stamp: dict) -> list[dict]:
    """ib None: the IB file could not be read, so its state is unknown, not "none"."""
    out = []
    for c in cands:
        qty = T.quantity(c["price"])
        ibs = P.ib_state(ib, c["symbol"], qty) if ib is not None else {"ib": None, "ib_avail": None, "ib_fee": None}
        r = {**stamp, **c, "qty": qty, "notional": T.NOTIONAL, **ibs, "etb": etb.get(c["symbol"])}
        q = quotes.get(c["symbol"])
        if q is None and stamp["slot"].startswith("q") and r["etb"]:
            r["outcome"] = "easy to borrow"  # not quoted because TradeZero has it easy to borrow
        elif q is not None:
            r.update(q)
            r.update(kinds(q.get("rows", [])))
        out.append(r)
    return out


def quote_all(tz: T.TZ, acct: str, cands: list[dict]) -> dict:
    res = {}
    for c in cands:
        try:
            q = T.measure(tz, acct, c["symbol"], T.quantity(c["price"]))
        except requests.RequestException as e:
            q = {"outcome": "error", "rows": [], "error": type(e).__name__}
        if any(str(x.get("text") or "").startswith(BUSY) for x in q["rows"]):
            q["outcome"] = "busy"
        res[c["symbol"]] = q
        tz.sleep(1.0)  # quote endpoint: 1 per second
    T.check_nothing_filled(tz, acct, {q["qid"] for q in res.values() if q.get("qid")})
    return res


def etb_all(tz: T.TZ, acct: str, syms: list[str]) -> dict:
    out: dict[str, bool | None] = {}
    for s in syms:
        try:
            out[s] = bool(tz.get(f"/v1/api/accounts/{acct}/is-easy-to-borrow/symbol/{s}").get("isEasyToBorrow"))
        except requests.RequestException:
            out[s] = None
        tz.sleep(0.6)  # 2 per second
    return out


# ---------------------------------------------------------------- files

def save(out: Path, name: str, data, gz: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=True)
    raw = data if isinstance(data, (bytes, str)) else json.dumps(data)
    b = raw.encode("utf-8") if isinstance(raw, str) else raw
    (out / (name + (".gz" if gz else ""))).write_bytes(gzip.compress(b) if gz else b)


def fetch(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=60, **kw)
    r.raise_for_status()
    if r.text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):  # Nasdaq answers a missing file with a page
        raise ValueError(f"web page instead of data: {r.url}")
    return r


def try_save(out: Path, name: str, fn, log: list[str], gz: bool = False) -> None:
    try:
        save(out, name, fn(), gz)
    except Exception as e:  # one source failing must not lose the others
        log.append(f"{name}: {type(e).__name__} {str(e)[:120]}")


# ---------------------------------------------------------------- report

def report(recs: list[dict], audits: list[dict], cash=None) -> str:
    q = [r for r in recs if r.get("slot", "").startswith("q") and r["slot"] != "qforced"
         and r.get("outcome") not in (None, "busy")]  # forced test runs, often out of hours, stay out
    L = ["# Borrow logger", "", f"Last {len({r['date'] for r in recs})} sessions, {len(recs)} stock snapshots, "
         f"{len(q)} TradeZero quotes (about ${T.NOTIONAL:,.0f} each).", "",
         "## Quotes by time of day", "",
         "| slot | quotes | easy to borrow | offered | regular offered | Pre-Borrow offered | Single Use only | "
         "no shares | rejected | no answer, expired or error | median price |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for slot in QUOTE_SLOTS:
        g = [r for r in q if r["slot"] == slot]
        if not g:
            continue
        n = len(g)
        off = [r.get("offer") or {} for r in g]
        reg = sum(bool(o.get("regular")) for o in off)
        pb = sum(bool(o.get("pb")) for o in off)
        su = sum(bool(o.get("su")) and not o.get("pb") and not o.get("regular") for o in off)
        px = [min(v for v in o.values() if v) / r["price"] for r, o in zip(g, off) if any(o.values())]
        L.append(f"| {slot} | {n} | " + " | ".join(f"{x / n:.0%}" for x in (
            sum(r["outcome"] == "easy to borrow" for r in g), sum(r["outcome"] == "offered" for r in g), reg, pb, su,
            sum(r["outcome"] == "no shares" for r in g), sum(r["outcome"] == "rejected" for r in g),
            sum(r["outcome"] not in ("easy to borrow", "offered", "no shares", "rejected") for r in g)))
            + f" | {f'{statistics.median(px):.2%}' if px else '-'} |")
    rej = Counter(x.get("text", "")[:40] for r in q if r["outcome"] == "rejected" for x in r.get("rows", []))
    L += ["", "Rejection reasons: " + ("; ".join(f"{k} x{v}" for k, v in rej.most_common(6)) or "none") + "."]
    th = [r for r in q if r.get("threshold")]
    if th:
        L += [f"Reg SHO threshold stocks quoted: {len(th)}; Pre-Borrow offered on "
              f"{sum(bool(r['offer'].get('pb')) for r in th)}, Single Use on {sum(bool(r['offer'].get('su')) for r in th)}."]
    e = [r for r in recs if r.get("etb") is not None and "08" <= r["time"][:2] <= "16"]
    if e:
        L += ["", "## Easy to borrow through the day", "", "| hour (New York) | snapshots | easy to borrow |",
              "|---|---|---|"]
        for h in sorted({r["time"][:2] for r in e}):
            g = [r for r in e if r["time"][:2] == h]
            L.append(f"| {h}:00 | {len(g)} | {sum(r['etb'] for r in g) / len(g):.0%} |")
    both = [r for r in q if r.get("ib")]
    if both:
        L += ["", "## Interactive Brokers' file against TradeZero quotes", "", "| IB | quotes | TZ offered or ETB |",
              "|---|---|---|"]
        for k in ("enough", "some", "none"):
            g = [r for r in both if r["ib"] == k]
            if g:
                L.append(f"| {k} | {len(g)} | "
                         f"{sum(r['outcome'] in ('offered', 'easy to borrow') for r in g) / len(g):.0%} |")
    L += ["", "## Money check", ""] + ([f"- cash now: {cash}"] if cash is not None else [])
    for a in audits[-10:]:
        L.append(f"- {a['date']} {a['time']}: {', '.join(a['spent']) or 'no positions, orders or locates'}")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- commands

def load_state(state: Path) -> tuple[list[dict], dict, list[dict]]:
    recs = T.load(state / "records.jsonl")
    prior = json.loads((state / "prior.json").read_text()) if (state / "prior.json").exists() else {}
    audits = T.load(state / "audits.jsonl")
    return recs, prior, audits


def append(path: Path, rows: list[dict]) -> None:
    """Add rows, keeping the last KEEP sessions: the cache stays small; every run's artifact keeps all of it."""
    old = T.load(path)
    keep = set(sorted({r["date"] for r in old + rows})[-KEEP:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in old + rows if r["date"] in keep), encoding="utf-8")


def cash_of(acc: dict):
    pnl = acc.get("pnl") or {}
    return pnl.get("availableCash", pnl.get("accountValue"))


def tz_snap(args, now: datetime, today: str, cands: list[dict], syms: list[str], recs: list[dict],
            audits: list[dict], log: list[str], out: Path) -> tuple[dict, dict, str]:
    """TradeZero part of a snapshot: account audit, easy-to-borrow flags and, once per quote slot, locate quotes."""
    key, secret = os.environ.get("TZ_API_KEY_ID"), os.environ.get("TZ_API_SECRET_KEY")
    if not (key and secret):
        return {}, {}, "snap"
    tz = T.TZ(key, secret)
    acct = T.live_account(tz)
    if not acct:
        return {}, {}, "snap"
    acc = tz_account(tz, acct)
    save(out, "account.json", acc)
    # the cache is not encrypted: it keeps whether money moved, never the balance or the account number
    audits_new = [{"date": today, "time": f"{now:%H:%M}", "spent": spent(acc)}]
    append(args.state / "audits.jsonl", audits_new)
    audits += audits_new
    if audits_new[0]["spent"]:
        log.append("account activity: " + ", ".join(audits_new[0]["spent"]))
    etb = etb_all(tz, acct, syms)
    slot = quote_slot(now) or ("qforced" if args.force_quotes else "snap")
    if slot != "qforced" and any(r["date"] == today and r["slot"] == slot for r in recs):
        slot = "snap"  # one quote batch per slot and day, whichever cron runs first
    quotes = quote_all(tz, acct, [c for c in cands if not etb.get(c["symbol"])]) if slot.startswith("q") else {}
    return etb, quotes, slot


def cmd_snap(args) -> int:
    now = datetime.now(T.NY)
    if not args.force and (now.weekday() >= 5 or not SNAP[0] <= minute(now) < SNAP[1]):
        print(f"outside the session ({now:%a %H:%M} New York): nothing to do", flush=True)
        return 0
    today, log = f"{now:%Y-%m-%d}", list[str]()
    if args.force:  # on a weekend or before the open, use the latest session the screener has
        movers = T._alpaca_get(f"{T.DATA}/v1beta1/screener/stocks/movers", {"top": T.TOP})
        today = T.session_day(movers) or today
    recs, prior, audits = load_state(args.state)
    days = sorted(d for d in prior if d < today)
    cands = T.candidates(T._alpaca_get, today, prior.get(days[-1], []) if days else [])
    if cands is None:
        print("the market screener is not on today's session (market closed): nothing to do", flush=True)
        return 0
    prior[today] = [c["symbol"] for c in cands if c["src"] == "today"]
    out = args.out / today / f"snap-{now:%H%M}"
    try_save(out, "movers.json", lambda: T._alpaca_get(f"{T.DATA}/v1beta1/screener/stocks/movers", {"top": T.TOP}),
             log)
    syms = [c["symbol"] for c in cands]
    try_save(out, "snapshots.json", lambda: T._alpaca_get(f"{T.DATA}/v2/stocks/snapshots",
                                                           {"symbols": ",".join(syms), "feed": "iex"}), log)
    ib_text = ""
    try:
        ib_text = P.ib_fetch()
        save(out, "ib_usa.txt", ib_text, gz=True)
    except Exception as e:
        log.append(f"ib: {type(e).__name__}")
    ib = P.ib_parse(ib_text) if ib_text else None
    etb: dict = {}
    quotes: dict = {}
    slot = "snap"
    try:
        etb, quotes, slot = tz_snap(args, now, today, cands, syms, recs, audits, log, out)
    except Exception as e:  # TradeZero down must not lose the free files of this run
        log.append(f"tradezero: {type(e).__name__}")
    stamp = {"date": today, "time": f"{now:%H:%M:%S}", "slot": slot}
    new = snap_records(cands, ib, etb, quotes, stamp)
    save(out, "records.json", new)
    append(args.state / "records.jsonl", new)
    (args.state / "prior.json").write_text(json.dumps({d: prior[d] for d in sorted(prior)[-10:]}))
    if log:
        save(out, "errors.txt", "\n".join(log))
    print(f"{today} {now:%H:%M} {slot}: {len(new)} stocks, {len(quotes)} quotes, {len(log)} source errors", flush=True)
    return 0


def alpaca_base(h: dict) -> str:
    """Live or paper Alpaca host for these keys; a failed probe only loses the asset flags."""
    for b in P.ALPACA:
        try:
            if requests.get(f"{b}/v2/account", headers=h, timeout=15).ok:
                return b
        except requests.RequestException:
            pass
    return P.ALPACA[0]


def cmd_daily(args) -> int:
    now = datetime.now(T.NY)
    day = now if now.hour >= 18 else now - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    d8, out, log = f"{day:%Y%m%d}", args.out / f"{day:%Y-%m-%d}" / "daily", list[str]()
    try_save(out, "nasdaq_threshold.txt", lambda: fetch(
        f"https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{d8}.txt").text, log)
    try_save(out, "nyse_threshold.txt", lambda: fetch(
        "https://www.nyse.com/api/regulatory/threshold-securities/download",
        params={"selectedDate": f"{day:%d-%b-%Y}"}).text, log)
    try_save(out, "finra_short_volume.txt", lambda: fetch(
        f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d8}.txt").text, log, gz=True)
    for f in ("nasdaqlisted", "otherlisted"):
        try_save(out, f"{f}.txt", lambda f=f: fetch(f"https://www.nasdaqtrader.com/dynamic/symdir/{f}.txt").text,
                 log, gz=True)
    try_save(out, "halts.xml", lambda: fetch("https://www.nasdaqtrader.com/rss.aspx",
                                             params={"feed": "tradehalts"}).text, log)
    recs, prior, audits = load_state(args.state)
    syms = sorted({r["symbol"] for r in recs if r["date"] == f"{day:%Y-%m-%d}"})
    if os.environ.get("APCA_API_KEY_ID"):
        h = {"APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]}
        base = alpaca_base(h)
        try_save(out, "alpaca_assets.json", lambda: requests.get(
            f"{base}/v2/assets", headers=h, params={"status": "active", "asset_class": "us_equity"}, timeout=60).json(),
            log, gz=True)
        if syms:
            try_save(out, "daily_bars.json", lambda: T._alpaca_get(f"{T.DATA}/v2/stocks/bars", {
                "symbols": ",".join(syms), "timeframe": "1Day", "start": f"{day - timedelta(days=10):%Y-%m-%d}",
                "end": f"{day + timedelta(days=1):%Y-%m-%d}", "feed": "iex", "limit": 10000}), log)
    key, secret = os.environ.get("TZ_API_KEY_ID"), os.environ.get("TZ_API_SECRET_KEY")
    if key and secret:
        tz = T.TZ(key, secret)
        acct = None
        try:
            acct = T.live_account(tz)
        except Exception as e:  # TradeZero down must not lose the free files of this run
            log.append(f"tradezero: {type(e).__name__}")
        if acct:
            try_save(out, "locate_history.json", lambda: tz.get(f"/v1/api/accounts/{acct}/locates/history"), log)
            try_save(out, "account.json", lambda: tz_account(tz, acct), log)
    acc_file = out / "account.json"
    cash = cash_of(json.loads(acc_file.read_text())) if acc_file.exists() else None
    text = report(recs, audits, cash)
    save(out, "REPORT.md", text)
    save(args.out, "REPORT.md", text)
    if log:
        save(out, "errors.txt", "\n".join(log))
    print(f"daily {day:%Y-%m-%d}: {len(syms)} symbols, {len(log)} source errors", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("snap", "daily"))
    ap.add_argument("--state", type=Path, default=Path("outputs/borrowlog/state"))
    ap.add_argument("--out", type=Path, default=Path("outputs/borrowlog/run"))
    ap.add_argument("--force", action="store_true", help="snap even outside the session")
    ap.add_argument("--force-quotes", action="store_true", help="quote even outside the quote slots")
    args = ap.parse_args()
    t0 = time.time()
    try:
        rc = {"snap": cmd_snap, "daily": cmd_daily}[args.cmd](args)
    except Exception as e:  # the log is public and an error message can hold the account number in a URL
        print(f"failed: {type(e).__name__}", flush=True)
        return 1
    print(f"took {time.time() - t0:.0f} s", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
