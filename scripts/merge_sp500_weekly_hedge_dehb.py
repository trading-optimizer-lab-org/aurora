from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd


def _load_search_module():
    module_path = ROOT / "research" / "sp500_weekly_hedge_search.py"
    spec = importlib.util.spec_from_file_location("sp500_weekly_hedge_search_runtime", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load SP500 hedge search module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[str(spec.name)] = module
    spec.loader.exec_module(module)
    return module


_SEARCH = _load_search_module()
METHOD = _SEARCH.METHOD
merge_stage_rows = _SEARCH.merge_stage_rows
method_summary = _SEARCH.method_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge SP500 weekly hedge DEHB stage artifacts.")
    parser.add_argument("--input-glob", required=True)
    parser.add_argument("--audit-glob", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--file-prefix", default="sp500_weekly_hedge_all_assets_all_features_dehb_500")
    parser.add_argument("--expected-jobs", type=int, default=500)
    parser.add_argument("--waves", type=int, default=1)
    parser.add_argument("--jobs-per-wave", type=int, default=80)
    parser.add_argument("--max-parallel-requested", type=int, default=500)
    parser.add_argument("--assumed-effective-parallelism", type=int, default=180)
    parser.add_argument("--minutes-per-stage", type=float, default=55.0)
    parser.add_argument("--top-n", type=int, default=2000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(glob.glob(args.input_glob, recursive=True))
    merged = _read_and_dedupe(paths)
    if not merged.empty and "train_score" in merged.columns:
        merged = merged.sort_values("train_score", ascending=False).reset_index(drop=True)

    leaderboard = merged
    train_top = merged.head(int(args.top_n)) if not merged.empty else merged
    verified = merged[merged["verified"].astype(bool)].copy() if not merged.empty and "verified" in merged.columns else merged.head(0).copy()
    validation_cols = [c for c in merged.columns if c.startswith("validation_")]
    id_cols = [
        c
        for c in (
            "candidate_id",
            "method",
            "assets",
            "asset_weights",
            "features",
            "position_size",
            "train_score",
            "verified",
            "rejection_reason",
        )
        if c in merged.columns
    ]
    validation_report = merged[id_cols + validation_cols].copy() if not merged.empty else merged
    sizing_cols = [
        c
        for c in merged.columns
        if c in {"candidate_id", "method", "assets", "asset_weights", "position_size", "max_leverage", "long_gross_weight", "short_gross_weight", "allows_short"}
        or c.startswith("train_1x_")
        or c.startswith("train_")
        or c.startswith("validation_1x_")
        or c.startswith("validation_")
    ]
    sizing = merged[sizing_cols].copy() if not merged.empty else merged
    methods = method_summary(merged)
    fail_reasons = _fail_reasons(merged)
    feature_audit = _feature_audit(args.audit_glob)
    summary = {
        "rows": int(len(leaderboard)),
        "unique_candidates": int(leaderboard["candidate_id"].nunique()) if "candidate_id" in leaderboard.columns else 0,
        "verified": int(leaderboard["verified"].astype(bool).sum()) if "verified" in leaderboard.columns else 0,
        "stage_files_found": int(len(paths)),
        "expected_jobs": int(args.expected_jobs),
        "waves": int(args.waves),
        "jobs_per_wave": int(args.jobs_per_wave),
        "partial": int(len(paths)) < int(args.expected_jobs),
        "method": METHOD,
        "methods": [METHOD],
        "max_parallel_requested": int(args.max_parallel_requested),
        "assumed_effective_parallelism": int(args.assumed_effective_parallelism),
        "minutes_per_stage": float(args.minutes_per_stage),
        "estimated_search_minutes_conservative": float(args.waves) * float(args.minutes_per_stage),
        "matrix_split": "single_matrix_80_jobs_per_wave",
        "objective": "gain_or_hold_when_sp500_falls_weekly_and_avoid_losses_when_sp500_rises",
        "locked_opened": False,
        "optimization_period": "train",
        "validation_role": "report_only",
        "validation_used_for_selection": False,
        "sort_order": "train_score_desc",
    }

    leaderboard.to_csv(output_dir / f"{args.file_prefix}_leaderboard.csv", index=False)
    train_top.to_csv(output_dir / f"{args.file_prefix}_train_top.csv", index=False)
    verified.to_csv(output_dir / f"{args.file_prefix}_verified.csv", index=False)
    validation_report.to_csv(output_dir / f"{args.file_prefix}_validation_report.csv", index=False)
    methods.to_csv(output_dir / f"{args.file_prefix}_methods.csv", index=False)
    fail_reasons.to_csv(output_dir / f"{args.file_prefix}_fail_reasons.csv", index=False)
    sizing.to_csv(output_dir / f"{args.file_prefix}_sizing.csv", index=False)
    (output_dir / f"{args.file_prefix}_feature_audit.json").write_text(
        json.dumps(feature_audit, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / f"{args.file_prefix}_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _read_and_dedupe(paths: list[str]) -> pd.DataFrame:
    frames = []
    for path in paths:
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            frames.append(frame)
    return merge_stage_rows(frames)


def _fail_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "rejection_reason" not in frame.columns:
        return pd.DataFrame(columns=["rejection_reason", "count"])
    reasons = frame["rejection_reason"].fillna("").replace("", "verified").value_counts()
    return reasons.rename_axis("rejection_reason").reset_index(name="count")


def _feature_audit(pattern: str) -> dict[str, object]:
    if not pattern:
        return {"available": False, "locked_opened": False}
    paths = sorted(glob.glob(pattern, recursive=True))
    for path in paths:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        payload["audit_files_found"] = len(paths)
        payload["locked_opened"] = False
        return payload
    return {"available": False, "audit_files_found": len(paths), "locked_opened": False}


if __name__ == "__main__":
    raise SystemExit(main())
