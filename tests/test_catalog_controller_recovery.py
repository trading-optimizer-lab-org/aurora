from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    TerminalState,
)
from aurora.infra.github_performance.recovery import (
    AuthorityRecoverySnapshot,
    CheckpointSlotEvidence,
    FailureClass,
    RecoveryEvidenceError,
    RecoveryLoopStatus,
    build_recovery_loop,
    decide_watchdog_reentry,
    failure_fingerprint,
    plan_retry_timing,
    reconcile_expected_artifacts,
    validate_checkpoint_slot_chain,
)
from github_performance_helpers import failed_attempt, make_shard


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _completed_attempt(index: int) -> AttemptManifest:
    shard_id = f"s{index:03d}"
    return AttemptManifest(
        shard_id=shard_id,
        attempt_id=f"a-{index:03d}",
        state=TerminalState.COMPLETED,
        spec_hash="1" * 64,
        policy_hash="2" * 64,
        snapshot_hash="3" * 64,
        code_sha="4" * 40,
        dependency_lock_sha256="5" * 64,
        capacity_profile_sha256="6" * 64,
        output_sha256="7" * 64,
        reason_code=None,
        artifact_name=f"result-{shard_id}",
        unit_attempts_path="unit_attempts.parquet",
        unit_attempts_sha256="8" * 64,
        checkpoint_artifact=None,
        completed_unit_count=1,
        output_rows=1,
        output_bytes=100,
        runtime_access_ledger_path="runtime_access_ledger.parquet",
        runtime_access_ledger_sha256="9" * 64,
        metric_inputs_path="metric_inputs.parquet",
        metric_inputs_sha256="a" * 64,
    )


def test_dynamic_noise_does_not_change_failure_fingerprint() -> None:
    first = failure_fingerprint(
        failure_class=FailureClass.TRANSIENT_NETWORK,
        reason_code="CONNECTION_RESET",
        stage="recipe_worker",
        logical_scope_id="strategy-00042",
        exit_code=1,
        exception_type="ConnectionResetError",
        normalized_frame="aurora/catalog/worker.py:run_unit",
        message="connection reset at 12:01; run 111; attempt a-1",
    )
    second = failure_fingerprint(
        failure_class=FailureClass.TRANSIENT_NETWORK,
        reason_code="connection-reset",
        stage="RECIPE WORKER",
        logical_scope_id="strategy-00042",
        exit_code=1,
        exception_type="ConnectionResetError",
        normalized_frame="C:/agent/_work/aurora/catalog/worker.py:run_unit",
        message="connection reset at 12:09; run 222; attempt a-2",
    )
    assert first == second


def test_different_logical_scope_has_an_independent_retry_budget() -> None:
    left = failure_fingerprint(
        failure_class=FailureClass.RUNNER_LOST,
        reason_code="RUNNER_LOST",
        stage="recipe_worker",
        logical_scope_id="strategy-a",
    )
    right = failure_fingerprint(
        failure_class=FailureClass.RUNNER_LOST,
        reason_code="RUNNER_LOST",
        stage="recipe_worker",
        logical_scope_id="strategy-b",
    )
    assert left != right


@pytest.mark.parametrize(
    ("occurrences", "expected_status", "expected_retry_count"),
    [
        (1, RecoveryLoopStatus.RETRY, 1),
        (2, RecoveryLoopStatus.RETRY, 1),
        (3, RecoveryLoopStatus.BLOCKED_HARD_FAILURE, 0),
    ],
)
def test_same_scoped_failure_has_exactly_two_retries(
    occurrences: int,
    expected_status: RecoveryLoopStatus,
    expected_retry_count: int,
) -> None:
    attempts = [
        failed_attempt("s001", f"attempt-{index}", "CONNECTION_RESET")
        for index in range(1, occurrences + 1)
    ]
    result = build_recovery_loop(
        [make_shard(1)],
        attempts,
        [],
        {"transient_network": 2},
        current_wave=occurrences - 1,
        max_waves=6,
    )
    assert result.status is expected_status
    assert result.retry_count == expected_retry_count
    assert result.plan.failure_occurrence_count == occurrences
    if occurrences == 3:
        assert result.reason_codes == ("SAME_FAILURE_OCCURRENCE_LIMIT",)
        assert result.plan.retry_matrix_a == ()
        assert result.plan.retry_matrix_b == ()


def test_359_successful_shards_schedule_only_one_failed_scope() -> None:
    shards = [make_shard(index) for index in range(360)]
    attempts = [_completed_attempt(index) for index in range(359)]
    attempts.append(failed_attempt("s359", "attempt-1", "RUNNER_LOST"))
    result = build_recovery_loop(
        shards,
        attempts,
        [],
        {"runner_lost": 2},
        current_wave=0,
        max_waves=6,
    )
    descriptors = (*result.plan.retry_matrix_a, *result.plan.retry_matrix_b)
    assert result.terminal_shard_count == 359
    assert result.retry_count == 1
    assert [row["shard_id"] for row in descriptors] == ["s359"]
    assert not ({f"s{index:03d}" for index in range(359)} & {"s359"})


def test_deterministic_code_failure_never_retries() -> None:
    result = build_recovery_loop(
        [make_shard(1)],
        [failed_attempt("s001", "attempt-1", "DETERMINISTIC_CODE_ERROR")],
        [],
        {"code": 2},
        current_wave=0,
        max_waves=6,
    )
    assert result.status is RecoveryLoopStatus.BLOCKED_HARD_FAILURE
    assert result.retry_count == 0
    assert result.plan.retry_matrix_a == ()
    assert result.plan.retry_matrix_b == ()


def test_missing_attempt_without_platform_proof_never_assumes_runner_loss() -> None:
    result = build_recovery_loop(
        [make_shard(1)],
        [],
        [],
        {"runner_lost": 2},
        current_wave=0,
        max_waves=6,
    )
    assert result.status is RecoveryLoopStatus.BLOCKED_HARD_FAILURE
    assert result.retry_count == 0
    assert result.reason_codes == ("RECOVERY_FAILURE_EVIDENCE_MISSING",)


def _slot(index: int, previous: str, current: str) -> CheckpointSlotEvidence:
    return CheckpointSlotEvidence(
        logical_scope_id="worker:7",
        slot_index=index,
        slot_count=8,
        artifact_name=f"checkpoint-worker-7-slot-{index}",
        previous_receipt_sha256=previous,
        receipt_sha256=current,
        artifact_uploaded=True,
    )


def test_slot_seven_checkpoint_reuses_one_through_seven() -> None:
    slots: list[CheckpointSlotEvidence] = []
    previous = "0" * 64
    for index in range(1, 8):
        current = f"{index:x}" * 64
        slots.append(_slot(index, previous, current))
        previous = current
    chain = validate_checkpoint_slot_chain(
        slots,
        logical_scope_id="worker:7",
        expected_slot_count=8,
    )
    assert chain.completed_slot_count == 7
    assert chain.next_slot_index == 8
    assert chain.reused_artifacts == tuple(
        f"checkpoint-worker-7-slot-{index}" for index in range(1, 8)
    )


@pytest.mark.parametrize("mutation", ["missing", "broken", "duplicate", "unuploaded"])
def test_invalid_checkpoint_chain_is_never_partially_trusted(mutation: str) -> None:
    first = _slot(1, "0" * 64, "1" * 64)
    second = _slot(2, "1" * 64, "2" * 64)
    slots = [first, second]
    if mutation == "missing":
        slots = [second]
    elif mutation == "broken":
        slots[1] = _slot(2, "f" * 64, "2" * 64)
    elif mutation == "duplicate":
        slots.append(second)
    else:
        slots[1] = second.model_copy(update={"artifact_uploaded": False})
    with pytest.raises(RecoveryEvidenceError):
        validate_checkpoint_slot_chain(
            slots,
            logical_scope_id="worker:7",
            expected_slot_count=8,
        )


def test_artifact_download_failure_cannot_be_treated_as_an_empty_valid_set() -> None:
    with pytest.raises(RecoveryEvidenceError, match="DOWNLOAD_FAILED"):
        reconcile_expected_artifacts(
            expected=("attempt-a",),
            observed=(),
            download_outcome="failure",
        )
    with pytest.raises(RecoveryEvidenceError, match="SET_MISMATCH"):
        reconcile_expected_artifacts(
            expected=("attempt-a",),
            observed=(),
            download_outcome="success",
        )


def test_six_total_recovery_waves_without_completion_block() -> None:
    result = build_recovery_loop(
        [make_shard(1)],
        [failed_attempt("s001", "attempt-1", "RUNNER_LOST")],
        [],
        {"runner_lost": 2},
        current_wave=5,
        max_waves=6,
    )
    assert result.status is RecoveryLoopStatus.BLOCKED_HARD_FAILURE
    assert result.retry_count == 0
    assert result.reason_codes == ("RECOVERY_WAVE_BUDGET_EXHAUSTED",)


def test_long_retry_delay_releases_runner_and_short_delay_does_not() -> None:
    short = plan_retry_timing(
        now=NOW,
        failure_occurrence_count=1,
        retry_after_seconds=30,
    )
    long = plan_retry_timing(
        now=NOW,
        failure_occurrence_count=1,
        retry_after_seconds=300,
    )
    assert short.action == "retry_now"
    assert short.retry_not_before is None
    assert long.action == "waiting_retry"
    assert long.retry_not_before == NOW + timedelta(seconds=300)


def _authority(**updates: object) -> AuthorityRecoverySnapshot:
    values: dict[str, object] = {
        "authority_id": "authority-1",
        "request_issue_number": 42,
        "state": "waiting_retry",
        "retry_not_before": NOW - timedelta(seconds=1),
        "owner_run_state": "completed",
        "latest_failure_class": FailureClass.RUNNER_LOST,
        "engine_started": True,
        "valid_checkpoint_count": 1,
        "evidence_complete": True,
        "current_protocol_sha256": "1" * 64,
        "authority_protocol_sha256": "1" * 64,
        "external_cancellation_proven_transient": False,
    }
    values.update(updates)
    return AuthorityRecoverySnapshot.model_validate(values)


def test_watchdog_without_authority_schedules_nothing() -> None:
    decision = decide_watchdog_reentry((), now=NOW)
    assert decision.action == "noop"
    assert decision.issue_numbers == ()


def test_watchdog_waits_for_due_time_and_active_owner() -> None:
    early = decide_watchdog_reentry(
        (_authority(retry_not_before=NOW + timedelta(minutes=5)),),
        now=NOW,
    )
    active = decide_watchdog_reentry(
        (_authority(owner_run_state="in_progress"),),
        now=NOW,
    )
    assert early.action == "noop"
    assert active.action == "noop"


def test_watchdog_reenters_only_the_existing_due_authority() -> None:
    first = decide_watchdog_reentry((_authority(),), now=NOW)
    second = decide_watchdog_reentry(
        (_authority(),),
        now=NOW,
        claimed_authority_ids=("authority-1",),
    )
    assert first.action == "call_controller"
    assert first.issue_numbers == (42,)
    assert second.action == "noop"


def test_watchdog_blocks_protocol_or_actions_ambiguity() -> None:
    mismatch = decide_watchdog_reentry(
        (_authority(current_protocol_sha256="2" * 64),),
        now=NOW,
    )
    ambiguous = decide_watchdog_reentry(
        (_authority(evidence_complete=False),),
        now=NOW,
    )
    assert mismatch.action == "blocked"
    assert mismatch.reason_codes == ("CATALOG_RECOVERY_PROTOCOL_MISMATCH",)
    assert ambiguous.action == "blocked"
    assert ambiguous.reason_codes == ("CATALOG_WATCHDOG_EVIDENCE_AMBIGUOUS",)
