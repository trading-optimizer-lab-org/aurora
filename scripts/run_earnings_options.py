#!/usr/bin/env python3
"""Earnings options study: straddles, calls/puts and iron flies around earnings releases.

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... SEC_USER_AGENT="Name email" \
        python scripts/run_earnings_options.py data --cache outputs/eo_cache --end 2026-10-23
    python scripts/run_earnings_options.py eval --cache outputs/eo_cache --out outputs/earnings_options

See docs/research/EARNINGS_OPTIONS_PREREGISTRATION.md. Only reports and strategy returns are written to the
artifact; raw market data stays in the cache folder.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from aurora.research import earnings_options as eo

DATA = "https://data.alpaca.markets"
TRADE = "https://paper-api.alpaca.markets"


class Http:
    """GET with retries; Alpaca at most ~3 requests a second, the SEC at most 8."""

    def __init__(self, headers: dict, pause: float) -> None:
        self.s = requests.Session()
        self.s.headers.update(headers)
        self.pause = pause
        self.calls = 0

    def get(self, url: str, params: dict | None = None) -> dict | None:
        for attempt in range(8):
            time.sleep(self.pause)
            self.calls += 1
            try:
                r = self.s.get(url, params=params, timeout=60)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 404:
                return None
            if r.status_code == 403:
                raise SystemExit(f"refused (403): {url.split('?')[0]}")
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"kept failing: {url.split('?')[0]}")


def alpaca() -> Http:
    key, sec = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not sec:
        raise SystemExit("APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set")
    return Http({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}, 0.32)


def sec_http() -> Http:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        raise SystemExit("SEC_USER_AGENT is not set")
    return Http({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, 0.13)


def cmd_probe(args) -> int:
    """Data-format checks only (no strategy result): expired contracts, option bars, SEC acceptance times."""
    a, s = alpaca(), sec_http()
    out: dict = {}
    c = a.get(f"{TRADE}/v2/options/contracts", {"underlying_symbols": "AAPL", "status": "inactive",
                                                 "expiration_date_gte": "2024-02-02", "expiration_date_lte": "2024-02-09",
                                                 "strike_price_gte": "180", "strike_price_lte": "190", "limit": 50})
    rows = (c or {}).get("option_contracts", [])
    out["inactive_contracts"] = [(r["symbol"], r["expiration_date"], r["strike_price"], r["type"]) for r in rows][:12]
    syms = [r["symbol"] for r in rows if r["expiration_date"] == "2024-02-02" and float(r["strike_price"]) in (185.0, 187.5)]
    b = a.get(f"{DATA}/v1beta1/options/bars", {"symbols": ",".join(syms[:4]), "timeframe": "15Min",
                                               "start": "2024-02-01T19:00:00Z", "end": "2024-02-02T15:30:00Z",
                                               "limit": 10000})
    bars = (b or {}).get("bars", {})
    out["bars"] = {k: [(x["t"], x["vw"], x["n"]) for x in v] for k, v in bars.items()}
    d = a.get(f"{DATA}/v1beta1/options/bars", {"symbols": syms[0] if syms else "", "timeframe": "1Day",
                                               "start": "2024-01-02", "end": "2024-02-02"})
    out["first_daily"] = [(x["t"], x["c"], x["v"]) for x in (d or {}).get("bars", {}).get(syms[0] if syms else "", [])][:3]
    e = a.get(f"{DATA}/v1beta1/options/bars", {"symbols": "AAPL240119C00185000", "timeframe": "1Day",
                                               "start": "2023-10-01", "end": "2024-01-19"})
    out["pre_feb_2024_daily"] = [(x["t"], x["c"]) for x in (e or {}).get("bars", {}).get("AAPL240119C00185000", [])][:3]
    sub = s.get("https://data.sec.gov/submissions/CIK0000320193.json") or {}
    rec = sub.get("filings", {}).get("recent", {})
    out["sec_keys"] = sorted(rec)
    out["aapl_202"] = [(f, d, t, it) for f, d, t, it in zip(rec.get("form", []), rec.get("filingDate", []),
                                                           rec.get("acceptanceDateTime", []), rec.get("items", []))
                       if f == "8-K" and "2.02" in str(it)][:8]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "probe.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    # prices stay out of the public log: counts, timestamps and SEC filing times only
    print(json.dumps({"inactive_contracts": len(rows), "contract_example": out["inactive_contracts"][:2],
                      "bars": {k: [(t, n) for t, _, n in v] for k, v in out["bars"].items()},
                      "first_daily_dates": [t for t, _, _ in out["first_daily"]],
                      "pre_feb_2024_dates": [t for t, _ in out["pre_feb_2024_daily"]],
                      "sec_keys": out["sec_keys"], "aapl_202": out["aapl_202"]}, indent=1))
    return 0


def cmd_probe2(args) -> int:
    """SEC clock on known before-open (JPM, WMT, PG, JNJ) and after-close (MSFT, NVDA, META, NFLX) reporters, and
    option bars on a reaction day."""
    a, s = alpaca(), sec_http()
    ciks = {"JPM": 19617, "WMT": 104169, "PG": 80424, "JNJ": 200406, "MSFT": 789019, "NVDA": 1045810,
            "META": 1326801, "NFLX": 1065280}
    out: dict = {"sec": {}}
    for t, c in ciks.items():
        rec = (s.get(f"https://data.sec.gov/submissions/CIK{c:010d}.json") or {}).get("filings", {}).get("recent", {})
        out["sec"][t] = [(d, x) for f, d, x, it in zip(rec.get("form", []), rec.get("filingDate", []),
                                                      rec.get("acceptanceDateTime", []), rec.get("items", []))
                         if f == "8-K" and "2.02" in str(it)][:6]
    sym = "AAPL240202C00185000"
    for tf, st, en in (("15Min", "2024-02-02T13:00:00Z", "2024-02-02T22:00:00Z"),
                       ("1Min", "2024-02-02T14:30:00Z", "2024-02-02T15:00:00Z"),
                       ("1Day", "2024-01-29", "2024-02-02")):
        b = a.get(f"{DATA}/v1beta1/options/bars", {"symbols": sym, "timeframe": tf, "start": st, "end": en,
                                                   "limit": 10000})
        out[tf] = [(x["t"], x["n"]) for x in (b or {}).get("bars", {}).get(sym, [])]
    t = a.get(f"{DATA}/v1beta1/options/trades", {"symbols": sym, "start": "2024-02-02T14:30:00Z",
                                                 "end": "2024-02-02T14:40:00Z", "limit": 5})
    out["trades"] = [x.get("t") for x in (t or {}).get("trades", {}).get(sym, [])]
    q = a.get(f"{DATA}/v1beta1/options/quotes", {"symbols": sym, "start": "2024-02-01T20:00:00Z",
                                                 "end": "2024-02-01T20:05:00Z", "limit": 5})
    out["hist_quotes"] = None if q is None else len(q.get("quotes", {}).get(sym, []))
    print(json.dumps(out))
    return 0


def cmd_probe3(args) -> int:
    """Option bars on the reaction day for a contract that does not expire that day, and on its own expiry day."""
    a = alpaca()
    out = {}
    for sym, st, en in (("AAPL240209C00185000", "2024-02-02T14:00:00Z", "2024-02-02T21:00:00Z"),
                        ("AAPL240209C00185000", "2024-02-09T14:00:00Z", "2024-02-09T21:00:00Z"),
                        ("MSFT240202C00400000", "2024-01-31T14:00:00Z", "2024-01-31T21:00:00Z"),
                        ("MSFT240202C00400000", "2024-02-02T14:00:00Z", "2024-02-02T21:00:00Z")):
        b = a.get(f"{DATA}/v1beta1/options/bars", {"symbols": sym, "timeframe": "15Min", "start": st, "end": en,
                                                   "limit": 10000})
        out[f"{sym} {st[:10]}"] = [(x["t"][11:16], x["n"]) for x in (b or {}).get("bars", {}).get(sym, [])]
    print(json.dumps(out))
    return 0


def _cached_json(path: Path, fetch):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def _frame(bars: dict[str, list]) -> pd.DataFrame:
    rows = [(s, b["t"], b["vw"], b["c"], b["v"]) for s, v in bars.items() for b in v]
    df = pd.DataFrame(rows, columns=["symbol", "t", "vw", "c", "v"])
    if len(df):
        df["t"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert(eo.NY).dt.tz_localize(None)
    return df


def fetch_bars(a: Http, url: str, syms: list[str], params: dict) -> dict[str, list]:
    """All pages of a multi-symbol bars request; a batch the API rejects (400/422) is split in two."""
    out: dict[str, list] = {}

    def run(batch: list[str]) -> None:
        got: dict[str, list] = {}
        p = dict(params, symbols=",".join(batch), limit=10000)
        while True:
            try:
                j = a.get(url, p) or {}
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if code in (400, 422):
                    if len(batch) > 1:
                        mid = len(batch) // 2
                        run(batch[:mid])
                        run(batch[mid:])
                    return
                raise
            for s, v in (j.get("bars") or {}).items():
                got.setdefault(s, []).extend(v)
            tok = j.get("next_page_token")
            if not tok:
                break
            p["page_token"] = tok
        for s, v in got.items():
            out.setdefault(s, []).extend(v)

    for i in range(0, len(syms), 100):
        run(syms[i:i + 100])
    return out


def _utc(d: pd.Timestamp, hhmm: str) -> str:
    return f"{d.date()}T{hhmm}:00Z"


def daily_frame(a: Http, syms: list[str], end: str, folder: Path) -> pd.DataFrame:
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    for i in range(0, len(syms), 100):
        f = folder / f"{i:05d}.parquet"
        if not f.exists():
            bars = fetch_bars(a, f"{DATA}/v2/stocks/bars", syms[i:i + 100],
                              {"timeframe": "1Day", "start": "2020-10-01", "end": end, "adjustment": "split",
                               "feed": "sip"})
            df = _frame(bars)
            df["date"] = df["t"].dt.normalize()
            df.drop(columns=["t", "vw"]).to_parquet(f, index=False)
        parts.append(pd.read_parquet(f))
        if i % 2000 == 0:
            print(f"daily {i}/{len(syms)}", flush=True)
    return pd.concat(parts, ignore_index=True)


def sec_releases(s: Http, cik: int, folder: Path) -> list[str]:
    def fetch():
        sub = s.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        if sub is None:
            return []
        blocks = [sub.get("filings", {}).get("recent", {})]
        for f in sub.get("filings", {}).get("files", []):
            if f.get("filingTo", "9999") >= "2020-09-01":
                blocks.append(s.get(f"https://data.sec.gov/submissions/{f['name']}") or {})
        out = []
        for b in blocks:
            for form, d, acc, it in zip(b.get("form", []), b.get("filingDate", []), b.get("acceptanceDateTime", []),
                                        b.get("items", [])):
                if form == "8-K" and "2.02" in str(it).split(",") and d >= "2020-09-01" and acc:
                    out.append(acc)
        return sorted(set(out))
    return _cached_json(folder / f"{cik}.json", fetch)


def gap_days(a: Http, spy: pd.Series, sessions: pd.DatetimeIndex, end: pd.Timestamp, folder: Path) -> list[str]:
    """Sessions on which SPY's call nearest the money of the next expiry has no 15-minute bar."""
    def fetch():
        days = sessions[(sessions >= pd.Timestamp("2024-01-22")) & (sessions <= end)]
        chain = []
        for m in pd.period_range(days[0], days[-1], freq="M"):
            px = spy[(spy.index >= m.start_time) & (spy.index <= m.end_time)]
            lo, hi = 0.97 * px.min(), 1.03 * px.max()
            for status in ("inactive", "active"):
                chain += contracts(a, "SPY", status, m.start_time, m.end_time + pd.Timedelta(days=7), lo, hi, "call")
        ch = pd.DataFrame(chain).drop_duplicates("symbol")
        ch["exp"] = pd.to_datetime(ch["expiration_date"])
        ch["k"] = ch["strike_price"].astype(float)
        want = {}
        for d in days:
            prev = spy[spy.index < d]
            nxt = ch[ch["exp"] > d]
            if prev.empty or nxt.empty:
                continue
            e = nxt["exp"].min()
            g = nxt[nxt["exp"] == e]
            want[d] = g.iloc[int((g["k"] - prev.iloc[-1]).abs().argmin())]["symbol"]
        gaps = []
        items = list(want.items())
        for i in range(0, len(items), 100):
            chunk = items[i:i + 100]
            bars = _frame(fetch_bars(a, f"{DATA}/v1beta1/options/bars", sorted({s for _, s in chunk}),
                                     {"timeframe": "15Min", "start": _utc(chunk[0][0], "13:00"),
                                      "end": _utc(chunk[-1][0], "21:15")}))
            seen = set(zip(bars["symbol"], bars["t"].dt.normalize())) if len(bars) else set()
            gaps += [str(d.date()) for d, s in chunk if (s, d) not in seen]
        return gaps
    return _cached_json(folder / "gaps.json", fetch)


def contracts(a: Http, sym: str, status: str, lo_exp: pd.Timestamp, hi_exp: pd.Timestamp, lo_k: float, hi_k: float,
              kind: str | None = None) -> list[dict]:
    p = {"underlying_symbols": sym, "status": status, "expiration_date_gte": str(lo_exp.date()),
         "expiration_date_lte": str(hi_exp.date()), "strike_price_gte": f"{lo_k:.2f}",
         "strike_price_lte": f"{hi_k:.2f}", "limit": 10000}
    if kind:
        p["type"] = kind
    out = []
    while True:
        j = a.get(f"{TRADE}/v2/options/contracts", p) or {}
        out += [{k: c.get(k) for k in ("symbol", "expiration_date", "strike_price", "type", "root_symbol", "size")}
                for c in j.get("option_contracts", [])]
        tok = j.get("next_page_token")
        if not tok:
            return out
        p["page_token"] = tok


def _days(df: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], pd.DataFrame]:
    if df.empty:
        return {}
    df = df.sort_values(["symbol", "t"])
    return {k: g for k, g in df.groupby([df["symbol"], df["t"].dt.normalize()])}


def _load(folder: Path, prefix: str = "") -> pd.DataFrame:
    fs = sorted(folder.glob(f"{prefix}*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True) if fs else pd.DataFrame(
        columns=["symbol", "t", "vw", "c", "v"])


def _plan_row(ev, sessions, chains, sday) -> dict | None:
    """Expiry, strikes per entry lag (0, 3, 5) and the contracts to download for one event."""
    ch = chains.get(ev.symbol)
    if ch is None or ch.empty:
        return None
    nxt = ch[ch["exp"] > ev.R]
    nxt = nxt[nxt["exp"] <= ev.R + pd.Timedelta(days=35)]
    if nxt.empty:
        return None
    exp = nxt["exp"].min()
    g = nxt[nxt["exp"] == exp]
    both = g.groupby("k")["type"].nunique()
    ks = both[both == 2].index.to_numpy()
    if not len(ks):
        return None
    sym = {(r.type[0].upper(), float(r.k)): r.symbol for r in g.itertuples()}
    row = {"symbol": ev.symbol, "R": ev.R, "exp": exp, "strikes": [float(k) for k in ks]}
    for lag in (0, 3, 5):
        en = sessions[ev.iR - 1 - lag]
        s = eo.price_entry(sday.get((ev.symbol, en)))
        if s is None:
            row[f"k{lag}"] = None
            continue
        k = eo.atm(ks, s)
        row[f"k{lag}"] = k
        row[f"C{lag}"], row[f"P{lag}"] = sym[("C", k)], sym[("P", k)]
    row["occ"] = sym
    return row


def cmd_data(args) -> int:
    a, s = alpaca(), sec_http()
    C = args.cache
    C.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp(args.end)
    tick = _cached_json(C / "company_tickers.json", lambda: s.get("https://www.sec.gov/files/company_tickers.json"))
    ciks: dict[str, int] = {}
    for v in tick.values():
        t = str(v["ticker"]).upper()
        if re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", t):
            ciks.setdefault(t.replace("-", "."), int(v["cik_str"]))
    if args.symbols:
        ciks = {k: v for k, v in ciks.items() if k in set(args.symbols.split(","))}
    syms = sorted(ciks)
    daily = daily_frame(a, syms + ["SPY"], str(end.date()), C / "daily")
    sessions = pd.DatetimeIndex(sorted(daily.loc[daily["symbol"] == "SPY", "date"].unique()))
    daily = daily[daily["symbol"] != "SPY"].sort_values(["symbol", "date"])
    daily["dv"] = daily["c"] * daily["v"]
    daily["med20"] = daily.groupby("symbol")["dv"].transform(lambda x: x.shift(1).rolling(20, min_periods=15).median())
    recent = daily[(daily["date"] >= "2024-01-01") & (daily["med20"] >= eo.MIN_DVOL) & (daily["c"] >= 5)]
    cand = recent.groupby("symbol")["dv"].mean()
    best: dict[int, str] = {}
    for sym, dv in cand.sort_values(ascending=False).items():
        best.setdefault(ciks[sym], sym)
    keep = sorted(best.values())
    print(f"tickers {len(syms)}, liquid since 2024 {len(cand)}, one per CIK {len(keep)}", flush=True)
    rel = []
    for i, sym in enumerate(keep):
        rel += [(sym, eo.sec_time(x)) for x in sec_releases(s, ciks[sym], C / "sec")]
        if i % 200 == 0:
            print(f"sec {i}/{len(keep)}", flush=True)
    filings = pd.DataFrame(rel, columns=["symbol", "t"])
    closes = {k: g.set_index("date")["c"] for k, g in daily[daily["symbol"].isin(keep)].groupby("symbol")}
    ev = eo.history(eo.build_events(filings, sessions), closes, sessions)
    ev = ev[ev["scheduled"] & (ev["R"] >= eo.DISCOVERY[0]) & (ev["R"] <= end) & (ev["iR"] >= 26)].copy()
    dvol = {k: g.set_index("date")["dv"] for k, g in daily[daily["symbol"].isin(keep)].groupby("symbol")}
    for lag in (0, 3, 5):
        ev[f"liq{lag}"] = [eo.dollar_volume_ok(dvol[r.symbol], sessions, sessions[r.iR - 1 - lag])
                           for r in ev.itertuples()]
        ev[f"dv{lag}"] = [float(dvol[r.symbol].reindex(sessions[r.iR - 21 - lag:r.iR - 1 - lag]).median())
                          for r in ev.itertuples()]
    ev = ev[ev[["liq0", "liq3", "liq5"]].any(axis=1)].reset_index(drop=True)
    ev.to_parquet(C / "events.parquet", index=False)
    print(f"events {len(ev)} ({ev['symbol'].nunique()} symbols)", flush=True)
    spy = daily_frame(a, ["SPY"], str(end.date()), C / "spy").set_index("date")["c"]
    gaps = gap_days(a, spy, sessions, end, C)
    print(f"gap days {len(gaps)}: {gaps[:20]}", flush=True)
    sf = C / "stock15"
    sf.mkdir(exist_ok=True)
    for r, g in ev.groupby("R"):
        f = sf / f"{r.date()}.parquet"
        if not f.exists():
            st = sessions[int(g["iR"].iloc[0]) - 7]
            _frame(fetch_bars(a, f"{DATA}/v2/stocks/bars", sorted(g["symbol"].unique()),
                              {"timeframe": "15Min", "start": _utc(st, "13:00"), "end": _utc(r, "21:15"),
                               "adjustment": "raw", "feed": "sip"})).to_parquet(f, index=False)
    sday = _days(_load(sf))
    print(f"stock days {len(sday)}", flush=True)
    cf = C / "contracts"
    cf.mkdir(exist_ok=True)
    chains = {}
    for sym, g in ev.groupby("symbol"):
        f = cf / f"{sym}.parquet"
        if not f.exists():
            px = [eo.last_close(sday.get((sym, e))) for e in g["E"]]
            px = [p for p in px if p]
            if not px:
                continue
            lo_e, hi_e = g["R"].min() + pd.Timedelta(days=1), g["R"].max() + pd.Timedelta(days=35)
            rows = contracts(a, sym, "inactive", lo_e, hi_e, 0.6 * min(px), 1.4 * max(px))
            if hi_e >= pd.Timestamp.now().normalize() - pd.Timedelta(days=3):
                rows += contracts(a, sym, "active", lo_e, hi_e, 0.6 * min(px), 1.4 * max(px))
            pd.DataFrame(rows, columns=["symbol", "expiration_date", "strike_price", "type", "root_symbol",
                                        "size"]).drop_duplicates("symbol").to_parquet(f, index=False)
        ch = pd.read_parquet(f)
        ch = ch[(ch["root_symbol"].fillna(sym) == sym) & (ch["size"].fillna("100").astype(str) == "100")].copy()
        ch["exp"] = pd.to_datetime(ch["expiration_date"])
        ch["k"] = ch["strike_price"].astype(float)
        chains[sym] = ch
    plan = [p for p in (_plan_row(r, sessions, chains, sday) for r in ev.itertuples()) if p]
    print(f"planned events {len(plan)}", flush=True)
    of = C / "opt"
    of.mkdir(exist_ok=True)
    by_r: dict[pd.Timestamp, set] = {}
    for p in plan:
        by_r.setdefault(p["R"], set()).update(p[f"{x}{lag}"] for x in "CP" for lag in (0, 3, 5) if p.get(f"k{lag}"))
    for n, (r, syms_r) in enumerate(sorted(by_r.items())):
        f = of / f"A_{r.date()}.parquet"
        if not f.exists():
            st = sessions[sessions.get_loc(r) - 6]
            _frame(fetch_bars(a, f"{DATA}/v1beta1/options/bars", sorted(syms_r),
                              {"timeframe": "15Min", "start": _utc(st, "13:00"), "end": _utc(r, "21:15")})
                   ).to_parquet(f, index=False)
        if n % 50 == 0:
            print(f"option bars A {n}/{len(by_r)}", flush=True)
    oday = _days(_load(of, "A_"))
    by_r = {}
    for p in plan:
        e = sessions[sessions.get_loc(p["R"]) - 1]
        if p.get("k0") is None:
            continue
        pc, pp = eo.price_entry(oday.get((p["C0"], e))), eo.price_entry(oday.get((p["P0"], e)))
        st = eo.price_entry(sday.get((p["symbol"], e)))
        if pc is None or pp is None or not st:
            continue
        w = eo.wings(np.array(p["strikes"]), p["k0"], (pc + pp) / st)
        if w is None:
            continue
        p["kc"], p["kp"] = w
        p["WC"], p["WP"] = p["occ"][("C", w[0])], p["occ"][("P", w[1])]
        by_r.setdefault(p["R"], set()).update((p["WC"], p["WP"]))
    for r, syms_r in sorted(by_r.items()):
        f = of / f"B_{r.date()}.parquet"
        if not f.exists():
            st = sessions[sessions.get_loc(r) - 1]
            _frame(fetch_bars(a, f"{DATA}/v1beta1/options/bars", sorted(syms_r),
                              {"timeframe": "15Min", "start": _utc(st, "13:00"), "end": _utc(r, "21:15")})
                   ).to_parquet(f, index=False)
    cols = ["symbol", "R", "exp", "k0", "k3", "k5", "kc", "kp", "C0", "P0", "C3", "P3", "C5", "P5", "WC", "WP"]
    pd.DataFrame([{c: p.get(c) for c in cols} for p in plan], columns=cols).to_parquet(C / "plan.parquet", index=False)
    pd.Series(sessions).to_frame("session").to_parquet(C / "sessions.parquet", index=False)
    print(f"done; alpaca calls {a.calls}, sec calls {s.calls}", flush=True)
    return 0


def _leg_out(oday, occ, kind, k, day, s_last, short: bool, p_in: float, rule) -> tuple[float, bool]:
    p = rule(oday.get((occ, day)))
    if p is not None:
        return p, False
    v = eo.intrinsic(kind, k, s_last) if s_last else 0.0
    return (v + 0.1 * p_in if short else v), True


def trades(C: Path) -> tuple[pd.DataFrame, dict]:
    ev = pd.read_parquet(C / "events.parquet")
    plan = pd.read_parquet(C / "plan.parquet")
    sessions = pd.DatetimeIndex(pd.read_parquet(C / "sessions.parquet")["session"])
    gaps = {pd.Timestamp(g) for g in json.loads((C / "gaps.json").read_text(encoding="utf-8"))}
    sday = _days(_load(C / "stock15"))
    oday = _days(_load(C / "opt"))
    df = ev.merge(plan, on=["symbol", "R"], how="left")
    rows, drop = [], {"events": len(df), "no_plan": 0, "gap": 0}
    for e in df.itertuples():
        if pd.isna(e.exp):
            drop["no_plan"] += 1
            continue
        iE = e.iR - 1
        if any(sessions[iE - lag] in gaps for lag in (0, 3, 5)) or e.R in gaps:
            drop["gap"] += 1
            continue
        period = "discovery" if e.R <= eo.DISCOVERY[1] else "validation"
        y, w, _ = e.R.isocalendar()
        base = {"symbol": e.symbol, "R": e.R, "period": period, "week": f"{y}-{w:02d}", "year": e.R.year,
                "timing": "before_open" if e.t.normalize() == e.R else "after_close"}
        E = sessions[iE]
        s_r = eo.last_close(sday.get((e.symbol, e.R)))
        s_e = eo.last_close(sday.get((e.symbol, E)))

        def ok(lag: int, e=e, iE=iE) -> bool:
            en = sessions[iE - lag]
            prior = eo.last_close(sday.get((e.symbol, sessions[iE - lag - 1])))
            return bool(getattr(e, f"liq{lag}") and prior is not None and prior >= eo.MIN_PRICE
                        and getattr(e, f"k{lag}") is not None and not pd.isna(getattr(e, f"k{lag}"))
                        and eo.price_entry(sday.get((e.symbol, en))) is not None)

        def add(trial, net, net_high, entry, exit_, prio, fb, e=e, base=base):
            rows.append(dict(base, trial=trial, net=net, net_high=net_high, entry=entry, exit=exit_, priority=prio,
                             fallback=fb, dv=getattr(e, "dv0")))

        for trial, lag in eo.ENTRY_LAG.items():
            if not ok(lag):
                continue
            en = sessions[iE - lag]
            c, p, k = getattr(e, f"C{lag}"), getattr(e, f"P{lag}"), getattr(e, f"k{lag}")
            pc, pp = eo.price_entry(oday.get((c, en))), eo.price_entry(oday.get((p, en)))
            if pc is None or pp is None:
                continue
            oc, fc = _leg_out(oday, c, "C", k, E, s_e, False, pc, eo.price_eve_exit)
            op, fp = _leg_out(oday, p, "P", k, E, s_e, False, pp, eo.price_eve_exit)
            add(trial, eo.long_return([pc, pp], [oc, op], eo.BASE), eo.long_return([pc, pp], [oc, op], eo.HIGH),
                en + pd.Timedelta(hours=15, minutes=30), E + pd.Timedelta(hours=15, minutes=30), e.dv0, fc or fp)
        if not ok(0):
            continue
        k = e.k0
        pc, pp = eo.price_entry(oday.get((e.C0, E))), eo.price_entry(oday.get((e.P0, E)))
        st = eo.price_entry(sday.get((e.symbol, E)))
        if pc is None or pp is None:
            continue
        im = (pc + pp) / st
        ratio = im / e.hm if e.hm and not pd.isna(e.hm) and e.hm > 0 else float("nan")
        t_in, t_out = E + pd.Timedelta(hours=15, minutes=30), e.R + pd.Timedelta(hours=9, minutes=45)
        oc, fc = _leg_out(oday, e.C0, "C", k, e.R, s_r, False, pc, eo.price_morning)
        op, fp = _leg_out(oday, e.P0, "P", k, e.R, s_r, False, pp, eo.price_morning)
        s_out = eo.price_morning(sday.get((e.symbol, e.R)))
        move = abs(s_out / st - 1) if s_out else float("nan")
        straddle = (eo.long_return([pc, pp], [oc, op], eo.BASE), eo.long_return([pc, pp], [oc, op], eo.HIGH))
        prio = -ratio if ratio == ratio else -1e9
        base.update(im=im, move=move, ratio=ratio)
        add("H2_hold_all", *straddle, t_in, t_out, prio, fc or fp)
        if ratio < 0.8:
            add("H2_cheap_08", *straddle, t_in, t_out, prio, fc or fp)
        if ratio < 0.6:
            add("H2_cheap_06", *straddle, t_in, t_out, prio, fc or fp)
        if not pd.isna(e.mom):
            pin, pout, fb = (pc, oc, fc) if e.mom > 0 else (pp, op, fp)
            add("H3_momentum", eo.long_return([pin], [pout], eo.BASE), eo.long_return([pin], [pout], eo.HIGH),
                t_in, t_out, e.dv0, fb)
        if not pd.isna(e.last_sign):
            pin, pout, fb = (pc, oc, fc) if e.last_sign > 0 else (pp, op, fp)
            add("H3_last_reaction", eo.long_return([pin], [pout], eo.BASE), eo.long_return([pin], [pout], eo.HIGH),
                t_in, t_out, e.dv0, fb)
        if pd.isna(e.WC) or e.WC is None:
            continue
        wc, wp = eo.price_entry(oday.get((e.WC, E))), eo.price_entry(oday.get((e.WP, E)))
        if wc is None or wp is None:
            continue
        sc, f1 = _leg_out(oday, e.C0, "C", k, e.R, s_r, True, pc, eo.price_morning)
        sp, f2 = _leg_out(oday, e.P0, "P", k, e.R, s_r, True, pp, eo.price_morning)
        lc, f3 = _leg_out(oday, e.WC, "C", e.kc, e.R, s_r, False, wc, eo.price_morning)
        lp, f4 = _leg_out(oday, e.WP, "P", e.kp, e.R, s_r, False, wp, eo.price_morning)
        width = max(e.kc - k, k - e.kp)
        fb = f1 or f2 or f3 or f4
        r_b = eo.fly_return([pc, pp], [wc, wp], [sc, sp], [lc, lp], width, eo.BASE)
        r_h = eo.fly_return([pc, pp], [wc, wp], [sc, sp], [lc, lp], width, eo.HIGH)
        if r_b is None or r_h is None:
            continue
        fprio = ratio if ratio == ratio else -1e9
        add("H4_fly_all", r_b, r_h, t_in, t_out, fprio, fb)
        if ratio > 1.2:
            add("H4_fly_12", r_b, r_h, t_in, t_out, fprio, fb)
        if ratio > 1.5:
            add("H4_fly_15", r_b, r_h, t_in, t_out, fprio, fb)
    return pd.DataFrame(rows), drop


def _pct(x) -> str:
    return "-" if x is None or x != x else f"{100 * x:.2f}%"


def _num(x) -> str:
    return "-" if x is None or x != x else f"{x:.2f}"


def cmd_eval(args) -> int:
    tr, drop = trades(args.cache)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.counts_only:
        info = {"drops": drop, "trades": {} if tr.empty else tr.groupby(["trial", "period"]).size().unstack().fillna(0)
                .astype(int).to_dict(), "fallback_share": 0 if tr.empty else float(tr["fallback"].mean())}
        print(json.dumps(info, indent=1, default=str))
        (args.out / "counts.json").write_text(json.dumps(info, indent=1, default=str), encoding="utf-8")
        return 0
    res: dict = {"drops": drop, "discovery": {}, "validation": {}, "books": {}, "breakdown": {}}
    for per in ("discovery", "validation"):
        for k in eo.TRIALS:
            res[per][k] = eo.stats(tr[(tr["trial"] == k) & (tr["period"] == per)])
    res["decision"] = eo.decide(res["discovery"], res["validation"])
    cuts = tr["dv"].quantile([1 / 3, 2 / 3]).to_numpy()
    tr["tercile"] = np.where(tr["dv"] < cuts[0], "low", np.where(tr["dv"] < cuts[1], "mid", "high"))
    for k in eo.TRIALS:
        t = tr[tr["trial"] == k]
        res["breakdown"][k] = {f"{c}={v}": eo.stats(g) for c in ("timing", "tercile", "year")
                               for v, g in t.groupby(c)}
    for k in res["decision"]["discovery_pass"]:
        for per in ("discovery", "validation"):
            t = tr[(tr["trial"] == k) & (tr["period"] == per)]
            res["books"][f"{k}:{per}"] = eo.book([eo.Trade(r.entry, r.exit, r.net, r.priority) for r in t.itertuples()])
    h2 = tr[tr["trial"] == "H2_hold_all"]
    res["implied_vs_realized"] = {per: {"mean_im": float(g["im"].mean()), "mean_move": float(g["move"].mean()),
                                        "median_ratio_im_hm": float(g["ratio"].median())}
                                  for per, g in h2.groupby("period")}
    res["fallback_share"] = {k: float(g["fallback"].mean()) for k, g in tr.groupby("trial")}
    (args.out / "summary.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    tr[["trial", "symbol", "R", "period", "timing", "net", "net_high"]].to_csv(args.out / "trades.csv", index=False)
    (args.out / "REPORT.md").write_text(render(res), encoding="utf-8")
    print(render(res))
    return 0


def render(res: dict) -> str:
    d = res["decision"]
    lines = ["# Earnings options study (pre-registered, 10 trials)", "",
             f"Events {res['drops']['events']}; without a contract plan {res['drops']['no_plan']}; on a gap day "
             f"{res['drops']['gap']}. Costs: base half-spread max(2%, $0.025), high max(4%, $0.05), $0.05 a "
             "contract a side.", "",
             "| trial | disc trades | mean | t | mean high | hit | val trades | mean | t | mean high | hit |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in eo.TRIALS:
        a, b = res["discovery"][k], res["validation"][k]
        lines.append(f"| {k} | {a.get('trades', 0)} | {_pct(a.get('mean'))} | {_num(a.get('t'))} | "
                     f"{_pct(a.get('mean_high'))} | {_pct(a.get('hit'))} | {b.get('trades', 0)} | "
                     f"{_pct(b.get('mean'))} | {_num(b.get('t'))} | {_pct(b.get('mean_high'))} | {_pct(b.get('hit'))} |")
    lines += ["", f"Discovery pass (t >= {eo.T_DISCOVERY}, mean high > 0, 200+ trades): "
              f"{', '.join(d['discovery_pass']) or 'none'}. Validation pass (t >= {eo.T_VALIDATION}, mean high > 0): "
              f"{', '.join(d['validation_pass']) or 'none'}. **{'Met' if d['met'] else 'Not met'}.**", ""]
    if res["books"]:
        lines += ["| book ($100k, 2% risk a trade, 15% at most) | taken | end | CAGR | max DD | worst session |",
                  "|---|---|---|---|---|---|"]
        for k, b in res["books"].items():
            lines.append(f"| {k} | {b['taken']} | {b['end']:,.0f} | {_pct(b['cagr'])} | {_pct(b['max_dd'])} | "
                         f"{_pct(b['worst_session'])} |")
        lines.append("")
    iv = res["implied_vs_realized"]
    lines += ["Implied move vs realized (H2_hold_all events): " + "; ".join(
        f"{p}: mean IM {_pct(v['mean_im'])}, mean |move| to 09:45 {_pct(v['mean_move'])}, median IM/HM "
        f"{_num(v['median_ratio_im_hm'])}" for p, v in iv.items()), "",
        "## Breakdown (all periods, base costs, no decision)", "",
        "| trial | group | trades | mean | t | hit |", "|---|---|---|---|---|---|"]
    for k, br in res["breakdown"].items():
        for g, s in br.items():
            lines.append(f"| {k} | {g} | {s.get('trades', 0)} | {_pct(s.get('mean'))} | {_num(s.get('t'))} | "
                         f"{_pct(s.get('hit'))} |")
    lines += ["", "Exit fallbacks (intrinsic value) share: " + ", ".join(
        f"{k} {_pct(v)}" for k, v in res["fallback_share"].items())]
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("probe")
    q.add_argument("--out", type=Path, default=Path("outputs/earnings_options"))
    q.set_defaults(fn=cmd_probe)
    q = sub.add_parser("probe2")
    q.set_defaults(fn=cmd_probe2)
    q = sub.add_parser("probe3")
    q.set_defaults(fn=cmd_probe3)
    q = sub.add_parser("data")
    q.add_argument("--cache", type=Path, default=Path("outputs/eo_cache"))
    q.add_argument("--end", required=True)
    q.add_argument("--symbols", default="")
    q.set_defaults(fn=cmd_data)
    q = sub.add_parser("eval")
    q.add_argument("--cache", type=Path, default=Path("outputs/eo_cache"))
    q.add_argument("--out", type=Path, default=Path("outputs/earnings_options"))
    q.add_argument("--counts-only", action="store_true")
    q.set_defaults(fn=cmd_eval)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
