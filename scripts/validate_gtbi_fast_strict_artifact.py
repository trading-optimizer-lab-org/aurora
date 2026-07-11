"""Fail-closed validation for a final GTBI Fast Strict V6 artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_DATES = {
    "train_end": "2010-12-31",
    "validation_start": "2011-01-01",
    "validation_end": "2020-12-31",
    "locked_start": "2021-01-01",
}
FAILURE_FILES = (
    "timeout_strategies.csv",
    "runtime_errors.csv",
    "unsupported_strategies.csv",
    "slow_deferred_strategies.csv",
)
REQUIRED_FILES = (
    "summary.json",
    "campaign_manifest.json",
    "leaderboard.csv",
    "early_rejected_strategies.csv",
    "dedupe_map.csv",
    "yearly_trade_performance.csv",
    *FAILURE_FILES,
    "_SUCCESS",
)


def _json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _count(summary: dict[str, Any], *names: str) -> int:
    for name in names:
        if name in summary:
            return int(summary[name] or 0)
    raise ValueError(f"summary is missing strict count: {'/'.join(names)}")


def _ids(frame: pd.DataFrame, *columns: str) -> list[str]:
    for column in columns:
        if column in frame.columns:
            return frame[column].dropna().astype(str).tolist()
    if frame.empty:
        return []
    raise ValueError(f"table is missing identity column: {columns}")


def validate_artifact(root: Path, *, expected_strategy_count: int = 72_000) -> dict[str, Any]:
    """Validate every cross-file invariant and return observed row counts."""

    source = Path(root)
    if not source.is_dir():
        raise ValueError(f"artifact directory does not exist: {source}")
    missing_files = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing_files:
        raise ValueError(f"artifact is missing required files including _SUCCESS: {missing_files}")

    summary = _json(source / "summary.json")
    campaign = _json(source / "campaign_manifest.json")
    fingerprint = str(summary.get("campaign_fingerprint") or "")
    if not fingerprint or str(campaign.get("campaign_fingerprint") or "") != fingerprint:
        raise ValueError("campaign fingerprint mismatch")
    success_value = (source / "_SUCCESS").read_text(encoding="utf-8").strip()
    if success_value not in {fingerprint, "strict_final_pass=true"}:
        raise ValueError("_SUCCESS does not bind the final campaign fingerprint")

    for field, expected in REQUIRED_DATES.items():
        if str(summary.get(field) or "") != expected:
            raise ValueError(f"{field} differs from strict value {expected}")
    if summary.get("github_only_run") is not True:
        raise ValueError("github_only_run must be true")
    if summary.get("requires_local_machine") is not False:
        raise ValueError("requires_local_machine must be false")
    if summary.get("strict_final_pass") is not True:
        raise ValueError("strict_final_pass must be true")
    if summary.get("fill_missing_timeouts_enabled") is not False:
        raise ValueError("fill_missing_timeouts_enabled must be false")
    if int(summary.get("synthetic_missing_timeout_rows", -1)) != 0:
        raise ValueError("synthetic_missing_timeout_rows must be zero")

    leaderboard = _csv(source / "leaderboard.csv")
    early = _csv(source / "early_rejected_strategies.csv")
    leaderboard_ids = _ids(leaderboard, "candidate_id", "strategy_id")
    early_ids = _ids(early, "strategy_id", "candidate_id")
    if len(leaderboard) != _count(summary, "total_strategies_evaluated", "strategies_evaluated"):
        raise ValueError("leaderboard row count differs from total_strategies_evaluated")
    if len(early) != _count(summary, "total_strategies_early_rejected", "strategies_early_rejected"):
        raise ValueError("early-rejected row count differs from summary")

    terminal_ids = leaderboard_ids + early_ids
    if len(terminal_ids) != len(set(terminal_ids)):
        raise ValueError("duplicate terminal strategy identity")
    if len(terminal_ids) != expected_strategy_count:
        raise ValueError(
            f"terminal strategy count {len(terminal_ids)} differs from expected {expected_strategy_count}"
        )
    requested = _count(summary, "total_strategies_requested", "strategies_requested")
    loaded = _count(summary, "total_strategies_loaded", "strategies_loaded")
    if requested != expected_strategy_count or loaded != expected_strategy_count:
        raise ValueError("requested/loaded strategy counts differ from strict expected count")

    for filename in FAILURE_FILES:
        frame = _csv(source / filename)
        if not frame.empty:
            raise ValueError(f"{filename} contains {len(frame)} failure rows")
    failure_counts = (
        ("total_strategies_timed_out", "strategies_timed_out"),
        ("total_strategies_runtime_error", "strategies_runtime_error"),
        ("total_strategies_unsupported", "strategies_unsupported"),
        ("total_strategies_slow_deferred", "strategies_slow_deferred"),
    )
    for names in failure_counts:
        if _count(summary, *names) != 0:
            raise ValueError(f"summary has nonzero failure count {names[0]}")

    best = summary.get("best_candidate_id")
    if leaderboard_ids:
        if best is None or str(best) not in set(leaderboard_ids):
            raise ValueError("best_candidate_id does not exist in leaderboard.csv")
    elif best is not None:
        raise ValueError("best_candidate_id must be null when leaderboard.csv is empty")

    dedupe = _csv(source / "dedupe_map.csv")
    dedupe_ids = _ids(dedupe, "strategy_id", "candidate_id")
    if len(dedupe_ids) != expected_strategy_count or set(dedupe_ids) != set(terminal_ids):
        raise ValueError("dedupe_map does not cover exactly all terminal strategy identities")

    return {
        "valid": True,
        "campaign_fingerprint": fingerprint,
        "expected_strategy_count": expected_strategy_count,
        "terminal_count": len(terminal_ids),
        "leaderboard_rows": len(leaderboard),
        "early_rejected_rows": len(early),
        "dedupe_map_rows": len(dedupe),
        "yearly_trade_performance_rows": len(_csv(source / "yearly_trade_performance.csv")),
        "best_candidate_id": best,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--expected-strategy-count", type=int, default=72_000)
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = validate_artifact(args.artifact_dir, expected_strategy_count=args.expected_strategy_count)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
