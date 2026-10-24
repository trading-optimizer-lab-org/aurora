#!/usr/bin/env python3
"""Options study 2: 0DTE, overnight/intraday and cross-sectional option strategies (pre-registered).

    APCA_API_KEY_ID=... APCA_API_SECRET_KEY=... python scripts/run_options_study2.py probe

Only reports, counts and strategy returns are printed or uploaded; raw market data stays in the cache folder.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_earnings_options import DATA, _frame, alpaca, contracts, fetch_bars  # noqa: E402


def cmd_probe(args) -> int:
    """Data-format checks only: which expiries are listed, bar coverage of 0DTE contracts, 1-minute bars."""
    a = alpaca()
    out: dict = {}
    for und in ("SPY", "QQQ", "IWM"):
        for lo, hi in (("2024-02-05", "2024-02-16"), ("2025-06-02", "2025-06-13")):
            ch = contracts(a, und, "inactive", pd.Timestamp(lo), pd.Timestamp(hi), 1, 2000, "call")
            out[f"{und} expiries {lo}"] = sorted({c["expiration_date"] for c in ch})
    for und, day, k in (("SPY", "2024-03-05", 505), ("QQQ", "2024-03-05", 435), ("SPY", "2025-06-10", 600)):
        ch = contracts(a, und, "inactive", pd.Timestamp(day), pd.Timestamp(day), k - 3, k + 3)
        syms = sorted(c["symbol"] for c in ch)
        out[f"{und} {day} contracts near {k}"] = len(syms)
        for tf in ("15Min", "1Min"):
            b = _frame(fetch_bars(a, f"{DATA}/v1beta1/options/bars", syms,
                                  {"timeframe": tf, "start": f"{day}T13:00:00Z", "end": f"{day}T21:30:00Z"}))
            if b.empty:
                out[f"{und} {day} {tf}"] = "no bars"
                continue
            per = b.groupby("symbol")["t"].agg(["count", "min", "max"])
            out[f"{und} {day} {tf}"] = {"symbols_with_bars": len(per), "median_bars": float(per["count"].median()),
                                        "first": str(per["min"].min().time()), "last": str(per["max"].max().time())}
    # a weekly SPY contract on a day before its expiry: are there bars after 16:00 (SPY options trade to 16:15)?
    ch = contracts(a, "SPY", "inactive", pd.Timestamp("2024-03-08"), pd.Timestamp("2024-03-08"), 503, 507, "call")
    b = _frame(fetch_bars(a, f"{DATA}/v1beta1/options/bars", sorted(c["symbol"] for c in ch),
                          {"timeframe": "15Min", "start": "2024-03-05T13:00:00Z", "end": "2024-03-05T21:30:00Z"}))
    out["SPY 2024-03-08 expiry on 2024-03-05, bar times"] = sorted({str(t.time()) for t in b["t"]}) if len(b) else []
    print(json.dumps(out, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(required=True)
    p = sub.add_parser("probe")
    p.set_defaults(fn=cmd_probe)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
