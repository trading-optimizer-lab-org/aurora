from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import build_run_plan
from aurora.infra.sp500_megarun.atlas_segments import build_segment_manifest
from scripts.verify_sp500_atlas_segment import verify_segment


def _plan():
    catalog = {
        "catalog_id": "atlas",
        "manifest_sha256": "a" * 64,
        "artifacts_sha256": {"recipe_space.json": "b" * 64},
        "counts": {"canonical_recipe_count": 4},
        "validation_opened": False,
        "locked_opened": False,
        "execution_authorized": False,
    }
    calibration = {
        "hard_limit_seconds": 1200.0,
        "catalog_sha256": "a" * 64,
        "receipt_sha256": "c" * 64,
        "available_minutes_to_target": 100.0,
        "safety_fraction": 0.8,
        "recipes_per_minute": 10.0,
        "recommended_mode": "cold",
        "target_recipe_count_with_margin": 4,
        "validation_opened": False,
        "locked_opened": False,
    }
    selection = {
        "schema_version": "1",
        "selection_domain": "AURORA-SP500-ATLAS-CAMPAIGN-SELECTION-V1",
        "seed": 7,
        "requested_recipe_count": 4,
        "canonical_recipe_count": 4,
        "ranges": [{"range_id": "r0", "raw_start": 0, "raw_stop": 4, "campaign_start": 0, "campaign_stop": 4, "quota": 4, "offset": 0, "step": 1}],
    }
    selection["selection_sha256"] = canonical_sha256(
        {key: value for key, value in selection.items() if key != "selection_sha256"}
    )
    return build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=calibration,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="d" * 40,
        total_shards=2,
        selection=selection,
    )


def _write_shard(root: Path, plan, shard_index: int) -> None:
    shard = plan.shard(shard_index)
    rows = []
    for ordinal in range(shard.start_ordinal, shard.stop_ordinal):
        row = {
            "ordinal": ordinal,
            "plan_sha256": plan.plan_sha256,
            "shard_index": shard_index,
            "validation_opened": False,
            "locked_opened": False,
        }
        row["result_sha256"] = canonical_sha256(row)
        rows.append(row)
    directory = root / f"shard-{shard_index}"
    directory.mkdir()
    results = directory / "results.jsonl"
    results.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    receipt = {
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "shard_index": shard_index,
        "start_ordinal": shard.start_ordinal,
        "stop_ordinal": shard.stop_ordinal,
        "expected_recipe_count": shard.expected_recipe_count,
        "actual_recipe_count": len(rows),
        "result_sha256": hashlib.sha256(results.read_bytes()).hexdigest(),
        "validation_opened": False,
        "locked_opened": False,
        "elapsed_seconds": 1.0,
    }
    (directory / "worker_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


def test_verify_segment_accepts_complete_train_only_segment(tmp_path: Path) -> None:
    plan = _plan()
    manifest = build_segment_manifest(plan, max_shards_per_segment=1)
    manifest_path = tmp_path / "segments.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    partitions = tmp_path / "partitions"
    partitions.mkdir()
    _write_shard(partitions, plan, 0)
    output = tmp_path / "output"

    receipt = verify_segment(
        plan_path=tmp_path / "plan.json",
        segment_manifest_path=manifest_path,
        segment_index=0,
        partitions_root=partitions,
        output_dir=output,
        plan_object=plan,
    )

    assert receipt["actual_recipe_count"] == 2
    assert receipt["validation_opened"] is False
    assert (output / "segment_receipt.json").is_file()
