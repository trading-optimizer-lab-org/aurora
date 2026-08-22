"""Freeze PREV7-0309 GitHub Actions use, price and capacity evidence."""

from __future__ import annotations

import csv
import json
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
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
OWNER_DECISIONS = READINESS / "owner_decisions.json"
PROVIDER_TERMS = READINESS / "g2_provider_terms_acceptance_receipt.json"
BILLING = READINESS / "billing_baseline_public_receipt.json"
CAPACITY_PROFILE = ROOT / "config/github_capacity_profile.json"
RECEIPT = READINESS / "g2_github_actions_envelope_receipt.json"
TRANSITION = READINESS / "transition_manifests/g2-github-actions-envelope-v1.json"
RECORDED_AT_UTC = "2026-07-31T19:55:00Z"
RECORDED_CAPACITY_PROFILE_SHA256 = (
    "sha256:c107f626a44b52c2cdfb50e9d49d544d1158abc2ac03d8cec09bc06c9b852829"
)
RECORDED_CAPACITY_PROFILE_FIELDS = {
    "schema_version": "1",
    "organization": "trading-optimizer-lab-org",
    "repository": "aurora",
    "repository_visibility": "public",
    "plan": "enterprise",
    "standard_concurrency_ceiling": 360,
    "matrix_job_ceiling": 256,
    "runner_label": "ubuntu-24.04",
    "reference_cpu": 4,
    "reference_memory_gb": 16,
    "reference_ssd_gb": 14,
    "larger_runners_allowed": False,
    "confirmed_on": "2026-06-02",
    "confirmation_source": "github_support_email",
}

OFFICIAL_DOCUMENTS = [
    {
        "purpose": "additional_product_terms",
        "url": "https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features",
        "retrieved_at_utc": "2026-07-31T19:43:00Z",
        "sha256": "sha256:57ad66800b6e7b9b2b9b0a9948f9a2173031581579113356417acfb2a9a08af3",
        "bytes": 195678,
    },
    {
        "purpose": "acceptable_use_policy",
        "url": "https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies",
        "retrieved_at_utc": "2026-07-31T19:43:00Z",
        "sha256": "sha256:1e29b790bf813dc93c68c44fd3528b0e29dbf5605c4ad373726b59525cf9dcaf",
        "bytes": 176105,
    },
    {
        "purpose": "actions_billing",
        "url": "https://docs.github.com/en/billing/concepts/product-billing/github-actions",
        "retrieved_at_utc": "2026-07-31T19:43:00Z",
        "sha256": "sha256:328b228f02f796905e59f22120de52c5d1458a79b4137af3fa47ddf34bf38cb5",
        "bytes": 233455,
    },
    {
        "purpose": "hosted_runner_specification",
        "url": "https://docs.github.com/en/actions/reference/runners/github-hosted-runners",
        "retrieved_at_utc": "2026-07-31T19:43:00Z",
        "sha256": "sha256:b4c5260fabe4be6977d76aba7d825ecc3dbf085afe3ac8fa7e7ab21b690b997e",
        "bytes": 434787,
    },
    {
        "purpose": "actions_limits",
        "url": "https://docs.github.com/en/actions/reference/limits",
        "retrieved_at_utc": "2026-07-31T19:43:00Z",
        "sha256": "sha256:5ced58a43b460cc31a89bc4358c3ee6d6ad37641f99a69e8da15c50e0ae909d9",
        "bytes": 378753,
    },
]


def _load_canonical(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(value) + b"\n":
        raise ValueError(f"non-canonical evidence: {path.relative_to(ROOT)}")
    return value


def _expected_result() -> str:
    with (READINESS / "task_status.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    return next(row["expected_result"] for row in rows if row["id"] == "PREV7-0309")


def build_receipt() -> dict[str, Any]:
    owner = _load_canonical(OWNER_DIRECTIVE)
    decisions = _load_canonical(OWNER_DECISIONS)
    provider = _load_canonical(PROVIDER_TERMS)
    billing = _load_canonical(BILLING)
    capacity = json.loads(CAPACITY_PROFILE.read_text(encoding="utf-8"))

    if not owner["accepted"]:
        raise ValueError("owner directive is not accepted")
    if provider["decision"] != "accepted_for_frozen_input_only":
        raise ValueError("data transport decision is not accepted")
    if billing["current_actions_net_amount_usd"] != 0:
        raise ValueError("current Actions net amount is not zero")
    if billing["maximum_incremental_net_spend_usd"] != 0:
        raise ValueError("billing baseline exceeds owner cap")
    if capacity["standard_concurrency_ceiling"] != 360:
        raise ValueError("owner capacity profile is not capped at 360")
    if capacity["reference_cpu"] != 4 or capacity["reference_memory_gb"] != 16:
        raise ValueError("public standard runner profile changed")
    if capacity["larger_runners_allowed"]:
        raise ValueError("billable larger runners are not allowed")
    if any(
        capacity.get(key) != expected
        for key, expected in RECORDED_CAPACITY_PROFILE_FIELDS.items()
    ):
        raise ValueError("recorded capacity profile fields changed")

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_github_actions_envelope_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "repository_id": 1232647748,
        "organization": "trading-optimizer-lab-org",
        "organization_id": 287229438,
        "organization_plan_observed": "enterprise",
        "repository_visibility": "public",
        "task_id": "PREV7-0309",
        "recorded_at_utc": RECORDED_AT_UTC,
        "official_documents": OFFICIAL_DOCUMENTS,
        "acceptable_use_decision": {
            "status": "approved_by_repository_owner",
            "reviewer_actor_id": "github-user:271768688",
            "independent_reviewer_required": False,
            "legal_opinion_claimed": False,
            "owner_residual_risk_accepted": True,
            "scientific_workload_purpose": (
                "development_testing_and_validation_of_the_aurora_quant_research_engine"
            ),
            "public_repository_development_test_nexus": True,
            "standalone_compute_service": False,
            "cryptomining": False,
            "content_delivery_network": False,
            "unrelated_automated_bulk_activity": False,
            "new_provider_collection": False,
            "plaintext_input_processing_on_ephemeral_github_runner": (
                "owner_accepted_for_frozen_private_release_input"
            ),
        },
        "capacity_topology": {
            "branch_id": "CAPACITY_TOPOLOGY",
            "selected_successor": "owner_controlled_public_standard_360",
            "runner_class": "ubuntu-24.04_standard_public_repository",
            "effective_cpu": 4,
            "memory_gib": 16,
            "ssd_gib": 14,
            "maximum_concurrent_jobs": 360,
            "source_control_reserve_when_shared": 0,
            "destination_control_reserve_when_shared": 0,
            "reserve_waiver_basis": "owner_controlled_single_domain_simplification",
            "matrix_job_ceiling": 256,
            "larger_runners_allowed": False,
            "self_hosted_runners_allowed": False,
            "local_machine_allowed": False,
            "control_workflows_may_queue_outside_scientific_wave": True,
        },
        "capacity_sources": {
            "profile_path": CAPACITY_PROFILE.relative_to(ROOT).as_posix(),
            "profile_sha256": RECORDED_CAPACITY_PROFILE_SHA256,
            "profile_confirmation_source": capacity["confirmation_source"],
            "profile_confirmed_on": capacity["confirmed_on"],
            "observed_run": {
                "run_id": 28111310277,
                "run_url": "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/28111310277",
                "workflow_name": (
                    "Global Technical Buy Indicator External Pack 360 Jobs"
                ),
                "head_sha": "5b3cdc87f50586fa1615df3138ffdfd5ae7b7ab4",
                "total_jobs": 363,
                "jobs_with_intervals": 363,
                "peak_concurrent_jobs": 360,
                "peak_at_utc": "2026-06-24T15:57:02Z",
                "measurement_method": (
                    "sweep_started_at_and_completed_at_from_github_actions_jobs_api"
                ),
                "capacity_only_evidence": True,
                "run_result_used_as_scientific_evidence": False,
            },
        },
        "billing_envelope": {
            "currency": "USD",
            "maximum_incremental_net_spend_usd": 0,
            "current_actions_net_amount_usd": 0,
            "new_billable_resources_authorized": False,
            "standard_public_runner_minutes": "free_under_retrieved_github_terms",
            "maximum_billable_runner_minutes": 0,
            "larger_runner_minutes": 0,
            "private_standard_runner_minutes": 0,
            "external_control_plane_spend_usd": 0,
            "billing_baseline_digest": raw_sha256(BILLING),
            "billing_change_effect": "invalidate_and_require_owner_reauthorization",
        },
        "preliminary_workload_envelope": {
            "maximum_concurrent_jobs": 360,
            "maximum_matrix_jobs_per_matrix": 256,
            "maximum_job_execution_seconds": 21600,
            "maximum_campaign_jobs": 7200,
            "artifact_and_packages_traffic": "private_inputs_and_bounded_results_only",
            "retries": "failed_units_only",
            "repository_visibility": "public",
            "locked_start": "2021-01-01",
            "validation_end": "2020-12-31",
            "exact_full_dispatch_requires_later_authorization": True,
        },
        "owner_decisions_sha256": raw_sha256(OWNER_DECISIONS),
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "scientific_boundaries": {
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "strategy_evaluation_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_GITHUB_ACTIONS_ENVELOPE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def build_transition_manifest(receipt: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = [
        RECEIPT.relative_to(ROOT).as_posix(),
        PROVIDER_TERMS.relative_to(ROOT).as_posix(),
        BILLING.relative_to(ROOT).as_posix(),
        OWNER_DECISIONS.relative_to(ROOT).as_posix(),
        OWNER_DIRECTIVE.relative_to(ROOT).as_posix(),
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g2-github-actions-envelope-v1",
        "transaction_id": "G2_CLOSE-6",
        "requested_at_utc": RECORDED_AT_UTC,
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0309",
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
                "terminal_reason": "owner_accepted_zero_cost_public_actions_envelope",
                "notes": (
                    "The owner selects a conservative 360-job public standard-runner "
                    "topology, accepts the retrieved terms for Aurora development, "
                    "testing and validation, and authorizes no incremental spend."
                ),
                "files_touched": evidence_paths,
                "expected_result": _expected_result(),
                "alternative_completion_receipt_set_digest_or_null": receipt[
                    "receipt_digest"
                ],
            }
        ],
        "branch_actions": [
            {
                "branch_id": "CAPACITY_TOPOLOGY",
                "task_id": "PREV7-0309",
                "predicate_evidence_digest": receipt["receipt_digest"],
                "selected_successor": "owner_controlled_public_standard_360",
                "decision_receipt_digest": receipt["receipt_digest"],
            }
        ],
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


def main() -> int:
    receipt = build_receipt()
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    transition = build_transition_manifest(receipt)
    TRANSITION.parent.mkdir(parents=True, exist_ok=True)
    TRANSITION.write_bytes(canonical_bytes(transition) + b"\n")
    print(json.dumps({"receipt_digest": receipt["receipt_digest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
