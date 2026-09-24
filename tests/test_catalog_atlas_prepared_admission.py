"""Focused admission guards for cached Atlas PREPARED calibration."""

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.verify_catalog_prepared_bundle import _atlas_identity_hashes_match, _atlas_verify_fresh_window


NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)


def test_atlas_sealed_envelope_reuses_same_gate_verified_bundle(tmp_path, monkeypatch) -> None:
    from scripts import admit_catalog_fast_request as admission

    bundle = tmp_path / "bundle"
    for relative in (
        "atlas_prepared_receipt.json", "plan/atlas_run_plan.json",
        "plan/atlas_campaign_selection.json", "atlas/manifest.json",
    ):
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    repo = tmp_path / "repo"
    definition = repo / "config/definition.json"
    definition.parent.mkdir(parents=True)
    definition.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(admission, "verify_atlas_prepared_bundle",
        lambda **kwargs: pytest.fail("the same gate must not verify its bundle twice"))
    monkeypatch.setattr(admission, "catalog_campaign_id", lambda **kwargs: "campaign")
    monkeypatch.setattr(admission, "catalog_authority_id", lambda **kwargs: "authority")
    monkeypatch.setattr(admission, "execution_protocol_sha256", lambda **kwargs: "0" * 64)
    receipt = SimpleNamespace(receipt_sha256="c" * 64, plan_sha256="d" * 64,
        selection_sha256="e" * 64, target_end_iso="2099-01-01T00:00:00Z")
    identity = SimpleNamespace(scientific_contract_sha256="a" * 64,
        protected_commit_sha="b" * 40, runtime_input_run_id=31418682679)
    entry = SimpleNamespace(definition_manifest_path="config/definition.json",
        campaign_key="sp500-atlas-v1", scientific_contract_sha256="a" * 64)
    envelope = admission._materialize_atlas_prepared_plan(
        bundle_dir=bundle, expected_identity=identity,
        prepared_receipt=receipt, verified_manifest={"catalog_manifest_sha256": "f" * 64},
        registry_entry=entry, request_sha256="1" * 64, decision_sha256="2" * 64,
        repo_root=repo, output_dir=tmp_path / "sealed-plan",
    )
    assert envelope["prepared_receipt_sha256"] == receipt.receipt_sha256
    assert envelope["catalog_manifest_sha256"] == "f" * 64
    assert json.loads((tmp_path / "sealed-plan/atlas_sealed_envelope.json").read_text())["envelope_sha256"] == envelope["envelope_sha256"]


def test_atlas_prepared_identity_binds_raw_and_semantic_data_contract_hashes() -> None:
    from aurora.infra.sp500_megarun.catalog_atlas_cloud_identity import build_atlas_preparation_identity
    from aurora.infra.sp500_megarun.catalog_campaign_registry import (
        load_catalog_campaign_registry, resolve_catalog_campaign,
    )
    from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract

    root = Path(__file__).resolve().parents[1]
    registry = load_catalog_campaign_registry(root / "config/catalog_campaign_registry_v1.json")
    entry = resolve_catalog_campaign(registry, "sp500-atlas-v1", root)
    identity = build_atlas_preparation_identity(root, entry, "a" * 40)
    semantic = load_and_validate_contract(root / entry.data_contract_path).sha256
    verified = {
        key: getattr(identity, key) for key in (
            "scientific_contract_sha256", "freeze_manifest_sha256",
            "feature_contract_sha256", "selection_sha256",
        )
    }
    verified["data_contract_sha256"] = semantic
    assert _atlas_identity_hashes_match(
        source_root=root, expected_identity=identity, verified=verified,
    )
    assert not _atlas_identity_hashes_match(
        source_root=root, expected_identity=identity,
        verified={**verified, "data_contract_sha256": "f" * 64},
    )
    assert not _atlas_identity_hashes_match(
        source_root=root,
        expected_identity=identity.model_copy(update={"data_contract_sha256": "f" * 64}),
        verified=verified,
    )


def test_cached_atlas_target_must_still_be_future() -> None:
    with pytest.raises(ValueError, match="CATALOG_ATLAS_PREPARED_TARGET_EXPIRED"):
        _atlas_verify_fresh_window(
            calibration={"recipes_per_minute": 10_000.0, "safety_fraction": 0.8},
            target_end_iso="2098-12-31T23:59:59Z",
            requested_recipe_count=209906,
            now=NOW,
        )


def test_cached_atlas_calibration_must_cover_full_request_from_now() -> None:
    with pytest.raises(ValueError, match="CATALOG_ATLAS_PREPARED_WINDOW_INSUFFICIENT"):
        _atlas_verify_fresh_window(
            calibration={"recipes_per_minute": 1.0, "safety_fraction": 0.8},
            target_end_iso="2099-01-01T01:00:00Z",
            requested_recipe_count=209906,
            now=NOW,
        )
