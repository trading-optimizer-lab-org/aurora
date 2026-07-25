from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    PerformanceContract,
    PilotResult,
    RuntimeEvidence,
    ShardDefinition,
    TerminalState,
    UnitAttemptRecord,
    VerificationReport,
    WorkUnit,
)


def minimal_valid_spec() -> dict[str, Any]:
    payload = yaml.safe_load(
        Path("config/templates/github_run_v3.yaml").read_text(encoding="utf-8")
    )
    payload["identity"].update(
        {
            "campaign_id": "test-campaign",
            "run_type": "reference",
            "code_ref": "refs/heads/test",
            "workflow": ".github/workflows/test.yml",
            "deadline_utc": "2099-12-31T00:00:00Z",
        }
    )
    payload["objective"].update(
        {
            "description": "Verify the GitHub performance framework",
            "success_criteria": ["partial=false"],
            "negative_result_criteria": ["no accepted result"],
            "technical_failure_criteria": ["partial=true"],
        }
    )
    payload["policy"].update(
        {
            "train_start": "1995-01-01",
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "decision_timezone": "UTC",
            "decision_timestamp_rule": "close",
            "execution_timestamp_rule": "next_open",
            "market_calendar": "XNYS",
        }
    )
    payload["execution"].update(
        {
            "shard_seed_formula": "global_seed + shard_index",
            "python_version": "3.12",
            "runner_image": "ubuntu-24.04",
        }
    )
    payload["artifacts"]["final_name"] = "test-campaign-results"
    payload["metrics"].update(
        {
            "return_type": "simple",
            "return_basis": "total_return",
            "annualization_rule": "252",
            "risk_free_source": "zero",
            "undefined_metric_policy": "null",
        }
    )
    return payload


def complete_runtime_evidence() -> RuntimeEvidence:
    return RuntimeEvidence(
        code_sha="a" * 40,
        workflow_sha256="d" * 64,
        policy_hash="b" * 64,
        dependency_lock_sha256="e" * 64,
        capacity_profile_sha256="f" * 64,
        data_manifest_sha256="1" * 64,
        snapshot_hash="c" * 64,
        metric_contract_sha256="2" * 64,
        environment_sha256="3" * 64,
    )


def write_yaml(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(dict(payload), sort_keys=False),
        encoding="utf-8",
    )
    return path


def make_unit(index: int, seconds: float = 1.0) -> WorkUnit:
    key = f"u{index:04d}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return WorkUnit(
        unit_key=key,
        estimated_seconds=seconds,
        payload_ref=f"units/{key}.json",
        payload_sha256=digest,
    )


def make_shard(index: int) -> ShardDefinition:
    return ShardDefinition(
        shard_id=f"s{index:03d}",
        assignment_artifact="run-assignment-bundle-000",
        assignment_member=f"assignments/s{index:03d}.parquet",
        assignment_sha256="8" * 64,
        unit_count=1,
        estimated_seconds=1.0,
        merge_group=f"g{index // 30:02d}",
    )


def contract() -> PerformanceContract:
    return PerformanceContract(
        resolved_spec_sha256="0" * 64,
        code_sha="a" * 40,
        workflow_sha256="b" * 64,
        policy_hash="c" * 64,
        snapshot_hash="d" * 64,
        data_manifest_sha256="e" * 64,
        metric_contract_sha256="f" * 64,
        dependency_lock_sha256="1" * 64,
        capacity_profile_sha256="2" * 64,
        environment_sha256="3" * 64,
        standard_runner_only=True,
        locked_opened=False,
        validation_used_for_selection=False,
        larger_runners_allowed=False,
        artifact_transport_mode="auto",
        planner_min_jobs=1,
        planner_max_jobs=360,
        planner_job_count_search="adaptive_exact",
        planner_large_unit_threshold=50_000,
        planner_exact_lpt_candidates_max=3,
        matrix_job_ceiling=256,
        standard_concurrency_ceiling=360,
        runner_label="ubuntu-24.04",
        max_memory_pct=80,
        min_free_disk_gb=5.0,
        merge_fan_in=30,
        target_setup_fraction_max=0.10,
        target_checkpoint_fraction_max=0.03,
    )


def pilot() -> PilotResult:
    return PilotResult(
        queue_seconds=2.0,
        setup_seconds=3.0,
        transfer_fixed_seconds=1.0,
        transfer_per_wave_seconds=0.5,
        checkpoint_seconds=0.2,
        merge_fixed_seconds=1.0,
        merge_per_shard_seconds=0.01,
        verify_seconds=0.5,
        unit_seconds_p50=1.0,
        unit_seconds_p95=2.0,
        usable_parallelism=360,
    )


def high_setup_pilot() -> PilotResult:
    return pilot().model_copy(
        update={"setup_seconds": 120.0, "transfer_per_wave_seconds": 5.0}
    )


def _shard_attempt_fields(shard_id: str, attempt_id: str) -> dict[str, Any]:
    return {
        "shard_id": shard_id,
        "attempt_id": attempt_id,
        "spec_hash": "1" * 64,
        "policy_hash": "2" * 64,
        "snapshot_hash": "3" * 64,
        "code_sha": "4" * 40,
        "dependency_lock_sha256": "5" * 64,
        "capacity_profile_sha256": "6" * 64,
    }


def completed_unit(
    unit_key: str,
    attempt_id: str,
    digest: str,
    shard_id: str = "s000",
) -> UnitAttemptRecord:
    return UnitAttemptRecord(
        unit_key=unit_key,
        shard_id=shard_id,
        attempt_id=attempt_id,
        state=TerminalState.COMPLETED,
        output_sha256=digest,
        reason_code=None,
    )


def unsupported_unit(
    unit_key: str,
    reason_code: str,
    shard_id: str = "s000",
) -> UnitAttemptRecord:
    return UnitAttemptRecord(
        unit_key=unit_key,
        shard_id=shard_id,
        attempt_id=f"unsupported-{unit_key}",
        state=TerminalState.UNSUPPORTED,
        output_sha256=None,
        reason_code=reason_code,
    )


def failed_attempt(
    shard_id: str,
    attempt_id: str,
    reason_code: str,
) -> AttemptManifest:
    return AttemptManifest(
        **_shard_attempt_fields(shard_id, attempt_id),
        state=TerminalState.FAILED_TECHNICAL,
        output_sha256=None,
        reason_code=reason_code,
        artifact_name=f"run-failure-{shard_id}-{attempt_id}",
        unit_attempts_path=None,
        unit_attempts_sha256=None,
        checkpoint_artifact=None,
        completed_unit_count=0,
        output_rows=0,
        output_bytes=0,
    )


def verification_report(
    partial: bool,
    requirements_passed: bool,
    locked_opened: bool,
) -> VerificationReport:
    passed = not partial and requirements_passed and not locked_opened
    return VerificationReport(
        passed=passed,
        partial=partial,
        requirements_passed=requirements_passed,
        locked_opened=locked_opened,
        validation_used_for_selection=False,
        standard_runner_only=True,
        matrix_job_ceiling_respected=True,
        evidence_paths=("final_artifact_manifest.json",),
    )


def manual_heavy_workflow(local_uses: str) -> dict[str, Any]:
    return {
        "name": "future manual run",
        "on": {"workflow_dispatch": {}},
        "permissions": {"contents": "read"},
        "jobs": {"run": {"uses": local_uses}},
    }


def workflow_with_step(uses: str) -> dict[str, Any]:
    return {
        "name": "future action test",
        "on": {"workflow_dispatch": {}},
        "permissions": {"contents": "read"},
        "jobs": {
            "run": {
                "runs-on": "ubuntu-24.04",
                "steps": [{"name": "external", "uses": uses}],
            }
        },
    }


def push_triggered_heavy_workflow() -> dict[str, Any]:
    payload = manual_heavy_workflow(
        "./.github/workflows/_aurora-future-run-v3.yml"
    )
    payload["on"] = {"push": {"branches": ["main"]}}
    return payload


def _timestamp(value: str) -> str:
    return f"2026-07-25T{value}Z"


def github_job(
    name: str,
    created: str,
    started: str,
    completed: str,
) -> dict[str, Any]:
    return {
        "id": int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16),
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "created_at": _timestamp(created),
        "started_at": _timestamp(started),
        "completed_at": _timestamp(completed),
        "steps": [
            {
                "name": "Aurora runtime setup",
                "status": "completed",
                "conclusion": "success",
                "started_at": _timestamp(started),
                "completed_at": _timestamp(completed),
                "number": 1,
            }
        ],
    }
