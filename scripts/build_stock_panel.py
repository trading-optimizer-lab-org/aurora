#!/usr/bin/env python3
"""Build the stock price panel for the catalog, from the local free_us_daily
files or by downloading the same symbols from Yahoo (GitHub runner).

Every series is cut before 2021-01-01 as soon as it is read, checked with
research/stock_data_checks.py, and severe series are dropped. Writes one
parquet per field (adjusted open/high/low/close, volume), a per-symbol data
quality report and a fingerprint used to compare the two sources.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from aurora.core.runtime_paths import base_data_dir
from aurora.research import stock_catalog as sc
from aurora.research import stock_data_checks as q

DEFAULT_DIR = base_data_dir() / "prices" / "free_us_daily"
START = pd.Timestamp("1992-01-01")
COLS = ["open", "high", "low", "close", "adj_close", "volume", "stock_splits"]
YF_COLS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
           "Volume": "volume", "Stock Splits": "stock_splits"}


def _sealed(df: pd.DataFrame) -> pd.DataFrame:
    df = df.loc[(df.index >= START) & (df.index < sc.LOCKED_START)]
    return df[~df.index.duplicated()].sort_index()


def read_local(prices_dir: Path, symbol: str) -> pd.DataFrame | None:
    path = prices_dir / "normalized" / f"{symbol}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["date", *COLS])
    df.index = pd.to_datetime(df.pop("date"))
    return _sealed(df)


def download_yahoo(tickers: list[str], batch: int = 80, attempts: int = 3) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    todo = list(tickers)
    for attempt in range(attempts):
        missing = []
        for k in range(0, len(todo), batch):
            chunk = todo[k:k + batch]
            try:
                raw = yf.download(chunk, start=str(START.date()), end=str(sc.LOCKED_START.date()),
                                  auto_adjust=False, actions=True, group_by="ticker", threads=True,
                                  progress=False)
            except Exception:  # network/rate limit: retry the whole chunk later
                missing.extend(chunk)
                continue
            for t in chunk:
                try:
                    df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                except KeyError:
                    missing.append(t)
                    continue
                df = df.rename(columns=YF_COLS)
                if "stock_splits" not in df:
                    df["stock_splits"] = 0.0
                df = df[COLS].dropna(subset=["close"])
                if df.empty:
                    missing.append(t)
                    continue
                df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                out[t] = _sealed(df.astype(float))
            time.sleep(1)
        todo = missing
        if not todo:
            break
        time.sleep(30 * (attempt + 1))
    return out


def benchmarks(source: str, prices_dir: Path) -> pd.DataFrame:
    """S&P 500 index close and SPY adjusted close (total return)."""
    cols = {}
    for name, ticker in (("gspc", "GSPC"), ("spy", "SPY")):
        if source == "local":
            df = pd.read_parquet(prices_dir / "benchmarks" / f"{ticker}.parquet", columns=["date", "adj_close"])
            s = pd.Series(df["adj_close"].to_numpy(), index=pd.to_datetime(df["date"]))
        else:
            import yfinance as yf
            raw = yf.download("^GSPC" if ticker == "GSPC" else "SPY", start=str(START.date()),
                              end=str(sc.LOCKED_START.date()), auto_adjust=False, progress=False)
            s = raw["Adj Close"]
            s = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        s = s.loc[(s.index >= START) & (s.index < sc.LOCKED_START)]
        cols[name] = s[~s.index.duplicated()].sort_index()
    out = pd.DataFrame(cols)
    if out["gspc"].isna().all() or out["spy"].dropna().empty:
        raise RuntimeError("benchmark download failed")
    return out


def fingerprint(df: pd.DataFrame) -> dict:
    r = np.log(df["adj_close"]).diff().loc["1995-01-01":]
    return {"rows": int(len(df)), "first": str(df.index[0].date()), "last": str(df.index[-1].date()),
            "sum_log_return": round(float(r.sum()), 6), "splits": int((df["stock_splits"].fillna(0) > 0).sum())}


def compare(fp: pd.DataFrame, ref: pd.DataFrame) -> dict:
    both = fp.join(ref, rsuffix="_ref", how="outer", lsuffix="")
    have = both["rows"].notna() & both["rows_ref"].notna()
    diff = (both["sum_log_return"] - both["sum_log_return_ref"]).abs()
    worst = diff[have].sort_values(ascending=False).head(15)
    return {"symbols_this_source": int(both["rows"].notna().sum()), "symbols_reference": int(both["rows_ref"].notna().sum()),
            "in_both": int(have.sum()), "same_rows": int((have & (both["rows"] == both["rows_ref"])).sum()),
            "same_returns_0.5pct": int((have & (diff < 0.005)).sum()),
            "worst_return_differences": {s: round(float(v), 4) for s, v in worst.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["local", "yahoo"], default="local")
    ap.add_argument("--prices-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--symbols", type=Path, default=Path("docs/research/data/stock_catalog_symbols.csv"))
    ap.add_argument("--fingerprint-ref", type=Path, default=Path("docs/research/data/stock_panel_fingerprint.csv"))
    ap.add_argument("--out-dir", type=Path, default=Path("outputs/stock_panel"))
    args = ap.parse_args()
    syms = pd.read_csv(args.symbols)
    if args.source == "local":
        series = {s: read_local(args.prices_dir, s) for s in syms["symbol"]}
    else:
        got = download_yahoo(syms["yfinance_symbol"].tolist())
        back = dict(zip(syms["yfinance_symbol"], syms["symbol"]))
        series = {back[t]: df for t, df in got.items()}
    bench = benchmarks(args.source, args.prices_dir)
    calendar = pd.DatetimeIndex(bench["gspc"].dropna().index)
    qc_rows, fps, keep = [], {}, {}
    for s, df in series.items():
        if df is None or len(df) < 2:
            qc_rows.append({"symbol": s, "status": "missing"})
            continue
        issues = q.check_series(df, calendar)
        reasons = q.is_severe(issues)
        qc_rows.append({"symbol": s, "status": "dropped" if reasons else "ok", "reasons": "; ".join(reasons), **issues})
        fps[s] = fingerprint(df)
        if not reasons:
            keep[s] = df
    args.out_dir.mkdir(parents=True, exist_ok=True)
    bench.to_parquet(args.out_dir / "benchmarks.parquet")
    qc = pd.DataFrame(qc_rows)
    qc.to_csv(args.out_dir / "data_quality.csv", index=False)
    fp = pd.DataFrame.from_dict(fps, orient="index").sort_index()
    fp.to_csv(args.out_dir / "fingerprint.csv", index_label="symbol")
    factor = {s: df["adj_close"] / df["close"] for s, df in keep.items()}
    for field in ("open", "high", "low", "close"):
        wide = pd.DataFrame({s: (df[field] * factor[s]).astype("float32") for s, df in keep.items()})
        wide.to_parquet(args.out_dir / f"{field}.parquet")
    pd.DataFrame({s: df["volume"].astype("float32") for s, df in keep.items()}).to_parquet(args.out_dir / "volume.parquet")
    summary = {"source": args.source, "symbols_requested": int(len(syms)),
               "status": qc["status"].value_counts().to_dict(),
               "drop_reasons": qc.get("reasons", pd.Series(dtype=str)).fillna("").str.split("; ").explode()
               .loc[lambda x: x != ""].value_counts().to_dict(),
               "issue_counts": {c: int((qc[c] > 0).sum()) for c in qc.columns
                                if c not in ("symbol", "status", "reasons", "rows", "missing_share")}}
    if args.fingerprint_ref.exists() and args.source != "local":
        ref = pd.read_csv(args.fingerprint_ref, index_col="symbol")
        summary["comparison_with_local"] = compare(fp, ref)
    (args.out_dir / "data_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
