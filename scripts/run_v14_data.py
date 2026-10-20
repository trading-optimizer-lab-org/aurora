"""v14 data: a survivorship-free US stock universe, minute bars for event days, SEC filings, crypto and macro series.

Only downloads; no strategy result is computed here. Everything is cached in the Actions cache and only coverage
statistics are printed. See docs/research/V14_PREREGISTRATION.md.

  finra    every symbol traded each day (FINRA Reg SHO daily files: consolidated NMS file, or the TRF files before it)
  daily    Alpaca daily bars, raw and split-adjusted, for every FINRA symbol; Alpaca assets; total-return ETFs
  minutes  Alpaca minute bars (04:00-16:00 ET) for the event days defined in event_days(), plus SPY, QQQ, IWM
  sec      insider purchases, offering and 13D filings, 8-K items, shares outstanding and EPS frames
  crypto   Binance spot daily klines of every USDT pair (delisted ones included), BTC/ETH hourly and funding
  macro    CBOE VIX, VIX3M, VIX9D and the scheduled FOMC statement dates
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import re
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

FIRST, LAST = pd.Timestamp("2015-06-01"), pd.Timestamp("2026-10-16")
CRYPTO_LAST = pd.Timestamp("2026-09-30")
NY = ZoneInfo("America/New_York")
BARS = "https://data.alpaca.markets/v2/stocks/bars"
ASSETS = "https://paper-api.alpaca.markets/v2/assets"
FINRA = "https://cdn.finra.org/equity/regsho/daily/{}shvol{}.txt"
TRF_FILES = ("FNSQ", "FNYX", "FNQC")  # Nasdaq Carteret, NYSE and Nasdaq Chicago TRFs; ORF (OTC) excluded
SYMBOL = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
BATCH = 50
ETFS_TR = ("SPY", "QQQ", "IWM", "DIA", "SVXY", "VXX", "VIXY", "UVXY", "TLT", "IEF", "SHY", "GLD", "XLB", "XLE", "XLF",
           "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC", "SMH", "XBI", "KRE", "HYG", "LQD", "EFA", "EEM")
INDEX_MINUTES = ("SPY", "QQQ", "IWM")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
MINUTE_COLS = ["symbol", "minute", "o", "h", "l", "c", "v", "vw", "n"]
DAILY_COLS = ["symbol", "date", "o", "h", "l", "c", "v", "vw", "n"]


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V9 = _script("run_v9")


def _ny(day: pd.Timestamp, hh: int, mm: int) -> pd.Timestamp:
    return pd.Timestamp(day.year, day.month, day.day, hh, mm, tz=NY).tz_convert("UTC")


def _http(url: str, headers: dict | None = None, tries: int = 6) -> requests.Response | None:
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=headers or {"User-Agent": "Mozilla/5.0"}, timeout=120)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (403, 404):
            return None
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r
    return None


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


# ---------------------------------------------------------------- FINRA

def parse_finra(texts: list[str], day: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for t in texts:
        for line in t.splitlines()[1:]:
            p = line.split("|")
            if len(p) >= 5 and p[0].isdigit():
                rows.append((p[1].replace("/", "."), float(p[2] or 0), float(p[4] or 0)))
    df = pd.DataFrame(rows, columns=["symbol", "short_vol", "total_vol"])
    df = df.groupby("symbol", as_index=False).sum()
    df = df[df["symbol"].str.match(SYMBOL)]
    df.insert(0, "date", day)
    return df


def _finra_day(day: pd.Timestamp, folder: Path) -> int:
    path = folder / f"{day:%Y%m%d}.parquet"
    if path.exists():
        return -1
    r = _http(FINRA.format("CNMS", f"{day:%Y%m%d}"))
    texts = [r.text] if r is not None else [x.text for x in (_http(FINRA.format(f, f"{day:%Y%m%d}"))
                                                             for f in TRF_FILES) if x is not None]
    if not texts:
        return 0
    df = parse_finra(texts, day)
    _write(df.astype({"short_vol": np.float32, "total_vol": np.float32}), path)
    return len(df)


def cmd_finra(args) -> int:
    folder = args.cache / "finra_days"
    days = pd.bdate_range(FIRST, LAST)
    with ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(_finra_day, d, folder): d for d in days}
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 500 == 0:
                print(f"FINRA: {n}/{len(days)} days", flush=True)
    files = sorted(folder.glob("*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    df["symbol"] = df["symbol"].astype("category")
    _write(df, args.cache / "finra.parquet")
    per_day = df.groupby("date").size()
    print(json.dumps({"finra_days": int(per_day.size), "symbols": int(df["symbol"].nunique()),
                      "median_symbols_per_day": float(per_day.median()), "first": str(per_day.index.min().date()),
                      "last": str(per_day.index.max().date())}), flush=True)
    return 0


# ---------------------------------------------------------------- Alpaca daily

def _alpaca_headers() -> dict:
    key, secret = os.environ.get("APCA_API_KEY_ID"), os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise SystemExit("APCA_API_KEY_ID / APCA_API_SECRET_KEY are not set")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _bars(symbols: list[str], timeframe: str, start: pd.Timestamp, end: pd.Timestamp, adjustment: str,
          headers: dict, limiter) -> list[tuple]:
    params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start.isoformat(), "end": end.isoformat(),
              "feed": "sip", "adjustment": adjustment, "limit": 10000}
    rows = []
    while True:
        body = V9._get(BARS, params, headers, limiter) or {}
        for sym, bars in (body.get("bars") or {}).items():
            rows += [(sym, x["t"], x["o"], x["h"], x["l"], x["c"], x["v"], x.get("vw", np.nan), x.get("n", 0))
                     for x in bars]
        token = body.get("next_page_token")
        if not token:
            return rows
        params = {**params, "page_token": token}


def _daily_frame(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
    df["date"] = pd.to_datetime(df.pop("t"), utc=True).dt.tz_convert(NY).dt.normalize().dt.tz_localize(None)
    return df[DAILY_COLS]


def cmd_daily(args) -> int:
    if (args.cache / "daily.parquet").exists() and (args.cache / "etf_total_return.parquet").exists():
        print("daily bars already complete", flush=True)
        return 0
    headers = _alpaca_headers()
    r = requests.get(ASSETS, params={"asset_class": "us_equity"}, headers=headers, timeout=120)
    r.raise_for_status()
    assets = pd.DataFrame(r.json())[["symbol", "name", "exchange", "status", "tradable", "shortable",
                                     "easy_to_borrow"]]
    _write(assets, args.cache / "assets.parquet")
    finra = pd.read_parquet(args.finra / "finra.parquet", columns=["symbol"])
    symbols = sorted(set(finra["symbol"].astype(str)) | set(ETFS_TR))
    print(json.dumps({"finra_symbols": len(symbols), "alpaca_assets": len(assets),
                      "finra_in_assets": int(pd.Series(symbols).isin(assets["symbol"]).sum())}), flush=True)
    limiter = V9.Limiter(V9.ALPACA_PER_MIN / 60)
    start, end = _ny(FIRST, 0, 0), _ny(LAST, 20, 0)
    batches = [symbols[i:i + BATCH] for i in range(0, len(symbols), BATCH)]
    jobs = [(adj, k, b) for adj in ("raw", "split") for k, b in enumerate(batches)]
    t0 = time.time()

    def one(adj: str, k: int, batch: list[str]) -> None:
        path = args.cache / f"daily_{adj}" / f"batch_{k:05d}.parquet"
        if path.exists() or time.time() - t0 > args.budget_min * 60:
            return
        _write(_daily_frame(_bars(batch, "1Day", start, end, adj, headers, limiter)), path)

    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, *j) for j in jobs]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 100 == 0:
                print(f"daily bars: {n}/{len(jobs)} batches, {limiter.calls} calls", flush=True)
    done = {adj: len(list((args.cache / f"daily_{adj}").glob("batch_*.parquet"))) for adj in ("raw", "split")}
    if min(done.values()) < len(batches):
        print(f"budget reached, {done} of {len(batches)} batches; rerun to continue", flush=True)
        return 0
    raw = pd.concat([pd.read_parquet(p) for p in sorted((args.cache / "daily_raw").glob("*.parquet"))])
    spl = pd.concat([pd.read_parquet(p) for p in sorted((args.cache / "daily_split").glob("*.parquet"))])
    df = raw.merge(spl[["symbol", "date", "c"]].rename(columns={"c": "c_split"}), on=["symbol", "date"], how="left")
    for col in ("o", "h", "l", "c", "vw", "c_split"):
        df[col] = df[col].astype(np.float32)
    df["v"] = df["v"].astype(np.float64)
    df["symbol"] = df["symbol"].astype("category")
    _write(df, args.cache / "daily.parquet")
    tr = _daily_frame(_bars(list(ETFS_TR), "1Day", start, end, "all", headers, limiter))
    _write(tr, args.cache / "etf_total_return.parquet")
    for adj in ("raw", "split"):  # consolidated; keeps the cache small
        shutil.rmtree(args.cache / f"daily_{adj}")
    print(json.dumps({"daily_rows": len(df), "symbols_with_bars": int(df["symbol"].nunique()),
                      "alpaca_calls": limiter.calls}), flush=True)
    return 0


# ---------------------------------------------------------------- event days and minutes

def wide(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.pivot(index="date", columns="symbol", values=col).sort_index()


def event_days(daily: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[pd.Timestamp, list[str]]:
    """Symbol-days whose minute bars are downloaded. Every rule uses only what is known at the open (the open
    price, earlier days) except the runner scope, which is a superset of every rule that trades runners: a rule
    that needs +X% at a given minute (X >= 40) is always inside it."""
    o, h, c = (wide(daily, k).reindex(calendar) for k in ("o", "h", "c"))
    f = wide(daily, "c_split").reindex(calendar) / c  # split adjustment factor of each day
    os_, hs, cs = o * f, h * f, c * f
    prev = cs.shift(1)
    gap = os_ / prev - 1
    run = hs / prev - 1
    dv = (c * wide(daily, "v").reindex(calendar)).rolling(20, min_periods=10).mean().shift(1)
    day1 = cs.shift(1) / cs.shift(2) - 1
    small = (o >= 0.5) & (o <= 50)
    gappers = (gap >= 0.15) & small
    gap_rank = gap.where(gappers).rank(axis=1, ascending=False)
    scopes = {
        "gap_up": gappers & (gap_rank <= 80),
        "runner": (run >= 0.40) & small,
        "gap_down": (gap <= -0.20) & small,
        "day2": (day1 >= 0.50) & small,
        "in_play": ((gap.abs() >= 0.03) & (o >= 5) & (dv >= 20e6)),
    }
    play_rank = gap.abs().where(scopes["in_play"]).rank(axis=1, ascending=False)
    scopes["in_play"] &= play_rank <= 30
    need: dict[pd.Timestamp, set] = {}
    counts = {}
    for name, m in scopes.items():
        st = m.loc[FIRST + pd.Timedelta(days=40):].stack()
        st = st[st]
        counts[name] = int(len(st))
        for d, s in st.index:
            need.setdefault(d, set()).add(s)
    for d in calendar[calendar >= FIRST + pd.Timedelta(days=40)]:
        need.setdefault(d, set()).update(INDEX_MINUTES)
    print(json.dumps({"event_symbol_days": counts, "days": len(need),
                      "symbol_days": int(sum(len(v) for v in need.values()))}), flush=True)
    return {d: sorted(v) for d, v in need.items()}


def _minute_day(day: pd.Timestamp, symbols: list[str], folder: Path, headers: dict, limiter) -> None:
    path = folder / f"{day.date()}.parquet"
    if path.exists():
        return
    rows = _bars(symbols, "1Min", _ny(day, 4, 0), _ny(day, 15, 59), "raw", headers, limiter)
    df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
    start = _ny(day, 4, 0)
    df["minute"] = ((pd.to_datetime(df.pop("t"), utc=True) - start).dt.total_seconds() // 60).astype(np.int16)
    df = df[(df["minute"] >= 0) & (df["minute"] < 720)][MINUTE_COLS]
    for col in ("o", "h", "l", "c", "vw"):
        df[col] = df[col].astype(np.float32)
    df["v"] = df["v"].astype(np.float32)
    _write(df.sort_values(["symbol", "minute"]), path)


def cmd_minutes(args) -> int:
    headers = _alpaca_headers()
    daily = pd.read_parquet(args.cache / "daily.parquet", columns=["symbol", "date", "o", "h", "c", "v", "c_split"])
    daily["symbol"] = daily["symbol"].astype(str)
    calendar = pd.DatetimeIndex(sorted(daily.loc[daily["symbol"] == "SPY", "date"].unique()))
    need = event_days(daily, calendar)
    del daily
    folder = args.cache / "minutes"
    limiter = V9.Limiter(V9.ALPACA_PER_MIN / 60)
    t0 = time.time()
    todo = [(d, s) for d, s in sorted(need.items()) if not (folder / f"{d.date()}.parquet").exists()]
    print(f"minute days to fetch: {len(todo)} of {len(need)}", flush=True)

    def one(d, s):
        if time.time() - t0 < args.budget_min * 60:
            _minute_day(d, s, folder, headers, limiter)

    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, d, s) for d, s in todo]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 100 == 0:
                print(f"minute bars: {n}/{len(todo)} days, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    left = sum(1 for d in need if not (folder / f"{d.date()}.parquet").exists())
    (args.cache / "event_days.json").write_text(json.dumps({str(d.date()): s for d, s in need.items()}),
                                                encoding="utf-8")
    print(json.dumps({"minute_days_missing": left, "alpaca_calls": limiter.calls}), flush=True)
    return 0


def cmd_coverage(args) -> int:
    finra = pd.read_parquet(args.finra / "finra.parquet", columns=["date", "symbol", "total_vol"])
    finra["symbol"] = finra["symbol"].astype(str)
    daily = pd.read_parquet(args.cache / "daily.parquet", columns=["symbol", "date", "c", "v"])
    daily["symbol"] = daily["symbol"].astype(str)
    assets = pd.read_parquet(args.cache / "assets.parquet")
    status = (assets.assign(a=assets["status"] == "active").sort_values("a", ascending=False)
              .drop_duplicates("symbol").set_index("symbol")["status"])  # a symbol can be listed twice
    m = finra.merge(daily[["symbol", "date", "c"]], on=["symbol", "date"], how="left")
    m["has_bar"] = m["c"].notna()
    m["status"] = m["symbol"].map(status).fillna("unknown")
    out = {"finra_symbol_days": len(m), "with_alpaca_bar": float(m["has_bar"].mean()),
           "by_status": {k: {"symbol_days": int(len(g)), "with_bar": float(g["has_bar"].mean()),
                             "symbols": int(g["symbol"].nunique())} for k, g in m.groupby("status")},
           "by_year": {int(y): float(g["has_bar"].mean()) for y, g in m.groupby(m["date"].dt.year)}}
    d = daily.assign(dv=daily["c"] * daily["v"])
    liquid = d[(d["c"] >= 1) & (d["dv"] >= 1e6)]
    out["liquid_symbols_ever"] = int(liquid["symbol"].nunique())
    out["liquid_symbols_ever_unknown_or_inactive"] = int(liquid["symbol"].map(status).fillna("unknown")
                                                          .isin(["inactive", "unknown"]).groupby(liquid["symbol"])
                                                          .first().sum())
    print(json.dumps(out, indent=1), flush=True)
    (args.cache / "coverage.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


# ---------------------------------------------------------------- SEC

class _Sec:
    def __init__(self) -> None:
        ua = os.environ.get("SEC_USER_AGENT")
        if not ua:
            raise SystemExit("SEC_USER_AGENT is not set")
        self.headers = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
        self.limiter = V9.Limiter(8)

    def raw(self, url: str) -> bytes | None:
        for attempt in range(8):
            self.limiter.wait()
            try:
                r = requests.get(url, headers=self.headers, timeout=180)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 404:
                return None
            if r.status_code in (403, 429, 500, 502, 503, 504):
                time.sleep(2 ** attempt + 1)
                continue
            r.raise_for_status()
            return r.content
        return None

    def json(self, url: str):
        b = self.raw(url)
        return None if b is None else json.loads(b)


QUARTERS = [(y, q) for y in range(2015, 2027) for q in range(1, 5) if pd.Timestamp(y, 3 * q - 2, 1) <= LAST
            and pd.Timestamp(y, 3 * q, 1) >= pd.Timestamp("2015-04-01")]
OFFER_FORMS = {"424B1", "424B2", "424B3", "424B4", "424B5", "S-1", "S-3", "F-1", "F-3", "S-1MEF", "S-3ASR"}
FORMS = OFFER_FORMS | {"SC 13D"}


def _form_index(sec: _Sec, y: int, q: int, cache: Path) -> pd.DataFrame:
    path = cache / "form_index" / f"{y}Q{q}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    b = sec.raw(f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx")
    rows = []
    if b:
        for line in b.decode("latin-1").splitlines():
            form = re.split(r"\s{2,}", line.strip())[0]
            if form in FORMS:
                m = re.search(r"\s(\d{1,10})\s+(\d{4}-\d{2}-\d{2})\s", line)
                if m:
                    rows.append((form, int(m.group(1)), m.group(2)))
    df = pd.DataFrame(rows, columns=["form", "cik", "date"])
    _write(df, path)
    return df


def _insider(sec: _Sec, y: int, q: int, cache: Path) -> pd.DataFrame | None:
    path = cache / "insider" / f"{y}Q{q}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    b = None
    for url in (f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{q}_form345.zip",
                f"https://www.sec.gov/files/dera/data/form-345/{y}q{q}_form345.zip"):
        b = sec.raw(url)
        if b:
            break
    if not b:
        print(f"insider data set {y}Q{q}: not found", flush=True)
        return None
    z = zipfile.ZipFile(io.BytesIO(b))
    names = {n.split("/")[-1].upper(): n for n in z.namelist()}

    def read(name: str, cols: list[str]) -> pd.DataFrame:
        return pd.read_csv(z.open(names[name]), sep="\t", usecols=cols, dtype=str, low_memory=False)

    sub = read("SUBMISSION.TSV", ["ACCESSION_NUMBER", "FILING_DATE", "ISSUERCIK", "ISSUERTRADINGSYMBOL"])
    tr = read("NONDERIV_TRANS.TSV", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                                      "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"])
    own = read("REPORTINGOWNER.TSV", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"])
    tr = tr[(tr["TRANS_CODE"] == "P") & (tr["TRANS_ACQUIRED_DISP_CD"] == "A")]
    own = own.drop_duplicates("ACCESSION_NUMBER")
    df = tr.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER", how="left")
    out = pd.DataFrame({"filed": pd.to_datetime(df["FILING_DATE"], format="mixed", errors="coerce"),
                        "traded": pd.to_datetime(df["TRANS_DATE"], format="mixed", errors="coerce"),
                        "cik": pd.to_numeric(df["ISSUERCIK"], errors="coerce"),
                        "symbol": df["ISSUERTRADINGSYMBOL"].str.upper().str.strip(),
                        "owner": pd.to_numeric(df["RPTOWNERCIK"], errors="coerce"),
                        "role": df["RPTOWNER_RELATIONSHIP"].fillna(""),
                        "shares": pd.to_numeric(df["TRANS_SHARES"], errors="coerce"),
                        "price": pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce")})
    tick = sub.assign(filed=pd.to_datetime(sub["FILING_DATE"], format="mixed", errors="coerce"),
                      cik=pd.to_numeric(sub["ISSUERCIK"], errors="coerce"),
                      symbol=sub["ISSUERTRADINGSYMBOL"].str.upper().str.strip())[["filed", "cik", "symbol"]]
    _write(tick.dropna().drop_duplicates(["cik", "symbol"]), cache / "tickers" / f"{y}Q{q}.parquet")
    _write(out, path)
    return out


def _submissions(sec: _Sec, cik: int, cache: Path) -> list[tuple]:
    path = cache / "submissions" / f"{cik}.json"
    if path.exists():
        return [tuple(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    sub = sec.json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    rows: list[tuple] = []
    if sub and "filings" in sub:
        blocks = [sub["filings"].get("recent", {})]
        for f in sub["filings"].get("files", []):
            if f.get("filingTo", "9999") >= "2015-01-01":
                blocks.append(sec.json(f"https://data.sec.gov/submissions/{f['name']}") or {})
        for b in blocks:
            for form, date, items, acc in zip(b.get("form", []), b.get("filingDate", []), b.get("items", []),
                                              b.get("accessionNumber", [])):
                if date >= "2015-01-01" and form in ("8-K", "10-Q", "10-K", "20-F", "6-K"):
                    rows.append((form, date, str(items), acc))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def _frames(sec: _Sec, cache: Path) -> pd.DataFrame:
    path = cache / "frames.parquet"
    if path.exists():
        return pd.read_parquet(path)
    rows = []
    for y, q in QUARTERS:
        for tag, unit, kind in (("dei/EntityCommonStockSharesOutstanding", "shares", "I"),
                                ("us-gaap/EarningsPerShareBasic", "USD-per-shares", ""),
                                ("us-gaap/EarningsPerShareDiluted", "USD-per-shares", "")):
            body = sec.json(f"https://data.sec.gov/api/xbrl/frames/{tag}/{unit}/CY{y}Q{q}{kind}.json")
            for x in (body or {}).get("data", []):
                rows.append((tag.split("/")[1], y, q, int(x["cik"]), x.get("end"), float(x["val"]), x.get("accn")))
    df = pd.DataFrame(rows, columns=["tag", "year", "quarter", "cik", "end", "val", "accn"])
    _write(df, path)
    return df


def cmd_sec(args) -> int:
    sec = _Sec()
    cache = args.cache
    tick = sec.json("https://www.sec.gov/files/company_tickers.json") or {}
    current = pd.DataFrame([(int(v["cik_str"]), str(v["ticker"]).upper()) for v in tick.values()],
                           columns=["cik", "symbol"])
    _write(current, cache / "company_tickers.parquet")
    ins = [x for x in (_insider(sec, y, q, cache) for y, q in QUARTERS) if x is not None]
    forms = pd.concat([_form_index(sec, y, q, cache) for y, q in QUARTERS], ignore_index=True)
    frames = _frames(sec, cache)
    hist = pd.concat([pd.read_parquet(p) for p in (cache / "tickers").glob("*.parquet")], ignore_index=True) \
        if (cache / "tickers").exists() else pd.DataFrame(columns=["filed", "cik", "symbol"])
    ciks = sorted(set(current["cik"]) | set(hist["cik"].dropna().astype(int)))
    with ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(_submissions, sec, c, cache): c for c in ciks}
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 1000 == 0:
                print(f"SEC submissions: {n}/{len(ciks)}, {sec.limiter.calls} calls", flush=True)
    rows = []
    for c in ciks:
        rows += [(c, *r) for r in _submissions(sec, c, cache)]
    filings = pd.DataFrame(rows, columns=["cik", "form", "date", "items", "accn"])
    _write(filings, cache / "filings.parquet")
    print(json.dumps({"insider_quarters": len(ins), "insider_buys": int(sum(len(x) for x in ins)),
                      "offering_or_13d_filings": len(forms), "frames_rows": len(frames), "ciks": len(ciks),
                      "filings_rows": len(filings), "sec_calls": sec.limiter.calls}), flush=True)
    return 0


# ---------------------------------------------------------------- crypto

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
VISION = "https://data.binance.vision/"
STABLE = {"USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD", "EUR", "GBP", "AUD", "USTC", "UST", "SUSD", "USDS"}
KLINE = ["open_time", "o", "h", "l", "c", "v", "close_time", "qv", "trades", "tb", "tq", "ignore"]


def _s3_list(prefix: str, delimiter: str = "/") -> tuple[list[str], list[str]]:
    keys, prefixes, marker = [], [], ""
    while True:
        r = _http(f"{S3}?delimiter={delimiter}&prefix={prefix}&marker={marker}")
        if r is None:
            return keys, prefixes
        txt = r.text
        keys += re.findall(r"<Key>([^<]+)</Key>", txt)
        prefixes += re.findall(r"<Prefix>([^<]+)</Prefix>", txt)[1:]
        nxt = re.search(r"<NextMarker>([^<]+)</NextMarker>", txt)
        if "<IsTruncated>true</IsTruncated>" not in txt:
            return keys, prefixes
        marker = nxt.group(1) if nxt else (keys[-1] if keys else prefixes[-1])


def _kline_zip(key: str) -> pd.DataFrame:
    r = _http(VISION + key)
    if r is None:
        return pd.DataFrame(columns=KLINE)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    df = pd.read_csv(z.open(z.namelist()[0]), header=None)
    if not str(df.iloc[0, 0]).isdigit():
        df = df.iloc[1:]
    df = df.iloc[:, :12]
    df.columns = KLINE
    return df.astype({"open_time": np.int64})


def _kline_frame(frames: list[pd.DataFrame], symbol: str) -> pd.DataFrame:
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=["symbol", "time", "o", "h", "l", "c", "v", "qv"])
    df = pd.concat(frames, ignore_index=True)
    t = df["open_time"].to_numpy()
    t = np.where(t > 10 ** 14, t // 1000, t)  # microseconds from 2025 on
    out = pd.DataFrame({"symbol": symbol, "time": pd.to_datetime(t, unit="ms")})
    for k in ("o", "h", "l", "c", "v", "qv"):
        out[k] = pd.to_numeric(df[k], errors="coerce").astype(np.float64)
    return out.drop_duplicates("time").sort_values("time")


def _crypto_symbol(sym: str, interval: str, cache: Path) -> pd.DataFrame:
    path = cache / f"klines_{interval}" / f"{sym}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    keys, _ = _s3_list(f"data/spot/monthly/klines/{sym}/{interval}/", delimiter="")
    keys = [k for k in keys if k.endswith(".zip") and k[-11:-4] <= f"{CRYPTO_LAST:%Y-%m}"]
    df = _kline_frame([_kline_zip(k) for k in keys], sym)
    _write(df, path)
    return df


def cmd_crypto(args) -> int:
    _, prefixes = _s3_list("data/spot/monthly/klines/")
    pairs = sorted(p.split("/")[-2] for p in prefixes)
    lev = re.compile(r"(UP|DOWN|BULL|BEAR)USDT$")
    usdt = [p for p in pairs if p.endswith("USDT") and p[:-4] not in STABLE and not lev.search(p)]
    print(json.dumps({"binance_spot_pairs": len(pairs), "usdt_pairs": len(usdt)}), flush=True)
    with ThreadPoolExecutor(12) as ex:
        futs = [ex.submit(_crypto_symbol, s, "1d", args.cache) for s in usdt]
        for n, f in enumerate(as_completed(futs)):
            f.result()
            if n % 100 == 0:
                print(f"crypto daily: {n}/{len(usdt)}", flush=True)
    for s in ("BTCUSDT", "ETHUSDT"):
        _crypto_symbol(s, "1h", args.cache)
    funding = []
    for s in ("BTCUSDT", "ETHUSDT"):
        keys, _ = _s3_list(f"data/futures/um/monthly/fundingRate/{s}/", delimiter="")
        for k in keys:
            if k.endswith(".zip") and k[-11:-4] <= f"{CRYPTO_LAST:%Y-%m}":
                r = _http(VISION + k)
                if r is not None:
                    z = zipfile.ZipFile(io.BytesIO(r.content))
                    f = pd.read_csv(z.open(z.namelist()[0]))
                    f["symbol"] = s
                    funding.append(f)
    if funding:
        _write(pd.concat(funding, ignore_index=True), args.cache / "funding.parquet")
    daily = pd.concat([pd.read_parquet(p) for p in (args.cache / "klines_1d").glob("*.parquet")], ignore_index=True)
    _write(daily, args.cache / "crypto_daily.parquet")
    last = daily.groupby("symbol")["time"].max()
    print(json.dumps({"crypto_symbols_with_data": int(daily["symbol"].nunique()),
                      "ended_before_2026_09": int((last < pd.Timestamp("2026-09-01")).sum()),
                      "funding_rows": int(sum(len(f) for f in funding))}), flush=True)
    return 0


# ---------------------------------------------------------------- macro

def parse_fomc(html_by_year: dict[int, str], calendar_html: str) -> list[pd.Timestamp]:
    """Scheduled FOMC statement days (the last day of each scheduled meeting)."""
    mon = "|".join(MONTHS + tuple(m[:3] for m in MONTHS))
    pat = re.compile(rf"\b({mon})(?:/({mon}))?\s+(\d{{1,2}})(?:-(\d{{1,2}}))?(\*?)\s+(?:Meeting|Statement)")
    full = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}
    out = []

    def add(year: int, text: str) -> None:
        for m1, m2, d1, d2, _ in pat.findall(text):
            month = full[(m2 or m1)[:3]]
            day = int(d2 or d1)
            out.append(pd.Timestamp(year, month, day))

    for year, html in html_by_year.items():
        add(year, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)))
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", calendar_html))
    parts = re.split(r"(\d{4}) FOMC Meetings", txt)
    for i in range(1, len(parts) - 1, 2):
        add(int(parts[i]), parts[i + 1])
    days = sorted(set(d for d in out if FIRST.year <= d.year <= LAST.year + 1))
    return days


def cmd_macro(args) -> int:
    args.cache.mkdir(parents=True, exist_ok=True)
    for name in ("VIX", "VIX3M", "VIX9D"):
        r = _http(f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv")
        if r is None:
            raise SystemExit(f"CBOE {name} not available")
        (args.cache / f"{name}.csv").write_text(r.text, encoding="utf-8")
    hist = {}
    for y in range(2015, 2021):
        r = _http(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm")
        if r is not None:
            hist[y] = r.text
    cal = _http("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
    days = parse_fomc(hist, cal.text if cal is not None else "")
    per_year = pd.Series(1, index=pd.DatetimeIndex(days)).groupby(lambda d: d.year).sum().to_dict()
    pd.Series(days, name="date").to_csv(args.cache / "fomc.csv", index=False)
    print(json.dumps({"fomc_days": len(days), "per_year": {int(k): int(v) for k, v in per_year.items()}}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("finra", "daily", "minutes", "coverage", "sec", "crypto", "macro"))
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--finra", type=Path, default=Path("outputs/v14/finra"))
    ap.add_argument("--budget-min", type=float, default=300.0)
    args = ap.parse_args()
    return {"finra": cmd_finra, "daily": cmd_daily, "minutes": cmd_minutes, "coverage": cmd_coverage, "sec": cmd_sec,
            "crypto": cmd_crypto, "macro": cmd_macro}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
