"""Verify one Atlas segment before it is accepted for final reduction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import AtlasRunPlanV1, load_plan
from aurora.infra.sp500_megarun.atlas_segments import load_segment_manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_row(row: dict[str, Any], *, plan_sha256: str, shard_index: int) -> int:
    if row.get("plan_sha256") != plan_sha256:
        raise ValueError("ATLAS_SEGMENT_ROW_PLAN_MISMATCH")
    if int(row.get("shard_index", -1)) != shard_index:
        raise ValueError("ATLAS_SEGMENT_ROW_SHARD_MISMATCH")
    if row.get("validation_opened") is not False or row.get("locked_opened") is not False:
        raise ValueError("ATLAS_SEGMENT_ROW_BOUNDARY_OPEN")
    supplied = row.get("result_sha256")
    identity = {key: value for key, value in row.items() if key != "result_sha256"}
    if supplied != canonical_sha256(identity):
        raise ValueError("ATLAS_SEGMENT_ROW_HASH_INVALID")
    return int(row["ordinal"])


def _receipt_paths(root: Path) -> list[Path]:
    return sorted(Path(root).rglob("worker_receipt.json"))


def _result_path(receipt_path: Path) -> Path:
    result = receipt_path.parent / "results.jsonl"
    if not result.is_file():
        raise ValueError(f"ATLAS_SEGMENT_RESULTS_MISSING:{receipt_path.parent}")
    return result


def _read_rows(path: Path):
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"ATLAS_SEGMENT_ROW_OBJECT_REQUIRED:{line_number}")
            yield row


def verify_segment(
    *,
    plan_path: Path,
    segment_manifest_path: Path,
    segment_index: int,
    partitions_root: Path,
    output_dir: Path,
    plan_object: AtlasRunPlanV1 | None = None,
) -> dict[str, Any]:
    plan = plan_object or load_plan(Path(plan_path))
    manifest = load_segment_manifest(Path(segment_manifest_path).read_text("utf-8"), plan=plan)
    segments = manifest["segments"]
    if segment_index < 0 or segment_index >= len(segments):
        raise ValueError("ATLAS_SEGMENT_INDEX_INVALID")
    segment = segments[segment_index]
    expected_indices = {int(value) for value in segment["shard_indices"]}
    receipt_by_index: dict[int, Path] = {}
    redundant_receipts: list[str] = []
    for path in _receipt_paths(Path(partitions_root)):
        receipt = json.loads(path.read_text("utf-8"))
        shard_index = int(receipt.get("shard_index", -1))
        if shard_index not in expected_indices:
            raise ValueError("ATLAS_SEGMENT_UNEXPECTED_SHARD")
        previous = receipt_by_index.get(shard_index)
        if previous is not None:
            prior = json.loads(previous.read_text("utf-8"))
            if (
                prior.get("plan_sha256") != receipt.get("plan_sha256")
                or prior.get("result_sha256") != receipt.get("result_sha256")
            ):
                raise ValueError("ATLAS_SEGMENT_CONFLICTING_DUPLICATE")
            redundant_receipts.append(str(path))
            continue
        receipt_by_index[shard_index] = path
    if set(receipt_by_index) != expected_indices:
        raise ValueError("ATLAS_SEGMENT_SHARD_COVERAGE_INVALID")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    seen_ordinals: set[int] = set()
    actual_recipe_count = 0
    worker_seconds = 0.0
    result_hashes: dict[str, str] = {}
    for shard_index in sorted(expected_indices):
        shard = plan.shard(shard_index)
        receipt_path = receipt_by_index[shard_index]
        receipt = json.loads(receipt_path.read_text("utf-8"))
        expected = {
            "plan_sha256": plan.plan_sha256,
            "catalog_manifest_sha256": plan.catalog_manifest_sha256,
            "shard_index": shard_index,
            "start_ordinal": shard.start_ordinal,
            "stop_ordinal": shard.stop_ordinal,
            "expected_recipe_count": shard.expected_recipe_count,
            "actual_recipe_count": shard.expected_recipe_count,
            "validation_opened": False,
            "locked_opened": False,
        }
        for key, value in expected.items():
            if receipt.get(key) != value:
                raise ValueError(f"ATLAS_SEGMENT_RECEIPT_MISMATCH:{shard_index}:{key}")
        result_path = _result_path(receipt_path)
        result_hash = _sha256_file(result_path)
        if result_hash != receipt.get("result_sha256"):
            raise ValueError(f"ATLAS_SEGMENT_RESULT_HASH_INVALID:{shard_index}")
        result_hashes[str(shard_index)] = result_hash
        worker_seconds += float(receipt.get("elapsed_seconds", 0.0))
        shard_rows = 0
        for row in _read_rows(result_path):
            ordinal = _verify_row(row, plan_sha256=plan.plan_sha256, shard_index=shard_index)
            if ordinal < shard.start_ordinal or ordinal >= shard.stop_ordinal:
                raise ValueError("ATLAS_SEGMENT_ORDINAL_OUT_OF_RANGE")
            if ordinal in seen_ordinals:
                raise ValueError("ATLAS_SEGMENT_DUPLICATE_ORDINAL")
            seen_ordinals.add(ordinal)
            shard_rows += 1
        if shard_rows != shard.expected_recipe_count:
            raise ValueError(f"ATLAS_SEGMENT_ROW_COUNT_INVALID:{shard_index}")
        actual_recipe_count += shard_rows

    identity = {
        "schema_version": 1,
        "segment_id": segment["segment_id"],
        "segment_index": segment_index,
        "plan_sha256": plan.plan_sha256,
        "segment_manifest_sha256": manifest["manifest_sha256"],
        "shard_indices": sorted(expected_indices),
        "expected_recipe_count": int(segment["expected_recipe_count"]),
        "actual_recipe_count": actual_recipe_count,
        "worker_seconds": worker_seconds,
        "result_hashes": result_hashes,
        "redundant_receipts": redundant_receipts,
        "validation_opened": False,
        "locked_opened": False,
    }
    receipt = {**identity, "segment_sha256": canonical_sha256(identity)}
    (output / "segment_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--segment-manifest", type=Path, required=True)
    parser.add_argument("--segment-index", type=int, required=True)
    parser.add_argument("--partitions-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify_segment(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
