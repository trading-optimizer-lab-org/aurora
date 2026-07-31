"""Generate the owner-approved zero-increment GTBI V7 retention policy."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import (  # noqa: E402
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

READINESS = ROOT / "docs/readiness/gtbi-v7"
POLICY = ROOT / "config/gtbi/governance/production_asset_retention_policy_v1.json"
MIGRATION_EVIDENCE = READINESS / "migration_duration_evidence.json"
RECEIPT = READINESS / "g2_retention_policy_receipt.json"
MANIFEST = READINESS / "transition_manifests/g2-retention-policy-v1.json"
OWNER_DECISIONS = READINESS / "owner_decisions.json"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
BILLING_RECEIPT = READINESS / "billing_baseline_public_receipt.json"
V6_RECEIPT = READINESS / "v6_durable_preservation_receipt.json"
DATA_RECEIPT = READINESS / "frozen_data_lake_github_release_receipt.json"
RECORDED_AT_UTC = "2026-07-31T17:50:00Z"
REVIEW_DUE_UTC = "2026-08-31T18:00:00Z"
FUNDED_THROUGH_UTC = "2026-08-31T23:59:59Z"
POLICY_EXPIRES_UTC = "2026-09-01T00:00:00Z"
MINIMUM_RETENTION_UNTIL_UTC = "2026-10-27T14:57:48Z"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_migration_evidence() -> dict[str, Any]:
    samples: list[dict[str, Any]] = [
        {
            "run_id": 30541859386,
            "purpose": "primary_v6_clean_runner_restore",
            "duration_seconds": 33,
        },
        {
            "run_id": 30541861880,
            "purpose": "mirror_v6_clean_runner_restore",
            "duration_seconds": 37,
        },
        {
            "run_id": 30528738857,
            "purpose": "frozen_data_lake_clean_runner_verify",
            "duration_seconds": 79,
        },
        {
            "run_id": 30544079501,
            "purpose": "mirror_source_bundle_restore",
            "duration_seconds": 114,
        },
        {
            "run_id": 30544068594,
            "purpose": "primary_source_bundle_restore",
            "duration_seconds": 118,
        },
    ]
    p95_restore = max(sample["duration_seconds"] for sample in samples)
    p95_migration = 0
    incident_response = 86_400
    safety_margin = 86_400
    minimum_days = math.ceil(
        (p95_migration + p95_restore + incident_response + safety_margin) / 86_400
    )
    payload: dict[str, Any] = {
        "schema_version": "gtbi_v7_migration_duration_evidence_v1",
        "recorded_at_utc": RECORDED_AT_UTC,
        "measurement_window_start_utc": "2026-07-30T08:57:31Z",
        "measurement_window_end_utc": "2026-07-30T12:50:00Z",
        "restore_samples": samples,
        "p95_method": "nearest_rank_conservative_max_for_five_samples",
        "p95_verified_restore_seconds": p95_restore,
        "migration_measurement_status": (
            "not_applicable_owner_approved_same_provider_zero_incremental_model"
        ),
        "p95_verified_full_migration_seconds": p95_migration,
        "maximum_incident_response_seconds": incident_response,
        "safety_margin_seconds": safety_margin,
        "minimum_required_migration_lead_time_days": minimum_days,
        "selected_migration_lead_time_days": 30,
        "external_provider_copy_required": False,
        "locked_or_scientific_processing_performed": False,
        "evidence_digest": "",
    }
    payload["evidence_digest"] = domain_digest(
        "GTBI_V7_MIGRATION_DURATION_EVIDENCE_V1",
        payload,
        omit_top_level_fields=("evidence_digest",),
    )
    return payload


def _asset_class(
    *,
    name: str,
    custody_domain: str,
    rpo: int | str,
    rto_seconds: int,
    restore_frequency_days: int,
    latest_restore_digest: str | None,
    acceptance_state: str,
) -> dict[str, Any]:
    return {
        "asset_class": name,
        "custody_domain": custody_domain,
        "provider_account_region": "github.com/global",
        "named_operational_owner_actor_id": "github-user:271768688",
        "named_payer_actor_or_organization_id": "trading-optimizer-lab-org",
        "funding_reservation_receipt_digest": raw_sha256(BILLING_RECEIPT),
        "funded_through_utc": FUNDED_THROUGH_UTC,
        "renewal_review_due_utc": REVIEW_DUE_UTC,
        "migration_lead_time_days": 30,
        "minimum_required_migration_lead_time_days": 3,
        "migration_duration_evidence_digest": "",
        "minimum_retention_until_utc": MINIMUM_RETENTION_UNTIL_UTC,
        "rpo_seconds_or_exact_batch_bound": rpo,
        "rto_seconds": rto_seconds,
        "restore_test_frequency_days": restore_frequency_days,
        "latest_restore_test_receipt_digest": latest_restore_digest,
        "acceptance_state": acceptance_state,
    }


def build_policy(migration: dict[str, Any]) -> dict[str, Any]:
    owner_decisions = _load(OWNER_DECISIONS)
    billing = _load(BILLING_RECEIPT)
    v6 = _load(V6_RECEIPT)
    data = _load(DATA_RECEIPT)
    classes = [
        _asset_class(
            name="canonical_final_reference",
            custody_domain="github_releases_primary_and_owner_mirror",
            rpo=0,
            rto_seconds=86_400,
            restore_frequency_days=30,
            latest_restore_digest=v6["receipt_digest"],
            acceptance_state="accepted_owner_controlled_same_provider",
        ),
        _asset_class(
            name="immutable_audit_log",
            custody_domain="protected_git_history_and_actions_evidence",
            rpo=0,
            rto_seconds=14_400,
            restore_frequency_days=30,
            latest_restore_digest=v6["receipt_digest"],
            acceptance_state="policy_active",
        ),
        _asset_class(
            name="checkpoint",
            custody_domain="github_actions_artifact_checkpoint_chain",
            rpo="one_unacknowledged_batch_per_planned_job_chain",
            rto_seconds=21_600,
            restore_frequency_days=30,
            latest_restore_digest=None,
            acceptance_state="policy_only_no_current_production_checkpoint",
        ),
        _asset_class(
            name="source_bundle",
            custody_domain="github_releases_primary_and_owner_mirror",
            rpo=0,
            rto_seconds=86_400,
            restore_frequency_days=30,
            latest_restore_digest=v6["receipt_digest"],
            acceptance_state="accepted_owner_controlled_same_provider",
        ),
        _asset_class(
            name="data_snapshot",
            custody_domain="github_release_owner_assets_repository",
            rpo=0,
            rto_seconds=86_400,
            restore_frequency_days=30,
            latest_restore_digest=data["github_verification_receipt_digest"],
            acceptance_state="accepted_frozen_local_source_published_github",
        ),
        _asset_class(
            name="strategy_pack",
            custody_domain="github_release_or_content_addressed_result_bundle",
            rpo=0,
            rto_seconds=86_400,
            restore_frequency_days=30,
            latest_restore_digest=v6["receipt_digest"],
            acceptance_state="policy_active",
        ),
        _asset_class(
            name="emergency_v6_package",
            custody_domain="github_releases_primary_and_owner_mirror",
            rpo=0,
            rto_seconds=86_400,
            restore_frequency_days=30,
            latest_restore_digest=v6["receipt_digest"],
            acceptance_state="accepted_owner_controlled_same_provider",
        ),
        _asset_class(
            name="platform_outage_copy",
            custody_domain="none_owner_waived_external_provider",
            rpo="not_applicable_no_external_copy_required",
            rto_seconds=86_400,
            restore_frequency_days=30,
            latest_restore_digest=None,
            acceptance_state="not_required_by_owner_simplification_directive",
        ),
    ]
    for row in classes:
        row["migration_duration_evidence_digest"] = migration["evidence_digest"]
    policy: dict[str, Any] = {
        "schema_version": "gtbi_v7_production_asset_retention_policy_v1",
        "policy_version": 1,
        "repository": "trading-optimizer-lab-org/aurora",
        "effective_at_utc": RECORDED_AT_UTC,
        "policy_expires_at_utc": POLICY_EXPIRES_UTC,
        "operational_owner_actor_id": "github-user:271768688",
        "payer_organization_id": "trading-optimizer-lab-org",
        "recurring_review": {
            "frequency_days": 30,
            "next_review_due_utc": REVIEW_DUE_UTC,
            "missed_review_effect": "invalidate_new_asset_acceptance_fail_closed",
            "workflow": ".github/workflows/aurora-maintenance-retention.yml",
        },
        "budget": {
            "currency": "USD",
            "current_actions_net_amount_usd": billing["current_actions_net_amount_usd"],
            "current_enterprise_cloud_full_month_unit_amount_usd": billing[
                "current_enterprise_cloud_full_month_unit_amount_usd"
            ],
            "maximum_incremental_net_spend_usd": 0,
            "new_billable_resources_authorized": False,
            "funding_model": "continue_existing_github_baseline_only",
            "discount_change_requires_reauthorization": True,
        },
        "custody_model": {
            "model": "owner_controlled_same_provider_primary_and_mirror",
            "external_provider_copy_required": False,
            "same_provider_outage_limitation_disclosed": True,
        },
        "acceptance_rules": {
            "zero_rpo_begins_after_asset_acceptance": True,
            "missing_or_stale_review_blocks_new_acceptance": True,
            "insufficient_migration_lead_time_blocks_new_acceptance": True,
            "failed_restore_test_invalidates_affected_asset_acceptance": True,
            "policy_completion_does_not_open_locked": True,
        },
        "asset_classes": classes,
        "evidence": {
            "owner_decisions_sha256": raw_sha256(OWNER_DECISIONS),
            "owner_directive_sha256": raw_sha256(OWNER_DIRECTIVE),
            "billing_receipt_sha256": raw_sha256(BILLING_RECEIPT),
            "v6_preservation_receipt_sha256": raw_sha256(V6_RECEIPT),
            "frozen_data_receipt_sha256": raw_sha256(DATA_RECEIPT),
            "migration_duration_evidence_digest": migration["evidence_digest"],
        },
        "owner_authorization": owner_decisions["execution_status"],
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "policy_digest": "",
    }
    policy["policy_digest"] = domain_digest(
        "GTBI_V7_PRODUCTION_ASSET_RETENTION_POLICY_V1",
        policy,
        omit_top_level_fields=("policy_digest",),
    )
    return policy


def validate_policy(policy: dict[str, Any], migration: dict[str, Any]) -> None:
    if policy["budget"]["maximum_incremental_net_spend_usd"] != 0:
        raise ValueError("retention policy exceeds the owner budget")
    if policy["budget"]["new_billable_resources_authorized"]:
        raise ValueError("retention policy authorizes new billable resources")
    if migration["selected_migration_lead_time_days"] < migration[
        "minimum_required_migration_lead_time_days"
    ]:
        raise ValueError("selected migration lead time is insufficient")
    classes = {row["asset_class"]: row for row in policy["asset_classes"]}
    if classes["canonical_final_reference"]["rpo_seconds_or_exact_batch_bound"] != 0:
        raise ValueError("canonical final/reference RPO must be zero")
    if classes["canonical_final_reference"]["rto_seconds"] > 86_400:
        raise ValueError("canonical final/reference RTO exceeds 24 hours")
    if classes["immutable_audit_log"]["rpo_seconds_or_exact_batch_bound"] != 0:
        raise ValueError("audit/log RPO must be zero")
    if classes["immutable_audit_log"]["rto_seconds"] > 14_400:
        raise ValueError("audit/log RTO exceeds four hours")
    if classes["checkpoint"]["rto_seconds"] > 21_600:
        raise ValueError("checkpoint RTO exceeds six hours")
    if classes["emergency_v6_package"]["rto_seconds"] > 86_400:
        raise ValueError("emergency V6 RTO exceeds 24 hours")
    for row in classes.values():
        if row["migration_lead_time_days"] < row[
            "minimum_required_migration_lead_time_days"
        ]:
            raise ValueError(f"insufficient migration lead time: {row['asset_class']}")


def build_receipt(policy: dict[str, Any], migration: dict[str, Any]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g2_retention_policy_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "task_id": "PREV7-0301",
        "recorded_at_utc": RECORDED_AT_UTC,
        "policy_path": POLICY.relative_to(ROOT).as_posix(),
        "policy_sha256": raw_sha256(POLICY),
        "policy_digest": policy["policy_digest"],
        "migration_evidence_path": MIGRATION_EVIDENCE.relative_to(ROOT).as_posix(),
        "migration_evidence_sha256": raw_sha256(MIGRATION_EVIDENCE),
        "migration_evidence_digest": migration["evidence_digest"],
        "asset_class_count": len(policy["asset_classes"]),
        "maximum_incremental_net_spend_usd": 0,
        "next_review_due_utc": REVIEW_DUE_UTC,
        "policy_expires_at_utc": POLICY_EXPIRES_UTC,
        "same_provider_outage_limitation_disclosed": True,
        "external_provider_copy_required": False,
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G2_RETENTION_POLICY_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def build_manifest(receipt: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = [
        RECEIPT.relative_to(ROOT).as_posix(),
        MIGRATION_EVIDENCE.relative_to(ROOT).as_posix(),
        OWNER_DECISIONS.relative_to(ROOT).as_posix(),
        BILLING_RECEIPT.relative_to(ROOT).as_posix(),
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g2-retention-policy-v1",
        "transaction_id": "G2_CLOSE-2",
        "requested_at_utc": RECORDED_AT_UTC,
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0301",
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
                "terminal_reason": "owner_zero_increment_retention_policy_frozen",
                "notes": (
                    "The owner freezes exact RPO/RTO, retention, review and expiry rules "
                    "within the existing GitHub billing baseline. No external provider or "
                    "new billable resource is claimed."
                ),
                "files_touched": evidence_paths,
                "expected_result": (
                    "Production asset, funded-retention and exact RPO/RTO policy finalized "
                    "with recurring review owner and expiry"
                ),
                "alternative_completion_receipt_set_digest_or_null": receipt[
                    "receipt_digest"
                ],
            }
        ],
        "branch_actions": [],
        "gate_actions": [],
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def verify_committed(*, now: datetime | None = None) -> dict[str, Any]:
    migration = _load(MIGRATION_EVIDENCE)
    policy = _load(POLICY)
    receipt = _load(RECEIPT)
    manifest = _load(MANIFEST)
    for path, payload in (
        (MIGRATION_EVIDENCE, migration),
        (POLICY, policy),
        (RECEIPT, receipt),
        (MANIFEST, manifest),
    ):
        if path.read_bytes() != canonical_bytes(payload) + b"\n":
            raise ValueError(f"non-canonical retention evidence: {path.name}")
    if migration["evidence_digest"] != domain_digest(
        "GTBI_V7_MIGRATION_DURATION_EVIDENCE_V1",
        migration,
        omit_top_level_fields=("evidence_digest",),
    ):
        raise ValueError("migration evidence digest mismatch")
    if policy["policy_digest"] != domain_digest(
        "GTBI_V7_PRODUCTION_ASSET_RETENTION_POLICY_V1",
        policy,
        omit_top_level_fields=("policy_digest",),
    ):
        raise ValueError("retention policy digest mismatch")
    validate_policy(policy, migration)
    if receipt["policy_sha256"] != raw_sha256(POLICY):
        raise ValueError("retention receipt policy hash mismatch")
    if receipt["receipt_digest"] != domain_digest(
        "GTBI_V7_G2_RETENTION_POLICY_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    ):
        raise ValueError("retention receipt digest mismatch")
    if manifest["manifest_digest"] != domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    ):
        raise ValueError("retention manifest digest mismatch")
    current = now or datetime.now(timezone.utc)
    expires = datetime.fromisoformat(policy["policy_expires_at_utc"].replace("Z", "+00:00"))
    return {
        "status": "valid" if current < expires else "expired_fail_closed",
        "policy_digest": policy["policy_digest"],
        "next_review_due_utc": policy["recurring_review"]["next_review_due_utc"],
        "policy_expires_at_utc": policy["policy_expires_at_utc"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--review-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.verify:
        result = verify_committed()
        if args.review_output is not None:
            args.review_output.parent.mkdir(parents=True, exist_ok=True)
            args.review_output.write_bytes(canonical_bytes(result) + b"\n")
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "valid" else 2
    migration = build_migration_evidence()
    MIGRATION_EVIDENCE.write_bytes(canonical_bytes(migration) + b"\n")
    policy = build_policy(migration)
    validate_policy(policy, migration)
    POLICY.parent.mkdir(parents=True, exist_ok=True)
    POLICY.write_bytes(canonical_bytes(policy) + b"\n")
    receipt = build_receipt(policy, migration)
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    manifest = build_manifest(receipt)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(canonical_bytes(manifest) + b"\n")
    print(json.dumps(verify_committed(now=datetime(2026, 7, 31, tzinfo=timezone.utc))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
