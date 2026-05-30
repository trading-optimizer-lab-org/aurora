from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from aurora.research.btc_5m_trainonly_search import METHODS, merge_stage_rows, method_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge BTC 5m train-only stage artifacts.")
    parser.add_argument("--input-glob", required=True)
    parser.add_argument("--audit-glob", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--file-prefix", default="btc_5m_all_features_5methods_trainonly_1h_180jobs")
    parser.add_argument("--expected-jobs", type=int, default=180)
    parser.add_argument("--top-n", type=int, default=1000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(glob.glob(args.input_glob, recursive=True))
    frames = []
    for path in paths:
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            frames.append(frame)
    merged = merge_stage_rows(frames)
    if not merged.empty and "train_score" in merged.columns:
        merged = merged.sort_values("train_score", ascending=False).reset_index(drop=True)

    leaderboard = merged
    train_top = merged.head(int(args.top_n)) if not merged.empty else merged
    verified = merged[merged["verified"].astype(bool)].copy() if not merged.empty and "verified" in merged.columns else merged.head(0).copy()
    validation_cols = [column for column in merged.columns if column.startswith("validation_")]
    id_cols = [column for column in ("candidate_id", "method", "source_method", "features", "position_size", "train_score", "verified", "rejection_reason") if column in merged.columns]
    validation_report = merged[id_cols + validation_cols].copy() if not merged.empty else merged
    sizing_cols = [column for column in merged.columns if column in {"candidate_id", "method", "position_size", "max_leverage"} or column.startswith("train_1x_") or column.startswith("train_") or column.startswith("validation_1x_") or column.startswith("validation_")]
    sizing = merged[sizing_cols].copy() if not merged.empty else merged
    methods = method_summary(merged)
    fail_reasons = _fail_reasons(merged)
    summary = {
        "rows": int(len(leaderboard)),
        "unique_candidates": int(leaderboard["candidate_id"].nunique()) if "candidate_id" in leaderboard.columns else 0,
        "verified": int(leaderboard["verified"].astype(bool).sum()) if "verified" in leaderboard.columns else 0,
        "stage_files_found": int(len(paths)),
        "expected_jobs": int(args.expected_jobs),
        "partial": int(len(paths)) < int(args.expected_jobs),
        "methods": list(METHODS),
        "locked_opened": False,
        "validation_role": "report_only",
        "optimization_period": "train",
        "validation_used_for_selection": False,
        "sort_order": "train_score_desc",
    }
    feature_audit = _feature_audit(args.audit_glob)

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
