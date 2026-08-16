"""End-to-end GitHub Actions runtime evidence for optimized catalog runs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime


_COMPUTE_STEP_MARKERS = (
    "scripts.run_sp500_optimized_recipe_worker",
    "scripts.build_sp500_component_store",
    "scripts.merge_sp500_component_store",
    "scripts.reduce_sp500_optimized_catalog_run",
    "scripts.verify_sp500_optimized_run",
)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("CATALOG_ACTIONS_TIMESTAMP_INVALID")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _duration(started: object, completed: object) -> float:
    return max(0.0, (_timestamp(completed) - _timestamp(started)).total_seconds())


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _completed_jobs(
    jobs: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    completed = [
        job
        for job in jobs
        if job.get("started_at") and job.get("completed_at")
    ]
    if not completed:
        raise ValueError("CATALOG_ACTIONS_JOBS_EMPTY")
    failed = [job for job in completed if job.get("conclusion") == "failure"]
    if failed:
        raise ValueError("CATALOG_ACTIONS_JOB_FAILURE")
    return completed


def build_actions_runtime_audit(
    *,
    run: Mapping[str, object],
    jobs: Sequence[Mapping[str, object]],
    artifacts: Sequence[Mapping[str, object]],
    receipt: Mapping[str, object],
    thermal_state: str,
) -> dict[str, object]:
    """Build honest wall, runner, queue, setup, compute and byte accounting."""

    if thermal_state not in {
        "cold",
        "runtime_warm",
        "component_warm",
        "fully_hot",
    }:
        raise ValueError("CATALOG_ACTIONS_THERMAL_STATE_INVALID")
    if receipt.get("validation_opened") is not False or receipt.get(
        "locked_opened"
    ) is not False:
        raise ValueError("CATALOG_PROTECTED_PERIOD_OPENED")
    completed = _completed_jobs(jobs)
    run_started = _timestamp(run["run_started_at"])
    run_completed = max(_timestamp(job["completed_at"]) for job in completed)
    wall_seconds = max(0.0, (run_completed - run_started).total_seconds())
    if wall_seconds <= 0:
        raise ValueError("CATALOG_ACTIONS_WALL_INVALID")

    runner_seconds = sum(
        _duration(job["started_at"], job["completed_at"]) for job in completed
    )
    queue_seconds = sum(
        _duration(job["created_at"], job["started_at"])
        for job in completed
        if job.get("created_at")
    )
    setup_samples: list[float] = []
    compute_seconds = 0.0
    upload_seconds = 0.0
    step_seconds = 0.0
    action_stage_seconds = {
        "component_build": 0.0,
        "component_merge": 0.0,
        "recipe_evaluation": 0.0,
        "reduction": 0.0,
        "verification": 0.0,
    }
    stage_markers = {
        "component_build": "scripts.build_sp500_component_store",
        "component_merge": "scripts.merge_sp500_component_store",
        "recipe_evaluation": "scripts.run_sp500_optimized_recipe_worker",
        "reduction": "scripts.reduce_sp500_optimized_catalog_run",
        "verification": "scripts.verify_sp500_optimized_run",
    }
    for job in completed:
        steps = job.get("steps", ())
        if not isinstance(steps, Sequence):
            continue
        step_seconds += sum(
            _duration(step["started_at"], step["completed_at"])
            for step in steps
            if isinstance(step, Mapping)
            and step.get("started_at")
            and step.get("completed_at")
        )
        compute_steps = [
            step
            for step in steps
            if isinstance(step, Mapping)
            and any(
                marker in str(step.get("name", ""))
                for marker in _COMPUTE_STEP_MARKERS
            )
            and step.get("started_at")
            and step.get("completed_at")
        ]
        if compute_steps:
            first_compute = min(
                _timestamp(step["started_at"]) for step in compute_steps
            )
            setup_samples.append(
                max(0.0, (first_compute - _timestamp(job["started_at"])).total_seconds())
            )
        compute_seconds += sum(
            _duration(step["started_at"], step["completed_at"])
            for step in compute_steps
        )
        for stage, marker in stage_markers.items():
            action_stage_seconds[stage] += sum(
                _duration(step["started_at"], step["completed_at"])
                for step in steps
                if isinstance(step, Mapping)
                and marker in str(step.get("name", ""))
                and step.get("started_at")
                and step.get("completed_at")
            )
        upload_seconds += sum(
            _duration(step["started_at"], step["completed_at"])
            for step in steps
            if isinstance(step, Mapping)
            and "upload-artifact" in str(step.get("name", ""))
            and step.get("started_at")
            and step.get("completed_at")
        )

    strategy_count = int(receipt["strategy_count"])
    if strategy_count < 1:
        raise ValueError("CATALOG_ACTIONS_STRATEGY_COUNT_INVALID")
    result_bytes = int(receipt.get("result_bytes", 0))
    artifact_bytes = sum(int(item.get("size_in_bytes", 0)) for item in artifacts)
    unattributed_runner_seconds = max(0.0, runner_seconds - step_seconds)
    accounted_runner_seconds = step_seconds + unattributed_runner_seconds
    accounting_difference_ratio = (
        abs(runner_seconds - accounted_runner_seconds) / runner_seconds
        if runner_seconds
        else 0.0
    )
    scientific_stage_seconds = receipt.get("scientific_stage_seconds", {})
    if not isinstance(scientific_stage_seconds, Mapping):
        raise ValueError("CATALOG_ACTIONS_SCIENTIFIC_STAGES_INVALID")
    return {
        "schema_version": 1,
        "run_id": int(run["id"]),
        "head_sha": str(run["head_sha"]),
        "thermal_state": thermal_state,
        "wall_seconds": wall_seconds,
        "runner_seconds": runner_seconds,
        "runner_hours": runner_seconds / 3600.0,
        "queue_seconds": queue_seconds,
        "setup_seconds_p50": _nearest_rank(setup_samples, 0.50),
        "setup_seconds_p95": _nearest_rank(setup_samples, 0.95),
        "compute_seconds": compute_seconds,
        "action_stage_seconds": action_stage_seconds,
        "reduction_wall_ratio": action_stage_seconds["reduction"] / wall_seconds,
        "upload_seconds": upload_seconds,
        "step_seconds": step_seconds,
        "unattributed_runner_seconds": unattributed_runner_seconds,
        "accounted_runner_seconds": accounted_runner_seconds,
        "accounting_difference_ratio": accounting_difference_ratio,
        "scientific_stage_seconds": {
            str(name): float(value)
            for name, value in scientific_stage_seconds.items()
        },
        "worker_cpu_seconds": float(receipt.get("worker_cpu_seconds", 0.0)),
        "worker_peak_memory_bytes": int(
            receipt.get("worker_peak_memory_bytes", 0)
        ),
        "worker_available_memory_bytes": int(
            receipt.get("worker_available_memory_bytes", 0)
        ),
        "worker_peak_memory_fraction": float(
            receipt.get("worker_peak_memory_fraction", 0.0)
        ),
        "requested_recipes": strategy_count,
        "new_complete_recipe_ids": int(
            receipt.get("physical_recipe_evaluations", strategy_count)
        ),
        "prior_result_cache_hits": int(receipt.get("prior_result_cache_hits", 0)),
        "worker_receipt_count": int(receipt.get("worker_receipt_count", 0)),
        "workers": int(receipt.get("workers", 0)),
        "processes_per_worker": int(receipt.get("processes_per_worker", 0)),
        "block_size": int(receipt.get("block_size", 0)),
        "strategies_per_wall_minute": strategy_count * 60.0 / wall_seconds,
        "artifact_count": len(artifacts),
        "artifact_bytes_uploaded": artifact_bytes,
        "result_bytes": result_bytes,
        "result_bytes_per_recipe": result_bytes / strategy_count,
        "validation_opened": False,
        "locked_opened": False,
    }


__all__ = ["build_actions_runtime_audit"]
