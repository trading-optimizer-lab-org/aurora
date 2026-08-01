"""Freeze PREV7-0307 as a no-V6-baseline decision and future proposal."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256
from infra.readiness_state_controller.policy import validate_transition_manifest

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
CLASSIFICATION = READINESS / "g2_reproducibility_classification_receipt.json"
RECOVERY_REPORT = READINESS / "v6_dependency_recovery_report.json"
LOCAL_DATA = READINESS / "local_data_lake_receipt.json"
GITHUB_DATA = READINESS / "frozen_data_lake_github_release_receipt.json"
PROVIDER_TERMS = READINESS / "g2_provider_terms_acceptance_receipt.json"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
PROPOSAL = READINESS / "new_reference_proposal.json"
RECEIPT = READINESS / "g2_v6_input_identity_decision_receipt.json"
MANIFEST = READINESS / "transition_manifests/g2-v6-input-identity-no-baseline-v1.json"
RECORDED_AT_UTC = "2026-08-01T06:30:00Z"
GATES_REMAINING_RED = [
    "G2",
    "G4",
    "G5",
    "G6A",
    "G3B",
    "G6B",
    "G7",
    "G8",
    "G9",
    "G9X",
    "G10",
]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_expected_result() -> str:
    with (READINESS / "task_status.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return next(row["expected_result"] for row in rows if row["id"] == "PREV7-0307")


def _validate_sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    classification = _load(CLASSIFICATION)
    local_data = _load(LOCAL_DATA)
    github_data = _load(GITHUB_DATA)
    if classification["classification"] != "result_preserved_inputs_incomplete":
        raise ValueError("unexpected V6 reproducibility classification")
    if classification["missing_layers"] != ["D0", "D1", "D2"]:
        raise ValueError("unexpected V6 missing input layers")
    if classification["reuse_recovered_v6_inputs"] is not False:
        raise ValueError("incomplete V6 inputs cannot be reused")
    if classification["v6_historical_reproduction_confirmed"] is not False:
        raise ValueError("V6 reproduction was not authenticated")
    if local_data["provider_download_required_now"] is not False:
        raise ValueError("the frozen local input unexpectedly requires a download")
    if local_data["scientific_cutoff_required"] != "2020-12-31":
        raise ValueError("scientific cutoff changed")
    if local_data["locked_start"] != "2021-01-01":
        raise ValueError("locked boundary changed")
    if github_data["status"] != "verified_published_private":
        raise ValueError("frozen input has no verified private GitHub copy")
    if github_data["provider_download_performed"] is not False:
        raise ValueError("decision step must not download provider data")
    return classification, local_data, github_data


def build_proposal() -> dict[str, Any]:
    classification, local_data, github_data = _validate_sources()
    proposal: dict[str, Any] = {
        "schema_version": "gtbi_v7_new_reference_proposal_v1",
        "proposal_id": "gtbi_v7_frozen_local_reference_candidate_v1",
        "product_identity": "gtbi_v7_separate_reference_candidate",
        "campaign_identity": "gtbi_v7_new_reference_campaign_unapproved",
        "recorded_at_utc": RECORDED_AT_UTC,
        "status": "proposal_only_not_designated_not_approved",
        "separate_from_v6": True,
        "may_serve_as_original_v6_input": False,
        "may_green_current_v7_gates": False,
        "requires_separate_product_campaign_plan": True,
        "reuse_recovered_v6_inputs": False,
        "source_v6_classification": classification["classification"],
        "missing_v6_dependency_layers": classification["missing_layers"],
        "candidate_transport_identity": {
            "archive_sha256": github_data["archive_sha256"],
            "archive_size_bytes": github_data["archive_size_bytes"],
            "release_id": github_data["release_id"],
            "release_tag": github_data["release_tag"],
            "repository_id": github_data["repository_id"],
            "source_file_count": github_data["source_file_count"],
            "source_total_bytes": github_data["source_total_bytes"],
            "github_verification_run_id": github_data["verification_run_id"],
        },
        "candidate_data_facts": {
            "provider": "legacy_yahoo_finance_via_yfinance_frozen_bytes",
            "retrieval_cutoff_utc": None,
            "last_observation_date": local_data["last_observation_date"],
            "price_data_vintage_utc": None,
            "source_event_cutoff_utc": "unknown_unverifiable",
            "observation_timestamp_state": "unknown_unverifiable",
            "universe_temporal_model": "static_post_period",
            "survivorship_biased_reference": True,
            "point_in_time_claim_allowed": False,
            "historical_causal_claim_allowed": False,
            "adjustment_temporal_model": "retrospectively_adjusted_reference",
            "cross_market_alignment_model": "v6_calendar_date_reference",
            "first_allowed_date": None,
            "last_allowed_date": "2020-12-31",
            "historical_exclusion_start": "2021-01-01",
            "locked_rows_present_but_excluded": local_data["locked_rows_present"],
        },
        "unresolved_before_separate_plan": [
            "authenticated_retrieval_cutoff_utc",
            "exact_universe_identity_digest",
            "instrument_alias_and_listing_manifest_digest",
            "membership_and_eligibility_policy_digest",
            "delisted_policy_digest",
            "corporate_action_knowledge_manifest_digest",
            "decision_time_policy_digest",
            "market_observation_availability_policy_digest",
            "calendar_policy_sha256",
            "currency_policy_sha256",
            "schema_digest",
            "reference_code_sha",
            "dependency_lock_digest",
            "per_file_hash_manifest_digest",
        ],
        "prohibited_claims": [
            "original_v6_dataset",
            "fully_reproducible_v6",
            "point_in_time_universe",
            "survivorship_free",
            "historical_knowability",
            "causal_cross_market_alignment",
            "current_v7_baseline_approved",
        ],
        "provider_download_performed": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
        "locked_data_accessed": False,
        "locked_start": "2021-01-01",
        "maximum_incremental_net_spend_usd": 0,
        "proposal_digest": "",
    }
    proposal["proposal_digest"] = domain_digest(
        "GTBI_V7_NEW_REFERENCE_PROPOSAL_V1",
        proposal,
        omit_top_level_fields=("proposal_digest",),
    )
    return proposal


def build_receipt(proposal: dict[str, Any]) -> dict[str, Any]:
    classification, _, _ = _validate_sources()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g2_v6_input_identity_decision_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "task_id": "PREV7-0307",
        "recorded_at_utc": RECORDED_AT_UTC,
        "owner_actor_id": "github-user:271768688",
        "decision": "no_authenticated_v6_input_identity",
        "reuse_recovered_v6_inputs": False,
        "v6_historical_reproduction_confirmed": False,
        "missing_v6_dependency_layers": classification["missing_layers"],
        "current_v7_baseline_authorized": False,
        "selected_branch_id": "V6_INPUT_IDENTITY",
        "selected_successor": "separate_reference_proposal_and_no_go_close",
        "new_reference_proposal_path": PROPOSAL.relative_to(ROOT).as_posix(),
        "new_reference_proposal_digest": proposal["proposal_digest"],
        "gates_required_to_remain_red": GATES_REMAINING_RED,
        "no_go_close_required": True,
        "no_go_close_activation_state": "required_after_prev7_0307_state_merge",
        "evidence": {
            "classification_receipt_sha256": raw_sha256(CLASSIFICATION),
            "recovery_report_sha256": raw_sha256(RECOVERY_REPORT),
            "local_data_lake_receipt_sha256": raw_sha256(LOCAL_DATA),
            "github_data_lake_receipt_sha256": raw_sha256(GITHUB_DATA),
            "provider_terms_receipt_sha256": raw_sha256(PROVIDER_TERMS),
            "owner_directive_sha256": raw_sha256(OWNER_DIRECTIVE),
        },
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "strategy_evaluation_performed": False,
            "provider_download_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G2_V6_INPUT_IDENTITY_DECISION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def build_manifest(receipt: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = [
        RECEIPT.relative_to(ROOT).as_posix(),
        PROPOSAL.relative_to(ROOT).as_posix(),
        CLASSIFICATION.relative_to(ROOT).as_posix(),
        RECOVERY_REPORT.relative_to(ROOT).as_posix(),
        LOCAL_DATA.relative_to(ROOT).as_posix(),
        GITHUB_DATA.relative_to(ROOT).as_posix(),
        PROVIDER_TERMS.relative_to(ROOT).as_posix(),
        OWNER_DIRECTIVE.relative_to(ROOT).as_posix(),
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g2-v6-input-identity-no-baseline-v1",
        "transaction_id": "G2_CLOSE-7",
        "requested_at_utc": RECORDED_AT_UTC,
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0307",
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
                "terminal_reason": "no_authenticated_v6_inputs_separate_reference_only",
                "notes": (
                    "The original V6 D0, D1 and D2 identities are not authenticated. "
                    "The frozen local bytes are recorded only as an unapproved separate "
                    "reference proposal. Current V7 gates remain red and NO_GO closure "
                    "is required."
                ),
                "files_touched": evidence_paths,
                "expected_result": _task_expected_result(),
                "alternative_completion_receipt_set_digest_or_null": receipt[
                    "receipt_digest"
                ],
            }
        ],
        "branch_actions": [
            {
                "branch_id": "V6_INPUT_IDENTITY",
                "task_id": "PREV7-0307",
                "selected_successor": receipt["selected_successor"],
                "predicate_evidence_digest": proposal["proposal_digest"],
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
    validate_transition_manifest(manifest)
    return manifest


def verify_committed() -> None:
    proposal = _load(PROPOSAL)
    receipt = _load(RECEIPT)
    manifest = _load(MANIFEST)
    for path, payload in ((PROPOSAL, proposal), (RECEIPT, receipt), (MANIFEST, manifest)):
        if path.read_bytes() != canonical_bytes(payload) + b"\n":
            raise ValueError(f"non-canonical generated document: {path}")
    if proposal != build_proposal():
        raise ValueError("new-reference proposal drift")
    if receipt != build_receipt(proposal):
        raise ValueError("V6 input decision receipt drift")
    if manifest != build_manifest(receipt, proposal):
        raise ValueError("V6 input decision manifest drift")


def main() -> int:
    proposal = build_proposal()
    receipt = build_receipt(proposal)
    PROPOSAL.write_bytes(canonical_bytes(proposal) + b"\n")
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(canonical_bytes(build_manifest(receipt, proposal)) + b"\n")
    verify_committed()
    print(receipt["receipt_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
