"""Deterministic owner-controlled G0 foundation evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .canonical import domain_digest, raw_sha256
from .locked_evidence import build_locked_evidence_preservation_report
from .v6_dependency_recovery import build_dependency_recovery_report

READINESS_ROOT = Path(__file__).resolve().parents[2] / "docs/readiness/gtbi-v7"
FOUNDATION_REPORT_PATH = (
    READINESS_ROOT / "g0_owner_controlled_foundation_report.json"
)

EVIDENCE_FILES = (
    "owner_decisions.json",
    "github_packages_inventory_receipt.json",
    "inventory_github_actions_attempt_receipt.json",
    "legacy_run_cleanup_receipt.json",
    "v6_durable_preservation_receipt.json",
    "v6_dependency_recovery_report.json",
    "locked_evidence_preservation_report.json",
    "v6_preservation_lease_public_receipt.json",
    "local_data_lake_receipt.json",
)


class G0FoundationError(ValueError):
    """Raised when owner-controlled G0 evidence is missing or contradictory."""


def _load(name: str) -> dict[str, Any]:
    path = READINESS_ROOT / name
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise G0FoundationError(f"JSON object required: {name}")
    return dict(value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise G0FoundationError(message)


def build_g0_foundation_report() -> dict[str, Any]:
    """Validate existing evidence and build the simplified G0 report."""

    owner = _load("owner_decisions.json")
    decisions = owner["decisions"]
    _require(
        owner["execution_status"] == "TECHNICAL_PREPARATION_AUTHORIZED",
        "technical preparation is not authorized",
    )
    _require(
        decisions["audits_and_people"] == {
            "distinct_people_required": False,
            "external_audits_required": 0,
            "external_custodians_required": False,
            "owner_controlled_model": "accepted_explicitly",
            "three_signed_audits_required": False,
        },
        "owner-controlled review decision mismatch",
    )
    _require(
        decisions["budget"]["maximum_incremental_net_spend_usd"] == 0,
        "incremental spend cap is not zero",
    )
    _require(
        decisions["github_permissions"]["read_packages_oauth_grant_status"]
        == "granted_verified",
        "read:packages grant is not verified",
    )
    _require(
        decisions["licences"]["current_v7_data_input"]
        == "owner_supplied_frozen_local_data_lake",
        "current V7 data input decision mismatch",
    )
    _require(
        decisions["licences"]["provider_download_required_now"] is False,
        "a provider download is still required",
    )
    _require(
        decisions["private_resources"]["owner_authorization"]
        == "authorized_explicitly",
        "private owner-controlled resources are not authorized",
    )

    packages = _load("github_packages_inventory_receipt.json")
    _require(packages["active_account"] is True, "GitHub account is inactive")
    _require(
        packages["read_packages_scope_present"] is True,
        "read:packages scope is absent",
    )

    inventory = _load("inventory_github_actions_attempt_receipt.json")
    _require(inventory["status"] == "success", "inventory run did not succeed")
    _require(inventory["github_only"] is True, "inventory was not GitHub-only")
    _require(
        inventory["requires_local_machine"] is False,
        "remote inventory depends on a local machine",
    )
    _require(
        inventory["packages"]["overall_status"] == "complete",
        "package inventory is incomplete",
    )

    cleanup = _load("legacy_run_cleanup_receipt.json")
    _require(
        cleanup["cleanup_complete_for_executable_or_evidentiary_risk"] is True,
        "legacy cleanup is not complete",
    )
    zombie = cleanup["quarantined_external_zombie"]
    _require(zombie["job_count"] == 0, "quarantined run still has jobs")
    _require(
        zombie["artifact_count"] == 0,
        "quarantined run still has artifacts",
    )
    _require(
        zombie["capacity_effect"] == "none_zero_jobs",
        "quarantined run still affects capacity",
    )

    durable = _load("v6_durable_preservation_receipt.json")
    _require(
        durable["restoration_state"]
        == "verified_on_two_clean_github_runners",
        "V6 durable preservation is incomplete",
    )
    _require(
        durable["primary"]["verification_run_id"] == 30_541_859_386,
        "V6 primary clean restore is unverified",
    )
    _require(
        durable["mirror"]["verification_run_id"] == 30_541_861_880,
        "V6 mirror clean restore is unverified",
    )

    locked = build_locked_evidence_preservation_report()
    _require(
        locked == _load("locked_evidence_preservation_report.json"),
        "locked-evidence report drift",
    )
    _require(
        locked["historical_post_validation_contaminated"] is True,
        "locked evidence is not marked contaminated",
    )
    _require(
        locked["pristine_locked"] is False,
        "locked evidence is incorrectly pristine",
    )

    recovery = build_dependency_recovery_report()
    _require(
        recovery == _load("v6_dependency_recovery_report.json"),
        "V6 dependency recovery report drift",
    )
    _require(
        recovery["missing_layers"] == ["D0", "D1", "D2"],
        "V6 missing dependency layers changed",
    )
    _require(
        recovery["full_v6_reproduction_claim_allowed"] is False,
        "full V6 reproduction is incorrectly allowed",
    )

    lease = _load("v6_preservation_lease_public_receipt.json")
    _require(lease["status"] == "verified", "V6 lease is unverified")
    _require(lease["github_only"] is True, "V6 lease was not GitHub-only")

    local_lake = _load("local_data_lake_receipt.json")
    _require(
        local_lake["provider_download_required_now"] is False,
        "local data-lake receipt still requires provider collection",
    )
    _require(
        local_lake["file_count"] == 10_678,
        "local data-lake file count drift",
    )
    _require(
        local_lake["scientific_cutoff_required"] == "2020-12-31",
        "scientific data cutoff changed",
    )
    _require(
        local_lake["locked_start"] == "2021-01-01",
        "locked boundary changed",
    )

    evidence = {
        name: raw_sha256((READINESS_ROOT / name).read_bytes())
        for name in EVIDENCE_FILES
    }
    report: dict[str, Any] = {
        "schema_version": "gtbi_v7_g0_owner_controlled_foundation_report_v1",
        "recorded_at_utc": "2026-07-30T14:35:00Z",
        "repository": "trading-optimizer-lab-org/aurora",
        "owner_actor_id": "github-user:271768688",
        "owner_controlled_model": True,
        "external_audits_required": 0,
        "distinct_people_required": False,
        "external_custodians_required": False,
        "maximum_incremental_net_spend_usd": 0,
        "read_packages_scope_present": True,
        "provider_download_required_now": False,
        "current_v7_data_input": "owner_supplied_frozen_local_data_lake",
        "private_storage": {
            "primary": {
                "repository": "trading-optimizer-lab-org/aurora-v7-assets",
                "repository_id": 1_317_002_870,
                "private": True,
                "release_count": 4,
                "stored_release_asset_bytes": 5_741_083_720,
            },
            "mirror": {
                "repository": (
                    "trading-optimizer-lab-org/aurora-v7-assets-mirror"
                ),
                "repository_id": 1_317_082_575,
                "private": True,
                "release_count": 3,
                "stored_release_asset_bytes": 2_487_309_886,
            },
            "same_provider_mirror_accepted_by_owner": True,
            "automatic_deletion_configured": False,
        },
        "private_authentication": {
            "model": "repository_scoped_ephemeral_github_token",
            "long_lived_token_in_workflow": False,
            "external_key_broker_required": False,
            "external_github_app_required": False,
            "owner_simplification_applied": True,
            "primary_verification_run_id": 30_550_156_880,
            "mirror_verification_run_id": 30_550_164_808,
        },
        "preservation": {
            "v6_primary_clean_restore": True,
            "v6_mirror_clean_restore": True,
            "locked_primary_clean_verification": True,
            "locked_mirror_clean_verification": True,
            "locked_payload_file_count": 343,
            "locked_source_run_count": 17,
            "locked_remote_artifact_count": 15,
        },
        "legacy_capacity": {
            "deleted_run_count": cleanup["deleted_run_count"],
            "quarantined_zero_job_run_count": 1,
            "remaining_capacity_effect": "none",
        },
        "v6_dependency_classification": {
            "authenticated_layers": ["C", "D3", "S", "R"],
            "missing_layers": ["D0", "D1", "D2"],
            "full_reproduction_claim_allowed": False,
        },
        "scientific_boundaries": {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "scientific_processing_performed": False,
            "locked_data_opened": False,
        },
        "evidence_file_sha256": evidence,
        "formal_task_effects": {
            "PREV7-0001": "evidence_ready",
            "PREV7-0002": "alternative_complete_external_zombie_quarantined",
            "PREV7-0003": "evidence_ready",
            "PREV7-0004": "evidence_ready",
            "PREV7-0005": "evidence_ready",
            "PREV7-0006": "evidence_ready_owner_controlled_storage",
            "PREV7-0007": "alternative_complete_ephemeral_github_token",
            "PREV7-0008": "alternative_complete_preservation_already_verified",
            "PREV7-0009": "alternative_complete_owner_controlled_auth",
            "PREV7-0012": "evidence_ready_preservation_complete",
        },
        "pending_g0_task_ids": ["PREV7-0010", "PREV7-0011"],
        "g0_green_claimed": False,
        "report_digest": "",
    }
    report["report_digest"] = domain_digest(
        "GTBI_V7_G0_OWNER_CONTROLLED_FOUNDATION_REPORT_V1",
        report,
        omit_top_level_fields=("report_digest",),
    )
    return report
