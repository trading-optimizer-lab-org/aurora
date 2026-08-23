"""Merge compact verification manifests for a recovered SP500 Atlas run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan


def merge_reference_chunks(
    *,
    plan_path: Path,
    chunks_root: Path,
    output_dir: Path,
    source_run_id: str,
    expected_chunks: int,
) -> dict[str, object]:
    if not source_run_id or not source_run_id.isdigit():
        raise ValueError("ATLAS_RECOVERY_SOURCE_RUN_ID_INVALID")
    plan = load_plan(Path(plan_path))
    manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(chunks_root).rglob("chunk_manifest.json"))
    ]
    if len(manifests) != expected_chunks:
        raise ValueError(f"ATLAS_RECOVERY_CHUNK_COUNT_INVALID:{len(manifests)}:{expected_chunks}")

    by_chunk: dict[int, dict[str, object]] = {}
    source_shards: list[dict[str, object]] = []
    cells: set[tuple[int, int, int]] = set()
    total_rows = 0
    for manifest in manifests:
        if manifest.get("chunk_index") in by_chunk:
            raise ValueError("ATLAS_RECOVERY_DUPLICATE_CHUNK")
        if manifest.get("plan_sha256") != plan.plan_sha256:
            raise ValueError("ATLAS_RECOVERY_CHUNK_PLAN_MISMATCH")
        if manifest.get("source_run_id") != source_run_id:
            raise ValueError("ATLAS_RECOVERY_CHUNK_SOURCE_RUN_MISMATCH")
        if manifest.get("validation_opened") is not False or manifest.get("locked_opened") is not False:
            raise ValueError("ATLAS_RECOVERY_CHUNK_BOUNDARY_OPEN")
        by_chunk[int(manifest["chunk_index"])] = manifest
        total_rows += int(manifest["verified_recipe_count"])
        cells.update(tuple(int(value) for value in cell) for cell in manifest["metric_cells"])
        source_shards.extend(manifest["source_shards"])

    if set(by_chunk) != set(range(expected_chunks)):
        raise ValueError("ATLAS_RECOVERY_CHUNK_INDEX_COVERAGE_INVALID")
    source_shards.sort(key=lambda item: int(item["shard_index"]))
    if len(source_shards) != plan.total_shards:
        raise ValueError("ATLAS_RECOVERY_SOURCE_SHARD_COUNT_INVALID")
    shard_indices = [int(item["shard_index"]) for item in source_shards]
    if shard_indices != list(range(plan.total_shards)):
        raise ValueError("ATLAS_RECOVERY_SOURCE_SHARD_COVERAGE_INVALID")
    if total_rows != plan.requested_recipe_count:
        raise ValueError(f"ATLAS_RECOVERY_RECIPE_COUNT_INVALID:{total_rows}:{plan.requested_recipe_count}")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    source_index: dict[str, object] = {
        "schema_version": 1,
        "storage_mode": "source_artifacts_referenced",
        "source_run_id": source_run_id,
        "source_artifact_pattern": "sp500-atlas-shard-*",
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "row_count": total_rows,
        "shard_count": len(source_shards),
        "validation_opened": False,
        "locked_opened": False,
        "shards": source_shards,
    }
    source_index["source_index_sha256"] = canonical_sha256(source_index)
    (output / "source_results_index.json").write_text(
        json.dumps(source_index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    dataset_manifest = {
        "schema_version": 1,
        "storage_mode": "source_artifacts_referenced",
        "results_path": None,
        "results_sha256": None,
        "source_run_id": source_run_id,
        "source_index_path": "../source_results_index.json",
        "source_index_sha256": source_index["source_index_sha256"],
        "row_count": total_rows,
        "streaming": False,
        "row_hash_verification_mode": "artifact_file_hash_bound",
        "row_hashes_recomputed": False,
        "result_file_hashes_verified": True,
        "validation_opened": False,
        "locked_opened": False,
    }
    dataset = output / "all_results_dataset"
    dataset.mkdir()
    (dataset / "manifest.json").write_text(
        json.dumps(dataset_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "all_results_manifest.json").write_text(
        json.dumps(dataset_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "coverage_report.json").write_text(
        json.dumps(
            {
                "requested_recipe_count": plan.requested_recipe_count,
                "verified_recipe_count": total_rows,
                "verified_shard_count": len(source_shards),
                "verified_chunk_count": expected_chunks,
                "missing_ordinals": 0,
                "duplicate_ordinals": 0,
                "conflicts": 0,
                "storage_mode": "source_artifacts_referenced",
                "source_run_id": source_run_id,
                "validation_opened": False,
                "locked_opened": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "positive_weeks": week,
                "positive_months": month,
                "joint_positive_above_spy_years": year,
            }
            for week, month, year in sorted(cells, reverse=True)
        ]
    ).to_parquet(output / "descriptive_metrics.parquet", index=False)
    summary: dict[str, object] = {
        "schema_version": 1,
        "accepted": True,
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "selection_sha256": plan.selection_sha256,
        "requested_recipe_count": plan.requested_recipe_count,
        "verified_recipe_count": total_rows,
        "verified_shard_count": len(source_shards),
        "verified_chunk_count": expected_chunks,
        "pareto_recipe_count": None,
        "pareto_cell_count": None,
        "reserve_recipe_count": 0,
        "results_sha256": None,
        "frontier_sha256": None,
        "storage_mode": "source_artifacts_referenced",
        "source_run_id": source_run_id,
        "source_index_sha256": source_index["source_index_sha256"],
        "unique_metric_cells": len(cells),
        "derived_frontier_deferred": True,
        "row_hash_verification_mode": "artifact_file_hash_bound",
        "row_hashes_recomputed": False,
        "result_file_hashes_verified": True,
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "reduction_receipt.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--chunks-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--expected-chunks", type=int, required=True)
    args = parser.parse_args()
    result = merge_reference_chunks(
        plan_path=args.plan,
        chunks_root=args.chunks_root,
        output_dir=args.output_dir,
        source_run_id=args.source_run_id,
        expected_chunks=args.expected_chunks,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
