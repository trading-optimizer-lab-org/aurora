"""Equivalent scientific-output comparison for GitHub performance runs."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    canonical_sha256,
    deep_thaw_json,
)


class ScientificOutputMismatch(RuntimeError):
    """Raised before timing is compared across non-equivalent outputs."""


class BenchmarkReport(FrozenModel):
    schema_version: str
    status: str
    scientific_outputs_equal: bool
    timing_comparable: bool
    compared_units: int
    same_code_sha: bool
    same_policy_hash: bool
    same_snapshot_hash: bool
    same_environment_sha256: bool
    dependency_environment_reproducible: bool
    setup_fast_path_selected: bool
    same_cache_state: bool
    same_performance_contract: bool
    same_selected_jobs: bool
    baseline_assignment_strategy: str
    optimized_assignment_strategy: str
    speedup: float
    setup_cold_speedup: float
    setup_warm_speedup: float
    estimated_billable_minutes_ratio: float
    baseline_predicted_error_fraction: float
    optimized_predicted_error_fraction: float
    matrix_job_ceiling_respected: bool
    standard_runner_only: bool
    larger_runner_used: bool
    locked_opened: bool
    validation_used_for_selection: bool
    partial: bool
    baseline: Mapping[str, Any]
    optimized: Mapping[str, Any]
    bottleneck: Mapping[str, Any]
    environment_setup_benchmark: Mapping[str, Any]
    failure_codes: tuple[str, ...]


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _scientific_hashes(root: Path) -> dict[str, str]:
    summary = _json(root / "final_merge_summary.json")
    output = root / str(summary["scientific_output"])
    table = pq.read_table(
        output,
        columns=["unit_key", "unit_output_sha256"],
    )
    rows = table.to_pylist()
    hashes = {
        str(row["unit_key"]): str(row["unit_output_sha256"])
        for row in rows
    }
    if len(hashes) != len(rows):
        raise ScientificOutputMismatch(
            "scientific output contains duplicate unit keys"
        )
    return hashes


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    value = numerator / denominator
    return float(value) if math.isfinite(value) else 0.0


def _run_metrics(root: Path) -> dict[str, Any]:
    timeline = _json(root / "timeline_summary.json")
    plan = _json(root / "execution_plan.json")
    contract = _json(root / "performance_contract.json")
    environment = _json(root / "environment_manifest.json")
    observations = environment.get("observations", {})
    if not isinstance(observations, dict):
        observations = {}
    cache = environment.get("cache", {})
    if not isinstance(cache, dict):
        cache = {}
    delivery_state = (
        str(observations.get("install_mode", "wheelhouse"))
        if environment.get("schema_version") == "2"
        else f"cache_hit={bool(cache.get('hit', False))}"
    )
    merge = _json(root / "final_merge_summary.json")
    wall = float(timeline["workflow_wall_seconds"])
    predicted = float(plan["job_count"]["predicted_seconds"])
    job_seconds = float(timeline["job_seconds_total"])
    return {
        "assignment_strategy": str(plan["assignment_strategy"]),
        "performance_contract_sha256": canonical_sha256(contract),
        "selected_jobs": int(plan["job_count"]["selected_jobs"]),
        "predicted_seconds": predicted,
        "workflow_wall_seconds": wall,
        "execution_wall_seconds": float(
            timeline["execution_wall_seconds"]
        ),
        "observed_peak_parallelism": int(
            timeline["observed_peak_parallelism"]
        ),
        "observed_average_parallelism": float(
            timeline.get("observed_average_parallelism", 0.0)
        ),
        "requested_parallelism": int(
            timeline["requested_parallelism"]
        ),
        "estimated_billable_minutes": float(
            timeline["estimated_billable_minutes"]
        ),
        "queue_seconds_total": float(timeline["queue_seconds_total"]),
        "setup_seconds_total": float(timeline["setup_seconds_total"]),
        "canonical_setup_seconds_total": float(
            timeline.get("canonical_setup_seconds_total", 0.0)
        ),
        "restore_setup_seconds_total": float(
            timeline.get("restore_setup_seconds_total", 0.0)
        ),
        "transfer_seconds_total": float(
            timeline["transfer_seconds_total"]
        ),
        "compute_seconds_total": float(
            timeline["compute_seconds_total"]
        ),
        "retry_seconds_total": float(
            timeline["retry_seconds_total"]
        ),
        "merge_seconds_total": float(timeline["merge_seconds_total"]),
        "other_seconds_total": float(
            timeline.get("other_seconds_total", 0.0)
        ),
        "job_seconds_total": job_seconds,
        "straggler_ratio": float(timeline["straggler_ratio"]),
        "merge_path": (
            "flat"
            if str(plan["assignment_strategy"]) == "equal_count_flat"
            else "hierarchical"
        ),
        "useful_compute_fraction": _ratio(
            float(timeline["compute_seconds_total"]),
            job_seconds,
        ),
        "setup_fraction": _ratio(
            float(timeline["setup_seconds_total"]),
            job_seconds,
        ),
        "transfer_fraction": _ratio(
            float(timeline["transfer_seconds_total"]),
            job_seconds,
        ),
        "retry_waste_fraction": _ratio(
            float(timeline["retry_seconds_total"]),
            job_seconds,
        ),
        "predicted_error_fraction": _ratio(
            abs(wall - predicted),
            predicted,
        ),
        "telemetry_complete": bool(timeline.get("complete", False)),
        "partial": bool(merge.get("partial", True)),
        "locked_opened": bool(merge.get("locked_opened", True)),
        "validation_used_for_selection": bool(
            merge.get("validation_used_for_selection", True)
        ),
        "code_sha": str(contract["code_sha"]),
        "policy_hash": str(contract["policy_hash"]),
        "snapshot_hash": str(contract["snapshot_hash"]),
        "environment_sha256": str(contract["environment_sha256"]),
        "environment_cache_hit": bool(cache.get("hit", False)),
        "environment_delivery_state": delivery_state,
        "standard_runner_only": bool(
            contract["standard_runner_only"]
        ),
        "larger_runners_allowed": bool(
            contract["larger_runners_allowed"]
        ),
        "matrix_job_ceiling": int(contract["matrix_job_ceiling"]),
        "standard_concurrency_ceiling": int(
            contract["standard_concurrency_ceiling"]
        ),
    }


def _dominant_component(metrics: Mapping[str, Any]) -> Mapping[str, Any]:
    components = {
        "setup": float(metrics["setup_seconds_total"]),
        "transfer": float(metrics["transfer_seconds_total"]),
        "compute": float(metrics["compute_seconds_total"]),
        "retry": float(metrics["retry_seconds_total"]),
        "merge": float(metrics["merge_seconds_total"]),
        "other": float(metrics["other_seconds_total"]),
    }
    name, seconds = max(
        components.items(),
        key=lambda item: (item[1], item[0]),
    )
    return {
        "component": name,
        "aggregate_job_seconds": seconds,
        "components": components,
    }


def build_bottleneck_report(
    reference: Mapping[str, Any],
    optimized: Mapping[str, Any],
    timeline: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Describe the measured dominant component for both equivalent runs."""

    payload = {
        "schema_version": "1",
        "baseline": _dominant_component(reference),
        "optimized": _dominant_component(optimized),
    }
    if timeline is not None:
        payload["timeline"] = dict(timeline)
    return payload


def compare_runs(
    reference_dir: Path,
    optimized_dir: Path,
    environment_setup_benchmark: Path | Mapping[str, Any] | None = None,
) -> BenchmarkReport:
    """Compare performance only after exact unit-level equivalence."""

    baseline_root = Path(reference_dir)
    optimized_root = Path(optimized_dir)
    baseline_hashes = _scientific_hashes(baseline_root)
    optimized_hashes = _scientific_hashes(optimized_root)
    if baseline_hashes.keys() != optimized_hashes.keys():
        raise ScientificOutputMismatch(
            "baseline and optimized unit keys differ"
        )
    conflicting = [
        key
        for key in sorted(baseline_hashes)
        if baseline_hashes[key] != optimized_hashes[key]
    ]
    if conflicting:
        raise ScientificOutputMismatch(
            "baseline and optimized scientific hashes differ: "
            + ",".join(conflicting[:10])
        )

    baseline = _run_metrics(baseline_root)
    optimized = _run_metrics(optimized_root)
    same_code = baseline["code_sha"] == optimized["code_sha"]
    same_policy = baseline["policy_hash"] == optimized["policy_hash"]
    same_snapshot = (
        baseline["snapshot_hash"] == optimized["snapshot_hash"]
    )
    same_environment = (
        baseline["environment_sha256"]
        == optimized["environment_sha256"]
    )
    same_cache_state = (
        baseline["environment_delivery_state"]
        == optimized["environment_delivery_state"]
    )
    if environment_setup_benchmark is None:
        setup_benchmark: dict[str, Any] = {
            "schema_version": "0",
            "status": "not_supplied",
            "dependency_environment_reproducible": True,
            "fast_path_selected": True,
            "cold_speedup": 0.0,
            "warm_speedup": 0.0,
            "failure_codes": [],
        }
    elif isinstance(environment_setup_benchmark, Mapping):
        setup_benchmark = dict(environment_setup_benchmark)
    else:
        setup_benchmark = _json(Path(environment_setup_benchmark))
    dependency_reproducible = bool(
        setup_benchmark.get(
            "dependency_environment_reproducible",
            False,
        )
    )
    setup_fast_path_selected = bool(
        setup_benchmark.get("fast_path_selected", False)
    )
    same_performance_contract = (
        baseline["performance_contract_sha256"]
        == optimized["performance_contract_sha256"]
    )
    same_jobs = baseline["selected_jobs"] == optimized["selected_jobs"]
    matrix_ok = (
        baseline["matrix_job_ceiling"] <= 256
        and optimized["matrix_job_ceiling"] <= 256
        and baseline["standard_concurrency_ceiling"] <= 360
        and optimized["standard_concurrency_ceiling"] <= 360
    )
    standard_only = bool(
        baseline["standard_runner_only"]
        and optimized["standard_runner_only"]
    )
    larger_used = bool(
        baseline["larger_runners_allowed"]
        or optimized["larger_runners_allowed"]
    )
    locked_opened = bool(
        baseline["locked_opened"] or optimized["locked_opened"]
    )
    validation_used = bool(
        baseline["validation_used_for_selection"]
        or optimized["validation_used_for_selection"]
    )
    partial = bool(
        baseline["partial"]
        or optimized["partial"]
        or not baseline["telemetry_complete"]
        or not optimized["telemetry_complete"]
    )
    failures: list[str] = []
    checks = (
        (same_code, "CODE_SHA_MISMATCH"),
        (same_policy, "POLICY_HASH_MISMATCH"),
        (same_snapshot, "SNAPSHOT_HASH_MISMATCH"),
        (same_environment, "ENVIRONMENT_HASH_MISMATCH"),
        (
            dependency_reproducible,
            "DEPENDENCY_ENVIRONMENT_NOT_REPRODUCIBLE",
        ),
        (setup_fast_path_selected, "SETUP_FAST_PATH_REJECTED"),
        (same_cache_state, "CACHE_STATE_MISMATCH"),
        (
            same_performance_contract,
            "PERFORMANCE_CONTRACT_MISMATCH",
        ),
        (same_jobs, "SELECTED_JOB_COUNT_MISMATCH"),
        (
            baseline["assignment_strategy"] == "equal_count_flat",
            "BASELINE_MODE_INVALID",
        ),
        (
            optimized["assignment_strategy"]
            == "weighted_lpt_hierarchical",
            "OPTIMIZED_MODE_INVALID",
        ),
        (matrix_ok, "MATRIX_CEILING_EXCEEDED"),
        (standard_only, "NONSTANDARD_RUNNER"),
        (not larger_used, "LARGER_RUNNER_USED"),
        (not locked_opened, "LOCKED_OPENED"),
        (not validation_used, "VALIDATION_USED_FOR_SELECTION"),
        (not partial, "PARTIAL_OR_INCOMPLETE"),
    )
    failures.extend(code for passed, code in checks if not passed)
    failures.extend(
        str(code)
        for code in setup_benchmark.get("failure_codes", [])
        if str(code)
    )
    failures = sorted(set(failures))
    timing_comparable = not failures
    for metrics in (baseline, optimized):
        canonical = float(metrics["canonical_setup_seconds_total"])
        restored = float(metrics["restore_setup_seconds_total"])
        cache_hit = bool(metrics["environment_cache_hit"])
        metrics["cold_setup_seconds_total"] = (
            0.0 if cache_hit else canonical
        )
        metrics["warm_setup_seconds_total"] = (
            restored + (canonical if cache_hit else 0.0)
        )
    speedup = (
        _ratio(
            float(baseline["workflow_wall_seconds"]),
            float(optimized["workflow_wall_seconds"]),
        )
        if timing_comparable
        else 0.0
    )
    billable_ratio = (
        _ratio(
            float(optimized["estimated_billable_minutes"]),
            float(baseline["estimated_billable_minutes"]),
        )
        if timing_comparable
        else 0.0
    )
    bottleneck = build_bottleneck_report(baseline, optimized)
    return BenchmarkReport(
        schema_version="1",
        status="success" if not failures else "failed",
        scientific_outputs_equal=True,
        timing_comparable=timing_comparable,
        compared_units=len(baseline_hashes),
        same_code_sha=same_code,
        same_policy_hash=same_policy,
        same_snapshot_hash=same_snapshot,
        same_environment_sha256=same_environment,
        dependency_environment_reproducible=dependency_reproducible,
        setup_fast_path_selected=setup_fast_path_selected,
        same_cache_state=same_cache_state,
        same_performance_contract=same_performance_contract,
        same_selected_jobs=same_jobs,
        baseline_assignment_strategy=str(
            baseline["assignment_strategy"]
        ),
        optimized_assignment_strategy=str(
            optimized["assignment_strategy"]
        ),
        speedup=speedup,
        setup_cold_speedup=float(
            setup_benchmark.get("cold_speedup", 0.0)
        ),
        setup_warm_speedup=float(
            setup_benchmark.get("warm_speedup", 0.0)
        ),
        estimated_billable_minutes_ratio=billable_ratio,
        baseline_predicted_error_fraction=float(
            baseline["predicted_error_fraction"]
        ),
        optimized_predicted_error_fraction=float(
            optimized["predicted_error_fraction"]
        ),
        matrix_job_ceiling_respected=matrix_ok,
        standard_runner_only=standard_only,
        larger_runner_used=larger_used,
        locked_opened=locked_opened,
        validation_used_for_selection=validation_used,
        partial=partial,
        baseline=baseline,
        optimized=optimized,
        bottleneck=bottleneck,
        environment_setup_benchmark=setup_benchmark,
        failure_codes=tuple(failures),
    )


def _atomic_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            deep_thaw_json(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def write_performance_final(
    report: BenchmarkReport,
    path: Path,
) -> Path:
    return _atomic_json(path, report)


def write_benchmark_outputs(
    report: BenchmarkReport,
    output_dir: Path,
) -> tuple[Path, ...]:
    root = Path(output_dir)
    performance = write_performance_final(
        report,
        root / "performance_final.json",
    )
    bottleneck = _atomic_json(
        root / "bottleneck_report.json",
        report.bottleneck,
    )
    closure = _atomic_json(
        root / "github_performance_phase1_closure.json",
        {
            "schema_version": "1",
            "status": report.status,
            "scientific_outputs_equal": (
                report.scientific_outputs_equal
            ),
            "timing_comparable": report.timing_comparable,
            "same_performance_contract": (
                report.same_performance_contract
            ),
            "dependency_environment_reproducible": (
                report.dependency_environment_reproducible
            ),
            "setup_fast_path_selected": (
                report.setup_fast_path_selected
            ),
            "compared_units": report.compared_units,
            "locked_opened": report.locked_opened,
            "validation_used_for_selection": (
                report.validation_used_for_selection
            ),
            "partial": report.partial,
            "matrix_job_ceiling_respected": (
                report.matrix_job_ceiling_respected
            ),
            "standard_runner_only": report.standard_runner_only,
            "larger_runner_used": report.larger_runner_used,
            "failure_codes": list(report.failure_codes),
        },
    )
    return performance, bottleneck, closure
