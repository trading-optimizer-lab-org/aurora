from __future__ import annotations

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from scripts.generate_gtbi_v7_reproducibility_apply_reconciliation_receipt import (
    DESTINATION,
    EXPECTED_COUNTS,
    EXPECTED_STATUS_COUNTS,
    build_receipt,
    validate_application,
)


def test_reproducibility_apply_is_reconciled_with_canonical_state() -> None:
    validation = validate_application()
    assert validation == {
        "historical_projection_verified": True,
        "task_status": "done",
    }
    expected = build_receipt()
    assert DESTINATION.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["post_apply_state"]["counts"] == EXPECTED_COUNTS
    assert expected["post_apply_state"]["task_status_counts"] == EXPECTED_STATUS_COUNTS
    assert expected["verified_properties"] == {
        "exact_projection_at_state_merge": True,
        "github_only": True,
        "locked_data_accessed": False,
        "scientific_work_performed": False,
        "state_merged": True,
    }
