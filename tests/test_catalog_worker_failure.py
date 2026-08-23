from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aurora.infra.github_performance.recovery import FailureClass
from aurora.infra.sp500_megarun.catalog_worker_failure import (
    CatalogWorkerFailureReceiptV1,
    build_catalog_worker_failure_receipt,
    classify_worker_exception,
    decide_catalog_worker_recovery,
    worker_failure_artifact_name,
)
from scripts.run_catalog_recipe_worker_guarded import execute_guarded


NOW = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
PLAN = "1" * 64
COMMIT = "2" * 40


def _receipt(
    *,
    worker_id: int = 7,
    attempt: int = 1,
    reason_code: str = "CONNECTION_RESET",
    created_at: datetime | None = None,
    retry_after_seconds: int | None = None,
) -> CatalogWorkerFailureReceiptV1:
    return build_catalog_worker_failure_receipt(
        authority_id="authority-1",
        campaign_id="campaign-1",
        execution_plan_sha256=PLAN,
        protected_commit_sha=COMMIT,
        worker_id=worker_id,
        attempt_id=f"authority-1:worker:{worker_id:03d}:attempt:{attempt}",
        stage="recipe_worker",
        reason_code=reason_code,
        exit_code=1,
        exception_type="ConnectionResetError",
        normalized_frame="scripts/run_sp500_optimized_recipe_worker.py:main",
        retry_after_seconds=retry_after_seconds,
        created_at=created_at or NOW + timedelta(seconds=attempt),
    )


def test_failure_receipt_is_content_hashed_and_attempt_artifact_is_unique() -> None:
    receipt = _receipt()
    parsed = CatalogWorkerFailureReceiptV1.model_validate_json(
        receipt.model_dump_json()
    )
    assert parsed.failure_class is FailureClass.TRANSIENT_NETWORK
    assert worker_failure_artifact_name(
        execution_plan_sha256=PLAN,
        worker_id=7,
        attempt_id=receipt.attempt_id,
    ).startswith("catalog-failure-attempt-1111111111111111-007-")
    tampered = json.loads(receipt.model_dump_json())
    tampered["reason_code"] = "OUT_OF_MEMORY"
    with pytest.raises(ValueError):
        CatalogWorkerFailureReceiptV1.model_validate(tampered)


def test_missing_failure_evidence_blocks_instead_of_assuming_runner_loss() -> None:
    plan = decide_catalog_worker_recovery(
        expected_worker_ids=(0,),
        completed_worker_ids=(),
        failure_receipts=(),
        current_wave=0,
        max_waves=6,
        now=NOW,
    )
    assert plan.status == "blocked"
    assert plan.decisions[0].reason_code == "RECOVERY_FAILURE_EVIDENCE_MISSING"
    assert plan.decisions[0].failure_class is FailureClass.UNKNOWN


def test_only_two_same_fingerprint_retries_are_permitted() -> None:
    first = decide_catalog_worker_recovery(
        expected_worker_ids=(7,),
        completed_worker_ids=(),
        failure_receipts=(_receipt(attempt=1),),
        current_wave=0,
        max_waves=6,
        now=NOW + timedelta(minutes=1),
    )
    second = decide_catalog_worker_recovery(
        expected_worker_ids=(7,),
        completed_worker_ids=(),
        failure_receipts=(_receipt(attempt=1), _receipt(attempt=2)),
        current_wave=1,
        max_waves=6,
        now=NOW + timedelta(minutes=1),
    )
    third = decide_catalog_worker_recovery(
        expected_worker_ids=(7,),
        completed_worker_ids=(),
        failure_receipts=(
            _receipt(attempt=1),
            _receipt(attempt=2),
            _receipt(attempt=3),
        ),
        current_wave=2,
        max_waves=6,
        now=NOW + timedelta(minutes=1),
    )
    assert (first.status, second.status) == ("retry", "retry")
    assert third.status == "blocked"
    assert third.failure_occurrence_count == 3
    assert third.failure_reason_code == "SAME_FAILURE_OCCURRENCE_LIMIT"


def test_long_retry_after_releases_the_runner() -> None:
    plan = decide_catalog_worker_recovery(
        expected_worker_ids=(7,),
        completed_worker_ids=(),
        failure_receipts=(_receipt(retry_after_seconds=300),),
        current_wave=0,
        max_waves=6,
        now=NOW,
    )
    assert plan.status == "waiting_retry"
    assert plan.retry_not_before == NOW + timedelta(seconds=300)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (MemoryError(), "OUT_OF_MEMORY"),
        (OSError(28, "disk full"), "DISK_EXHAUSTED"),
        (ConnectionResetError(), "CONNECTION_RESET"),
        (SystemExit("RECIPE_ASSIGNMENT_SCHEMA_INVALID"), "SCHEMA_MISMATCH"),
        (RuntimeError("bug"), "DETERMINISTIC_CODE_ERROR"),
    ],
)
def test_caught_worker_errors_use_only_closed_failure_classes(
    error: BaseException,
    reason: str,
) -> None:
    assert classify_worker_exception(error)[0] == reason


def test_guarded_worker_writes_failure_receipt_and_preserves_nonzero_exit(
    tmp_path: Path,
) -> None:
    output = tmp_path / "failure.json"

    def fail(_: object) -> int:
        raise ConnectionResetError("dynamic run 123")

    result = execute_guarded(
        [
            "--failure-receipt",
            str(output),
            "--authority-id",
            "authority-1",
            "--campaign-id",
            "campaign-1",
            "--execution-plan-sha256",
            PLAN,
            "--protected-commit-sha",
            COMMIT,
            "--worker-id",
            "7",
            "--attempt-id",
            "authority-1:worker:007:attempt:1",
            "--",
            "--unused-worker-arg",
        ],
        run_worker=fail,
        created_at=NOW,
    )
    receipt = CatalogWorkerFailureReceiptV1.model_validate_json(
        output.read_text("utf-8")
    )
    assert result == 1
    assert receipt.reason_code == "CONNECTION_RESET"
    assert receipt.validation_opened is False
    assert receipt.locked_opened is False
