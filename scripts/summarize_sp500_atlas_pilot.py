"""Verify real pilot shards and report measured effective concurrency."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.atlas_pilot import load_pilot_manifest
try:
    from scripts.verify_sp500_atlas_segment import _read_rows, _verify_row
except ModuleNotFoundError:
    from verify_sp500_atlas_segment import _read_rows, _verify_row


def summarize_worker_intervals(
    intervals: Iterable[tuple[datetime, datetime, float]],
) -> dict[str, float]:
    values = list(intervals)
    if not values:
        raise ValueError("ATLAS_PILOT_INTERVALS_EMPTY")
    start = min(item[0] for item in values)
    finish = max(item[1] for item in values)
    worker_seconds = sum(float(item[2]) for item in values)
    wall_seconds = (finish - start).total_seconds()
    if wall_seconds <= 0:
        raise ValueError("ATLAS_PILOT_WALL_TIME_INVALID")
    return {
        "worker_seconds": worker_seconds,
        "wall_seconds": wall_seconds,
        "effective_concurrency": worker_seconds / wall_seconds,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def summarize_pilot(
    *,
    plan_path: Path,
    pilot_manifest_path: Path,
    partitions_root: Path,
    fault_receipt_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    plan = load_plan(plan_path)
    pilot = load_pilot_manifest(pilot_manifest_path.read_text("utf-8"), plan=plan)
    expected_indices = {int(value) for value in pilot["shard_indices"]}
    receipt_by_index: dict[int, Path] = {}
    for path in sorted(Path(partitions_root).rglob("worker_receipt.json")):
        receipt = json.loads(path.read_text("utf-8"))
        index = int(receipt.get("shard_index", -1))
        if index not in expected_indices:
            raise ValueError("ATLAS_PILOT_UNEXPECTED_SHARD")
        prior_path = receipt_by_index.get(index)
        if prior_path is not None:
            prior = json.loads(prior_path.read_text("utf-8"))
            if prior.get("result_sha256") != receipt.get("result_sha256"):
                raise ValueError("ATLAS_PILOT_CONFLICTING_DUPLICATE")
            continue
        receipt_by_index[index] = path
    if set(receipt_by_index) != expected_indices:
        raise ValueError("ATLAS_PILOT_SHARD_COVERAGE_INVALID")

    intervals: list[tuple[datetime, datetime, float]] = []
    actual_recipe_count = 0
    for index in sorted(expected_indices):
        shard = plan.shard(index)
        receipt_path = receipt_by_index[index]
        receipt = json.loads(receipt_path.read_text("utf-8"))
        for key, value in {
            "plan_sha256": plan.plan_sha256,
            "catalog_manifest_sha256": plan.catalog_manifest_sha256,
            "shard_index": index,
            "start_ordinal": shard.start_ordinal,
            "stop_ordinal": shard.stop_ordinal,
            "expected_recipe_count": shard.expected_recipe_count,
            "actual_recipe_count": shard.expected_recipe_count,
            "validation_opened": False,
            "locked_opened": False,
        }.items():
            if receipt.get(key) != value:
                raise ValueError(f"ATLAS_PILOT_RECEIPT_MISMATCH:{index}:{key}")
        results = receipt_path.parent / "results.jsonl"
        if _sha256_file(results) != receipt.get("result_sha256"):
            raise ValueError("ATLAS_PILOT_RESULT_HASH_INVALID")
        seen = 0
        for row in _read_rows(results):
            ordinal = _verify_row(row, plan_sha256=plan.plan_sha256, shard_index=index)
            if ordinal < shard.start_ordinal or ordinal >= shard.stop_ordinal:
                raise ValueError("ATLAS_PILOT_ORDINAL_INVALID")
            seen += 1
        if seen != shard.expected_recipe_count:
            raise ValueError("ATLAS_PILOT_ROW_COUNT_INVALID")
        actual_recipe_count += seen
        started = datetime.fromisoformat(str(receipt["started_at_iso"]).replace("Z", "+00:00"))
        finished = datetime.fromisoformat(str(receipt["finished_at_iso"]).replace("Z", "+00:00"))
        intervals.append((started, finished, float(receipt["elapsed_seconds"])))

    if not fault_receipt_path.is_file():
        raise ValueError("ATLAS_PILOT_FAULT_RECEIPT_MISSING")
    fault = json.loads(fault_receipt_path.read_text("utf-8"))
    if any(fault.get(key) is not True for key in (
        "retry_once_success",
        "corrupt_artifact_rejected",
        "identical_duplicate_accepted_once",
        "controller_duplicate_invocation_idempotent",
    )):
        raise ValueError("ATLAS_PILOT_FAULT_FIXTURE_INCOMPLETE")
    timing = summarize_worker_intervals(intervals)
    receipt = {
        "schema_version": 1,
        "accepted": True,
        "plan_sha256": plan.plan_sha256,
        "pilot_manifest_sha256": pilot["manifest_sha256"],
        "shard_count": len(expected_indices),
        "expected_recipe_count": pilot["expected_recipe_count"],
        "actual_recipe_count": actual_recipe_count,
        **timing,
        "fault_fixture_receipt_sha256": _sha256_file(fault_receipt_path),
        "validation_opened": False,
        "locked_opened": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--pilot-manifest", type=Path, required=True)
    parser.add_argument("--partitions-root", type=Path, required=True)
    parser.add_argument("--fault-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize_pilot(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
