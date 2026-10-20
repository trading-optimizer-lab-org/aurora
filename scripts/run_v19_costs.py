"""v19 realistic costs, step 1: the measured quoted half-spreads of small caps on their event days.

Reads the v17 quote study (Alpaca SIP quotes in the entry and exit minute of 10,417 gap-fade trades, 2016-2023H1,
cache of run 39419245445): per raw-price tier and time of day, the median, mean (winsorised at the 99th
percentile), 75th and 90th percentiles of the half-spread (half the median ask-bid spread over the mid in that
minute). It reads quotes only, never a return.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

TIERS = ((0, 2, "<2"), (2, 5, "2-5"), (5, 10, "5-10"), (10, 20, "10-20"))
BUCKETS = ((0, 5, "09:30-09:35"), (5, 30, "09:35-10:00"), (30, 120, "10:00-11:30"), (120, 385, "11:30-15:55"),
           (385, 391, "close"))


def _stats(x: pd.Series) -> dict:
    x = x.dropna()
    if not len(x):
        return {"n": 0}
    w = x.clip(upper=x.quantile(0.99))
    return {"n": int(len(x)), "median": float(x.median()), "mean_w99": float(w.mean()),
            "p75": float(x.quantile(0.75)), "p90": float(x.quantile(0.90))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quotes", type=Path, default=Path("outputs/v17/quotes"))
    ap.add_argument("--out", type=Path, default=Path("outputs/v19/costs"))
    args = ap.parse_args()
    t = pd.read_parquet(args.quotes / "trades.parquet")
    sp = pd.read_parquet(args.quotes / "spreads.parquet").drop_duplicates(["date", "symbol", "minute"])
    sp["half"] = sp["spread"] / 2
    legs = pd.concat([t[["date", "symbol", "minute", "price"]].assign(leg="entry"),
                      t[["date", "symbol", "exit_minute", "price"]].rename(columns={"exit_minute": "minute"})
                      .assign(leg="exit")], ignore_index=True)
    legs = legs.merge(sp[["date", "symbol", "minute", "half"]], on=["date", "symbol", "minute"], how="left")
    out: dict = {"legs": int(len(legs)), "with_quotes": int(legs["half"].notna().sum()), "tiers": {}}
    lines = ["# v19 realistic costs: measured half-spreads of small caps on event days", "",
             f"{out['legs']} trade legs, {out['with_quotes']} with quotes (v17 quote study, 2016-2023H1).", "",
             "| tier | time | n | median | mean (w99) | p75 | p90 |", "|---|---|---|---|---|---|---|"]
    for lo, hi, name in TIERS:
        tier = legs[(legs["price"] >= lo) & (legs["price"] < hi)]
        rows = {"all": _stats(tier["half"])}
        for a, b, label in BUCKETS:
            rows[label] = _stats(tier.loc[(tier["minute"] >= a) & (tier["minute"] < b), "half"])
        out["tiers"][name] = rows
        for label, s in rows.items():
            if s["n"]:
                lines.append(f"| {name} | {label} | {s['n']} | {s['median']:.2%} | {s['mean_w99']:.2%} | "
                             f"{s['p75']:.2%} | {s['p90']:.2%} |")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "costs.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (args.out / "COSTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
