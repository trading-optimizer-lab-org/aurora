from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.generate_gtbi_v7_reproducibility_classification import (
    MANIFEST,
    RECEIPT,
    build_receipt,
    build_transition_manifest,
)


def test_reproducibility_classification_is_canonical_and_evidence_backed() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt == build_receipt()
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_REPRODUCIBILITY_CLASSIFICATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["classification"] == "result_preserved_inputs_incomplete"
    assert receipt["authenticated_layers"] == ["C", "D3", "S", "R"]
    assert receipt["missing_layers"] == ["D0", "D1", "D2"]
    assert receipt["full_v6_reproduction_claim_allowed"] is False
    assert receipt["reuse_recovered_v6_inputs"] is False
    assert receipt["v6_historical_reproduction_confirmed"] is False
    assert receipt["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
    }


def test_reproducibility_transition_closes_only_prev7_0306() -> None:
    receipt = build_receipt()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert manifest == build_transition_manifest(receipt)
    assert manifest["manifest_digest"] == domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    assert len(manifest["task_actions"]) == 1
    assert manifest["task_actions"][0]["task_id"] == "PREV7-0306"
    assert manifest["task_actions"][0]["target_status"] == "done"
    assert manifest["branch_actions"] == []
    assert manifest["gate_actions"] == []
