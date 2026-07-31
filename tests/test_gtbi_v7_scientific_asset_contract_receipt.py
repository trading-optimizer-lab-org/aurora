from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_scientific_asset_contract_receipt import (
    MANIFEST,
    RECEIPT,
    build_receipt,
    build_transition_manifest,
)


def test_scientific_asset_contract_receipt_is_canonical_and_complete() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt == build_receipt()
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_SCIENTIFIC_ASSET_CONTRACT_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["closed_schema"] is True
    assert receipt["all_fields_required"] is True
    assert receipt["fixture_lifecycle_state"] == "wrapper_only"
    assert receipt["nullability_validated"] is True
    assert receipt["immutable_wrapper_validated"] is True
    assert receipt["scientific_boundaries"]["locked_start"] == "2021-01-01"
    assert receipt["scientific_boundaries"]["locked_data_accessed"] is False
    assert receipt["scientific_boundaries"]["scientific_processing_performed"] is False


def test_scientific_asset_contract_transition_is_controller_valid() -> None:
    receipt = build_receipt()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert manifest == build_transition_manifest(receipt)
    validate_transition_manifest(manifest)
    assert [action["task_id"] for action in manifest["task_actions"]] == [
        "PREV7-0303"
    ]
    assert manifest["branch_actions"] == []
    assert manifest["gate_actions"] == []
