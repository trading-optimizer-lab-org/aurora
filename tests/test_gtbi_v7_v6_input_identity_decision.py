from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_v6_input_identity_decision import (
    GATES_REMAINING_RED,
    MANIFEST,
    PROPOSAL,
    RECEIPT,
    build_manifest,
    build_proposal,
    build_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v6_input_decision_is_canonical_and_reproducible() -> None:
    proposal = _load(PROPOSAL)
    receipt = _load(RECEIPT)
    manifest = _load(MANIFEST)
    assert PROPOSAL.read_bytes() == canonical_bytes(proposal) + b"\n"
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert proposal == build_proposal()
    assert receipt == build_receipt(proposal)
    assert manifest == build_manifest(receipt, proposal)
    assert proposal["proposal_digest"] == domain_digest(
        "GTBI_V7_NEW_REFERENCE_PROPOSAL_V1",
        proposal,
        omit_top_level_fields=("proposal_digest",),
    )
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_G2_V6_INPUT_IDENTITY_DECISION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    validate_transition_manifest(manifest)


def test_local_frozen_bytes_are_only_a_separate_unapproved_reference() -> None:
    proposal = _load(PROPOSAL)
    assert proposal["status"] == "proposal_only_not_designated_not_approved"
    assert proposal["separate_from_v6"] is True
    assert proposal["may_serve_as_original_v6_input"] is False
    assert proposal["may_green_current_v7_gates"] is False
    assert proposal["requires_separate_product_campaign_plan"] is True
    assert proposal["candidate_data_facts"]["universe_temporal_model"] == (
        "static_post_period"
    )
    assert proposal["candidate_data_facts"]["survivorship_biased_reference"] is True
    assert proposal["candidate_data_facts"]["point_in_time_claim_allowed"] is False
    assert proposal["candidate_data_facts"]["source_event_cutoff_utc"] == (
        "unknown_unverifiable"
    )
    assert "original_v6_dataset" in proposal["prohibited_claims"]
    assert "current_v7_baseline_approved" in proposal["prohibited_claims"]


def test_negative_identity_decision_preserves_all_scientific_boundaries() -> None:
    receipt = _load(RECEIPT)
    assert receipt["decision"] == "no_authenticated_v6_input_identity"
    assert receipt["reuse_recovered_v6_inputs"] is False
    assert receipt["v6_historical_reproduction_confirmed"] is False
    assert receipt["missing_v6_dependency_layers"] == ["D0", "D1", "D2"]
    assert receipt["current_v7_baseline_authorized"] is False
    assert receipt["gates_required_to_remain_red"] == GATES_REMAINING_RED
    assert receipt["no_go_close_required"] is True
    assert receipt["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
        "provider_download_performed": False,
    }


def test_transition_selects_no_baseline_branch_without_greening_a_gate() -> None:
    manifest = _load(MANIFEST)
    assert manifest["transaction_id"] == "G2_CLOSE-7"
    assert manifest["gate_actions"] == []
    assert manifest["task_actions"][0]["task_id"] == "PREV7-0307"
    assert manifest["task_actions"][0]["target_status"] == "done"
    assert manifest["branch_actions"] == [
        {
            "branch_id": "V6_INPUT_IDENTITY",
            "task_id": "PREV7-0307",
            "selected_successor": "separate_reference_proposal_and_no_go_close",
            "predicate_evidence_digest": _load(PROPOSAL)["proposal_digest"],
            "decision_receipt_digest": _load(RECEIPT)["receipt_digest"],
        }
    ]
