#!/usr/bin/env python3
"""Robustness checks for the All Weather + VAA-G4 blend.

Reads the price panel written by scripts/run_multiasset_baselines.py (already
truncated before 2021-01-01) and writes ROBUSTNESS.md and robustness.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aurora.research.multiasset_robustness import run_robustness


def _fmt(v: object) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def _table(rows: dict[str, dict], keys: list[str]) -> list[str]:
    lines = ["| variant | " + " | ".join(keys) + " |", "|" + "---|" * (len(keys) + 1)]
    lines += ["| " + name + " | " + " | ".join(_fmt(r.get(k)) for k in keys) + " |"
              for name, r in rows.items()]
    return lines


def render(result: dict) -> str:
    keys = ["is_sortino_monthly", "val_sortino_monthly", "max_drawdown", "start"]
    roll, boot = result["rolling_36m"], result["bootstrap"]
    lines = ["# All Weather + VAA-G4 robustness", "",
             "Data before 2021-01-01 only. Sortino on calendar-month excess returns over T-bills.", "",
             "## 1. Costs", *_table(result["costs"], keys), "",
             "## 2. Rebalance day", *_table(result["rebalance_day"], keys), "",
             "## 3. Rolling 36-month Sortino", "",
             f"Windows: {roll['windows']}; min {roll['min']:.2f} (ending {roll['worst_window_end']}), "
             f"median {roll['median']:.2f}, max {roll['max']:.2f}; "
             f"share >= 2: {roll['share_ge_2']:.0%}; share >= 1: {roll['share_ge_1']:.0%}.", "",
             "## 4. Block bootstrap of monthly excess returns (5th / 50th / 95th percentile)", ""]
    for label, b in boot.items():
        lines.append(f"- {label}: {b['p05']:.2f} / {b['p50']:.2f} / {b['p95']:.2f}; "
                     f"probability >= 2: {b['share_ge_2']:.0%}")
    lines += ["", "## 5. Parameters (VAA score x All Weather share)",
              *_table(result["parameters"], keys)]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices", type=Path, default=Path("outputs/multiasset_baselines/prices.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/multiasset_baselines"))
    parser.add_argument("--bootstrap-draws", type=int, default=5000)
    args = parser.parse_args()
    result = run_robustness(pd.read_parquet(args.prices), bootstrap_draws=args.bootstrap_draws)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "robustness.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    text = render(result)
    (args.output_dir / "ROBUSTNESS.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
