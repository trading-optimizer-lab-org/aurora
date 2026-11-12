"""Borrow logger: keeps a record of everything free that bears on shorting the stocks the book would short.

Runs every 30 minutes while TradeZero gives locates (04:00-20:00 New York) and once the next morning. Nothing here can spend money: TradeZero locate quotes
are cancelled and never accepted (tz_locate_meter.TZ refuses any accept call), and no order endpoint is called.

  snap   every run 04:00-20:00 New York: Alpaca movers, a 15-minute delayed snapshot of the whole market (the free
         IEX feed has no trades before 08:00 or after 17:00), IEX snapshots of the candidates, Nasdaq halts,
         Interactive Brokers' public
         shortable file, TradeZero easy-to-borrow flags, the account (cash, positions, locate inventory) to prove
         nothing was spent, and at the quote slots (premarket, session, after hours) a TradeZero locate quote
         per candidate. Candidates: the screener's gainers, the prior session's gainers, and the top gainers of the
         whole-market snapshot (premarket and after hours, when the screener still shows the session).
  daily  next morning: Reg SHO threshold lists (Nasdaq, NYSE), Rule 201 short sale restriction lists (Nasdaq,
         Cboe), FINRA daily short volume, Nasdaq symbol directories, trading halts (Nasdaq, NYSE history),
         Alpaca's asset flags, the day's TradeZero locate history and cash transactions, daily bars and 1-minute
         bars 04:00-20:00 (consolidated feed) plus the overnight session (Blue Ocean) of the candidates, and the
         report over all stored records.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import borrow_proxy_meter as P  # noqa: E402
import tz_locate_meter as T  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (research logger)"}
SNAP = (4 * 60, 20 * 60)  # TradeZero's locate hours
OPEN = 9 * 60 + 30
QUOTE_SLOTS = {"q0415": (4 * 60, 4 * 60 + 45), "q0700": (6 * 60 + 45, 7 * 60 + 25),
               "q0900": (8 * 60 + 45, 9 * 60 + 25), "q1100": (10 * 60 + 45, 11 * 60 + 25),
               "q1300": (12 * 60 + 45, 13 * 60 + 25), "q1430": (14 * 60 + 15, 14 * 60 + 55),
               "q1550": (15 * 60 + 40, 16 * 60), "q1700": (16 * 60 + 45, 17 * 60 + 25),
               "q1930": (19 * 60 + 15, 19 * 60 + 55)}
# TradeZero refuses locate quotes (429 "unpurchased_limit") after about 100 unpurchased ones a day, so the quotes
# are budgeted: most at the decision time, a sample in the other slots, a margin left below the cap
DAILY_QUOTES = 95
QUOTE_BUDGET = {"q0415": 5, "q0700": 5, "q0900": 10, "q1100": 5, "q1300": 5, "q1430": 5, "q1550": 50, "q1700": 5,
                "q1930": 5, "qforced": 10}
KEEP = 60  # sessions of compact records kept in the Actions cache
SCAN_TOP, SCAN_MIN_PCT = 20, 10.0  # whole-market gainers added to the candidates
EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "NYSEARCA", "BATS"}
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
    # TradeZero offers these pools for Reg SHO threshold stocks and also for some new listings (leveraged ETFs)
    return {"pb_su_pool": any(r.get("locateType") in (3, 4) for r in rows), "offer": offer}


def tz_account(tz: T.TZ, acct: str) -> dict:
    out = {}
    for k, path in (("account", f"/v1/api/account/{acct}"), ("pnl", f"/v1/api/accounts/{acct}/pnl"),
                    ("positions", f"/v1/api/accounts/{acct}/positions"),
                    ("orders", f"/v1/api/accounts/{acct}/orders"),
                    ("inventory", f"/v1/api/accounts/{acct}/locates/inventory"),
                    ("cash", f"/v1/api/accounts/{acct}/cash-transactions/start-date/2026-11-01")):
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
    ks = ("positions", "orders", "inventory")  # cash holds the deposit too: its rows are counted, not flagged
    return ([k for k in ks if rows(acc.get(k) or {})]
            + [f"{k} unchecked" for k in ks if not isinstance(acc.get(k), dict) or "error" in acc[k]])


def cash_rows(acc: dict) -> int | None:
    """How many cash transactions TradeZero lists (a new one is a fee or a deposit); no amounts."""
    c = acc.get("cash")
    if not isinstance(c, (dict, list)) or (isinstance(c, dict) and "error" in c):
        return None
    rows = [v for v in (c.values() if isinstance(c, dict) else [c]) if isinstance(v, list)]
    return sum(len(v) for v in rows)


def ny_date(ts: str) -> str:
    """New York date of an Alpaca UTC timestamp."""
    try:
        return f"{datetime.fromisoformat(ts[:19]).replace(tzinfo=timezone.utc).astimezone(T.NY):%Y-%m-%d}"
    except ValueError:
        return ""


def fresh_price(today: str, *snaps: dict | None) -> tuple[float, str, str] | None:
    """Latest trade of today across the feeds' snapshots of one symbol: (price, UTC time, feed)."""
    best = None
    for feed, s in zip(("delayed_sip", "iex"), snaps):
        t = (s or {}).get("latestTrade") or {}
        if t.get("p") and ny_date(str(t.get("t", ""))) == today and (best is None or t["t"] > best[1]):
            best = (float(t["p"]), t["t"], feed)
    return best


def scan_gainers(scan: dict, today: str, skip: set) -> list[dict]:
    """Top gainers of the whole-market snapshot against the last close before today."""
    out = []
    for sym, s in scan.items():
        p = fresh_price(today, s)
        d, pd = (s or {}).get("dailyBar") or {}, (s or {}).get("prevDailyBar") or {}
        ref = pd.get("c") if ny_date(str(d.get("t", ""))) == today else d.get("c")
        if p and ref and sym not in skip and T.shortable(sym, p[0]):
            pct = (p[0] / float(ref) - 1) * 100
            if pct >= SCAN_MIN_PCT:
                out.append({"symbol": sym, "price": p[0], "pct": round(pct, 2), "src": "scan"})
    return sorted(out, key=lambda c: -c["pct"])[:SCAN_TOP]


def market_scan(get, syms: list[str]) -> dict:
    """15-minute delayed consolidated snapshots of every symbol, 1,000 per request."""
    out: dict = {}
    for i in range(0, len(syms), 1000):
        out.update(get(f"{T.DATA}/v2/stocks/snapshots", {"symbols": ",".join(syms[i:i + 1000]),
                                                        "feed": "delayed_sip"}))
    return out


def alpaca_all(get, url: str, params: dict) -> dict:
    """Every page of a multi-symbol bars request."""
    bars: dict = {}
    page = None
    for _ in range(50):
        r = get(url, {**params, **({"page_token": page} if page else {})})
        for k, v in (r.get("bars") or {}).items():
            bars.setdefault(k, []).extend(v)
        page = r.get("next_page_token")
        if not page:
            break
    return {"bars": bars}


def snap_records(cands: list[dict], ib: dict | None, etb: dict, quotes: dict, stamp: dict,
                 threshold: set | None = None, threshold_day: str | None = None) -> list[dict]:
    """ib None: the IB file could not be read, so its state is unknown, not "none". threshold: symbols of the
    Reg SHO threshold lists of threshold_day, None when no recent list was fetched."""
    out = []
    for c in cands:
        qty = T.quantity(c["price"])
        ibs = P.ib_state(ib, c["symbol"], qty) if ib is not None else {"ib": None, "ib_avail": None, "ib_fee": None}
        r = {**stamp, **c, "qty": qty, "notional": T.NOTIONAL, **ibs, "etb": etb.get(c["symbol"]),
             "threshold": None if threshold is None else c["symbol"] in threshold,
             "threshold_day": None if threshold is None else threshold_day}
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
            q = T.measure(tz, acct, c["symbol"], T.quote_quantity(c["price"]))
        except requests.RequestException as e:
            q = {"outcome": "error", "rows": [], **T.why(e, "easy to borrow or cancel check", acct)}
        q["quote_qty"] = T.quote_quantity(c["price"])  # qty stays the $500 size the IB file is read against
        if any(str(x.get("text") or "").startswith(BUSY) for x in q["rows"]):
            q["outcome"] = "busy"
        res[c["symbol"]] = q
        if q.get("status") == 429 and q.get("step") == "quote" and "unpurchased_limit" in q.get("body", ""):
            # the daily cap: every further quote would fail too
            q["outcome"] = "capped"
            break
        tz.sleep(1.0)  # quote endpoint: 1 per second
    try:
        T.check_nothing_filled(tz, acct, {q["qid"] for q in res.values() if q.get("qid")})
    except requests.RequestException as e:  # keep the quotes: they count against the day's budget
        for q in res.values():
            q["check"] = type(e).__name__
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
         and r.get("outcome") not in (None, "busy", "capped")  # forced test runs, often out of hours, stay out
         and not (r["date"] == "2026-11-10" and r.get("outcome") == "error")]  # the cap, before errors had a status
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
    rej = Counter(str(x.get("text") or "")[:40] for r in q if r["outcome"] == "rejected" for x in r.get("rows", []))
    L += ["", "Rejection reasons: " + ("; ".join(f"{k} x{v}" for k, v in rej.most_common(6)) or "none") + "."]
    for name, th in (("Reg SHO threshold stocks quoted", [r for r in q if r.get("threshold")]),
                     ("Quotes with Pre-Borrow or Single Use pools", [r for r in q if r.get("pb_su_pool")])):
        if th:
            L += [f"{name}: {len(th)}; Pre-Borrow offered on {sum(bool((r.get('offer') or {}).get('pb')) for r in th)}, "
                  f"Single Use on {sum(bool((r.get('offer') or {}).get('su')) for r in th)}."]
    e = [r for r in recs if r.get("etb") is not None
         and SNAP[0] <= int(r["time"][:2]) * 60 + int(r["time"][3:5]) < SNAP[1]]  # locate hours only
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

def migrate(r: dict) -> dict:
    """Records written before threshold_day existed used "threshold" for the Pre-Borrow / Single Use pool."""
    if "threshold_day" not in r:
        if "threshold" in r:
            r["pb_su_pool"] = r.pop("threshold")
        r["threshold"] = r["threshold_day"] = None
    return r


def load_state(state: Path) -> tuple[list[dict], dict, list[dict]]:
    recs = [migrate(r) for r in T.load(state / "records.jsonl")]
    prior = json.loads((state / "prior.json").read_text()) if (state / "prior.json").exists() else {}
    audits = T.load(state / "audits.jsonl")
    return recs, prior, audits


def append(path: Path, rows: list[dict]) -> None:
    """Add rows, keeping the last KEEP sessions: the cache stays small; every run's artifact keeps all of it."""
    old = [migrate(r) for r in T.load(path)] if path.name == "records.jsonl" else T.load(path)
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
    sp = spent(acc)
    audits_new = [{"date": today, "time": f"{now:%H:%M}", "spent": sp, "cash_rows": cash_rows(acc)}]
    append(args.state / "audits.jsonl", audits_new)
    audits += audits_new
    if sp:
        log.append("account activity: " + ", ".join(sp))
    etb = etb_all(tz, acct, syms)
    # a hand-run test never takes a scheduled slot: its date can be the prior session's
    slot = "qforced" if args.force_quotes else (quote_slot(now) or "snap")
    if slot != "qforced" and any(r["date"] == today and r["slot"] == slot for r in recs):
        slot = "snap"  # one quote batch per slot and day, whichever cron runs first
    quotes: dict = {}
    if slot.startswith("q"):
        # the cap counts real New York days: a forced run can carry the prior session's date
        day = f"{now:%Y-%m-%d}"
        used = sum(1 for r in recs if r.get("qid") and r.get("qday", r["date"]) == day)
        n = max(0, min(QUOTE_BUDGET[slot], DAILY_QUOTES - used))
        # the biggest gainers first: they are what the strategy shorts
        pick = sorted([c for c in cands if not etb.get(c["symbol"])], key=lambda c: (c["pct"] is None, -(c["pct"] or 0)))
        quotes = quote_all(tz, acct, pick[:n]) if n else {}
        for q in quotes.values():
            q["qday"] = day
    return etb, quotes, slot


def prior_cands(names: list[str], scan: dict) -> list[dict]:
    """The prior session's gainers at their last consolidated trade (premarket, or the prior close)."""
    out = []
    for s in names:
        p = ((scan.get(s) or {}).get("latestTrade") or {}).get("p")
        if p and T.shortable(s, float(p)):
            out.append({"symbol": s, "price": float(p), "pct": None, "src": "prior"})
    return out


def trading_day(today: str) -> bool | None:
    """Alpaca's market calendar: False on a holiday, None when it cannot be read."""
    if not os.environ.get("APCA_API_KEY_ID"):
        return None
    h = {"APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]}
    try:
        r = requests.get(f"{alpaca_base(h)}/v2/calendar", headers=h, params={"start": today, "end": today},
                         timeout=15)
        r.raise_for_status()
        return any(d.get("date") == today for d in r.json())
    except (requests.RequestException, ValueError):
        return None


def threshold_symbols(*texts: str) -> list[str]:
    """Symbols of Nasdaq / NYSE threshold files: a header, pipe-separated rows, a timestamp line."""
    return sorted({ln.split("|")[0] for t in texts for ln in t.splitlines()[1:] if "|" in ln and ln.split("|")[0]})


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
    qs = quote_slot(now)
    if not args.force and any(r["date"] == today and 0 <= minute(now) - minute(
            datetime.strptime(r["time"][:5], "%H:%M")) < 10 for r in recs) and not (
            qs and os.environ.get("TZ_API_KEY_ID") and not any(
                r["date"] == today and r["slot"] == qs for r in recs)):  # a quote slot still to do runs
        print(f"{today} {now:%H:%M}: snapped less than 10 minutes ago (the cron and the ticker both ran)", flush=True)
        return 0
    days = sorted(d for d in prior if d < today)
    last = prior.get(days[-1], []) if days else []
    out = args.out / today / f"snap-{now:%H%M}"
    scan: dict = {}
    uni = args.state / "universe.json"
    try:
        syms_all = json.loads(uni.read_text()) if uni.exists() else []
        scan = market_scan(T._alpaca_get, syms_all) if syms_all else {}
    except Exception as e:  # the whole-market scan is extra: the candidates still come from the screener
        log.append(f"market scan: {type(e).__name__}")
    cands = T.candidates(T._alpaca_get, today, last)
    if cands is not None:
        prior[today] = [c["symbol"] for c in cands if c["src"] == "today"]
    elif not args.force and trading_day(today) is not False:  # the screener still shows the prior session
        src = scan or (market_scan(T._alpaca_get, last) if last else {})  # the delayed full feed, not IEX
        cands = prior_cands(last, src)
    if cands is not None:
        cands += scan_gainers(scan, today, {c["symbol"] for c in cands})
    if not cands:
        print("the market is closed today or there are no candidates: nothing to do", flush=True)
        return 0
    if scan:
        save(out, "market_snapshot.json", scan, gz=True)
    try_save(out, "movers.json", lambda: T._alpaca_get(f"{T.DATA}/v1beta1/screener/stocks/movers", {"top": T.TOP}),
             log)
    syms = [c["symbol"] for c in cands]
    iex: dict = {}
    try:
        iex = T._alpaca_get(f"{T.DATA}/v2/stocks/snapshots", {"symbols": ",".join(syms), "feed": "iex"})
        save(out, "snapshots.json", iex)
    except Exception as e:
        log.append(f"snapshots.json: {type(e).__name__}")
    sip = {k: scan[k] for k in syms if k in scan}
    try:  # candidates outside the scan (no universe yet, or not in it) still get the delayed full-market feed
        if [k for k in syms if k not in sip]:
            sip.update(market_scan(T._alpaca_get, [k for k in syms if k not in sip]))
    except Exception as e:
        log.append(f"candidate sip: {type(e).__name__}")
    for c in cands:  # the freshest of today's trades; else the screener's or the last close
        p = fresh_price(today, sip.get(c["symbol"]), iex.get(c["symbol"]))
        if p:
            c["price"], c["price_t"], c["price_feed"] = p
    try_save(out, "halts.xml", lambda: fetch("https://www.nasdaqtrader.com/rss.aspx",
                                             params={"feed": "tradehalts"}).text, log)
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
        code = getattr(getattr(e, "response", None), "status_code", "")  # the status only: the URL has the account
        log.append(f"tradezero: {type(e).__name__} {code}".strip())
    stamp = {"date": today, "time": f"{now:%H:%M:%S}", "slot": slot}
    th = args.state / "threshold.json"
    tl = json.loads(th.read_text()) if th.exists() else {}
    # a list older than 4 days means the daily fetch failed: membership is unknown, not the stale list
    fresh = bool(tl) and (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(tl["day"], "%Y%m%d")).days <= 4
    new = snap_records(cands, ib, etb, quotes, stamp, set(tl["symbols"]) if fresh else None,
                       tl["day"] if fresh else None)
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
    done = args.state / "daily_done.txt"
    if not args.force and done.exists() and done.read_text() == d8:
        print(f"daily {day:%Y-%m-%d} already collected", flush=True)  # the backup cron after a run that happened
        return 0
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
    try_save(out, "nyse_halts.csv", lambda: fetch("https://www.nyse.com/api/trade-halts/historical/download",
                                                  params={"haltDateFrom": f"{day:%Y-%m-%d}"}).text, log)
    try_save(out, "nasdaq_ssr.txt", lambda: fetch(
        f"https://www.nasdaqtrader.com/dynamic/symdir/shorthalts/shorthalts{d8}.txt").text, log)
    try_save(out, "cboe_ssr.csv", lambda: fetch("https://www-api.cboe.com/us/equities/market_statistics/"
                                                f"short_sale_circuit_breakers/downloads/BatsCircuitBreakers{day:%Y}.csv"
                                                ).text, log)
    lists = [out / "nasdaq_threshold.txt", out / "nyse_threshold.txt"]
    if all(f.exists() for f in lists):
        args.state.mkdir(parents=True, exist_ok=True)
        (args.state / "threshold.json").write_text(json.dumps(
            {"day": d8, "symbols": threshold_symbols(*(f.read_text(encoding="utf-8") for f in lists))}))
    if all(f.exists() for f in lists) and (out / "finra_short_volume.txt.gz").exists():
        (args.state / "daily_done.txt").write_text(d8)  # else the backup runs fetch the day again
    recs, prior, audits = load_state(args.state)
    syms = sorted({r["symbol"] for r in recs if r["date"] == f"{day:%Y-%m-%d}"})
    if os.environ.get("APCA_API_KEY_ID"):
        h = {"APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]}
        base = alpaca_base(h)
        def assets_list():
            r = requests.get(f"{base}/v2/assets", headers=h, params={"status": "active", "asset_class": "us_equity"},
                             timeout=60)
            r.raise_for_status()
            if not isinstance(r.json(), list):
                raise ValueError("assets: not a list")
            return r.json()
        try_save(out, "alpaca_assets.json", assets_list, log, gz=True)
        assets = out / "alpaca_assets.json.gz"
        if assets.exists():  # the symbols of the snapshots' whole-market scan
            uni = sorted(a["symbol"] for a in json.loads(gzip.decompress(assets.read_bytes()))
                         if a.get("tradable") and a.get("exchange") in EXCHANGES and a["symbol"].isalpha())
            if len(uni) > 1000:
                args.state.mkdir(parents=True, exist_ok=True)
                (args.state / "universe.json").write_text(json.dumps(uni))
        if syms:
            try_save(out, "daily_bars.json", lambda: T._alpaca_get(f"{T.DATA}/v2/stocks/bars", {
                "symbols": ",".join(syms), "timeframe": "1Day", "start": f"{day - timedelta(days=10):%Y-%m-%d}",
                "end": f"{day + timedelta(days=1):%Y-%m-%d}", "feed": "iex", "limit": 10000}), log)
            d0 = datetime(day.year, day.month, day.day, tzinfo=T.NY)
            for name, feed, a, b, tf in (("daily_bars_sip.json", "sip", d0 - timedelta(days=10), d0 + timedelta(days=1), "1Day"),
                                         ("minute_bars_sip.json", "sip", d0 + timedelta(hours=4), d0 + timedelta(hours=20), "1Min"),
                                         ("overnight_bars.json", "boats", d0 + timedelta(hours=20), d0 + timedelta(hours=28), "1Min")):
                try_save(out, name, lambda feed=feed, a=a, b=b, tf=tf: alpaca_all(T._alpaca_get, f"{T.DATA}/v2/stocks/bars", {
                    "symbols": ",".join(syms), "timeframe": tf, "start": a.isoformat(), "end": b.isoformat(),
                    "feed": feed, "limit": 10000}), log, gz=True)
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
