from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.reconcile_gtbi_v7_master_execution import (
    DESTINATION,
    build_reconciliation,
)


def test_master_execution_reconciliation_is_canonical_and_reproducible() -> None:
    receipt = json.loads(DESTINATION.read_text(encoding="utf-8"))
    assert DESTINATION.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt == build_reconciliation()
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_MASTER_EXECUTION_RECONCILIATION_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )


def test_closed_v6_plan_is_not_confused_with_independent_v7() -> None:
    receipt = build_reconciliation()
    master = receipt["master_plan"]
    campaign = receipt["independent_new_reference_campaign"]
    assert master["v6_equivalent_terminal_state"] == "NO_GO_CLOSED"
    assert master["scientific_success"] is False
    assert campaign["status"] == "completed_historical_and_preserved"
    assert campaign["separate_from_v6"] is True
    assert campaign["v6_equivalence_claim_allowed"] is False
    assert campaign["terminal_strategy_identities"] == 72_000


def test_locked_and_local_execution_remain_prohibited() -> None:
    boundaries = build_reconciliation()["scientific_boundaries"]
    assert boundaries == {
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "locked_authorized": False,
        "locked_data_accessed": False,
        "github_only": True,
        "requires_local_machine": False,
        "maximum_incremental_net_spend_usd": 0,
    }


def test_formal_projection_remains_honest_after_terminal_no_go() -> None:
    projection = build_reconciliation()["formal_projection"]
    assert projection["task_count"] == 110
    assert projection["task_counts"] == {
        "done": 32,
        "cancelled": 1,
        "blocked": 77,
    }
    assert projection["gate_count"] == 15
    assert projection["gate_counts"] == {"green": 4, "red": 11}
    assert projection["terminal_no_go_does_not_green_pending_gates"] is True
