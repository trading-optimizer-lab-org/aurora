from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aurora.infra.github_performance.checkpoint import (
    CheckpointIntegrityError,
    CheckpointManager,
    load_checkpoint,
)
from aurora.infra.github_performance.contracts import CheckpointManifest
from aurora.infra.github_performance.recovery import (
    build_recovery_plan,
    build_recovery_plan_from_paths,
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
    assert sha256_file(Path(loaded.payload_path)) == loaded.payload_sha256


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


def test_corrupt_checkpoint_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "rows.parquet"
    payload.write_bytes(b"valid")
    manager = CheckpointManager(tmp_path / "checkpoint")
    manager.commit("s001", "a001", 12, "u0012", payload)
    payload.write_bytes(b"tampered")
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
