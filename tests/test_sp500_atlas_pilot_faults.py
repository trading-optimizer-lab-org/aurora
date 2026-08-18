from __future__ import annotations

import hashlib

import pytest

from aurora.infra.sp500_megarun.atlas_pilot_faults import (
    ControllerLedger,
    deduplicate_receipts,
    run_fail_once_then_success,
    verify_artifact_hash,
)


def test_fail_once_is_retried_and_succeeds() -> None:
    calls = {"count": 0}

    def operation() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("controlled")
        return "ok"

    assert run_fail_once_then_success(operation) == "ok"
    assert calls["count"] == 2


def test_corrupt_artifact_is_rejected() -> None:
    payload = b"original"
    expected = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError, match="ATLAS_PILOT_ARTIFACT_HASH_INVALID"):
        verify_artifact_hash(b"corrupt", expected)


def test_identical_duplicate_is_kept_once_and_conflict_is_rejected() -> None:
    receipt = {"shard_index": 1, "result_sha256": "a" * 64, "plan_sha256": "p" * 64}
    selected, redundant = deduplicate_receipts([receipt, dict(receipt)])
    assert selected == [receipt]
    assert redundant == 1
    with pytest.raises(ValueError, match="ATLAS_PILOT_CONFLICTING_DUPLICATE"):
        deduplicate_receipts([receipt, {**receipt, "result_sha256": "b" * 64}])


def test_controller_success_is_idempotent() -> None:
    ledger = ControllerLedger()
    assert ledger.record_success("segment-0", "run-1") is True
    assert ledger.record_success("segment-0", "run-1") is False
    assert ledger.successful_run("segment-0") == "run-1"
