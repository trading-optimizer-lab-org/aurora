from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from infra.gtbi_v7_readiness.scientific_assets import (
    SCIENTIFIC_ASSET_FIELDS,
    ScientificAssetManifestError,
    compute_asset_manifest_digest,
    lifecycle_state,
    scientific_asset_manifest_schema,
    seal_asset_manifest,
    validate_scientific_asset_manifest,
)
from scripts.generate_gtbi_v7_scientific_asset_contract import (
    FIXTURE_PATH,
    SCHEMA_PATH,
    wrapper_only_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
MASTER_PLAN = ROOT / "docs/plans/gtbi-v7-master-plan.md"


def test_schema_has_exact_required_plan_fields() -> None:
    schema = scientific_asset_manifest_schema()
    assert set(schema["properties"]) == set(SCIENTIFIC_ASSET_FIELDS)
    assert set(schema["required"]) == set(SCIENTIFIC_ASSET_FIELDS)
    assert schema["additionalProperties"] is False
    assert schema["x-gtbi-hash-domain-id"] == (
        "GTBI_SCIENTIFIC_ASSET_MANIFEST_V1"
    )


def test_schema_field_order_matches_master_plan_normative_block() -> None:
    text = MASTER_PLAN.read_text(encoding="utf-8")
    marker = "Every stored `scientific_asset_manifest_v1` must include:"
    block = text.split(marker, 1)[1].split("```text", 1)[1].split("```", 1)[0]
    plan_fields = tuple(line.strip() for line in block.splitlines() if line.strip())
    assert plan_fields == SCIENTIFIC_ASSET_FIELDS


def test_generated_schema_and_fixture_are_deterministic() -> None:
    checked_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    checked_fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert checked_schema == scientific_asset_manifest_schema()
    assert checked_fixture == wrapper_only_fixture()
    jsonschema.Draft202012Validator.check_schema(checked_schema)
    validate_scientific_asset_manifest(checked_fixture)
    assert lifecycle_state(checked_fixture) == "wrapper_only"


def test_digest_omits_only_self_field() -> None:
    fixture = wrapper_only_fixture()
    original_digest = fixture["asset_manifest_digest"]
    fixture["asset_manifest_digest"] = "sha256:" + ("f" * 64)
    assert compute_asset_manifest_digest(fixture) == original_digest
    fixture["provider"] = "different"
    assert compute_asset_manifest_digest(fixture) != original_digest


def test_locked_and_validation_boundaries_are_fixed() -> None:
    fixture = wrapper_only_fixture()
    fixture["last_date"] = "2021-01-04"
    with pytest.raises(ScientificAssetManifestError, match="after validation"):
        validate_scientific_asset_manifest(
            seal_asset_manifest_without_validation(fixture)
        )


def test_incomplete_classification_cannot_claim_reproduction() -> None:
    fixture = wrapper_only_fixture()
    fixture["v6_historical_reproduction_confirmed"] = True
    fixture["asset_type"] = "other_asset"
    with pytest.raises(
        ScientificAssetManifestError,
        match="incomplete-input classification",
    ):
        validate_scientific_asset_manifest(
            seal_asset_manifest_without_validation(fixture)
        )


def test_archival_wrapper_cannot_claim_engine_equivalence() -> None:
    fixture = wrapper_only_fixture()
    fixture["optimized_vs_reference_equivalence_confirmed"] = True
    fixture["reproducibility_classification"] = "historical_reference_only"
    with pytest.raises(
        ScientificAssetManifestError,
        match="archival preservation",
    ):
        validate_scientific_asset_manifest(
            seal_asset_manifest_without_validation(fixture)
        )


def test_custody_parts_require_contiguous_indices_and_bound_ids() -> None:
    fixture = wrapper_only_fixture()
    fixture["primary_release_repository_id"] = 10
    fixture["primary_release_id"] = 20
    fixture["primary_release_asset_count"] = 1
    fixture["primary_release_parts"] = [
        {
            "part_index": 1,
            "repository_id": 10,
            "release_id": 20,
            "asset_id": 30,
            "asset_name": "part-0000.bin",
            "size_bytes": 10,
            "sha256": "sha256:" + ("1" * 64),
        }
    ]
    with pytest.raises(ScientificAssetManifestError, match="contiguous"):
        validate_scientific_asset_manifest(
            seal_asset_manifest_without_validation(fixture)
        )


def test_static_universe_cannot_claim_point_in_time() -> None:
    fixture = wrapper_only_fixture()
    fixture["universe_point_in_time_claim_allowed"] = True
    with pytest.raises(ScientificAssetManifestError, match="causal claim"):
        validate_scientific_asset_manifest(
            seal_asset_manifest_without_validation(fixture)
        )


def seal_asset_manifest_without_validation(manifest: dict) -> dict:
    """Seal a deliberately invalid fixture so the target invariant is tested."""

    result = deepcopy(manifest)
    result["asset_manifest_digest"] = compute_asset_manifest_digest(result)
    return result
