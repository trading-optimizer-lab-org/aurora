from __future__ import annotations

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from scripts.generate_gtbi_v7_g2_closure_reconciliation import (
    DESTINATION,
    TRANSITIONS,
    build_receipt,
    validate_application,
)


def test_g2_closure_transitions_are_reconciled_with_canonical_state() -> None:
    validation = validate_application()
    assert len(validation["reconciled"]) == 4
    assert sum(len(item["tasks"]) for item in validation["reconciled"]) == 5
    expected = build_receipt()
    assert DESTINATION.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["verified_properties"] == {
        "all_five_tasks_done": True,
        "controller_receipts_digest_verified": True,
        "event_chains_verified": True,
        "github_only_controller": True,
        "locked_data_accessed": False,
        "scientific_work_performed": False,
        "no_baseline_branch_selected": True,
        "no_go_close_required": True,
    }
    assert {item["manifest_id"] for item in TRANSITIONS} == {
        "g2-scientific-asset-contract-v1",
        "g2-v6-production-promotion-restore-v1",
        "g2-github-actions-envelope-v1",
        "g2-v6-input-identity-no-baseline-v1",
    }
