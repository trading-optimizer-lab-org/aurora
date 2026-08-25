from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance.checkpoint import (
    CheckpointIntegrityError,
    CheckpointManager,
    load_checkpoint,
)
from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    CheckpointManifest,
    TerminalState,
    UnitAttemptRecord,
)
from aurora.infra.github_performance.merge_planner import (
    write_unit_attempt_manifest,
)
from aurora.infra.github_performance.recovery import (
    FailureClass,
    RecoveryEvidenceError,
    RecoveryLoopStatus,
    build_recovery_plan,
    build_recovery_plan_from_paths,
    build_recovery_loop,
    build_terminal_unit_evidence_from_paths,
    failure_fingerprint,
    write_recovery_plan,
)
from aurora.infra.github_performance.shard_planner import sha256_file
from github_performance_helpers import failed_attempt, make_shard
from github_performance_helpers import minimal_valid_spec, write_yaml


def test_checkpoint_manifest_is_published_after_payload(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "rows.parquet"
    payload.write_bytes(b"valid")
    manager = CheckpointManager(tmp_path / "checkpoint")
    manifest = manager.commit("s001", "a001", 12, "u0012", payload)
    loaded = load_checkpoint(
        tmp_path / "checkpoint" / "checkpoint_manifest.json"
    )
    assert loaded == manifest
    assert Path(loaded.payload_path).is_absolute() is False
    stored_payload = tmp_path / "checkpoint" / loaded.payload_path
    assert sha256_file(stored_payload) == loaded.payload_sha256


def test_transient_failure_retries_with_new_attempt_id() -> None:
    plan = build_recovery_plan(
        [make_shard(1)],
        [failed_attempt("s001", "a001", "GITHUB_5XX")],
        [],
        {"github_5xx": 3},
    )
    decision = plan.decisions[0]
    assert decision.action == "retry"
    assert decision.next_attempt_id != decision.prior_attempt_id


@pytest.mark.parametrize(
    ("reason", "expected_action"),
    [
        ("SCHEMA_MISMATCH", "do_not_retry"),
        ("POLICY_VIOLATION", "do_not_retry"),
        ("DETERMINISTIC_CODE_ERROR", "do_not_retry"),
        ("OUT_OF_MEMORY", "replan"),
        ("DISK_EXHAUSTED", "replan"),
    ],
)
def test_non_transient_failures_are_not_retried_identically(
    reason: str,
    expected_action: str,
) -> None:
    plan = build_recovery_plan(
        [make_shard(1)],
        [failed_attempt("s001", "a001", reason)],
        [],
        {"runner_lost": 2},
    )
    assert plan.decisions[0].action == expected_action


def test_retry_budget_exhaustion_stops_retry() -> None:
    attempts = [
        failed_attempt("s001", "a001", "GITHUB_5XX"),
        failed_attempt("s001", "a002", "GITHUB_5XX"),
    ]
    plan = build_recovery_plan(
        [make_shard(1)],
        attempts,
        [],
        {"github_5xx": 1},
    )
    assert plan.decisions[0].action == "do_not_retry"
    assert plan.decisions[0].reason_code == "RETRY_BUDGET_EXHAUSTED"


def test_retry_budget_is_not_reset_by_another_reason_in_same_transient_class() -> None:
    attempts = [
        failed_attempt("s001", "a001", "CONNECTION_RESET"),
        failed_attempt("s001", "a002", "NETWORK_TIMEOUT"),
        failed_attempt("s001", "a003", "CONNECTION_RESET"),
    ]

    plan = build_recovery_plan(
        [make_shard(1)],
        attempts,
        [],
        {"transient_network": 2},
    )

    assert plan.decisions[0].action == "do_not_retry"
    assert plan.decisions[0].reason_code == "RETRY_BUDGET_EXHAUSTED"


def test_duplicate_transient_attempt_evidence_is_not_counted_twice() -> None:
    attempt = failed_attempt("s001", "a001", "GITHUB_5XX")

    plan = build_recovery_plan(
        [make_shard(1)],
        [attempt, attempt],
        [],
        {"github_5xx": 1},
    )

    assert plan.decisions[0].action == "retry"
    assert plan.failure_occurrence_count == 1


def test_recovery_never_reuses_an_existing_transient_attempt_id() -> None:
    fingerprint = failure_fingerprint(
        failure_class=FailureClass.GITHUB_5XX,
        reason_code="GITHUB_5XX",
        stage="recipe_worker",
        logical_scope_id="s001",
    )
    prior_id = f"recovery-2-{fingerprint[:20]}"

    plan = build_recovery_plan(
        [make_shard(1)],
        [failed_attempt("s001", prior_id, "GITHUB_5XX")],
        [],
        {"github_5xx": 2},
    )

    assert plan.decisions[0].next_attempt_id not in {prior_id}


def test_recovery_blocks_when_one_shard_is_hard_failed_even_if_another_retries() -> None:
    result = build_recovery_loop(
        [make_shard(1), make_shard(2)],
        [
            failed_attempt("s001", "a001", "GITHUB_5XX"),
            failed_attempt("s002", "a001", "DETERMINISTIC_CODE_ERROR"),
        ],
        [],
        {"github_5xx": 2, "code": 2},
        current_wave=0,
        max_waves=4,
    )

    assert result.status is RecoveryLoopStatus.BLOCKED_HARD_FAILURE
    assert result.retry_count == 0


def test_corrupt_checkpoint_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "rows.parquet"
    payload.write_bytes(b"valid")
    manager = CheckpointManager(tmp_path / "checkpoint")
    manifest = manager.commit("s001", "a001", 12, "u0012", payload)
    stored_payload = tmp_path / "checkpoint" / manifest.payload_path
    stored_payload.write_bytes(b"tampered")
    with pytest.raises(CheckpointIntegrityError, match="sha256"):
        load_checkpoint(
            tmp_path / "checkpoint" / "checkpoint_manifest.json"
        )


def test_regressing_checkpoint_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "rows.parquet"
    payload.write_bytes(b"valid")
    manager = CheckpointManager(tmp_path / "checkpoint")
    manager.commit("s001", "a001", 12, "u0012", payload)
    with pytest.raises(CheckpointIntegrityError, match="regressed"):
        manager.commit("s001", "a002", 11, "u0011", payload)


def test_recovery_matrices_respect_github_limits() -> None:
    shards = [make_shard(index) for index in range(360)]
    attempts = [
        failed_attempt(
            shard.shard_id,
            f"a{index:03d}",
            "RUNNER_LOST",
        )
        for index, shard in enumerate(shards)
    ]
    plan = build_recovery_plan(
        shards,
        attempts,
        [],
        {"runner_lost": 2},
    )
    assert len(plan.retry_matrix_a) == 256
    assert len(plan.retry_matrix_b) == 104
    assert plan.has_retry_matrix_a is True
    assert plan.has_retry_matrix_b is True


def test_verified_checkpoint_is_selected_for_resume() -> None:
    checkpoint = CheckpointManifest(
        shard_id="s001",
        attempt_id="a001",
        artifact_name="run-checkpoint-s001-a001",
        completed_unit_count=12,
        last_completed_unit_key="u0012",
        payload_path="rows.parquet",
        payload_sha256="9" * 64,
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    plan = build_recovery_plan(
        [make_shard(1)],
        [failed_attempt("s001", "a001", "RUNNER_LOST")],
        [checkpoint],
        {"runner_lost": 2},
    )
    assert plan.decisions[0].checkpoint_artifact == (
        "run-checkpoint-s001-a001"
    )


def test_zero_retry_plan_still_writes_all_outputs(tmp_path: Path) -> None:
    plan = build_recovery_plan(
        [],
        [],
        [],
        {"runner_lost": 2},
    )
    paths = write_recovery_plan(plan, tmp_path)
    assert {path.name for path in paths} == {
        "recovery_plan.json",
        "retry_matrix_a.json",
        "retry_matrix_b.json",
        "checkpoint_audit.parquet",
    }
    assert plan.has_retry_matrix_a is False
    assert plan.has_retry_matrix_b is False
    assert (tmp_path / "retry_matrix_a.json").read_text().strip() == (
        '{"include":[]}'
    )
    assert (tmp_path / "retry_matrix_b.json").read_text().strip() == (
        '{"include":[]}'
    )


def test_corrupt_checkpoint_is_rejected_without_blocking_recovery(
    tmp_path: Path,
) -> None:
    shard = make_shard(1)
    shard_plan = {
        "selected_jobs": 1,
        "work_unit_manifest_sha256": "1" * 64,
        "assignment_artifact": "run-assignment-bundle",
        "assignment_manifest_sha256": "2" * 64,
        "shards": [shard.model_dump(mode="json")],
        "plan_sha256": "3" * 64,
    }
    shard_plan_path = tmp_path / "shard_plan.json"
    shard_plan_path.write_text(json.dumps(shard_plan), encoding="utf-8")
    attempt = failed_attempt("s001", "a001", "RUNNER_LOST")
    attempt_path = tmp_path / "attempt.json"
    attempt_path.write_text(attempt.model_dump_json(), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint_manifest.json"
    checkpoint_path.write_text("{broken", encoding="utf-8")
    spec = minimal_valid_spec()
    spec["retries"]["runner_lost"] = 2
    spec_path = write_yaml(tmp_path / "spec.yaml", spec)

    plan = build_recovery_plan_from_paths(
        shard_plan_path,
        [attempt_path],
        [checkpoint_path],
        spec_path,
    )

    assert plan.decisions[0].action == "retry"
    assert plan.decisions[0].checkpoint_artifact is None
    assert plan.checkpoint_audit[0].status == "rejected"
    assert plan.checkpoint_audit[0].reason_code == (
        "CHECKPOINT_INTEGRITY_ERROR"
    )


def _completed_attempt(shard_id: str, attempt_id: str) -> AttemptManifest:
    return AttemptManifest(
        shard_id=shard_id,
        attempt_id=attempt_id,
        state=TerminalState.COMPLETED,
        spec_hash="1" * 64,
        policy_hash="2" * 64,
        snapshot_hash="3" * 64,
        code_sha="4" * 40,
        dependency_lock_sha256="5" * 64,
        capacity_profile_sha256="6" * 64,
        output_sha256="7" * 64,
        reason_code=None,
        artifact_name=f"artifact-{shard_id}-{attempt_id}",
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


def test_recovery_loop_retries_repeated_transient_waves() -> None:
    shard = make_shard(1)
    first = build_recovery_loop(
        [shard],
        [failed_attempt("s001", "a001", "GITHUB_5XX")],
        [],
        {"github_5xx": 3},
        current_wave=0,
        max_waves=4,
    )
    second_attempt = first.plan.decisions[0].next_attempt_id
    assert second_attempt is not None
    second = build_recovery_loop(
        [shard],
        [
            failed_attempt("s001", "a001", "GITHUB_5XX"),
            failed_attempt("s001", second_attempt, "GITHUB_5XX"),
        ],
        [],
        {"github_5xx": 3},
        current_wave=1,
        max_waves=4,
    )

    assert first.status is RecoveryLoopStatus.RETRY
    assert second.status is RecoveryLoopStatus.RETRY
    assert second.next_wave == 2
    assert second.plan.decisions[0].next_attempt_id not in {
        "a001",
        second_attempt,
    }


@pytest.mark.parametrize("reason", ["OUT_OF_MEMORY", "DISK_EXHAUSTED"])
def test_recovery_loop_requires_operational_replan(reason: str) -> None:
    result = build_recovery_loop(
        [make_shard(1)],
        [failed_attempt("s001", "a001", reason)],
        [],
        {"runner_lost": 2},
        current_wave=0,
        max_waves=4,
    )
    assert result.status is RecoveryLoopStatus.REPLAN
    assert result.retry_count == 0
    assert result.replan_shard_ids == ("s001",)


def test_recovery_loop_never_retries_deterministic_failure() -> None:
    result = build_recovery_loop(
        [make_shard(1)],
        [failed_attempt("s001", "a001", "SCHEMA_MISMATCH")],
        [],
        {"runner_lost": 2},
        current_wave=0,
        max_waves=4,
    )
    assert result.status is RecoveryLoopStatus.BLOCKED_HARD_FAILURE
    assert result.retry_count == 0
    assert result.reason_codes == ("SCHEMA_MISMATCH",)


def test_recovery_loop_completes_when_every_shard_is_verified() -> None:
    result = build_recovery_loop(
        [make_shard(1)],
        [_completed_attempt("s001", "a001")],
        [],
        {"runner_lost": 2},
        current_wave=2,
        max_waves=4,
    )
    assert result.status is RecoveryLoopStatus.COMPLETE
    assert result.next_wave is None
    assert result.terminal_shard_count == 1
    assert result.terminal_unit_count == 1
    assert len(result.terminal_unit_manifest_sha256 or "") == 64
    assert result.verified_source_artifacts == ("artifact-s001-a001",)


def _attempt_with_unit_evidence(
    tmp_path: Path,
    *,
    shard_id: str,
    attempt_id: str,
    rows: tuple[UnitAttemptRecord, ...],
    reason_code: str | None = None,
) -> tuple[Path, Path]:
    unit_path = write_unit_attempt_manifest(
        rows,
        tmp_path / f"{shard_id}-{attempt_id}-units.parquet",
    )
    completed = sum(
        row.state is TerminalState.COMPLETED for row in rows
    )
    attempt = AttemptManifest(
        shard_id=shard_id,
        attempt_id=attempt_id,
        state=(
            TerminalState.COMPLETED
            if reason_code is None
            else TerminalState.FAILED_TECHNICAL
        ),
        spec_hash="1" * 64,
        policy_hash="2" * 64,
        snapshot_hash="3" * 64,
        code_sha="4" * 40,
        dependency_lock_sha256="5" * 64,
        capacity_profile_sha256="6" * 64,
        output_sha256=("7" * 64 if reason_code is None else None),
        reason_code=reason_code,
        artifact_name=f"artifact-{shard_id}-{attempt_id}",
        unit_attempts_path=unit_path.name,
        unit_attempts_sha256=sha256_file(unit_path),
        checkpoint_artifact=None,
        completed_unit_count=completed,
        output_rows=completed,
        output_bytes=100 * completed,
        runtime_access_ledger_path=(
            "runtime_access_ledger.parquet"
            if reason_code is None
            else None
        ),
        runtime_access_ledger_sha256=(
            "9" * 64 if reason_code is None else None
        ),
        metric_inputs_path=(
            "metric_inputs.parquet" if reason_code is None else None
        ),
        metric_inputs_sha256=(
            "a" * 64 if reason_code is None else None
        ),
    )
    attempt_path = tmp_path / f"{shard_id}-{attempt_id}.json"
    attempt_path.write_text(attempt.model_dump_json(), encoding="utf-8")
    return attempt_path, unit_path


def test_terminal_unit_evidence_salvages_verified_units_before_oom(
    tmp_path: Path,
) -> None:
    completed_rows = (
        UnitAttemptRecord(
            unit_key="u000",
            shard_id="s000",
            attempt_id="a000",
            state=TerminalState.COMPLETED,
            output_sha256="b" * 64,
            reason_code=None,
        ),
        UnitAttemptRecord(
            unit_key="u001",
            shard_id="s000",
            attempt_id="a000",
            state=TerminalState.COMPLETED,
            output_sha256="c" * 64,
            reason_code=None,
        ),
    )
    partial_rows = (
        UnitAttemptRecord(
            unit_key="u002",
            shard_id="s001",
            attempt_id="a001",
            state=TerminalState.COMPLETED,
            output_sha256="d" * 64,
            reason_code=None,
        ),
        UnitAttemptRecord(
            unit_key="u003",
            shard_id="s001",
            attempt_id="a001",
            state=TerminalState.FAILED_TECHNICAL,
            output_sha256=None,
            reason_code="OUT_OF_MEMORY",
        ),
    )
    first_attempt, first_units = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s000",
        attempt_id="a000",
        rows=completed_rows,
    )
    second_attempt, second_units = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s001",
        attempt_id="a001",
        rows=partial_rows,
        reason_code="OUT_OF_MEMORY",
    )

    evidence = build_terminal_unit_evidence_from_paths(
        (first_attempt, second_attempt),
        (first_units, second_units),
    )

    assert evidence.unit_keys == ("u000", "u001", "u002")
    assert evidence.unit_count == 3
    assert len(evidence.unit_manifest_sha256 or "") == 64
    assert evidence.source_artifacts == (
        "artifact-s000-a000",
        "artifact-s001-a001",
    )
    assert pq.read_metadata(second_units).num_rows == 2


def test_terminal_unit_evidence_rejects_unbound_manifest(
    tmp_path: Path,
) -> None:
    rows = (
        UnitAttemptRecord(
            unit_key="u000",
            shard_id="s000",
            attempt_id="a000",
            state=TerminalState.COMPLETED,
            output_sha256="b" * 64,
            reason_code=None,
        ),
    )
    attempt_path, unit_path = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s000",
        attempt_id="a000",
        rows=rows,
    )
    unit_path.write_bytes(unit_path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="hash mismatch"):
        build_terminal_unit_evidence_from_paths(
            (attempt_path,),
            (unit_path,),
        )


def test_terminal_unit_evidence_accepts_checkpoint_resumed_rows(
    tmp_path: Path,
) -> None:
    inherited = UnitAttemptRecord(
        unit_key="u000",
        shard_id="s000",
        attempt_id="a000",
        state=TerminalState.COMPLETED,
        output_sha256="b" * 64,
        reason_code=None,
    )
    original_attempt, original_units = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s000",
        attempt_id="a000",
        rows=(inherited,),
        reason_code="TRANSIENT_NETWORK",
    )
    resumed = UnitAttemptRecord(
        unit_key="u001",
        shard_id="s000",
        attempt_id="a001",
        state=TerminalState.COMPLETED,
        output_sha256="c" * 64,
        reason_code=None,
    )
    retry_attempt, retry_units = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s000",
        attempt_id="a001",
        rows=(inherited, resumed),
    )

    evidence = build_terminal_unit_evidence_from_paths(
        (original_attempt, retry_attempt),
        (original_units, retry_units),
    )

    assert evidence.unit_keys == ("u000", "u001")
    assert evidence.unit_count == 2
    assert evidence.source_artifacts == (
        "artifact-s000-a000",
        "artifact-s000-a001",
    )


def test_terminal_unit_evidence_binds_inherited_row_to_checkpoint(
    tmp_path: Path,
) -> None:
    inherited = UnitAttemptRecord(
        unit_key="u000",
        shard_id="s000",
        attempt_id="a000",
        state=TerminalState.COMPLETED,
        output_sha256="b" * 64,
        reason_code=None,
    )
    original_attempt, _ = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s000",
        attempt_id="a000",
        rows=(inherited,),
        reason_code="TRANSIENT_NETWORK",
    )
    checkpoint_payload = tmp_path / "checkpoint-payload.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "unit_key": inherited.unit_key,
                    "source_attempt_id": inherited.attempt_id,
                    "unit_output_sha256": inherited.output_sha256,
                }
            ]
        ),
        checkpoint_payload,
    )
    manager = CheckpointManager(tmp_path / "checkpoint")
    manager.commit(
        "s000",
        "a000",
        1,
        inherited.unit_key,
        checkpoint_payload,
    )
    resumed = UnitAttemptRecord(
        unit_key="u001",
        shard_id="s000",
        attempt_id="a001",
        state=TerminalState.COMPLETED,
        output_sha256="c" * 64,
        reason_code=None,
    )
    retry_attempt, retry_units = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s000",
        attempt_id="a001",
        rows=(inherited, resumed),
    )

    evidence = build_terminal_unit_evidence_from_paths(
        (original_attempt, retry_attempt),
        (retry_units,),
        (tmp_path / "checkpoint" / "checkpoint_manifest.json",),
    )

    assert evidence.unit_keys == ("u000", "u001")
    assert evidence.unit_count == 2


def test_terminal_unit_evidence_rejects_unbound_resumed_row(
    tmp_path: Path,
) -> None:
    original = UnitAttemptRecord(
        unit_key="u000",
        shard_id="s000",
        attempt_id="a000",
        state=TerminalState.COMPLETED,
        output_sha256="b" * 64,
        reason_code=None,
    )
    original_attempt, original_units = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s000",
        attempt_id="a000",
        rows=(original,),
        reason_code="TRANSIENT_NETWORK",
    )
    altered = original.model_copy(update={"output_sha256": "c" * 64})
    resumed = UnitAttemptRecord(
        unit_key="u001",
        shard_id="s000",
        attempt_id="a001",
        state=TerminalState.COMPLETED,
        output_sha256="d" * 64,
        reason_code=None,
    )
    retry_attempt, retry_units = _attempt_with_unit_evidence(
        tmp_path,
        shard_id="s000",
        attempt_id="a001",
        rows=(altered, resumed),
    )

    with pytest.raises(ValueError, match="independently bound"):
        build_terminal_unit_evidence_from_paths(
            (original_attempt, retry_attempt),
            (original_units, retry_units),
        )


def test_recovery_loop_stops_at_wave_budget() -> None:
    result = build_recovery_loop(
        [make_shard(1)],
        [failed_attempt("s001", "a001", "RUNNER_LOST")],
        [],
        {"runner_lost": 5},
        current_wave=3,
        max_waves=4,
    )
    assert result.status is RecoveryLoopStatus.BLOCKED_HARD_FAILURE
    assert result.retry_count == 0
    assert result.next_wave is None
    assert result.reason_codes == ("RECOVERY_WAVE_BUDGET_EXHAUSTED",)
