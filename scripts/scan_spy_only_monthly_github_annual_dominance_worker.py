from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_spy_only_monthly_lsc_nightly_funnel as funnel
from scripts.scan_spy_only_monthly_all_annual_dominance import (
    build_year_slices,
    combine_stage_files,
    compound_by_year,
    write_stage_matches,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--stage-summary-csv", required=True)
    parser.add_argument("--scan-name", default="github360_annual_dominance")
    parser.add_argument("--worker-index", type=int, default=-1)
    parser.add_argument("--worker-count", type=int, default=360)
    parser.add_argument("--combine-only", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    scan_dir = output_dir / "annual_dominance_scan"
    final_dir = output_dir / "final"
    scan_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    if args.combine_only:
        combine_workers(output_dir, args.scan_name, int(args.worker_count))
        return

    worker_index = int(args.worker_index)
    worker_count = int(args.worker_count)
    if worker_index < 0 or worker_index >= worker_count:
        raise ValueError("--worker-index must be in [0, worker-count)")

    summaries = load_stage_summary_csv(Path(args.stage_summary_csv))
    intervals = worker_intervals(summaries, worker_index, worker_count)
    started = time.time()

    returns = pd.read_csv(output_dir / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    features = pd.read_csv(output_dir / "paper_monthly_feature_frame.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if returns.index.max() >= funnel.LOCKED_START or features.index.max() >= funnel.LOCKED_START:
        raise RuntimeError("Locked data reached scan input")

    feature_cols = list(features.columns)
    matrix = features.to_numpy(dtype=float)
    spy_values = returns["SPY"].reindex(features.index).astype(float).to_numpy()
    train_mask = np.asarray((features.index >= funnel.TRAIN_START) & (features.index <= funnel.TRAIN_END), dtype=bool)
    validation_mask = np.asarray((features.index >= funnel.VALIDATION_START) & (features.index <= funnel.VALIDATION_END), dtype=bool)
    year_indices, spy_yearly = build_year_slices(features.index, spy_values, train_mask | validation_mask)

    rows: list[dict[str, Any]] = []
    checked = 0
    for interval in intervals:
        stage_rows, stage_checked = scan_interval(
            interval=interval,
            feature_cols=feature_cols,
            matrix=matrix,
            spy_values=spy_values,
            train_mask=train_mask,
            validation_mask=validation_mask,
            year_indices=year_indices,
            spy_yearly=spy_yearly,
        )
        rows.extend(stage_rows)
        checked += stage_checked

    worker_file = scan_dir / f"{args.scan_name}_worker_{worker_index:03d}_matches.csv"
    write_stage_matches(worker_file, rows)
    summary = {
        "scan_name": args.scan_name,
        "worker_index": worker_index,
        "worker_count": worker_count,
        "configs_checked": int(checked),
        "matches": int(len(rows)),
        "intervals": intervals,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "elapsed_seconds": float(time.time() - started),
    }
    summary_path = scan_dir / f"{args.scan_name}_worker_{worker_index:03d}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def scan_interval(
    *,
    interval: dict[str, int],
    feature_cols: list[str],
    matrix: np.ndarray,
    spy_values: np.ndarray,
    train_mask: np.ndarray,
    validation_mask: np.ndarray,
    year_indices: list[tuple[int, np.ndarray]],
    spy_yearly: np.ndarray,
) -> tuple[list[dict[str, Any]], int]:
    stage = int(interval["stage"])
    start0 = int(interval["start_config0"])
    end0 = int(interval["end_config0"])
    spec = funnel.ROUND_SPECS[stage % len(funnel.ROUND_SPECS)]
    selected = funnel.feature_indices_for_prefixes(feature_cols, list(spec["prefixes"]))
    if not selected or end0 <= start0:
        return [], 0

    rng = np.random.default_rng(20260610 + stage * 1_000_003)
    rows: list[dict[str, Any]] = []
    checked = 0
    for config_index0 in range(end0):
        params = funnel.sample_params(rng, selected, spec, feature_cols)
        if config_index0 < start0:
            continue
        checked += 1
        positions, train_metrics = funnel.fit_positions(matrix, spy_values, train_mask, params)
        policy = funnel.position_policy_audit(positions)
        if not policy["policy_pass"]:
            continue

        yearly_strategy = compound_by_year(positions * spy_values, year_indices)
        excess = yearly_strategy - spy_yearly
        if not (np.all(excess >= -1e-12) and np.any(excess > 1e-12)):
            continue

        strategy_returns = positions * spy_values
        validation_metrics = funnel.metrics(strategy_returns[validation_mask])
        train_position = funnel.position_summary(positions[train_mask])
        validation_position = funnel.position_summary(positions[validation_mask])
        train_turnover = funnel.turnover(positions[train_mask])
        validation_turnover = funnel.turnover(positions[validation_mask])
        features_used = [feature_cols[int(i)] for i in params["feature_indices"]]
        payload = {"round": spec["name"], "params": params, "features": features_used, "frequency": "monthly"}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "strategy_id": f"spy_only_monthly_lsc_{spec['name']}_s{stage:03d}_{digest}",
                "stage": stage,
                "config_index": int(config_index0 + 1),
                "round_index": int(stage % len(funnel.ROUND_SPECS)),
                "round_name": spec["name"],
                "rule_type": str(params["rule_type"]),
                "feature_count": int(len(features_used)),
                "features": "|".join(features_used),
                "train_sharpe": float(train_metrics["sharpe"]),
                "validation_sharpe": float(validation_metrics["sharpe"]),
                "min_train_validation_sharpe": funnel.safe_nanmin([train_metrics["sharpe"], validation_metrics["sharpe"]]),
                "train_cagr_pct": float(train_metrics["cagr"] * 100.0),
                "validation_cagr_pct": float(validation_metrics["cagr"] * 100.0),
                "train_mdd_pct": float(train_metrics["mdd"] * 100.0),
                "validation_mdd_pct": float(validation_metrics["mdd"] * 100.0),
                "train_turnover_monthly": float(train_turnover),
                "validation_turnover_monthly": float(validation_turnover),
                "train_long_pct": float(train_position["long_pct"]),
                "train_short_pct": float(train_position["short_pct"]),
                "train_cash_pct": float(train_position["cash_pct"]),
                "validation_long_pct": float(validation_position["long_pct"]),
                "validation_short_pct": float(validation_position["short_pct"]),
                "validation_cash_pct": float(validation_position["cash_pct"]),
                "annual_years_checked": int(len(year_indices)),
                "annual_equal_or_better_years": int(np.sum(excess >= -1e-12)),
                "annual_outperform_years": int(np.sum(excess > 1e-12)),
                "annual_equal_years": int(np.sum(np.abs(excess) <= 1e-12)),
                "annual_min_excess_pct": float(np.min(excess) * 100.0),
                "annual_mean_excess_pct": float(np.mean(excess) * 100.0),
                "annual_max_excess_pct": float(np.max(excess) * 100.0),
                "unique_positions": policy["unique_positions"],
                "max_abs_position": float(policy["max_abs_position"]),
                "traded_asset": "SPY",
                "frequency": "monthly",
                "locked_opened": False,
                "validation_used_for_selection": False,
                "params_json": json.dumps(params, sort_keys=True),
            }
        )
    return rows, checked


def load_stage_summary_csv(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "stage": int(row["stage"]),
                "round_name": str(row["round_name"]),
                "configs_evaluated": int(row["configs_evaluated"]),
            }
        )
    return rows


def worker_intervals(summaries: list[dict[str, Any]], worker_index: int, worker_count: int) -> list[dict[str, int]]:
    total = int(sum(int(item["configs_evaluated"]) for item in summaries))
    global_start = total * worker_index // worker_count
    global_end = total * (worker_index + 1) // worker_count
    intervals: list[dict[str, int]] = []
    cursor = 0
    for item in summaries:
        stage = int(item["stage"])
        count = int(item["configs_evaluated"])
        stage_start = cursor
        stage_end = cursor + count
        cursor = stage_end
        local_start = max(global_start, stage_start)
        local_end = min(global_end, stage_end)
        if local_start >= local_end:
            continue
        intervals.append(
            {
                "stage": stage,
                "start_config0": int(local_start - stage_start),
                "end_config0": int(local_end - stage_start),
            }
        )
    return intervals


def combine_workers(output_dir: Path, scan_name: str, worker_count: int) -> None:
    scan_dir = output_dir / "annual_dominance_scan"
    final_dir = output_dir / "final"
    worker_files = [scan_dir / f"{scan_name}_worker_{idx:03d}_matches.csv" for idx in range(worker_count)]
    missing = [str(path) for path in worker_files if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing worker files: {len(missing)}")
    combined = combine_stage_files(worker_files)
    if not combined.empty:
        combined = combined.drop_duplicates("strategy_id", keep="first")
        combined = combined.sort_values(
            ["annual_min_excess_pct", "annual_outperform_years", "min_train_validation_sharpe", "validation_sharpe"],
            ascending=[False, False, False, False],
        )
    out_csv = final_dir / f"{scan_name}_matches.csv"
    combined.to_csv(out_csv, index=False)

    summaries = []
    for idx in range(worker_count):
        path = scan_dir / f"{scan_name}_worker_{idx:03d}_summary.json"
        if path.exists():
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
    result = {
        "scan_name": scan_name,
        "worker_count": int(worker_count),
        "worker_summaries": int(len(summaries)),
        "configs_checked": int(sum(int(item.get("configs_checked", 0)) for item in summaries)),
        "matches_before_dedupe": int(sum(int(item.get("matches", 0)) for item in summaries)),
        "matches_after_dedupe": int(len(combined)),
        "criterion": "strategy annual return >= SPY every train+validation year and > SPY at least one year",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "output_csv": str(out_csv),
    }
    summary_path = final_dir / f"{scan_name}_summary.json"
    summary_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
