"""Focused admission guards for cached Atlas PREPARED calibration."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.verify_catalog_prepared_bundle import _atlas_identity_hashes_match, _atlas_verify_fresh_window


NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)


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
