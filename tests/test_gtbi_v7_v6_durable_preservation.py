from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.scientific_assets import (
    lifecycle_state,
    validate_scientific_asset_manifest,
)
from scripts.generate_gtbi_v7_v6_durable_preservation import (
    ARCHIVE_SHA256,
    ARCHIVE_SIZE,
    CLEANUP_PATH,
    DELETED_LEGACY_RUN_IDS,
    PRESERVATION_PATH,
    SCIENTIFIC_MANIFEST_PATH,
    SOURCE_BUNDLE_SHA256,
    SOURCE_BUNDLE_SIZE,
    ZOMBIE_RUN_ID,
    build_cleanup_receipt,
    build_preservation_receipt,
    build_scientific_manifest,
)


def test_durable_preservation_receipt_is_canonical_and_self_bound() -> None:
    receipt = build_preservation_receipt()
    checked = json.loads(PRESERVATION_PATH.read_text(encoding="utf-8"))
    assert checked == receipt
    assert PRESERVATION_PATH.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V6_DURABLE_PRESERVATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["source"]["archive_size_bytes"] == ARCHIVE_SIZE
    assert receipt["source"]["archive_sha256"] == ARCHIVE_SHA256
    assert receipt["primary"]["asset_sha256"] == ARCHIVE_SHA256
    assert receipt["mirror"]["asset_sha256"] == ARCHIVE_SHA256
    assert receipt["primary"]["verification_run_id"] == 30541859386
    assert receipt["mirror"]["verification_run_id"] == 30541861880
    source = receipt["source_closure"]
    assert source["source_commit_sha"] == receipt["source"]["commit_sha"]
    assert source["bundle_sha256"] == SOURCE_BUNDLE_SHA256
    assert source["bundle_size_bytes"] == SOURCE_BUNDLE_SIZE
    assert source["primary"]["bundle_asset_sha256"] == SOURCE_BUNDLE_SHA256
    assert source["mirror"]["bundle_asset_sha256"] == SOURCE_BUNDLE_SHA256
    assert source["primary"]["verification_run_id"] == 30544068594
    assert source["mirror"]["verification_run_id"] == 30544079501
    assert source["byte_identical_primary_mirror"] is True
    assert source["bundle_restore_verified"] is True
    assert source["gitleaks_finding_count"] == 0
    assert source["gitleaks_ignored_test_fixture_count"] == 4
    assert source["submodules"] == []
    assert source["lfs_pointers"] == []
    assert [row["path"] for row in source["dependency_files"]] == [
        "pyproject.toml",
        "requirements/gtbi-fast-strict.lock",
    ]
    assert receipt["github_only_restore_verification"] is True
    assert receipt["requires_local_machine"] is False
    assert receipt["scientific_processing_performed"] is False
    assert receipt["locked_data_opened"] is False


def test_v6_scientific_manifest_records_truthful_owner_controlled_custody() -> None:
    receipt = build_preservation_receipt()
    manifest = build_scientific_manifest(receipt)
    checked = json.loads(
        SCIENTIFIC_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    assert checked == manifest
    assert SCIENTIFIC_MANIFEST_PATH.read_bytes() == (
        canonical_bytes(manifest) + b"\n"
    )
    validate_scientific_asset_manifest(manifest)
    assert lifecycle_state(manifest) == "restore_verified_owner_controlled"
    assert manifest["reproducibility_classification"] == (
        "result_preserved_inputs_incomplete"
    )
    assert manifest["missing_v6_dependency_layers"] == [
        "C",
        "D0",
        "D1",
        "D2",
        "D3",
        "S",
    ]
    assert manifest["v6_historical_reproduction_confirmed"] is False
    assert manifest["engine_equivalence_confirmed"] is False
    assert manifest["validation_end"] == "2020-12-31"
    assert manifest["locked_start"] == "2021-01-01"
    assert manifest["last_date"] is None
    assert manifest["primary_release_asset_count"] == 1
    assert manifest["mirror_release_asset_count"] == 1
    assert manifest["independent_github_disaster_asset_count"] == 0
    assert manifest["latest_restore_receipt_digest"] == receipt[
        "receipt_digest"
    ]


def test_legacy_cleanup_receipt_discloses_external_zombie_exactly() -> None:
    receipt = build_cleanup_receipt()
    checked = json.loads(CLEANUP_PATH.read_text(encoding="utf-8"))
    assert checked == receipt
    assert CLEANUP_PATH.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_LEGACY_RUN_CLEANUP_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["deleted_run_count"] == 11
    assert [row["run_id"] for row in receipt["deleted_runs"]] == (
        DELETED_LEGACY_RUN_IDS
    )
    zombie = receipt["quarantined_external_zombie"]
    assert zombie["run_id"] == ZOMBIE_RUN_ID
    assert zombie["github_status"] == "queued"
    assert zombie["job_count"] == 0
    assert zombie["artifact_count"] == 0
    assert zombie["cancel_http_status"] == 500
    assert zombie["force_cancel_http_status"] == 500
    assert zombie["delete_http_status"] == 403
    assert receipt["cleanup_complete_for_executable_or_evidentiary_risk"] is True
    assert receipt["github_state_fully_terminal"] is False
