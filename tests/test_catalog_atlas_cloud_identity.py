"""Offline tests for the fail-closed Atlas cloud identity verifier."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun import catalog_atlas_cloud_identity as identity
from aurora.infra.sp500_megarun import catalog_campaign_definition_builder
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    CatalogCampaignDefinitionEntryV1,
    CatalogCampaignDefinitionManifestV1,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogAtlasCampaignEntryV1,
)


def _write_json(path, payload):
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    encoded = raw.encode("utf-8")
    path.write_bytes(encoded)
    return encoded


@pytest.fixture
def valid_inputs(tmp_path, monkeypatch):
    root = tmp_path / "catalog"
    root.mkdir()
    space_identity = {
        "schema_version": 1,
        "space_version": "1",
        "catalog_id": "sp500-atlas-1",
        "train_end": "2010-12-31",
        "ranges": [
            {
                "range_id": "range-a",
                "start_ordinal": 0,
                "stop_ordinal": 20,
            },
            {
                "range_id": "range-b",
                "start_ordinal": 20,
                "stop_ordinal": 40,
            },
        ],
        "canonical_recipe_count": 40,
        "validation_opened": False,
        "locked_opened": False,
    }
    selection = identity.build_campaign_selection(
        space_identity, requested_recipe_count=10, seed=17
    )
    space = space_identity | {"space_sha256": canonical_sha256(space_identity)}
    space_bytes = _write_json(root / "recipe_space.json", space)
    space_file_sha256 = hashlib.sha256(space_bytes).hexdigest()

    manifest_identity = {
        "schema_version": 1,
        "catalog_id": "sp500-atlas-1",
        "catalog_format": "atlas_compact_ordinal_ranges_v1",
        "search_end": "2010-12-31",
        "data_contract_sha256": "c923005def76f5ac8f908bc3e29b31a84dd1848fa70879ae506378123292f057",
        "feature_contract_sha256": "58dd6dba2857223c2040ef383b7ec0513b957675f4ba104ffc408ab5f47ad62c",
        "validation_opened": False,
        "locked_opened": False,
        "execution_authorized": False,
        "counts": {"canonical_recipe_count": 40},
        "artifacts_sha256": {
            "recipe_space.json": hashlib.sha256(space_bytes).hexdigest()
        },
    }
    manifest = manifest_identity | {
        "manifest_sha256": canonical_sha256(manifest_identity)
    }
    _write_json(root / "manifest.json", manifest)

    freeze = {
        "catalog_id": "sp500-atlas-1",
        "catalog_manifest_sha256": manifest["manifest_sha256"],
        "catalog_space_sha256": space_file_sha256,
        "catalog_counts": {"canonical_recipe_count": 40},
        "train_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "requested_recipe_count": 10,
        "total_shards": 3,
        "selection_seed": 17,
        "selection_sha256": selection["selection_sha256"],
        "target_end_iso": "2000-01-01T00:00:00+00:00",
        "scientific_implementation_commit_sha": "0" * 40,
        "runtime_input_run_id": "31418682679",
    }
    freeze_path = tmp_path / "freeze.json"
    _write_json(freeze_path, freeze)
    monkeypatch.setattr(identity, "FREEZE_MANIFEST_PATH", freeze_path)
    monkeypatch.setattr(identity, "_EXPECTED_FREEZE", {
        "catalog_id": "sp500-atlas-1",
        "catalog_manifest_sha256": manifest["manifest_sha256"],
        "catalog_space_sha256": space_file_sha256,
        "requested_recipe_count": 10,
        "total_shards": 3,
        "selection_seed": 17,
        "selection_sha256": selection["selection_sha256"],
        "train_end": "2010-12-31",
        "scientific_implementation_commit_sha": "0" * 40,
    })
    calibration = {
        "schema_version": "1",
        "catalog_sha256": manifest["manifest_sha256"],
        "started_at_iso": "2029-12-31T23:35:00+00:00",
        "stopped_at_iso": "2029-12-31T23:55:00+00:00",
        "wall_seconds": 1200.0,
        "hard_limit_seconds": 1200.0,
        "timed_out_cleanly": True,
        "recommended_mode": "cold",
        "available_minutes_to_target": 60.0,
        "recipes_per_minute": 6000.0,
        "safety_fraction": 0.8,
        "target_recipe_count_with_margin": 288000,
        "validation_opened": False,
        "locked_opened": False,
    }
    return root, calibration, datetime(2029, 12, 31, 23, 59, tzinfo=timezone.utc)


def test_returns_deterministic_prepared_identity(valid_inputs):
    root, calibration, now = valid_inputs

    planned_target = "2030-01-01T00:55:00+00:00"
    first = identity.verify_atlas_cloud_identity(
        root, calibration, planned_target_end_iso=planned_target, now=now
    )
    second = identity.verify_atlas_cloud_identity(
        root, calibration, planned_target_end_iso=planned_target, now=now
    )

    assert first == second
    assert first["kind"] == "atlas_cloud_prepared_identity"
    assert first["requested_recipe_count"] == 10
    assert first["total_shards"] == 3
    assert first["validation_opened"] is False
    assert first["locked_opened"] is False
    assert first["execution_authorized"] is False
    assert len(first["scientific_contract_sha256"]) == 64
    assert "calibration_receipt_sha256" in first
    assert "planned_target_end_iso" in first


def test_scientific_contract_is_stable_across_calibration_changes(valid_inputs):
    root, calibration, now = valid_inputs
    planned_target = "2030-01-01T00:55:00+00:00"
    first = identity.verify_atlas_cloud_identity(
        root, calibration, planned_target_end_iso=planned_target, now=now
    )
    refreshed_calibration = {
        **calibration,
        "started_at_iso": "2029-12-31T23:30:00+00:00",
        "stopped_at_iso": "2029-12-31T23:50:00+00:00",
        "available_minutes_to_target": 65.0,
        "target_recipe_count_with_margin": 312000,
    }

    second = identity.verify_atlas_cloud_identity(
        root, refreshed_calibration, planned_target_end_iso=planned_target, now=now
    )

    assert first["scientific_contract_sha256"] == second["scientific_contract_sha256"]
    assert first["calibration_receipt_sha256"] != second["calibration_receipt_sha256"]
    assert first["prepared_identity_sha256"] != second["prepared_identity_sha256"]


def test_static_identity_and_prepared_receipt_self_verify(valid_inputs):
    root, calibration, now = valid_inputs
    verified = identity.verify_atlas_cloud_identity(
        root,
        calibration,
        planned_target_end_iso="2030-01-01T00:55:00+00:00",
        now=now,
    )
    static = identity.AtlasPreparationIdentityV1(
        campaign_key="sp500-atlas-v1",
        engine_id="atlas_static_v1",
        protected_commit_sha="c" * 40,
        campaign_definition_sha256="1" * 64,
        scientific_contract_sha256=verified["scientific_contract_sha256"],
        dependency_lock_sha256="2" * 64,
        freeze_manifest_sha256=verified["freeze_manifest_sha256"],
        data_contract_sha256="3" * 64,
        feature_contract_sha256="4" * 64,
        runtime_input_run_id=12345,
        selection_sha256=verified["selection_sha256"],
    )
    receipt = identity.create_atlas_prepared_receipt(
        verified,
        identity=static,
        qualified_worker_ceiling=20,
        plan_sha256="5" * 64,
        generated_at=now,
    )

    assert static.preparation_key_sha256 == identity.canonical_sha256(
        static.model_dump(mode="json")
    )
    assert receipt.identity == static
    assert receipt.status == "PREPARED"
    assert receipt.qualified_worker_ceiling == 20
    assert receipt.plan_sha256 == "5" * 64
    assert receipt.receipt_sha256 == identity.canonical_sha256(
        receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    )
    assert "calibration_receipt_sha256" not in static.model_fields
    assert "target_end_iso" not in static.model_fields


def test_prepared_receipt_requires_explicit_qualified_worker_ceiling():
    with pytest.raises(TypeError):
        identity.AtlasPreparedReceiptV1.create(
            identity=None,
            target_end_iso="2030-01-01T00:55:00+00:00",
            calibration_receipt_sha256="a" * 64,
            plan_sha256="b" * 64,
            generated_at=datetime.now(timezone.utc),
        )


def test_builds_static_identity_from_verified_protected_repository(
    valid_inputs, monkeypatch
):
    root, _, _ = valid_inputs
    repo = root.parent
    definition_rel = "config/catalog_campaign_definitions/sp500-atlas-v1.manifest.json"
    paths = {
        "definition": repo / definition_rel,
        "campaign": repo / "config/sp500_atlas_1/campaign_contract_v1.json",
        "data": repo / "config/sp500_atlas_1/data_contract_v1.json",
        "feature": repo / "config/sp500_atlas_1/feature_contract_v1.json",
        "lock": repo / "requirements/catalog-optimized.lock",
    }
    for key, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if key != "definition":
            content = b"catalog-lock\n" if key == "lock" else b'{"schema_version":"1"}'
            path.write_bytes(content)
    entry = CatalogAtlasCampaignEntryV1(
        campaign_key="sp500-atlas-v1",
        engine_id="atlas_static_v1",
        definition_manifest_path=definition_rel,
        campaign_contract_path="config/sp500_atlas_1/campaign_contract_v1.json",
        freeze_manifest_path="freeze.json",
        data_contract_path="config/sp500_atlas_1/data_contract_v1.json",
        feature_contract_path="config/sp500_atlas_1/feature_contract_v1.json",
        runtime_input_run_id=31418682679,
        scientific_contract_sha256="f" * 64,
        max_free_workers=360,
        allowed_protected_branch="main",
        source_artifact_contracts=("runtime_input_pack_v1",),
        active=True,
    )
    campaign_content = paths["campaign"].read_bytes()
    definition = CatalogCampaignDefinitionManifestV1(
        schema_version="1",
        closure_algorithm="aurora-catalog-transitive-closure-v1",
        campaign_key=entry.campaign_key,
        registry_entry_sha256="a" * 64,
        entries=(
            CatalogCampaignDefinitionEntryV1.from_bytes(
                path=entry.campaign_contract_path,
                role="contract",
                content=campaign_content,
            ),
        ),
    )
    paths["definition"].write_bytes(definition.canonical_bytes)

    def verify_definition(*, repo_root, registry_entry, manifest):
        assert repo_root == repo
        assert registry_entry.campaign_key == entry.campaign_key
        assert manifest == definition
        return manifest

    monkeypatch.setattr(
        catalog_campaign_definition_builder,
        "verify_catalog_campaign_definition",
        verify_definition,
    )

    prepared = identity.build_atlas_preparation_identity(
        repo, entry, "c" * 40
    )

    assert prepared.campaign_key == entry.campaign_key
    assert prepared.engine_id == "atlas_static_v1"
    assert prepared.protected_commit_sha == "c" * 40
    assert prepared.campaign_definition_sha256 == definition.campaign_definition_sha256
    assert prepared.scientific_contract_sha256 == entry.scientific_contract_sha256
    assert prepared.runtime_input_run_id == entry.runtime_input_run_id
    assert prepared.runtime_input_run_id == 31418682679
    assert prepared.selection_sha256 == identity._EXPECTED_FREEZE["selection_sha256"]
    assert prepared.dependency_lock_sha256 == hashlib.sha256(
        paths["lock"].read_bytes()
    ).hexdigest()
    assert "calibration_receipt_sha256" not in prepared.model_fields
    assert "planned_target_end_iso" not in prepared.model_fields

    mismatched_entry = entry.model_copy(update={"runtime_input_run_id": 31418682680})
    with pytest.raises(ValueError, match="PREPARATION_RUNTIME_INPUT_ID_MISMATCH"):
        identity.build_atlas_preparation_identity(repo, mismatched_entry, "c" * 40)


@pytest.mark.parametrize(
    ("contract_key", "error_code"),
    [
        ("data_contract_sha256", "CATALOG_DATA_CONTRACT_HASH_MISMATCH"),
        ("feature_contract_sha256", "CATALOG_FEATURE_CONTRACT_HASH_MISMATCH"),
    ],
)
def test_rejects_contract_hash_that_does_not_match_real_contract_file(
    valid_inputs, monkeypatch, contract_key, error_code
):
    root, calibration, now = valid_inputs
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[contract_key] = "0" * 64
    manifest_identity = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    manifest["manifest_sha256"] = canonical_sha256(manifest_identity)
    _write_json(manifest_path, manifest)

    expected = dict(identity._EXPECTED_FREEZE)
    expected["catalog_manifest_sha256"] = manifest["manifest_sha256"]
    monkeypatch.setattr(identity, "_EXPECTED_FREEZE", expected)
    freeze = json.loads(identity.FREEZE_MANIFEST_PATH.read_text(encoding="utf-8"))
    freeze["catalog_manifest_sha256"] = manifest["manifest_sha256"]
    _write_json(identity.FREEZE_MANIFEST_PATH, freeze)
    calibration["catalog_sha256"] = manifest["manifest_sha256"]

    with pytest.raises(ValueError, match=error_code):
        identity.verify_atlas_cloud_identity(
            root,
            calibration,
            planned_target_end_iso="2030-01-01T00:55:00+00:00",
            now=now,
        )


def test_rejects_mutated_recipe_space_hash(valid_inputs):
    root, calibration, now = valid_inputs
    path = root / "recipe_space.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"stop_ordinal":40', '"stop_ordinal":41'), encoding="utf-8")

    with pytest.raises(ValueError, match="RECIPE_SPACE_FILE_HASH_INVALID"):
        identity.verify_atlas_cloud_identity(
            root,
            calibration,
            planned_target_end_iso="2030-01-01T00:55:00+00:00",
            now=now,
        )


def test_rejects_insufficient_calibration_capacity(valid_inputs):
    root, calibration, now = valid_inputs
    calibration["recipes_per_minute"] = 0.1
    calibration["target_recipe_count_with_margin"] = 4

    with pytest.raises(ValueError, match="CALIBRATION_CAPACITY_INSUFFICIENT"):
        identity.verify_atlas_cloud_identity(
            root,
            calibration,
            planned_target_end_iso="2030-01-01T00:55:00+00:00",
            now=now,
        )


def test_rejects_expired_planned_target(valid_inputs):
    root, calibration, _ = valid_inputs
    now = datetime(2029, 12, 31, 23, 59, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="PLANNED_TARGET_EXPIRED"):
        identity.verify_atlas_cloud_identity(
            root,
            calibration,
            planned_target_end_iso="2029-12-31T23:58:00+00:00",
            now=now,
        )


def test_rejects_available_minutes_not_matching_planned_target(valid_inputs):
    root, calibration, now = valid_inputs
    calibration["available_minutes_to_target"] = 59.0

    with pytest.raises(ValueError, match="CALIBRATION_AVAILABLE_MINUTES_MISMATCH"):
        identity.verify_atlas_cloud_identity(
            root,
            calibration,
            planned_target_end_iso="2030-01-01T00:55:00+00:00",
            now=now,
        )


def test_rejects_changed_selection_hash(valid_inputs, monkeypatch):
    root, calibration, now = valid_inputs
    expected = dict(identity._EXPECTED_FREEZE)
    expected["selection_sha256"] = "0" * 64
    monkeypatch.setattr(identity, "_EXPECTED_FREEZE", expected)
    freeze = json.loads(identity.FREEZE_MANIFEST_PATH.read_text(encoding="utf-8"))
    freeze["selection_sha256"] = "0" * 64
    _write_json(identity.FREEZE_MANIFEST_PATH, freeze)

    with pytest.raises(ValueError, match="SELECTION_HASH_MISMATCH"):
        identity.verify_atlas_cloud_identity(
            root,
            calibration,
            planned_target_end_iso="2030-01-01T00:55:00+00:00",
            now=now,
        )


def test_real_generated_catalog_verifies_with_historical_calibration():
    catalog_dir = Path(
        "C:/Users/HP/AppData/Local/Temp/aurora-atlas-verify-209906-20260923"
    )
    freeze = identity._read_json(identity.FREEZE_MANIFEST_PATH, "FREEZE_UNREADABLE")
    identity._verify_freeze(freeze)
    manifest, space, selection = identity._verify_frozen_catalog(catalog_dir)
    old_receipt = identity._read_json(
        Path("config/sp500_atlas_1/calibration_receipt_32137133180.json"),
        "CALIBRATION_UNREADABLE",
    )

    assert manifest["manifest_sha256"] == freeze["catalog_manifest_sha256"]
    assert identity._file_sha256(catalog_dir / "recipe_space.json") == freeze[
        "catalog_space_sha256"
    ]
    assert space["space_sha256"] == "19c978ff358e61ec2f664de90fd01a2a37de149c624799b8491d3a2670c27eb0"
    assert space["space_sha256"] != freeze["catalog_space_sha256"]
    assert old_receipt["catalog_sha256"] == manifest["manifest_sha256"]
    assert selection["selection_sha256"] == freeze["selection_sha256"]
    result = identity.verify_atlas_cloud_identity(
        catalog_dir,
        old_receipt,
        planned_target_end_iso=freeze["target_end_iso"],
        now=datetime.fromisoformat("2026-08-19T00:00:00+02:00"),
    )
    assert len(result["scientific_contract_sha256"]) == 64
