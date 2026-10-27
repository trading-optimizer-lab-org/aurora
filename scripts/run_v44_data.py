"""v44 data (V44_PREREGISTRATION.md section 0). Market data stays in the Actions cache; only counts are printed.

  edgar    acceptance times, forms and 8-K items of the companies of v14's ticker history, 2018+ (SEC submissions bulk)
  btc      BTCUSDT one-minute closes (data.binance.vision; Coinbase BTC-USD candles for a missing month)
  index    SPY and IWM one-minute bars, 04:00-19:59
  ticks    per-minute trade and quote aggregates of the book's entry sessions (v43's trades)
  filing   one-minute bars and a store of the filing symbol-days not in the event, liquid or mover stores
  news     Alpaca news headlines of every store symbol-day and the book's symbol-days
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests


def _script(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D24 = _script("run_v24_data")
D23, D14, P14 = D24.D23, D24.D14, D24.P14
V9 = D14.V9
NY = "America/New_York"
FIRST = pd.Timestamp("2017-12-01")
DATA = "https://data.alpaca.markets"
FORM_RE = re.compile(r"^(424B\d|S-1|S-1/A|F-1|F-1/A|S-3|S-3/A|S-3ASR|F-3|F-3/A|EFFECT|8-K|SC 13D|SC 13D/A|SC 13G|"
                     r"SC 13G/A|SCHEDULE 13D|SCHEDULE 13D/A|SCHEDULE 13G|SCHEDULE 13G/A|6-K)$")
FILING_TOP = 150
BLOCK_SHARES, BLOCK_DOLLARS = 10_000, 100_000.0


def _limiter():
    return V9.Limiter(V9.ALPACA_PER_MIN / 60)


def _daily(args) -> dict:
    return P14.load(args.inputs / "daily.pkl")


# ---------------------------------------------------------------- EDGAR

def _accepted(raw: pd.Series) -> pd.Series:
    """Acceptance times as naive New York times. The bulk file writes them with a 'Z'; EDGAR accepts filings from
    06:00 to 22:00 Eastern, so the hours tell whether the stamps are Eastern (kept) or UTC (converted)."""
    ts = pd.to_datetime(raw.str.slice(0, 19), errors="coerce")
    hours = ts.dt.hour.dropna()
    eastern = bool(len(hours) and ((hours >= 6) & (hours < 22)).mean() >= 0.95)
    print(json.dumps({"acceptance_hours_6_22": float(((hours >= 6) & (hours < 22)).mean()) if len(hours) else None,
                      "treated_as": "eastern" if eastern else "utc"}), flush=True)
    if eastern:
        return ts
    return ts.dt.tz_localize("UTC").dt.tz_convert(NY).dt.tz_localize(None)


def _filings(obj: dict) -> pd.DataFrame:
    cols = ("form", "acceptanceDateTime", "accessionNumber")
    if not all(k in obj for k in cols):
        return pd.DataFrame(columns=cols + ("items",))
    n = len(obj["form"])
    return pd.DataFrame({**{k: obj[k] for k in cols}, "items": obj.get("items") or [""] * n})


def cmd_edgar(args) -> int:
    out = args.out / "edgar.parquet"
    if out.exists():
        print("edgar done", flush=True)
        return 0
    sec = D14._Sec()
    hist = P14.ticker_history(args.sec)
    ciks = set(hist["cik"].astype(int))
    path = args.out / "bulk" / "submissions.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        b = sec.raw("https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip")
        assert b, "submissions.zip not downloaded"
        path.write_bytes(b)
    z = zipfile.ZipFile(path)
    parts = []
    for n in z.namelist():
        m = re.fullmatch(r"CIK(\d+)(-submissions-\d+)?\.json", n.split("/")[-1])
        if not m or int(m.group(1)) not in ciks:
            continue
        j = json.loads(z.read(n))
        f = _filings(j["filings"]["recent"] if "filings" in j else j)
        if len(f):
            parts.append(f.assign(cik=int(m.group(1))))
    df = pd.concat(parts, ignore_index=True)
    df = df[df["form"].astype(str).str.match(FORM_RE)].drop_duplicates("accessionNumber")
    df["accepted"] = _accepted(df["acceptanceDateTime"].astype(str))
    df = df[df["accepted"] >= FIRST].dropna(subset=["accepted"])
    df["date"] = df["accepted"].dt.normalize()
    df["symbol"] = P14.map_symbols(df[["cik", "date"]], hist)
    df = df.dropna(subset=["symbol"])[["cik", "symbol", "form", "items", "accepted"]]
    D14._write(df.reset_index(drop=True), out)
    path.unlink()
    print(json.dumps({"filings": len(df), "forms": df["form"].value_counts().head(25).to_dict(),
                      "sec_calls": sec.limiter.calls}), flush=True)
    return 0


def edgar_events(D: dict, edgar: pd.DataFrame) -> pd.DataFrame:
    """Each filing on its session: t, j, minute (-1 for a pre event, else minutes after 09:30)."""
    ev = session_events(D, edgar["symbol"], edgar["accepted"])
    ev["form"] = edgar["form"].to_numpy()[ev.index]
    ev["items"] = edgar["items"].astype(str).to_numpy()[ev.index]
    return ev


def session_events(D: dict, symbols: pd.Series, when_ny: pd.Series) -> pd.DataFrame:
    """Map naive New York times to sessions: 16:00 of t-1 to 09:29 of t is a pre event of t (minute -1), 09:30-15:59 an
    intra event at its minute, later a pre event of the next session."""
    dates = D["dates"]
    pos = {str(c): i for i, c in enumerate(D["cols"])}
    w = pd.to_datetime(pd.Series(when_ny).to_numpy())
    day = w.normalize()
    mins = (w - day).total_seconds().to_numpy() / 60.0
    t_same = dates.searchsorted(day, side="left")
    is_session = (t_same < len(dates)) & (dates[np.minimum(t_same, len(dates) - 1)] == day)
    intra = is_session & (mins >= 570) & (mins < 960)
    before = is_session & (mins < 570)
    t = np.where(intra | before, t_same, dates.searchsorted(day, side="right"))
    minute = np.where(intra, np.floor(mins - 570), -1).astype(int)
    j = pd.Series(np.asarray(symbols, str)).map(pos)
    ev = pd.DataFrame({"t": t, "j": j.to_numpy(), "minute": minute})
    keep = ev["j"].notna().to_numpy() & (ev["t"].to_numpy() < len(dates))
    return ev[keep].astype({"t": np.int64, "j": np.int64}).set_index(np.flatnonzero(keep))


# ---------------------------------------------------------------- BTC

def _binance(month: pd.Period, daily: pd.Timestamp | None = None) -> pd.DataFrame | None:
    if daily is None:
        url = (f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-{month.year}-"
               f"{month.month:02d}.zip")
    else:
        url = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/BTCUSDT-1m-{daily.date()}.zip"
    r = D14._http(url)
    if r is None or r.status_code != 200:
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    raw = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=[0, 4, 5])
    raw = raw[pd.to_numeric(raw[0], errors="coerce").notna()].astype(float)
    ts = raw[0].to_numpy()
    unit = np.where(ts > 1e14, 1e6, 1e3)  # microseconds from 2025, milliseconds before
    return pd.DataFrame({"ts": pd.to_datetime((ts / unit * 1e3).astype(np.int64), unit="ms", utc=True),
                         "c": raw[4].to_numpy(), "v": raw[5].to_numpy()})


def _coinbase(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows, s = [], start
    while s < end:
        e = min(s + pd.Timedelta(minutes=300), end)
        r = D14._http(f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60&start="
                      f"{s.isoformat()}&end={e.isoformat()}")
        if r is not None and r.status_code == 200:
            rows += [(x[0], x[4], x[5]) for x in r.json()]
        time.sleep(0.15)
        s = e
    df = pd.DataFrame(rows, columns=["ts", "c", "v"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    return df


def cmd_btc(args) -> int:
    out = args.out / "btc.parquet"
    if out.exists():
        print("btc done", flush=True)
        return 0
    last = pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    parts, used = [], {"binance": 0, "coinbase": 0}
    for p in pd.period_range(FIRST, last, freq="M"):
        df = _binance(p)
        if df is None and p == pd.Period(last, "M"):
            got = [_binance(p, d) for d in pd.date_range(p.start_time, last)]
            got = [g for g in got if g is not None]
            df = pd.concat(got, ignore_index=True) if got else None
        if df is None:
            a = pd.Timestamp(p.start_time, tz="UTC")
            df = _coinbase(a, min(pd.Timestamp(p.end_time, tz="UTC"), pd.Timestamp(last, tz="UTC")))
            used["coinbase"] += 1
        else:
            used["binance"] += 1
        parts.append(df)
    btc = pd.concat(parts, ignore_index=True).drop_duplicates("ts").sort_values("ts")
    D14._write(btc, out)
    print(json.dumps({"btc_minutes": len(btc), "months": used, "first": str(btc["ts"].min()),
                      "last": str(btc["ts"].max())}), flush=True)
    return 0


# ---------------------------------------------------------------- SPY and IWM

def cmd_index(args) -> int:
    out = args.out / "index.parquet"
    if out.exists():
        print("index done", flush=True)
        return 0
    D = _daily(args)
    folder = args.out / "index_days"
    folder.mkdir(parents=True, exist_ok=True)
    headers, limiter = D14._alpaca_headers(), _limiter()
    days = [d for d in D["dates"] if d >= FIRST and not (folder / f"{d.date()}.parquet").exists()]

    def one(day: pd.Timestamp) -> None:
        rows = D14._bars(["SPY", "IWM"], "1Min", D14._ny(day, 4, 0), D14._ny(day, 19, 59), "raw", headers, limiter)
        df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
        start = D14._ny(day, 4, 0)
        df["minute"] = ((pd.to_datetime(df.pop("t"), utc=True) - start).dt.total_seconds() // 60).astype(np.int16)
        D14._write(df[["symbol", "minute", "c", "v", "vw"]].assign(date=day), folder / f"{day.date()}.parquet")

    with ThreadPoolExecutor(4) as ex:
        for f in as_completed([ex.submit(one, d) for d in days]):
            f.result()
    idx = pd.concat([pd.read_parquet(p) for p in sorted(folder.glob("*.parquet"))], ignore_index=True)
    D14._write(idx, out)
    print(json.dumps({"index_days": int(idx["date"].nunique()), "rows": len(idx), "alpaca_calls": limiter.calls}),
          flush=True)
    return 0


# ---------------------------------------------------------------- ticks of the book's entry sessions

def _paged(url: str, key: str, params: dict, headers: dict, limiter) -> list[dict]:
    out: list[dict] = []
    while True:
        body = V9._get(url, params, headers, limiter) or {}
        got = body.get(key) or {}
        for v in (got.values() if isinstance(got, dict) else [got]):
            out += v
        token = body.get("next_page_token")
        if not token:
            return out
        params = {**params, "page_token": token}


def aggregate_ticks(trades: pd.DataFrame, quotes: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    """Per minute from ``start``: buy and sell volume (Lee-Ready inside the quotes, the tick rule elsewhere), sweep,
    odd-lot and block volume, trade count; mean relative spread, depth imbalance and quote count."""
    tr = trades.sort_values("t").reset_index(drop=True)
    p, s = tr["p"].to_numpy(float), tr["s"].to_numpy(float)
    d = np.sign(np.diff(p, prepend=np.nan))
    d = pd.Series(np.where(d == 0, np.nan, d)).ffill().fillna(0.0).to_numpy()
    if len(quotes):
        q = quotes.sort_values("t")
        mid = ((q["bp"] + q["ap"]) / 2).where((q["bp"] > 0) & (q["ap"] > q["bp"]))
        m = pd.merge_asof(tr[["t"]], pd.DataFrame({"t": q["t"], "mid": mid.to_numpy()}).dropna(), on="t",
                          tolerance=pd.Timedelta(seconds=5))["mid"].to_numpy()
        lr = np.where(p > m, 1.0, np.where(p < m, -1.0, np.nan))
        d = np.where(np.isfinite(lr), lr, d)
    minute = ((tr["t"] - start).dt.total_seconds() // 60).astype(int).to_numpy()
    cond = tr["c"].map(lambda c: "F" in (c or [])).to_numpy(bool)
    agg = pd.DataFrame({"minute": minute, "vb": np.where(d > 0, s, 0.0), "vs": np.where(d < 0, s, 0.0),
                        "viso": np.where(cond, s, 0.0), "vodd": np.where(s < 100, s, 0.0),
                        "vblk": np.where((s >= BLOCK_SHARES) | (s * p >= BLOCK_DOLLARS), s, 0.0), "n": 1.0})
    out = agg.groupby("minute").sum()
    if len(quotes):
        q = quotes.assign(minute=((quotes["t"] - start).dt.total_seconds() // 60).astype(int))
        ok = (q["bp"] > 0) & (q["ap"] > q["bp"])
        q = q[ok]
        qa = pd.DataFrame({"minute": q["minute"], "spread": (q["ap"] - q["bp"]) / ((q["ap"] + q["bp"]) / 2),
                           "dimb": (q["bs"] - q["as"]) / (q["bs"] + q["as"]).where(q["bs"] + q["as"] > 0),
                           "nq": 1.0}).groupby("minute").agg({"spread": "mean", "dimb": "mean", "nq": "sum"})
        out = out.join(qa, how="outer")
    for k in ("spread", "dimb", "nq"):
        if k not in out:
            out[k] = np.nan
    return out.reset_index()


def _tick_day(sym: str, day: pd.Timestamp, kind: str, headers: dict, limiter) -> pd.DataFrame:
    start, end = D14._ny(day, 4, 0), D14._ny(day, 16, 0)
    tr = _paged(f"{DATA}/v2/stocks/trades", "trades", {"symbols": sym, "start": start.isoformat(),
                                                      "end": end.isoformat(), "limit": 10000, "feed": "sip"},
                headers, limiter)
    qs, qe = (D14._ny(day, 9, 15), D14._ny(day, 10, 0)) if kind == "open" else (D14._ny(day, 15, 30), end)
    qu = _paged(f"{DATA}/v2/stocks/quotes", "quotes", {"symbols": sym, "start": qs.isoformat(), "end": qe.isoformat(),
                                                      "limit": 10000, "feed": "sip"}, headers, limiter)
    if not tr:
        return pd.DataFrame()
    trades = pd.DataFrame(tr)
    trades["t"] = pd.to_datetime(trades["t"], utc=True, format="ISO8601")
    if "c" not in trades:
        trades["c"] = [[] for _ in range(len(trades))]
    quotes = pd.DataFrame(qu)
    if len(quotes):
        quotes["t"] = pd.to_datetime(quotes["t"], utc=True, format="ISO8601")
        for k in ("bp", "ap", "bs", "as"):
            quotes[k] = pd.to_numeric(quotes.get(k), errors="coerce")
    return aggregate_ticks(trades, quotes, start).assign(symbol=sym, date=day, kind=kind)


def cmd_ticks(args) -> int:
    out = args.out / "ticks.parquet"
    if out.exists():
        print("ticks done", flush=True)
        return 0
    tr = pd.read_pickle(args.v43 / "trades.pkl")
    tr = tr[tr["kind"].notna()].drop_duplicates(["member", "t", "j"])
    jobs = sorted({(str(r.sym), pd.Timestamp(r.date), str(r.kind)) for r in tr.itertuples()})
    folder = args.out / "tick_days"
    folder.mkdir(parents=True, exist_ok=True)
    headers, limiter = D14._alpaca_headers(), _limiter()
    t0 = time.time()

    def one(job) -> None:
        sym, day, kind = job
        p = folder / f"{day.date()}_{sym}_{kind}.parquet"
        if p.exists() or time.time() - t0 > args.budget_min * 60:
            return
        D14._write(_tick_day(sym, day, kind, headers, limiter), p)

    with ThreadPoolExecutor(4) as ex:
        for n, f in enumerate(as_completed([ex.submit(one, j) for j in jobs])):
            f.result()
            if n % 100 == 0:
                print(f"ticks {n}/{len(jobs)}, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    parts = [pd.read_parquet(p) for p in sorted(folder.glob("*.parquet"))]
    parts = [p for p in parts if len(p)]
    left = sum(1 for s, d, k in jobs if not (folder / f"{d.date()}_{s}_{k}.parquet").exists())
    if left:
        print(json.dumps({"tick_sessions_left": left}), flush=True)
        return 0
    df = pd.concat(parts, ignore_index=True)
    D14._write(df, out)
    print(json.dumps({"tick_sessions": len(jobs), "with_trades": len(parts), "minutes": len(df),
                      "with_quotes": int(df["nq"].notna().sum()), "alpaca_calls": limiter.calls}), flush=True)
    return 0


# ---------------------------------------------------------------- the filing store

def store_keys(args) -> set[tuple[int, int]]:
    keys: set[tuple[int, int]] = set()
    for path in (args.inputs / "cands.parquet", args.v23 / "cands.parquet", args.v24 / "cands.parquet"):
        c = pd.read_parquet(path, columns=["t", "j"])
        keys |= set(zip(c["t"].astype(int), c["j"].astype(int)))
    return keys


def filing_sets(D: dict, ev: pd.DataFrame, taken: set) -> dict[int, list[int]]:
    """Session -> the columns with a filing from 16:00 the session before to 15:30, prior close $1-$20, prior 20-day
    dollar volume >= $0.5M, not in another store; at most FILING_TOP a day by dollar volume."""
    P1, DV1, ok = D["P1"], D["DV1"], D["valid1"]
    ev = ev[(ev["minute"] < 360)]
    out = {}
    for t, g in ev.groupby("t"):
        cols = sorted({int(j) for j in g["j"] if (int(t), int(j)) not in taken})
        with np.errstate(invalid="ignore"):
            cols = [j for j in cols if ok[t, j] and 1 <= P1[t, j] <= 20 and np.isfinite(DV1[t, j]) and
                    DV1[t, j] >= D24.MIN_DV]
        if cols:
            out[int(t)] = sorted(cols, key=lambda j: -DV1[t, j])[:FILING_TOP]
    return out


def cmd_filing(args) -> int:
    store = args.out / "filing" / "store"
    if (store / "cands.parquet").exists():
        print("filing store done", flush=True)
        return 0
    D = _daily(args)
    ev = edgar_events(D, pd.read_parquet(args.out / "edgar.parquet"))
    sets = filing_sets(D, ev, store_keys(args))
    folder = args.out / "filing" / "minutes"
    folder.mkdir(parents=True, exist_ok=True)
    headers, limiter = D14._alpaca_headers(), _limiter()
    t0 = time.time()
    todo = [(t, c) for t, c in sets.items() if not (folder / f"{D['dates'][t].date()}.parquet").exists()]
    print(f"filing days to fetch: {len(todo)} of {len(sets)}, symbol-days {sum(len(c) for c in sets.values())}",
          flush=True)

    def one(t, cols):
        if time.time() - t0 < args.budget_min * 60:
            D14._minute_day(D["dates"][t], [str(D["cols"][j]) for j in cols], folder, headers, limiter)

    with ThreadPoolExecutor(4) as ex:
        for f in as_completed([ex.submit(one, t, c) for t, c in todo]):
            f.result()
    if any(not (folder / f"{D['dates'][t].date()}.parquet").exists() for t in sets):
        print("filing minutes incomplete", flush=True)
        return 0
    cands, arrays = D23.build_store(D, sets, folder)
    store.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(store / "store.npz", **arrays)
    cands.to_parquet(store / "cands.parquet", index=False)
    print(json.dumps({"filing_symbol_days": len(cands), "bars": int(len(arrays["c"])), "alpaca_calls": limiter.calls}),
          flush=True)
    return 0


# ---------------------------------------------------------------- news

def news_need(args, D: dict) -> dict[int, set[str]]:
    cols = np.asarray(D["cols"]).astype(str)
    need: dict[int, set[str]] = {}
    for path in (args.inputs / "cands.parquet", args.v23 / "cands.parquet", args.v24 / "cands.parquet",
                 args.out / "filing" / "store" / "cands.parquet"):
        c = pd.read_parquet(path, columns=["t", "j"])
        for t, j in zip(c["t"].astype(int), c["j"].astype(int)):
            need.setdefault(t, set()).add(cols[j])
    row = {str(d.date()): t for t, d in enumerate(D["dates"])}
    for d, syms in json.loads((args.v43 / "need.json").read_text(encoding="utf-8")).items():
        if d in row:
            need.setdefault(row[d], set()).update(syms)
    return need


def _news_day(D: dict, t: int, syms: list[str], headers: dict, limiter) -> list[dict]:
    day = D["dates"][t]
    prev = D["dates"][t - 1] if t > 0 else day - pd.Timedelta(days=1)
    start, end = D14._ny(prev, 16, 0), D14._ny(day, 16, 0)
    out = []
    for k in range(0, len(syms), 50):
        out += _paged(f"{DATA}/v1beta1/news", "news", {"symbols": ",".join(syms[k:k + 50]), "start": start.isoformat(),
                                                       "end": end.isoformat(), "limit": 50, "sort": "asc",
                                                       "include_content": "false"}, headers, limiter)
    return [{"id": int(x["id"]), "created_at": x["created_at"], "headline": x.get("headline", ""),
             "symbols": ",".join(x.get("symbols") or [])} for x in out]


def cmd_news(args) -> int:
    out = args.out / "news.parquet"
    if out.exists():
        print("news done", flush=True)
        return 0
    D = _daily(args)
    need = news_need(args, D)
    folder = args.out / "news_days"
    folder.mkdir(parents=True, exist_ok=True)
    headers, limiter = D14._alpaca_headers(), _limiter()
    t0 = time.time()
    todo = [t for t in sorted(need) if D["dates"][t] >= FIRST and not (folder / f"{D['dates'][t].date()}.parquet").exists()]
    print(f"news days to fetch: {len(todo)}, symbol-days {sum(len(need[t]) for t in todo)}", flush=True)

    def one(t: int) -> None:
        if time.time() - t0 > args.budget_min * 60:
            return
        rows = _news_day(D, t, sorted(need[t]), headers, limiter)
        D14._write(pd.DataFrame(rows, columns=["id", "created_at", "headline", "symbols"]),
                   folder / f"{D['dates'][t].date()}.parquet")

    with ThreadPoolExecutor(4) as ex:
        for n, f in enumerate(as_completed([ex.submit(one, t) for t in todo])):
            f.result()
            if n % 200 == 0:
                print(f"news {n}/{len(todo)} days, {limiter.calls} calls, {time.time() - t0:.0f}s", flush=True)
    left = [t for t in need if D["dates"][t] >= FIRST and not (folder / f"{D['dates'][t].date()}.parquet").exists()]
    if left:
        print(json.dumps({"news_days_left": len(left)}), flush=True)
        return 0
    df = pd.concat([pd.read_parquet(p) for p in sorted(folder.glob("*.parquet"))], ignore_index=True)
    df = df.drop_duplicates("id")
    D14._write(df, out)
    print(json.dumps({"news_items": len(df), "alpaca_calls": limiter.calls}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("edgar", "btc", "index", "ticks", "filing", "news"))
    ap.add_argument("--inputs", type=Path, default=Path("outputs/v18/v14"))
    ap.add_argument("--sec", type=Path, default=Path("outputs/v14/sec"))
    ap.add_argument("--v23", type=Path, default=Path("outputs/v23/store"))
    ap.add_argument("--v24", type=Path, default=Path("outputs/v24/store"))
    ap.add_argument("--v43", type=Path, default=Path("outputs/v43"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v44"))
    ap.add_argument("--budget-min", type=float, default=300.0)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    return {"edgar": cmd_edgar, "btc": cmd_btc, "index": cmd_index, "ticks": cmd_ticks, "filing": cmd_filing,
            "news": cmd_news}[args.cmd](args)


if __name__ == "__main__":
    sys.argv[0] = "run_v44_data"
    raise SystemExit(main())
