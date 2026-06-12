from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scan-name", default="all_configs_annual_dominance")
    parser.add_argument("--start-stage", type=int, default=0)
    parser.add_argument("--end-stage", type=int, default=-1)
    parser.add_argument("--max-configs-per-stage", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=10_000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    final_dir = output_dir / "final"
    scan_dir = output_dir / "annual_dominance_scan"
    scan_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    returns = pd.read_csv(output_dir / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    features = pd.read_csv(output_dir / "paper_monthly_feature_frame.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if returns.index.max() >= funnel.LOCKED_START or features.index.max() >= funnel.LOCKED_START:
        raise RuntimeError("Locked data reached scan input")

    feature_cols = list(features.columns)
    matrix = features.to_numpy(dtype=float)
    spy_values = returns["SPY"].reindex(features.index).astype(float).to_numpy()
    train_mask = np.asarray((features.index >= funnel.TRAIN_START) & (features.index <= funnel.TRAIN_END), dtype=bool)
    validation_mask = np.asarray((features.index >= funnel.VALIDATION_START) & (features.index <= funnel.VALIDATION_END), dtype=bool)
    train_valid_mask = train_mask | validation_mask

    year_indices, spy_yearly = build_year_slices(features.index, spy_values, train_valid_mask)
    summaries = load_shard_summaries(output_dir, args.start_stage, args.end_stage)

    progress_path = scan_dir / f"{args.scan_name}_progress.jsonl"
    all_stage_files: list[Path] = []
    total_checked = 0
    total_matches = 0
    started = time.time()

    for summary in summaries:
        stage = int(summary["stage"])
        requested = int(summary.get("configs_evaluated", 0))
        if args.max_configs_per_stage > 0:
            requested = min(requested, int(args.max_configs_per_stage))
        stage_file = scan_dir / f"stage_{stage:03d}_matches.csv"
        all_stage_files.append(stage_file)
        if stage_file.exists() and stage_file.stat().st_size > 0:
            existing = pd.read_csv(stage_file)
            checked = requested
            matches = len(existing)
            total_checked += checked
            total_matches += matches
            append_progress(progress_path, stage, checked, requested, matches, "skipped_existing", started)
            continue

        spec = funnel.ROUND_SPECS[stage % len(funnel.ROUND_SPECS)]
        selected = funnel.feature_indices_for_prefixes(feature_cols, list(spec["prefixes"]))
        if not selected:
            write_stage_matches(stage_file, [])
            append_progress(progress_path, stage, 0, requested, 0, "unsupported", started)
            continue

        rng = np.random.default_rng(20260610 + stage * 1_000_003)
        rows: list[dict[str, Any]] = []
        checked = 0
        for config_index in range(1, requested + 1):
            checked += 1
            params = funnel.sample_params(rng, selected, spec, feature_cols)
            positions, train_metrics = funnel.fit_positions(matrix, spy_values, train_mask, params)
            policy = funnel.position_policy_audit(positions)
            if not policy["policy_pass"]:
                continue

            yearly_strategy = compound_by_year(positions * spy_values, year_indices)
            excess = yearly_strategy - spy_yearly
            if np.all(excess >= -1e-12) and np.any(excess > 1e-12):
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
                        "config_index": config_index,
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

            if args.progress_every > 0 and checked % int(args.progress_every) == 0:
                append_progress(progress_path, stage, checked, requested, len(rows), "running", started)

        write_stage_matches(stage_file, rows)
        total_checked += checked
        total_matches += len(rows)
        append_progress(progress_path, stage, checked, requested, len(rows), "done", started)

    combined = combine_stage_files(all_stage_files)
    if not combined.empty:
        combined = combined.drop_duplicates("strategy_id", keep="first")
        combined = combined.sort_values(
            ["annual_min_excess_pct", "annual_outperform_years", "min_train_validation_sharpe", "validation_sharpe"],
            ascending=[False, False, False, False],
        )
    out_csv = final_dir / f"{args.scan_name}_matches.csv"
    combined.to_csv(out_csv, index=False)
    result = {
        "scan_name": args.scan_name,
        "configs_checked": int(total_checked),
        "matches_before_dedupe": int(total_matches),
        "matches_after_dedupe": int(len(combined)),
        "years_checked": [int(year) for year, _ in year_indices],
        "criterion": "strategy annual return >= SPY every train+validation year and > SPY at least one year",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "output_csv": str(out_csv),
        "elapsed_seconds": float(time.time() - started),
    }
    (final_dir / f"{args.scan_name}_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


def build_year_slices(index: pd.DatetimeIndex, spy_values: np.ndarray, mask: np.ndarray) -> tuple[list[tuple[int, np.ndarray]], np.ndarray]:
    years = sorted({int(y) for y in index[mask].year})
    year_indices: list[tuple[int, np.ndarray]] = []
    spy_yearly: list[float] = []
    for year in years:
        idx = np.where(mask & (index.year == year))[0]
        if len(idx) == 0:
            continue
        year_indices.append((year, idx))
        spy_yearly.append(float(np.prod(1.0 + spy_values[idx]) - 1.0))
    return year_indices, np.asarray(spy_yearly, dtype=float)


def compound_by_year(values: np.ndarray, year_indices: list[tuple[int, np.ndarray]]) -> np.ndarray:
    out = np.empty(len(year_indices), dtype=float)
    for i, (_, idx) in enumerate(year_indices):
        out[i] = float(np.prod(1.0 + values[idx]) - 1.0)
    return out


def load_shard_summaries(output_dir: Path, start_stage: int, end_stage: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((output_dir / "shards").glob("stage_*/shard_summary.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        stage = int(item.get("stage", -1))
        if stage < start_stage:
            continue
        if end_stage >= 0 and stage > end_stage:
            continue
        if int(item.get("configs_evaluated", 0)) <= 0:
            continue
        rows.append(item)
    return rows


def write_stage_matches(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "strategy_id",
        "stage",
        "config_index",
        "round_index",
        "round_name",
        "rule_type",
        "feature_count",
        "features",
        "train_sharpe",
        "validation_sharpe",
        "min_train_validation_sharpe",
        "train_cagr_pct",
        "validation_cagr_pct",
        "train_mdd_pct",
        "validation_mdd_pct",
        "train_turnover_monthly",
        "validation_turnover_monthly",
        "train_long_pct",
        "train_short_pct",
        "train_cash_pct",
        "validation_long_pct",
        "validation_short_pct",
        "validation_cash_pct",
        "annual_years_checked",
        "annual_equal_or_better_years",
        "annual_outperform_years",
        "annual_equal_years",
        "annual_min_excess_pct",
        "annual_mean_excess_pct",
        "annual_max_excess_pct",
        "unique_positions",
        "max_abs_position",
        "traded_asset",
        "frequency",
        "locked_opened",
        "validation_used_for_selection",
        "params_json",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def combine_stage_files(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            try:
                frame = pd.read_csv(path)
            except pd.errors.EmptyDataError:
                continue
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def append_progress(path: Path, stage: int, checked: int, requested: int, matches: int, status: str, started: float) -> None:
    payload = {
        "time": pd.Timestamp.now(tz="Europe/Madrid").isoformat(),
        "stage": int(stage),
        "checked": int(checked),
        "requested": int(requested),
        "matches": int(matches),
        "status": status,
        "elapsed_seconds": float(time.time() - started),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


if __name__ == "__main__":
    main()
