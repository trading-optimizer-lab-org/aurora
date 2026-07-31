from __future__ import annotations

import json
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.generate_gtbi_v7_g3a_owner_auth_apply_reconciliation_receipt import (
    DESTINATION,
    OWNER_AUTH_COUNTS,
    OWNER_AUTH_STATUS_COUNTS,
    SOURCE,
    build_receipt,
    validate_application,
)


def test_owner_auth_apply_receipt_is_canonical_and_reconciled() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert SOURCE.read_bytes() == canonical_bytes(source) + b"\n"
    assert source["receipt_digest"] == domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )

    validation = validate_application()
    assert validation["append_only_owner_auth_history_preserved"] is True
    assert isinstance(validation["exact_owner_auth_projection"], bool)

    expected = build_receipt()
    assert DESTINATION.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["post_apply_state"]["counts"] == OWNER_AUTH_COUNTS
    assert (
        expected["post_apply_state"]["task_status_counts"]
        == OWNER_AUTH_STATUS_COUNTS
    )
    assert expected["post_apply_state"]["g3a_gate_status"] == "green"
    assert expected["post_apply_state"]["remaining_g3a_tasks"] == []
    assert expected["verified_properties"] == {
        "append_only_owner_auth_history_preserved": True,
        "arbitrary_command_execution_supported": False,
        "exact_owner_auth_projection_at_state_merge": True,
        "github_only": True,
        "locked_data_accessed": False,
        "owner_controlled": True,
        "scientific_work_performed": False,
        "state_merged": True,
    }


def test_owner_auth_reconciliation_uses_distinct_historical_files() -> None:
    root = Path(__file__).resolve().parents[1]
    assert SOURCE.name == "g3a_owner_auth_state_controller_apply_receipt.json"
    assert DESTINATION.name == (
        "g3a_owner_auth_state_transition_reconciliation_receipt.json"
    )
    assert SOURCE != root / "docs/readiness/gtbi-v7/g3a_state_controller_apply_receipt.json"
    assert DESTINATION != root / (
        "docs/readiness/gtbi-v7/g3a_state_transition_reconciliation_receipt.json"
    )
