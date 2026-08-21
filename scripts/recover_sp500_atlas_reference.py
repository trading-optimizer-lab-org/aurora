"""Verify one block of immutable SP500 Atlas source artifacts.

This recovery path never re-evaluates a recipe and never builds a combined
results file.  The original run remains the source of every complete result;
this script verifies a bounded block and emits only a compact index fragment.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
from typing import Any

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts.reduce_sp500_atlas_run import (
    _cell,
    _find_result_path,
    _read_recovery_shard_payload,
    _verify_row,
)


def _receipt_by_index(partitions_root: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for receipt_path in sorted(Path(partitions_root).rglob("worker_receipt.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        index = int(receipt.get("shard_index", -1))
        if index in result:
            raise ValueError(f"ATLAS_RECOVERY_DUPLICATE_SHARD:{index}")
        result[index] = receipt_path
    return result


def _expected_receipt(plan: Any, receipt: dict[str, object], shard: Any) -> None:
    expected = {
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "shard_index": shard.shard_index,
        "start_ordinal": shard.start_ordinal,
        "stop_ordinal": shard.stop_ordinal,
        "expected_recipe_count": shard.expected_recipe_count,
        "actual_recipe_count": shard.expected_recipe_count,
        "validation_opened": False,
        "locked_opened": False,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"ATLAS_RECOVERY_RECEIPT_MISMATCH:{shard.shard_index}:{key}")


def recover_reference_chunk(
    *,
    plan_path: Path,
    partitions_root: Path,
    output_dir: Path,
    chunk_index: int,
    chunk_start: int,
    chunk_stop: int,
    source_run_id: str,
    workers: int = 4,
) -> dict[str, object]:
    if not source_run_id or not source_run_id.isdigit():
        raise ValueError("ATLAS_RECOVERY_SOURCE_RUN_ID_INVALID")
    plan = load_plan(Path(plan_path))
    if chunk_start < 0 or chunk_stop <= chunk_start or chunk_stop > plan.total_shards:
        raise ValueError("ATLAS_RECOVERY_CHUNK_RANGE_INVALID")
    shards = list(plan.shards[chunk_start:chunk_stop])
    receipts = _receipt_by_index(Path(partitions_root))
    if set(receipts) != {shard.shard_index for shard in shards}:
        missing = sorted({shard.shard_index for shard in shards} - set(receipts))
        extra = sorted(set(receipts) - {shard.shard_index for shard in shards})
        raise ValueError(f"ATLAS_RECOVERY_CHUNK_COVERAGE_INVALID:missing={missing}:extra={extra}")

    source_shards: list[dict[str, object]] = []
    futures = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        for shard in shards:
            receipt_path = receipts[shard.shard_index]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            _expected_receipt(plan, receipt, shard)
            result_path = _find_result_path(receipt_path)
            futures[shard.shard_index] = executor.submit(
                _read_recovery_shard_payload,
                shard.shard_index,
                result_path,
                shard.expected_recipe_count,
                receipt_result_sha256=receipt.get("result_sha256"),
            )
            source_shards.append(
                {
                    "artifact_name": receipt_path.parent.name,
                    "result_path": "results.jsonl",
                    "result_sha256": receipt.get("result_sha256"),
                    "shard_index": shard.shard_index,
                    "start_ordinal": shard.start_ordinal,
                    "stop_ordinal": shard.stop_ordinal,
                    "expected_recipe_count": shard.expected_recipe_count,
                }
            )

        seen: set[int] = set()
        cells: set[tuple[int, int, int]] = set()
        verified_recipe_count = 0
        for shard in shards:
            payload_shard_index, _raw_bytes, projected_rows = futures[shard.shard_index].result()
            if payload_shard_index != shard.shard_index:
                raise ValueError(f"ATLAS_RECOVERY_CHUNK_ORDER_INVALID:{shard.shard_index}")
            for row in projected_rows:
                ordinal = _verify_row(
                    row,
                    plan_sha256=plan.plan_sha256,
                    shard_index=shard.shard_index,
                    verify_result_hash=False,
                )
                if ordinal < shard.start_ordinal or ordinal >= shard.stop_ordinal:
                    raise ValueError(f"ATLAS_RECOVERY_ORDINAL_OUT_OF_SHARD:{ordinal}")
                if ordinal in seen:
                    raise ValueError(f"ATLAS_RECOVERY_DUPLICATE_ORDINAL:{ordinal}")
                seen.add(ordinal)
                cells.add(_cell(row))
                verified_recipe_count += 1
            if len(projected_rows) != shard.expected_recipe_count:
                raise ValueError(f"ATLAS_RECOVERY_PROJECTED_COUNT_INVALID:{shard.shard_index}")

    expected_ordinals = set(range(shards[0].start_ordinal, shards[-1].stop_ordinal))
    if seen != expected_ordinals:
        raise ValueError(f"ATLAS_RECOVERY_CHUNK_ORDINAL_COVERAGE_INVALID:{chunk_index}")

    source_shards.sort(key=lambda item: int(item["shard_index"]))
    manifest: dict[str, object] = {
        "schema_version": 1,
        "chunk_index": chunk_index,
        "chunk_start": chunk_start,
        "chunk_stop": chunk_stop,
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "source_run_id": source_run_id,
        "source_artifact_pattern": "sp500-atlas-shard-*",
        "verified_recipe_count": verified_recipe_count,
        "verified_shard_count": len(shards),
        "metric_cells": [list(cell) for cell in sorted(cells, reverse=True)],
        "source_shards": source_shards,
        "validation_opened": False,
        "locked_opened": False,
    }
    manifest["chunk_manifest_sha256"] = canonical_sha256(manifest)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "chunk_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--partitions-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chunk-index", type=int, required=True)
    parser.add_argument("--chunk-start", type=int, required=True)
    parser.add_argument("--chunk-stop", type=int, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--workers", type=int, default=int(os.environ.get("ATLAS_RECOVERY_CHUNK_WORKERS", "4")))
    args = parser.parse_args()
    result = recover_reference_chunk(
        plan_path=args.plan,
        partitions_root=args.partitions_root,
        output_dir=args.output_dir,
        chunk_index=args.chunk_index,
        chunk_start=args.chunk_start,
        chunk_stop=args.chunk_stop,
        source_run_id=args.source_run_id,
        workers=args.workers,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
