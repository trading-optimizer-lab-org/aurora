from __future__ import annotations

import pytest

from aurora.infra.sp500_megarun.atlas_execution_contract import (
    AtlasRunPlanV1,
    build_run_plan,
)
from aurora.infra.sp500_megarun.atlas_segments import (
    build_segment_manifest,
    load_segment_manifest,
)


def _plan() -> AtlasRunPlanV1:
    catalog = {
        "catalog_id": "atlas",
        "manifest_sha256": "a" * 64,
        "artifacts_sha256": {"recipe_space.json": "b" * 64},
        "counts": {"canonical_recipe_count": 20},
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
        "target_recipe_count_with_margin": 20,
        "validation_opened": False,
        "locked_opened": False,
    }
    selection = {
        "schema_version": "1",
        "selection_domain": "AURORA-SP500-ATLAS-CAMPAIGN-SELECTION-V1",
        "seed": 7,
        "requested_recipe_count": 20,
        "canonical_recipe_count": 20,
        "ranges": [
            {
                "range_id": "r0",
                "raw_start": 0,
                "raw_stop": 20,
                "campaign_start": 0,
                "campaign_stop": 20,
                "quota": 20,
                "offset": 0,
                "step": 1,
            }
        ],
    }
    from aurora.infra.github_performance.contracts import canonical_sha256

    selection["selection_sha256"] = canonical_sha256(
        {key: value for key, value in selection.items() if key != "selection_sha256"}
    )
    return build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=calibration,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="d" * 40,
        total_shards=4,
        selection=selection,
    )


def test_segment_manifest_covers_each_shard_once_and_is_hash_bound() -> None:
    first = build_segment_manifest(_plan(), max_shards_per_segment=2)
    second = build_segment_manifest(_plan(), max_shards_per_segment=2)

    assert first == second
    assert [item["shard_indices"] for item in first["segments"]] == [[0, 1], [2, 3]]
    assert sorted(
        index
        for item in first["segments"]
        for index in item["shard_indices"]
    ) == list(range(4))
    assert load_segment_manifest(first)["manifest_sha256"] == first["manifest_sha256"]


def test_segment_manifest_rejects_duplicate_or_missing_shards() -> None:
    manifest = build_segment_manifest(_plan(), max_shards_per_segment=2)
    manifest["segments"][1]["shard_indices"] = [1, 3]

    with pytest.raises(ValueError, match="ATLAS_SEGMENT_COVERAGE_INVALID"):
        load_segment_manifest(manifest)


def test_segment_manifest_rejects_wrong_plan_hash() -> None:
    plan = _plan()
    manifest = build_segment_manifest(plan, max_shards_per_segment=2)
    manifest["plan_sha256"] = "e" * 64

    with pytest.raises(ValueError, match="ATLAS_SEGMENT_PLAN_HASH_INVALID"):
        load_segment_manifest(manifest, plan=plan)
