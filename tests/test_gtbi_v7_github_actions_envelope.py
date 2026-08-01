from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_github_actions_envelope import (
    RECEIPT,
    TRANSITION,
    build_receipt,
    build_transition_manifest,
)


def test_github_actions_envelope_is_canonical_and_zero_cost() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt == build_receipt()
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_GITHUB_ACTIONS_ENVELOPE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["repository_visibility"] == "public"
    assert receipt["acceptable_use_decision"]["status"] == (
        "approved_by_repository_owner"
    )
    assert receipt["capacity_topology"]["maximum_concurrent_jobs"] == 360
    assert receipt["capacity_sources"]["observed_run"]["peak_concurrent_jobs"] == 360
    assert receipt["billing_envelope"]["maximum_incremental_net_spend_usd"] == 0
    assert receipt["billing_envelope"]["maximum_billable_runner_minutes"] == 0
    assert receipt["capacity_topology"]["larger_runners_allowed"] is False
    assert receipt["capacity_topology"]["self_hosted_runners_allowed"] is False
    assert receipt["capacity_topology"]["local_machine_allowed"] is False
    assert receipt["scientific_boundaries"] == {
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
    }


def test_github_actions_envelope_transition_is_controller_valid() -> None:
    receipt = build_receipt()
    transition = json.loads(TRANSITION.read_text(encoding="utf-8"))
    assert TRANSITION.read_bytes() == canonical_bytes(transition) + b"\n"
    assert transition == build_transition_manifest(receipt)
    validate_transition_manifest(transition)
    assert [row["task_id"] for row in transition["task_actions"]] == [
        "PREV7-0309"
    ]
    assert transition["branch_actions"] == [
        {
            "branch_id": "CAPACITY_TOPOLOGY",
            "task_id": "PREV7-0309",
            "predicate_evidence_digest": receipt["receipt_digest"],
            "selected_successor": "owner_controlled_public_standard_360",
            "decision_receipt_digest": receipt["receipt_digest"],
        }
    ]
    assert transition["gate_actions"] == []
