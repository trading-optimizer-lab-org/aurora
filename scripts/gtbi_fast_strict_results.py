"""Expand canonical GTBI results to all proven economically equivalent aliases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts import global_technical_buy_indicator as gtbi
from scripts import gtbi_fast_strict as planner


ALIAS_COLUMNS = [
    "strategy_id",
    "evaluation_hash",
    "canonical_strategy_id",
    "source_shard_id",
    "source_slot_in_shard",
    "global_slot",
    "worker_id",
]
HASH_COLUMNS = ["economic_hash", "canonical_hash", "signal_hash", "exit_hash"]


def _read_csv(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns or [])
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=columns or [])


def _write_csv(path: Path, frame: pd.DataFrame, columns: list[str] | None = None) -> None:
    if frame.empty and columns is not None:
        frame = pd.DataFrame(columns=columns)
    frame.to_csv(path, index=False)


def _campaign_fingerprint(path: Path) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    fingerprint = str(payload.get("campaign_fingerprint") or "")
    if not fingerprint:
        raise ValueError(f"campaign manifest has no fingerprint: {path}")
    return fingerprint


def _campaign_inputs(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    inputs = dict(payload.get("inputs") or {})
    required = (
        "train_end",
        "validation_start",
        "validation_end",
        "locked_start",
        "min_market_cap",
    )
    missing = [name for name in required if inputs.get(name) in (None, "")]
    if missing:
        raise ValueError(f"campaign manifest is missing inputs: {', '.join(missing)}")
    return inputs


def _validate_alias_map(alias_map: pd.DataFrame, expected_alias_count: int) -> None:
    missing = [column for column in ALIAS_COLUMNS if column not in alias_map.columns]
    if missing:
        raise ValueError(f"alias map is missing columns: {', '.join(missing)}")
    if len(alias_map) != int(expected_alias_count):
        raise ValueError(
            f"alias count {len(alias_map)} differs from expected count {expected_alias_count}"
        )
    if alias_map["strategy_id"].isna().any() or alias_map["strategy_id"].astype(str).str.strip().eq("").any():
        raise ValueError("alias map contains an empty strategy_id")
    if alias_map["strategy_id"].astype(str).duplicated().any():
        raise ValueError("alias map contains duplicate strategy_id values")
    slots = pd.to_numeric(alias_map["global_slot"], errors="raise").astype(int)
    if slots.duplicated().any():
        raise ValueError("alias map contains duplicate global_slot values")
    shards = pd.to_numeric(alias_map["source_shard_id"], errors="raise").astype(int)
    positions = pd.to_numeric(alias_map["source_slot_in_shard"], errors="raise").astype(int)
    if bool(((shards < 0) | (shards > 359)).any()):
        raise ValueError("alias map source_shard_id is outside 0..359")
    if bool(((positions < 0) | (positions > 199)).any()):
        raise ValueError("alias map source_slot_in_shard is outside 0..199")
    expected_slots = shards * 200 + positions
    if not bool((slots.to_numpy() == expected_slots.to_numpy()).all()):
        raise ValueError("alias map global_slot does not match source identity")


def _candidate_map(original_pack_path: Path) -> dict[str, gtbi.ExternalStrategyCandidate]:
    candidates = gtbi.load_external_strategy_candidates(
        Path(original_pack_path),
        shard_id=None,
        offset=0,
        limit=None,
        strategy_format="auto",
    )
    result: dict[str, gtbi.ExternalStrategyCandidate] = {}
    for candidate in candidates:
        strategy_id = str(candidate.payload.get("strategy_id") or "")
        if not strategy_id or strategy_id in result:
            raise ValueError(f"original pack has invalid or duplicate strategy_id {strategy_id!r}")
        result[strategy_id] = candidate
    return result


def _records_by_id(frame: pd.DataFrame, id_column: str) -> dict[str, dict[str, Any]]:
    if frame.empty:
        return {}
    gtbi._assert_consistent_duplicate_rows(frame, [id_column], label=id_column)
    return {
        str(row[id_column]): row.to_dict()
        for _, row in frame.drop_duplicates(subset=[id_column], keep="first").iterrows()
    }


def _planned_hash(alias: pd.Series, name: str, actual: str) -> str:
    if name not in alias.index or pd.isna(alias[name]) or not str(alias[name]).strip():
        return actual
    planned = str(alias[name])
    if planned != actual:
        raise ValueError(f"{name} mismatch for alias {alias['strategy_id']}")
    return planned


def _rank_leaderboard(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.sort_values(["score", "candidate_id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)


def _filtered_leaderboard(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "strict_quality_pass" not in frame.columns:
        return pd.DataFrame(columns=frame.columns)
    filtered = frame.loc[
        frame["strict_quality_pass"].astype(str).str.lower().isin({"true", "1"})
    ].copy()
    if filtered.empty:
        return filtered
    return filtered.sort_values(
        ["adjusted_return_time_risk", "candidate_id"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def expand_canonical_results(
    *,
    canonical_results_root: Path,
    alias_map_path: Path,
    original_pack_path: Path,
    campaign_manifest_path: Path,
    output_dir: Path,
    expected_alias_count: int = 72_000,
) -> dict[str, Any]:
    """Create strict-merge inputs for every original strategy identity."""
    canonical_root = Path(canonical_results_root)
    output = Path(output_dir)
    if output.is_file() or (output.exists() and any(path.is_file() for path in output.rglob("*"))):
        raise ValueError(f"output directory already contains files: {output}")
    output.mkdir(parents=True, exist_ok=True)

    fingerprint = _campaign_fingerprint(Path(campaign_manifest_path))
    inputs = _campaign_inputs(Path(campaign_manifest_path))
    canonical_manifest = canonical_root / "campaign_manifest.json"
    if _campaign_fingerprint(canonical_manifest) != fingerprint:
        raise ValueError("campaign fingerprint mismatch between canonical results and plan")

    alias_map = _read_csv(Path(alias_map_path), ALIAS_COLUMNS)
    _validate_alias_map(alias_map, expected_alias_count)
    candidates = _candidate_map(Path(original_pack_path))
    alias_ids = set(alias_map["strategy_id"].astype(str))
    if set(candidates) != alias_ids:
        missing_from_pack = sorted(alias_ids - set(candidates))
        extra_in_pack = sorted(set(candidates) - alias_ids)
        raise ValueError(
            "alias/original-pack identity mismatch: "
            f"missing={missing_from_pack[:5]} extra={extra_in_pack[:5]}"
        )

    leaderboard = _read_csv(canonical_root / "leaderboard.csv", gtbi.LEADERBOARD_COLUMNS)
    rejected = _read_csv(canonical_root / "early_rejected_strategies.csv", gtbi.EARLY_REJECT_COLUMNS)
    yearly = _read_csv(canonical_root / "yearly_trade_performance.csv", gtbi.YEARLY_COLUMNS)
    timing = _read_csv(canonical_root / "timing_diagnostics.csv", gtbi.TIMING_DIAGNOSTIC_COLUMNS)
    gtbi._assert_consistent_duplicate_rows(leaderboard, ["candidate_id"], label="canonical leaderboard")
    gtbi._assert_consistent_duplicate_rows(rejected, ["strategy_id"], label="canonical early_rejected")
    gtbi._assert_consistent_duplicate_rows(
        yearly,
        ["candidate_id", "split", "year"],
        label="canonical yearly",
    )

    leaderboard_by_id = _records_by_id(leaderboard, "candidate_id")
    rejected_by_id = _records_by_id(rejected, "strategy_id")
    mixed = set(leaderboard_by_id) & set(rejected_by_id)
    if mixed:
        raise ValueError(f"canonical strategies have mixed terminal outcomes: {sorted(mixed)[:5]}")
    canonical_ids = set(alias_map["canonical_strategy_id"].astype(str))
    terminal_ids = set(leaderboard_by_id) | set(rejected_by_id)
    if canonical_ids != terminal_ids:
        raise ValueError(
            "canonical terminal identity mismatch: "
            f"missing={sorted(canonical_ids - terminal_ids)[:5]} "
            f"extra={sorted(terminal_ids - canonical_ids)[:5]}"
        )

    yearly_groups = {
        str(candidate_id): group.copy()
        for candidate_id, group in yearly.groupby("candidate_id", sort=False)
    } if not yearly.empty and "candidate_id" in yearly.columns else {}
    timing_by_id = _records_by_id(timing, "strategy_id")

    leaderboard_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    yearly_frames: list[pd.DataFrame] = []
    timing_rows: list[dict[str, Any]] = []
    dedupe_rows: list[dict[str, Any]] = []
    job_rows: list[dict[str, Any]] = []

    aliases = alias_map.sort_values(["global_slot", "strategy_id"], kind="stable")
    for _, alias in aliases.iterrows():
        strategy_id = str(alias["strategy_id"])
        canonical_id = str(alias["canonical_strategy_id"])
        evaluation_hash = str(alias["evaluation_hash"])
        candidate = candidates[strategy_id]
        actual_hash = planner.economic_evaluation_hash(candidate)
        if actual_hash != evaluation_hash:
            raise ValueError(f"economic hash mismatch for alias {strategy_id}")
        canonical_candidate = candidates.get(canonical_id)
        if canonical_candidate is None or planner.economic_evaluation_hash(canonical_candidate) != evaluation_hash:
            raise ValueError(f"unknown or mismatched canonical strategy {canonical_id}")
        hashes = {
            "economic_hash": evaluation_hash,
            "canonical_hash": gtbi.canonical_external_strategy_hash(candidate),
            "signal_hash": _planned_hash(
                alias,
                "signal_hash",
                planner.signal_evaluation_hash(candidate),
            ),
            "exit_hash": _planned_hash(
                alias,
                "exit_hash",
                planner.exit_evaluation_hash(candidate),
            ),
        }

        if canonical_id in leaderboard_by_id:
            row = dict(leaderboard_by_id[canonical_id])
            row.update(gtbi._external_metadata(candidate.payload))
            row["candidate_id"] = strategy_id
            leaderboard_rows.append(row)
            canonical_yearly = yearly_groups.get(canonical_id)
            if canonical_yearly is not None:
                alias_yearly = canonical_yearly.copy()
                alias_yearly["candidate_id"] = strategy_id
                yearly_frames.append(alias_yearly)
            result_status = "evaluated" if strategy_id == canonical_id else "deduped"
        elif canonical_id in rejected_by_id:
            row = dict(rejected_by_id[canonical_id])
            row["strategy_id"] = strategy_id
            row["shard_id"] = int(alias["source_shard_id"])
            row["slot_in_shard"] = int(alias["source_slot_in_shard"])
            rejected_rows.append(row)
            result_status = "early_rejected"
        else:
            raise ValueError(f"unknown canonical terminal result {canonical_id}")

        canonical_timing = dict(timing_by_id.get(canonical_id, {}))
        canonical_timing.update(
            gtbi._external_diagnostic_base(
                candidate.payload,
                job_id=str(alias["worker_id"]),
            )
        )
        canonical_timing.update(
            {
                "strategy_id": strategy_id,
                "result_status": result_status,
                "canonical_strategy_id": canonical_id,
                "evaluation_hash": evaluation_hash,
                "deduped": strategy_id != canonical_id,
                **hashes,
            }
        )
        timing_rows.append(canonical_timing)
        dedupe_rows.append(
            {
                "strategy_id": strategy_id,
                **hashes,
                "canonical_strategy_id": canonical_id,
                "deduped": strategy_id != canonical_id,
                "signal_canonical_strategy_id": canonical_id,
                "signal_deduped": strategy_id != canonical_id,
            }
        )
        job_rows.append(
            {
                "job_id": int(alias["worker_id"]),
                "strategy_id": strategy_id,
                "shard_id": int(alias["source_shard_id"]),
                "slot_in_shard": int(alias["source_slot_in_shard"]),
                **hashes,
                "cost_score": "",
                "estimated_cost_bucket": "economic_alias",
            }
        )

    expanded_leaderboard = _rank_leaderboard(pd.DataFrame(leaderboard_rows))
    expanded_filtered = _filtered_leaderboard(expanded_leaderboard)
    expanded_rejected = pd.DataFrame(rejected_rows)
    expanded_yearly = (
        pd.concat(yearly_frames, ignore_index=True, sort=False)
        if yearly_frames
        else pd.DataFrame(columns=gtbi.YEARLY_COLUMNS)
    )
    expanded_timing = pd.DataFrame(timing_rows)
    _write_csv(output / "leaderboard_job_aliases.csv", expanded_leaderboard, gtbi.LEADERBOARD_COLUMNS)
    _write_csv(
        output / "filtered_leaderboard_job_aliases.csv",
        expanded_filtered,
        list(expanded_leaderboard.columns),
    )
    _write_csv(output / "early_rejected_strategies_job_aliases.csv", expanded_rejected, gtbi.EARLY_REJECT_COLUMNS)
    _write_csv(output / "yearly_trade_performance_job_aliases.csv", expanded_yearly, gtbi.YEARLY_COLUMNS)
    _write_csv(output / "timing_diagnostics_job_aliases.csv", expanded_timing, gtbi.TIMING_DIAGNOSTIC_COLUMNS)
    _write_csv(output / "dedupe_map_job_aliases.csv", pd.DataFrame(dedupe_rows), gtbi.DEDUPE_MAP_COLUMNS)
    _write_csv(output / "job_manifest_job_aliases.csv", pd.DataFrame(job_rows), gtbi.JOB_MANIFEST_COLUMNS)
    _write_csv(output / "timeout_strategies_job_aliases.csv", pd.DataFrame(), gtbi.TIMEOUT_COLUMNS)
    _write_csv(output / "slow_deferred_strategies_job_aliases.csv", pd.DataFrame(), gtbi.SLOW_DEFERRED_COLUMNS)
    _write_csv(output / "unsupported_strategies_job_aliases.csv", pd.DataFrame(), gtbi.UNSUPPORTED_COLUMNS)
    _write_csv(output / "runtime_errors_job_aliases.csv", pd.DataFrame(), gtbi.RUNTIME_ERROR_COLUMNS)

    summary = {
        "campaign_fingerprint": fingerprint,
        "total_aliases": int(len(alias_map)),
        "canonical_evaluations": int(len(canonical_ids)),
        "leaderboard_rows": int(len(expanded_leaderboard)),
        "early_rejected_rows": int(len(expanded_rejected)),
        "timeout_rows": 0,
        "runtime_error_rows": 0,
        "unsupported_rows": 0,
        "slow_deferred_rows": 0,
        "synthetic_missing_timeout_rows": 0,
        "fill_missing_timeouts_enabled": False,
        "total_strategies_loaded": int(len(alias_map)),
        "total_strategies_evaluated": int(len(expanded_leaderboard)),
        "total_strategies_early_rejected": int(len(expanded_rejected)),
        "total_strategies_timed_out": 0,
        "total_strategies_runtime_error": 0,
        "total_strategies_unsupported": 0,
        "total_strategies_slow_deferred": 0,
        "strategy_slots_requested": int(len(alias_map)),
        "locked_start": str(inputs["locked_start"]),
        "train_end": str(inputs["train_end"]),
        "validation_start": str(inputs["validation_start"]),
        "validation_end": str(inputs["validation_end"]),
        "min_market_cap": inputs["min_market_cap"],
    }
    (output / "summary_job_aliases.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "campaign_manifest.json").write_text(
        Path(campaign_manifest_path).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-results-root", type=Path, required=True)
    parser.add_argument("--alias-map", type=Path, required=True)
    parser.add_argument("--original-pack", type=Path, required=True)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-alias-count", type=int, default=72_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = expand_canonical_results(
        canonical_results_root=args.canonical_results_root,
        alias_map_path=args.alias_map,
        original_pack_path=args.original_pack,
        campaign_manifest_path=args.campaign_manifest,
        output_dir=args.output_dir,
        expected_alias_count=args.expected_alias_count,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
