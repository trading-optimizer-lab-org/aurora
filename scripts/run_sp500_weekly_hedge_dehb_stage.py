from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from aurora.research.sp500_weekly_hedge_search import SP500WeeklyHedgeConfig, run_stage


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one SP500 weekly hedge DEHB stage.")
    parser.add_argument("--wave", type=int, default=0)
    parser.add_argument("--total-waves", type=int, default=1)
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--total-stages", type=int, default=500)
    parser.add_argument("--time-budget-minutes", type=float, default=55.0)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--file-prefix", default="sp500_weekly_hedge_all_assets_all_features_dehb_500")
    parser.add_argument("--top-rows-per-stage", type=int, default=500)
    parser.add_argument("--random-seed", type=int, default=9102601)
    parser.add_argument("--synthetic-smoke", action="store_true")
    args = parser.parse_args()

    config = SP500WeeklyHedgeConfig(
        top_rows_per_stage=int(args.top_rows_per_stage),
        random_seed=int(args.random_seed),
    )
    dataset = _synthetic_dataset() if args.synthetic_smoke else None
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, meta, audit = run_stage(
        config,
        stage=int(args.stage),
        total_stages=int(args.total_stages),
        time_budget_minutes=float(args.time_budget_minutes),
        wave=int(args.wave),
        total_waves=int(args.total_waves),
        dataset=dataset,
    )
    stem = f"{args.file_prefix}_wave_{int(args.wave)}_stage_{int(args.stage)}"
    pd.DataFrame(rows).to_csv(output_dir / f"{stem}.csv", index=False)
    (output_dir / f"{stem}_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / f"{stem}_feature_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(meta, indent=2, sort_keys=True))
    return 0


def _synthetic_dataset() -> dict[str, object]:
    idx = pd.date_range("2020-01-03", periods=160, freq="W-FRI")
    spy = np.resize(np.array([0.03, -0.04, 0.02, -0.03], dtype=float), len(idx))
    tlt = np.where(spy < 0.0, 0.025, 0.002)
    xle = np.where(spy < 0.0, -0.020, 0.020)
    asset_returns = pd.DataFrame({"SPY": spy, "TLT": tlt, "XLE": xle}, index=idx)
    features = pd.DataFrame(
        {
            "SPY__ret_1w": spy,
            "TLT__ret_1w": tlt,
            "XLE__ret_1w": xle,
            "macro__stress": np.where(spy < 0.0, 1.0, -1.0),
        },
        index=idx,
    )
    return {
        "train_x": features.iloc[:120],
        "valid_x": features.iloc[120:],
        "train_asset_returns": asset_returns.iloc[:120],
        "valid_asset_returns": asset_returns.iloc[120:],
        "train_spy_returns": asset_returns["SPY"].iloc[:120].to_numpy(dtype=float),
        "valid_spy_returns": asset_returns["SPY"].iloc[120:].to_numpy(dtype=float),
        "train_index": pd.DatetimeIndex(idx[:120]),
        "valid_index": pd.DatetimeIndex(idx[120:]),
        "feature_names": tuple(features.columns),
        "asset_symbols": ("SPY", "TLT", "XLE"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
