#!/usr/bin/env python3
"""Download the free_us_daily layout from Yahoo for the X swing study (docs/research/X_SWING_PREREGISTRATION.md).

  shard     one shard of config/x_swing/symbols.csv -> <out>/normalized/<symbol>.parquet
  finish    benchmarks (SPY, ^GSPC) and metadata/company_metadata.parquet from the symbol list

Only rows before 2021-01-01 are kept, plus every split event (the SEPA loader needs later splits to recover the quoted
price). Nothing is published: the files stay inside the workflow.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

LOCKED = pd.Timestamp("2021-01-01")
SYMBOLS = Path("config/x_swing/symbols.csv")


def fetch(ticker: str, tries: int = 3) -> pd.DataFrame | None:
    for k in range(tries):
        try:
            h = yf.Ticker(ticker).history(period="max", auto_adjust=False, actions=True)
            break
        except Exception:  # noqa: BLE001 - Yahoo fails in many ways; retry then skip
            time.sleep(2 * (k + 1))
    else:
        return None
    if h is None or h.empty:
        return None
    h = h.rename(columns=str.lower).rename(columns={"adj close": "adj_close", "stock splits": "stock_splits"})
    h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
    keep = (h.index < LOCKED) | (h.get("stock_splits", 0) > 0)
    h = h.loc[keep]
    out = pd.DataFrame({"date": h.index.strftime("%Y-%m-%d")})
    for c in ("open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"):
        out[c] = h[c].to_numpy() if c in h else 0.0
    late = (h.index >= LOCKED)
    out.loc[late, ["open", "high", "low", "close", "adj_close", "volume", "dividends"]] = float("nan")  # splits only
    return out


def cmd_shard(args) -> int:
    syms = pd.read_csv(SYMBOLS)
    part = syms.iloc[args.shard::args.shards]
    (args.out / "normalized").mkdir(parents=True, exist_ok=True)
    ok = 0
    for sym, yfs in zip(part["symbol"], part["yfinance_symbol"]):
        df = fetch(str(yfs))
        if df is not None and len(df):
            df.assign(symbol=sym).to_parquet(args.out / "normalized" / f"{sym}.parquet", index=False)
            ok += 1
    print(f"shard {args.shard}: {ok} of {len(part)} symbols", flush=True)
    return 0


def cmd_finish(args) -> int:
    (args.out / "benchmarks").mkdir(parents=True, exist_ok=True)
    for name, ticker in (("SPY", "SPY"), ("GSPC", "^GSPC")):
        df = fetch(ticker)
        assert df is not None, ticker
        df.to_parquet(args.out / "benchmarks" / f"{name}.parquet", index=False)
    (args.out / "metadata").mkdir(parents=True, exist_ok=True)
    pd.read_csv(SYMBOLS).to_parquet(args.out / "metadata" / "company_metadata.parquet", index=False)
    print(len(list((args.out / "normalized").glob("*.parquet"))), "symbol files", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shard")
    s.add_argument("--shard", type=int, required=True)
    s.add_argument("--shards", type=int, required=True)
    sub.add_parser("finish")
    for p in sub.choices.values():
        p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    return {"shard": cmd_shard, "finish": cmd_finish}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
