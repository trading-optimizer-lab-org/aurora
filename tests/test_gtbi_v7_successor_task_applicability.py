from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.generate_gtbi_v7_successor_task_applicability import (
    DESTINATION,
    REMAINING_APPLICABLE,
    build_applicability,
)


def test_successor_task_applicability_is_complete_and_reproducible() -> None:
    payload = build_applicability()
    assert len(payload["tasks"]) == 110
    assert len({row["task_id"] for row in payload["tasks"]}) == 110
    assert payload["remaining_task_ids"] == sorted(REMAINING_APPLICABLE)
    assert payload["receipt_digest"] == domain_digest(
        "GTBI_V7_SUCCESSOR_TASK_APPLICABILITY_V1",
        payload,
        omit_top_level_fields=("receipt_digest",),
    )


def test_successor_ledger_preserves_historical_registry() -> None:
    payload = build_applicability()
    assert payload["historical_task_registry"]["immutable"] is True
    assert payload["classification_policy"] == {
        "historical_task_status_mutated": False,
        "no_task_may_disappear": True,
        "retired_requirements_do_not_block_successor": True,
        "conditional_unselected_tasks_do_not_block_successor": True,
        "only_remaining_applicable_blocks_completed_clean": True,
    }
    historical = [
        row
        for row in payload["tasks"]
        if row["historical_status"] in {"done", "cancelled"}
    ]
    assert len(historical) == 33
    assert {row["successor_status"] for row in historical} == {"historical_terminal"}


def test_successor_ledger_keeps_scientific_boundaries_closed() -> None:
    assert build_applicability()["scientific_boundaries"] == {
        "github_only": True,
        "requires_local_machine": False,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "locked_authorized": False,
        "locked_data_accessed": False,
        "maximum_incremental_net_spend_usd": 0,
    }


def test_generated_successor_ledger_matches_builder() -> None:
    recorded = json.loads(DESTINATION.read_text(encoding="utf-8"))
    assert DESTINATION.read_bytes() == canonical_bytes(recorded) + b"\n"
    assert recorded == build_applicability()
