from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_v6_production_promotion import (
    RECEIPT,
    TRANSITION,
    build_receipt,
    build_transition_manifest,
)


def test_v6_production_promotion_receipt_is_canonical_and_complete() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt == build_receipt()
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_V6_PRODUCTION_PROMOTION_RESTORE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["promotion"]["production_registry_status"] == "canonical"
    assert receipt["promotion"]["republish_performed"] is False
    assert receipt["requires_local_machine"] is False
    assert receipt["maximum_incremental_net_spend_usd"] == 0
    assert len(receipt["clean_runner_restores"]) == 2
    assert {row["source"] for row in receipt["clean_runner_restores"]} == {
        "primary",
        "mirror",
    }
    assert all(row["conclusion"] == "success" for row in receipt["clean_runner_restores"])
    assert all(
        row["duration_seconds"] < row["rto_seconds"]
        for row in receipt["clean_runner_restores"]
    )
    assert receipt["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "validation_end": "2020-12-31",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
        "provider_download_performed": False,
    }


def test_v6_production_transition_is_controller_valid() -> None:
    receipt = build_receipt()
    transition = json.loads(TRANSITION.read_text(encoding="utf-8"))
    assert TRANSITION.read_bytes() == canonical_bytes(transition) + b"\n"
    assert transition == build_transition_manifest(receipt)
    validate_transition_manifest(transition)
    assert [row["task_id"] for row in transition["task_actions"]] == [
        "PREV7-0304",
        "PREV7-0305",
    ]
    assert transition["transaction_id"] == "G2_CLOSE-5"
    assert transition["gate_actions"] == []
