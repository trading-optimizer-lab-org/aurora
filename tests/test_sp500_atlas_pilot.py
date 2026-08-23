from __future__ import annotations

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import build_run_plan
from aurora.infra.sp500_megarun.atlas_pilot import (
    build_pilot_manifest,
    load_pilot_manifest,
)


def _plan():
    catalog = {
        "catalog_id": "atlas",
        "manifest_sha256": "a" * 64,
        "artifacts_sha256": {"recipe_space.json": "b" * 64},
        "counts": {"canonical_recipe_count": 40},
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
        "target_recipe_count_with_margin": 40,
        "validation_opened": False,
        "locked_opened": False,
    }
    selection = {
        "schema_version": "1",
        "selection_domain": "AURORA-SP500-ATLAS-CAMPAIGN-SELECTION-V1",
        "seed": 7,
        "requested_recipe_count": 40,
        "canonical_recipe_count": 40,
        "ranges": [{"range_id": "r0", "raw_start": 0, "raw_stop": 40, "campaign_start": 0, "campaign_stop": 40, "quota": 40, "offset": 0, "step": 1}],
    }
    selection["selection_sha256"] = canonical_sha256(
        {key: value for key, value in selection.items() if key != "selection_sha256"}
    )
    return build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=calibration,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="d" * 40,
        total_shards=8,
        selection=selection,
    )


def test_pilot_manifest_is_deterministic_and_spread_across_plan() -> None:
    first = build_pilot_manifest(_plan(), shard_count=4, seed=20260818)
    second = build_pilot_manifest(_plan(), shard_count=4, seed=20260818)

    assert first == second
    assert first["shard_indices"] == [0, 2, 5, 7]
    assert first["validation_opened"] is False
    assert load_pilot_manifest(first)["manifest_sha256"] == first["manifest_sha256"]


def test_pilot_manifest_rejects_too_many_shards() -> None:
    with pytest.raises(ValueError, match="ATLAS_PILOT_COUNT_INVALID"):
        build_pilot_manifest(_plan(), shard_count=9, seed=1)
