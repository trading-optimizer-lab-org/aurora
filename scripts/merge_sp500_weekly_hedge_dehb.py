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
generate_subperiod_report = _SEARCH.generate_subperiod_report
generate_negative_sp500_years_report = _SEARCH.generate_negative_sp500_years_report
build_hedge_rankings = _SEARCH.build_hedge_rankings


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
    parser.add_argument("--train-start", default="1995-01-01")
    parser.add_argument("--train-end", default="2010-12-31")
    parser.add_argument("--validation-start", default="2011-01-01")
    parser.add_argument("--validation-end", default="2020-12-31")
    parser.add_argument("--locked-start", default="2021-01-01")
    parser.add_argument("--allow-late-entry", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--require-spy-only", action="store_true")
    parser.add_argument("--require-momentum-trend-only", action="store_true")
    parser.add_argument(
        "--exclude-asset-group",
        action="append",
        default=[],
        help="Manifest asset_group excluded by the stage runner. Repeatable.",
    )
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
    subperiods = generate_subperiod_report(merged)
    negative_years = generate_negative_sp500_years_report(merged)
    rankings = build_hedge_rankings(merged)
    feature_audit = _feature_audit(args.audit_glob)
    parallelism = _parallelism_summary(args.input_glob, expected_jobs=int(args.expected_jobs))
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
        "objective": "maximize_convex_protection_on_negative_sp500_weeks_with_acceptable_cost_on_positive_weeks",
        "locked_opened": False,
        "optimization_period": "train",
        "validation_role": "report_only",
        "validation_used_for_selection": False,
        "sort_order": "train_downside_hedge_score_desc",
        "train_start": str(args.train_start),
        "train_end": str(args.train_end),
        "validation_start": str(args.validation_start),
        "validation_end": str(args.validation_end),
        "locked_start": str(args.locked_start),
        "allow_late_entry": bool(args.allow_late_entry),
        "excluded_asset_groups": [str(group) for group in args.exclude_asset_group],
        "crypto_used": False if "crypto_spot" in set(args.exclude_asset_group) else None,
        "single_name_equities_used": False if "equity_single_name" in set(args.exclude_asset_group) else None,
        "subperiods": 6,
        "jobs_started": int(parallelism["jobs_started"]),
        "jobs_completed": int(parallelism["jobs_completed"]),
        "max_parallel_observed": int(parallelism["max_parallel_observed"]),
        "parallelism_valid": bool(parallelism["parallelism_valid"]),
        "spy_only": bool(feature_audit.get("spy_only", False)) if args.require_spy_only else None,
        "feature_filter": str(feature_audit.get("feature_filter", "")) if args.require_momentum_trend_only else "",
    }

    leaderboard.to_csv(output_dir / f"{args.file_prefix}_leaderboard.csv", index=False)
    train_top.to_csv(output_dir / f"{args.file_prefix}_train_top.csv", index=False)
    verified.to_csv(output_dir / f"{args.file_prefix}_verified.csv", index=False)
    validation_report.to_csv(output_dir / f"{args.file_prefix}_validation_report.csv", index=False)
    methods.to_csv(output_dir / f"{args.file_prefix}_methods.csv", index=False)
    fail_reasons.to_csv(output_dir / f"{args.file_prefix}_fail_reasons.csv", index=False)
    sizing.to_csv(output_dir / f"{args.file_prefix}_sizing.csv", index=False)
    subperiods.to_csv(output_dir / f"{args.file_prefix}_subperiods.csv", index=False)
    negative_years.to_csv(output_dir / f"{args.file_prefix}_negative_sp500_years_report.csv", index=False)
    for name, ranking in rankings.items():
        ranking.to_csv(output_dir / f"{args.file_prefix}_{name}.csv", index=False)
    _feature_audit_frame(feature_audit).to_csv(output_dir / f"{args.file_prefix}_feature_audit.csv", index=False)
    (output_dir / f"{args.file_prefix}_parallelism.json").write_text(
        json.dumps(parallelism, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / f"{args.file_prefix}_feature_audit.json").write_text(
        json.dumps(feature_audit, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / f"{args.file_prefix}_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    _fail_if_invalid_summary(
        summary,
        feature_audit,
        allow_partial=bool(args.allow_partial),
        require_spy_only=bool(args.require_spy_only),
        require_momentum_trend_only=bool(args.require_momentum_trend_only),
    )
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


def _feature_audit_frame(feature_audit: dict[str, object]) -> pd.DataFrame:
    features = feature_audit.get("feature_columns_used_names", [])
    if not isinstance(features, list):
        features = []
    if not features:
        return pd.DataFrame(
            [
                {
                    "feature": "",
                    "allowed": False,
                    "feature_filter": feature_audit.get("feature_filter", ""),
                    "spy_only": bool(feature_audit.get("spy_only", False)),
                    "crypto_used": bool(feature_audit.get("crypto_used", False)),
                }
            ]
        )
    return pd.DataFrame(
        [
            {
                "feature": str(feature),
                "allowed": True,
                "feature_filter": feature_audit.get("feature_filter", ""),
                "spy_only": bool(feature_audit.get("spy_only", False)),
                "crypto_used": bool(feature_audit.get("crypto_used", False)),
            }
            for feature in features
        ]
    )


def _parallelism_summary(pattern: str, *, expected_jobs: int) -> dict[str, object]:
    root = _root_from_glob(pattern)
    metas = []
    if root.exists():
        for path in root.rglob("job_meta.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if payload.get("started_epoch") is not None:
                metas.append(payload)
    events: list[tuple[float, int]] = []
    for meta in metas:
        start = float(meta.get("started_epoch") or 0.0)
        end = float(meta.get("ended_epoch") or start)
        events.append((start, 1))
        events.append((end, -1))
    active = 0
    max_active = 0
    for _, delta in sorted(events, key=lambda item: (item[0], -item[1])):
        active += delta
        max_active = max(max_active, active)
    starts = [float(meta.get("started_epoch")) for meta in metas if meta.get("started_epoch") is not None]
    return {
        "jobs_started": int(len(metas)),
        "jobs_completed": int(sum(1 for meta in metas if meta.get("ended_epoch") is not None)),
        "expected_jobs": int(expected_jobs),
        "max_parallel_observed": int(max_active),
        "parallelism_valid": bool(max_active >= int(expected_jobs)),
        "first_start_epoch": min(starts) if starts else None,
        "last_start_epoch": max(starts) if starts else None,
        "first_last_start_spread_seconds": (max(starts) - min(starts)) if starts else None,
    }


def _root_from_glob(pattern: str) -> Path:
    marker = "**"
    if marker in pattern:
        return Path(pattern.split(marker, 1)[0])
    return Path(pattern).parent


def _fail_if_invalid_summary(
    summary: dict[str, object],
    feature_audit: dict[str, object],
    *,
    allow_partial: bool = False,
    require_spy_only: bool = False,
    require_momentum_trend_only: bool = False,
) -> None:
    if int(summary.get("stage_files_found", 0) or 0) <= 0:
        raise SystemExit("merge failed: no stage artifacts found")
    if bool(summary.get("partial", False)) and not allow_partial:
        raise SystemExit("merge failed: partial stage artifacts")
    if int(summary.get("rows", 0) or 0) <= 0:
        raise SystemExit("merge failed: no merged candidate rows")
    if bool(summary.get("locked_opened", True)) or bool(feature_audit.get("locked_opened", True)):
        raise SystemExit("merge failed: locked_opened must be false")
    excluded = {str(group) for group in summary.get("excluded_asset_groups", []) or []}
    if "crypto_spot" in excluded and summary.get("crypto_used") is not False:
        raise SystemExit("merge failed: crypto exclusion was not confirmed")
    if "equity_single_name" in excluded and summary.get("single_name_equities_used") is not False:
        raise SystemExit("merge failed: single-name equity exclusion was not confirmed")
    if require_spy_only and feature_audit.get("spy_only") is not True:
        raise SystemExit("merge failed: SPY-only audit was not confirmed")
    if require_momentum_trend_only and feature_audit.get("feature_filter") != "momentum_trend_only":
        raise SystemExit("merge failed: momentum/trend-only feature audit was not confirmed")
    if require_momentum_trend_only and feature_audit.get("forbidden_features_found"):
        used = set(feature_audit.get("feature_columns_used_names", []) or [])
        forbidden_used = [feature for feature in feature_audit.get("forbidden_features_found", []) or [] if feature in used]
        if forbidden_used:
            raise SystemExit("merge failed: forbidden features were used")


if __name__ == "__main__":
    raise SystemExit(main())
