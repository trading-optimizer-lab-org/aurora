from __future__ import annotations

import pytest


def _inventory(*, digest: str = "a" * 64, boundary: int = 0, conflicts: int = 0):
    return {
        "campaign_id": "campaign-1",
        "campaign_state": "searching",
        "code_commit_sha": "b" * 40,
        "validation_opened": False,
        "locked_opened": False,
        "boundary_violations": boundary,
        "conflict_count": conflicts,
        "database_size_bytes": 123,
        "tables": {"results": {"row_count": 2, "rows_sha256": digest}},
    }


def test_clone_verifier_accepts_exact_closed_boundary_copy():
    from aurora.infra.sp500_megarun.dehb_continuous_migration import (
        compare_clone_inventories,
    )

    report = compare_clone_inventories(_inventory(), _inventory())

    assert report["verified"] is True
    assert report["campaign_id"] == "campaign-1"
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert len(report["verification_sha256"]) == 64


@pytest.mark.parametrize(
    ("source", "target", "error"),
    [
        (_inventory(), _inventory(digest="c" * 64), "CLONE_TABLE_DIGEST_MISMATCH"),
        (_inventory(boundary=1), _inventory(boundary=1), "CLONE_BOUNDARY_OPENED"),
        (_inventory(conflicts=1), _inventory(conflicts=1), "CLONE_CONFLICT_PRESENT"),
    ],
)
def test_clone_verifier_fails_closed(source, target, error):
    from aurora.infra.sp500_megarun.dehb_continuous_migration import (
        ContinuousMigrationError,
        compare_clone_inventories,
    )

    with pytest.raises(ContinuousMigrationError, match=error):
        compare_clone_inventories(source, target)


def test_row_digest_is_order_sensitive_and_stable():
    from aurora.infra.sp500_megarun.dehb_continuous_migration import (
        canonical_rows_sha256,
    )

    assert canonical_rows_sha256(["one", "two"]) == canonical_rows_sha256(
        ["one", "two"]
    )
    assert canonical_rows_sha256(["one", "two"]) != canonical_rows_sha256(
        ["two", "one"]
    )
