"""TradeZero locate-quote logger (V29_RESULTS.md: the missing number is the price of a locate). It asks TradeZero for
a locate quote on each of today's short candidates, writes what it was offered, and cancels the quote. It never
accepts a locate, sells one back or sends an order: the only TradeZero calls are reading the accounts and the locate
history, the easy-to-borrow check, a quote request and its cancel (see ALLOWED). An unaccepted quote expires by
itself after 30 seconds; TradeZero records a locate's cost on accept. As a guard, the account's ``totalLocateCosts``
is read before and after: if it changes, the logger stops.

Run it on your own machine, with your keys in environment variables (read, never printed or written):
  TZ_API_KEY_ID, TZ_API_SECRET_KEY        TradeZero Developer API, live account (locates do not work on paper)
  APCA_API_KEY_ID, APCA_API_SECRET_KEY    Alpaca market data for the candidates (the free plan is enough)

  python scripts/tz_locate_logger.py candidates           today's candidates (no TradeZero call)
  python scripts/tz_locate_logger.py quotes --max 30      quote and cancel; appends to outputs/tz_locates/quotes.csv
  python scripts/tz_locate_logger.py summary              the locate price by tier, as v29's grid uses it
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

TZ_BASE = "https://webapi.tradezero.com"
DATA = "https://data.alpaca.markets"
NY = ZoneInfo("America/New_York")
OUT = Path("outputs/tz_locates")
ALLOWED = (("GET", r"/v1/api/accounts"),
           ("GET", r"/v1/api/accounts/[^/]+/is-easy-to-borrow/symbol/[A-Z.]+"),
           ("GET", r"/v1/api/accounts/[^/]+/locates/history"),
           ("POST", r"/v1/api/accounts/locates/quote"),
           ("DELETE", r"/v1/api/accounts/locates/cancel/accounts/[^/]+/quoteReqID/[A-Za-z0-9.]+"))
GAP = {"GET": 0.6, "POST": 1.2, "DELETE": 0.6}  # seconds between calls of a kind (TradeZero: quote 1/s, others 2/s)
OFFERED, TERMINAL = 65, (50, 52, 56, 67)
COLS = ["ts_utc", "symbol", "price", "prev_close", "gap", "rise20", "threshold", "etb", "tier", "status", "type",
        "locate_price", "locate_pct", "su_price", "su_pct", "error", "text"]
PRICE_MIN, PRICE_MAX = 1.0, 20.0


class Blocked(RuntimeError):
    pass


class TZ:
    """The TradeZero calls the logger may make, and nothing else."""

    def __init__(self, session=None, sleep=time.sleep) -> None:
        key, secret = os.environ.get("TZ_API_KEY_ID"), os.environ.get("TZ_API_SECRET_KEY")
        if not key or not secret:
            raise SystemExit("TZ_API_KEY_ID / TZ_API_SECRET_KEY are not set")
        self.h = {"TZ-API-KEY-ID": key, "TZ-API-SECRET-KEY": secret}
        self.s = session or requests.Session()
        self.sleep = sleep
        self.last: dict[str, float] = {}

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        if not any(m == method and re.fullmatch(p, path) for m, p in ALLOWED):
            raise Blocked(f"{method} {path} is not a call this logger makes")
        for attempt in range(4):
            wait = GAP[method] - (time.monotonic() - self.last.get(method, -1e9))
            if wait > 0:
                self.sleep(wait)
            self.last[method] = time.monotonic()
            r = self.s.request(method, TZ_BASE + path, headers=self.h, json=body, timeout=30)
            if r.status_code == 429:
                self.sleep(2 ** (attempt + 1))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path.split('/accounts/')[0]}...: HTTP {r.status_code} {r.text[:200]}")
            return r.json() if r.text else {}
        raise RuntimeError(f"{method}: kept getting 429")

    def account(self) -> dict:
        rows = self.call("GET", "/v1/api/accounts").get("accounts", [])
        live = [a for a in rows if a.get("accountType") != "Paper" and a.get("accountStatus") == "Active"]
        if not live:
            raise SystemExit("no active live account on these keys (locates need a live account)")
        return live[0]

    def costs(self, acct: str) -> float:
        for a in self.call("GET", "/v1/api/accounts").get("accounts", []):
            if a.get("account") == acct:
                return float(a.get("totalLocateCosts") or 0.0)
        raise RuntimeError("the account disappeared from /accounts")

    def etb(self, acct: str, sym: str) -> bool:
        return bool(self.call("GET", f"/v1/api/accounts/{acct}/is-easy-to-borrow/symbol/{sym}").get("isEasyToBorrow"))

    def quote(self, acct: str, sym: str, qty: int, qid: str) -> None:
        self.call("POST", "/v1/api/accounts/locates/quote",
                  {"account": acct, "symbol": sym, "quantity": int(qty), "quoteReqID": qid})

    def history(self, acct: str) -> list[dict]:
        return self.call("GET", f"/v1/api/accounts/{acct}/locates/history").get("locateHistory", [])

    def cancel(self, acct: str, qid: str) -> None:
        self.call("DELETE", f"/v1/api/accounts/locates/cancel/accounts/{acct}/quoteReqID/{qid}")


# ---------------------------------------------------------------- candidates (Alpaca + Nasdaq)

def _alpaca(path: str, params: dict) -> dict:
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set")
    r = requests.get(DATA + path, params=params, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                     timeout=60)
    r.raise_for_status()
    return r.json()


def threshold_list(day: pd.Timestamp) -> set[str]:
    """Nasdaq's Reg SHO threshold list for the session (the latest file up to it), without ETFs."""
    for k in range(5):
        d = day - pd.offsets.BDay(k)
        r = requests.get(f"https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{d:%Y%m%d}.txt",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=60, allow_redirects=False)
        if r.status_code == 200 and r.text.startswith("Symbol|"):  # a missing day redirects to a page
            return {p.split("|")[0].strip().upper() for p in r.text.splitlines()[1:]
                    if p.count("|") >= 3 and p.split("|")[3].strip() == "Y" and "ETF" not in p.split("|")[1]}
    return set()


def daily_closes(symbols: list[str], day: pd.Timestamp) -> dict[str, np.ndarray]:
    """Split-adjusted daily closes of the sessions before ``day`` (about two months)."""
    out: dict[str, list] = {}
    for k in range(0, len(symbols), 100):
        params = {"symbols": ",".join(symbols[k:k + 100]), "timeframe": "1Day", "adjustment": "split",
                  "start": (day - timedelta(days=60)).strftime("%Y-%m-%d"),
                  "end": (day - timedelta(days=1)).strftime("%Y-%m-%d"), "feed": "sip", "limit": 10000}
        while True:
            body = _alpaca("/v2/stocks/bars", params)
            for sym, bars in (body.get("bars") or {}).items():
                out.setdefault(sym, []).extend(b["c"] for b in bars)
            if not body.get("next_page_token"):
                break
            params = {**params, "page_token": body["next_page_token"]}
    return {s: np.array(v, float) for s, v in out.items()}


def features(price: float, closes: np.ndarray | None) -> tuple[float, float, float]:
    """(prior close, gap to it, prior close over the lowest close of the 20 sessions before the prior one)."""
    if closes is None or len(closes) < 2:
        return np.nan, np.nan, np.nan
    pc = float(closes[-1])
    low = float(np.min(closes[-21:-1]))
    return pc, (price / pc if pc > 0 and np.isfinite(price) else np.nan), (pc / low if low > 0 else np.nan)


def tier(etb: bool, thr: bool, gap: float, rise: float) -> str:
    """v29's tiers (short interest is not known here): ETB from TradeZero's own check."""
    if etb:
        return "ETB"
    hot = thr or (np.isfinite(gap) and gap >= 1.5) or (np.isfinite(rise) and rise >= 2.0)
    return "HOT" if hot else "HTB"


def candidates(day: pd.Timestamp, n: int) -> pd.DataFrame:
    """Today's short candidates: the top gainers and the Reg SHO threshold names, prior close $1-$20; threshold
    names fill at most half."""
    movers = _alpaca("/v1beta1/screener/stocks/movers", {"top": 50}).get("gainers", [])
    price = {m["symbol"]: float(m["price"]) for m in movers}
    thr = threshold_list(day)
    syms = sorted(set(price) | thr)
    closes = daily_closes(syms, day) if syms else {}
    rows = []
    for s in syms:
        pc, gap, rise = features(price.get(s, np.nan), closes.get(s))
        if not (np.isfinite(pc) and PRICE_MIN <= pc <= PRICE_MAX):
            continue
        rows.append({"symbol": s, "price": price.get(s, pc), "prev_close": pc, "gap": gap, "rise20": rise,
                     "threshold": s in thr, "move": price.get(s, pc) / pc - 1})
    df = pd.DataFrame(rows, columns=["symbol", "price", "prev_close", "gap", "rise20", "threshold", "move"])
    t = df[df["threshold"]].sort_values("move", ascending=False).head(n // 2)
    g = df[~df["symbol"].isin(t["symbol"])].sort_values("move", ascending=False).head(n - len(t))
    return pd.concat([t, g]).reset_index(drop=True)


# ---------------------------------------------------------------- quotes

def offers(hist: list[dict], qid: str) -> dict[str, dict]:
    return {r["quoteReqID"]: r for r in hist if r.get("quoteReqID") in (qid, qid + ".SU")}


def quote_one(tz: TZ, acct: str, sym: str, qid: str, polls: int = 6) -> dict[str, dict]:
    """Quote 100 shares, read the offer(s), cancel whatever is still open."""
    tz.quote(acct, sym, 100, qid)
    got: dict[str, dict] = {}
    tz.sleep(2.0)
    for _ in range(polls):
        got = offers(tz.history(acct), qid)
        base = got.get(qid)
        if base and int(base.get("locateStatus", 0)) in (OFFERED, *TERMINAL):
            break
        tz.sleep(2.0)
    for rid, r in got.items():
        if int(r.get("locateStatus", 0)) not in TERMINAL:
            try:
                tz.cancel(acct, rid)
            except RuntimeError as e:  # it expires by itself 30 seconds after the offer
                print(f"{sym}: cancel {rid} failed ({e}); it expires unaccepted", flush=True)
    return got


def _row(c: dict, etb: bool, got: dict[str, dict], qid: str) -> dict:
    base, su = got.get(qid, {}), got.get(qid + ".SU", {})
    price = float(c["price"])

    def pct(x):
        return float(x) / price if x not in (None, "") and price > 0 else np.nan
    return {"ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbol": c["symbol"],
            "price": price, "prev_close": c["prev_close"], "gap": c["gap"], "rise20": c["rise20"],
            "threshold": bool(c["threshold"]), "etb": etb,
            "tier": tier(etb, bool(c["threshold"]), float(c["gap"]), float(c["rise20"])),
            "status": base.get("locateStatus", "") if not etb else "etb", "type": base.get("locateType", ""),
            "locate_price": base.get("locatePrice", ""), "locate_pct": pct(base.get("locatePrice")),
            "su_price": su.get("locatePrice", ""), "su_pct": pct(su.get("locatePrice")),
            "error": base.get("locateError", ""), "text": str(base.get("text", ""))[:120]}


def _append(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerows(rows)


def run_quotes(tz: TZ, cands: pd.DataFrame, out: Path) -> list[dict]:
    acct = tz.account()["account"]
    c0 = tz.costs(acct)
    stamp = datetime.now(NY).strftime("%y%m%d%H%M%S")
    rows: list[dict] = []
    checked = False
    for k, c in enumerate(cands.to_dict("records")):
        sym = str(c["symbol"]).upper()
        etb = tz.etb(acct, sym)
        got: dict[str, dict] = {}
        qid = f"AU{stamp}{k:03d}"
        if not etb:
            got = quote_one(tz, acct, sym, qid)
        rows.append(_row(c, etb, got, qid))
        _append(rows[-1:], out)
        r = rows[-1]
        pct = r["locate_pct"]
        shown = f"{pct:.2%}" if isinstance(pct, float) and np.isfinite(pct) else "-"
        print(f"{sym:6s} {r['tier']:3s} status {r['status']} locate {r['locate_price']} ({shown})", flush=True)
        if got and not checked:
            tz.sleep(5.0)
            if tz.costs(acct) > c0 + 1e-9:
                raise SystemExit("STOP: the account's locate costs changed after a quote and its cancel")
            checked = True
    if tz.costs(acct) > c0 + 1e-9:
        raise SystemExit("STOP: the account's locate costs changed during the run")
    return rows


def summary(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    q = df[df["tier"] != "ETB"]
    out = []
    for t, g in [("ETB", df[df["tier"] == "ETB"])] + list(q.groupby("tier")):
        pct = pd.to_numeric(g["locate_pct"], errors="coerce").dropna()
        out.append({"tier": t, "rows": len(g), "days": g["ts_utc"].str[:10].nunique(),
                    "offered": len(pct), "unavailable": int((pd.to_numeric(g["error"], errors="coerce") == 11).sum()),
                    "median": pct.median() if len(pct) else np.nan, "p75": pct.quantile(0.75) if len(pct) else np.nan,
                    "p90": pct.quantile(0.9) if len(pct) else np.nan})
    return pd.DataFrame(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("candidates", "quotes", "summary"))
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--out", type=Path, default=OUT / "quotes.csv")
    args = ap.parse_args()
    if args.cmd == "summary":
        print(summary(args.out).to_string(index=False))
        return 0
    day = pd.Timestamp(datetime.now(NY).date())
    cands = candidates(day, args.max)
    print(cands.to_string(index=False), flush=True)
    if args.cmd == "quotes":
        run_quotes(TZ(), cands, args.out)
        print(f"written to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
