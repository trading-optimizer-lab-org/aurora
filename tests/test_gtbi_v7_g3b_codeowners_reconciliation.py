from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.generate_gtbi_v7_g3b_codeowners_apply_reconciliation_receipt import (
    CODEOWNERS_COUNTS,
    CODEOWNERS_STATUS_COUNTS,
    DESTINATION,
    REMAINING_G3B_TASKS,
    SOURCE,
    build_receipt,
    validate_application,
)


def test_codeowners_apply_receipt_is_canonical_and_reconciled() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert SOURCE.read_bytes() == canonical_bytes(source) + b"\n"
    assert source["receipt_digest"] == domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )

    validation = validate_application()
    assert validation["append_only_readiness_history_preserved"] is True
    assert validation["remaining_g3b_tasks"] == list(REMAINING_G3B_TASKS)
    assert set(validation["current_remaining_g3b_tasks"]).issubset(REMAINING_G3B_TASKS)
    assert "PREV7-0207" not in validation["current_remaining_g3b_tasks"]

    expected = build_receipt()
    assert DESTINATION.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["post_apply_state"] == {
        "counts": CODEOWNERS_COUNTS,
        "task_status_counts": CODEOWNERS_STATUS_COUNTS,
        "completed_task_id": "PREV7-0203",
        "g3b_gate_status": "red",
        "g3b_blocking_reason": "required_tasks_not_done",
        "remaining_g3b_tasks": list(REMAINING_G3B_TASKS),
    }
    assert expected["verified_properties"] == {
        "append_only_readiness_history_preserved": True,
        "arbitrary_command_execution_supported": False,
        "exact_codeowners_projection_at_state_merge": True,
        "github_only": True,
        "locked_data_accessed": False,
        "owner_controlled": True,
        "scientific_work_performed": False,
        "state_merged": True,
    }


def test_codeowners_reconciliation_records_exact_closed_transition() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert source["task_actions_applied"] == [
        {"target_status": "done", "task_id": "PREV7-0203"}
    ]
    assert source["branch_actions_applied"] == []
    assert source["gate_actions_applied"] == []
    assert source["scientific_work_performed"] is False
    assert source["locked_data_accessed"] is False
