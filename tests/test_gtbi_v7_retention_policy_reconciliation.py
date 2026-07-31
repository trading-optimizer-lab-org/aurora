from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.generate_gtbi_v7_retention_policy_apply_reconciliation_receipt import (
    DESTINATION,
    SOURCE,
    build_receipt,
    validate_application,
)


def test_retention_policy_apply_is_reconciled_with_merged_state() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert SOURCE.read_bytes() == canonical_bytes(source) + b"\n"
    assert source["receipt_digest"] == domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )
    validation = validate_application()
    assert validation["append_only_retention_history_preserved"] is True
    expected = build_receipt()
    assert DESTINATION.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["post_apply_state"]["prev7_0301_status"] == "done"
    assert expected["post_apply_state"]["g2_gate_status"] == "red"
    assert expected["verified_properties"]["github_only"] is True
    assert expected["verified_properties"]["locked_data_accessed"] is False
    assert expected["verified_properties"]["scientific_work_performed"] is False
