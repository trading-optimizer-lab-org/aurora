"""Adaptive standard-runner planning for Aurora GitHub workloads."""

from __future__ import annotations

import heapq
import json
import math
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aurora.infra.github_performance.contracts import (
    ExecutionPlan,
    JobCountAlternative,
    JobCountDecision,
    PerformanceContract,
    PilotResult,
    RunSpec,
    ShardPlan,
    WorkUnitManifest,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.shard_planner import (
    equal_count,
    encode_matrix_outputs,
    read_work_units,
    split_matrices,
    weighted_lpt,
)


LptBuilder = Callable[[WorkUnitManifest, int, Path], ShardPlan]


class AssignmentTransportBudgetExceeded(RuntimeError):
    """Raised before wasteful repeated artifact downloads can begin."""


@dataclass(frozen=True)
class _PlannerSettings:
    planner_min_jobs: int
    planner_max_jobs: int
    planner_large_unit_threshold: int
    planner_exact_lpt_candidates_max: int
    target_setup_fraction_max: float
    target_checkpoint_fraction_max: float


def _settings(contract: PerformanceContract) -> _PlannerSettings:
    return _PlannerSettings(
        planner_min_jobs=contract.planner_min_jobs,
        planner_max_jobs=contract.planner_max_jobs,
        planner_large_unit_threshold=contract.planner_large_unit_threshold,
        planner_exact_lpt_candidates_max=(
            contract.planner_exact_lpt_candidates_max
        ),
        target_setup_fraction_max=contract.target_setup_fraction_max,
        target_checkpoint_fraction_max=(
            contract.target_checkpoint_fraction_max
        ),
    )


def _settings_from_spec(spec: RunSpec) -> _PlannerSettings:
    performance = spec.performance
    return _PlannerSettings(
        planner_min_jobs=int(performance["planner_min_jobs"]),
        planner_max_jobs=min(
            int(performance["planner_max_jobs"]),
            int(performance["confirmed_standard_concurrency"]),
            360,
        ),
        planner_large_unit_threshold=int(
            performance["planner_large_unit_threshold"]
        ),
        planner_exact_lpt_candidates_max=int(
            performance["planner_exact_lpt_candidates_max"]
        ),
        target_setup_fraction_max=float(
            performance["target_setup_fraction_max"]
        ),
        target_checkpoint_fraction_max=float(
            performance["target_checkpoint_fraction_max"]
        ),
    )


def _exact_lpt_slowest(costs: Iterable[tuple[str, float]], jobs: int) -> float:
    loads: list[tuple[float, int]] = [(0.0, index) for index in range(jobs)]
    heapq.heapify(loads)
    for _, seconds in sorted(costs, key=lambda item: (-item[1], item[0])):
        load, index = heapq.heappop(loads)
        heapq.heappush(loads, (load + seconds, index))
    return max(load for load, _ in loads)


def _histogram_slowest(costs: tuple[float, ...], jobs: int) -> float:
    """Approximate LPT using eight logarithmic buckets per cost octave."""

    positive = [value for value in costs if value > 0]
    if not positive:
        return 0.0
    minimum = min(positive)
    buckets: dict[int, list[float]] = {}
    for value in positive:
        bucket = int(math.floor(math.log2(value / minimum) * 8))
        current = buckets.setdefault(bucket, [0.0, 0.0])
        current[0] += value
        current[1] += 1.0
    loads = [0.0] * jobs
    for bucket in sorted(buckets, reverse=True):
        total, raw_count = buckets[bucket]
        count = int(raw_count)
        representative = total / count
        quotient, remainder = divmod(count, jobs)
        if quotient:
            addition = quotient * representative
            loads = [load + addition for load in loads]
        loads.sort()
        for index in range(remainder):
            loads[index] += representative
    return max(max(loads), max(positive), sum(costs) / jobs)


def _predicted_seconds(
    jobs: int,
    slowest_shard_seconds: float,
    pilot: PilotResult,
) -> float:
    waves = math.ceil(jobs / pilot.usable_parallelism)
    return (
        pilot.queue_seconds
        + pilot.setup_seconds
        + slowest_shard_seconds
        + pilot.transfer_fixed_seconds
        + pilot.transfer_per_wave_seconds * waves
        + pilot.checkpoint_seconds
        + pilot.merge_fixed_seconds
        + pilot.merge_per_shard_seconds * jobs
        + pilot.verify_seconds
    )


def _setup_fraction(
    alternative: JobCountAlternative,
    pilot: PilotResult,
) -> float:
    waves = alternative.waves
    startup = (
        pilot.setup_seconds
        + pilot.transfer_fixed_seconds
        + pilot.transfer_per_wave_seconds * waves
    )
    denominator = startup + alternative.slowest_shard_seconds
    return startup / denominator if denominator > 0 else 1.0


def _choose_exact(
    alternatives: Iterable[JobCountAlternative],
    pilot: PilotResult,
    settings: _PlannerSettings,
) -> JobCountAlternative:
    candidates = tuple(alternatives)
    within_target = tuple(
        item
        for item in candidates
        if _setup_fraction(item, pilot) <= settings.target_setup_fraction_max
    )
    if within_target:
        return min(
            within_target,
            key=lambda item: (item.predicted_seconds, item.jobs),
        )
    return min(
        candidates,
        key=lambda item: (
            _setup_fraction(item, pilot),
            item.predicted_seconds,
            item.jobs,
        ),
    )


def _alternative(
    jobs: int,
    slowest: float,
    pilot: PilotResult,
    kind: str,
) -> JobCountAlternative:
    return JobCountAlternative(
        jobs=jobs,
        waves=math.ceil(jobs / pilot.usable_parallelism),
        slowest_shard_seconds=slowest,
        predicted_seconds=_predicted_seconds(jobs, slowest, pilot),
        estimate_kind=kind,
    )


def choose_job_count(
    manifest: WorkUnitManifest,
    contract: PerformanceContract,
    pilot: PilotResult,
    *,
    lpt_builder: LptBuilder = weighted_lpt,
) -> JobCountDecision:
    """Select the fastest useful standard-runner count deterministically."""

    settings = _settings(contract)
    units = read_work_units(manifest)
    if not units:
        raise ValueError("cannot plan an empty work-unit manifest")
    lower = min(settings.planner_min_jobs, len(units))
    upper = min(len(units), settings.planner_max_jobs, 360)
    if lower > upper:
        raise ValueError("planner job bounds are infeasible")
    keyed_costs = tuple(
        (unit.unit_key, unit.estimated_seconds) for unit in units
    )
    costs = tuple(seconds for _, seconds in keyed_costs)
    total = sum(costs)
    maximum = max(costs)
    alternatives: list[JobCountAlternative] = []
    for jobs in range(lower, upper + 1):
        lower_bound = max(maximum, total / jobs)
        alternatives.append(
            _alternative(jobs, lower_bound, pilot, "analytical")
        )

    exact: list[JobCountAlternative] = []
    if len(units) <= settings.planner_large_unit_threshold:
        for jobs in range(lower, upper + 1):
            slowest = _exact_lpt_slowest(keyed_costs, jobs)
            item = _alternative(jobs, slowest, pilot, "exact_lpt")
            alternatives.append(item)
            exact.append(item)
    else:
        histogram: list[JobCountAlternative] = []
        for jobs in range(lower, upper + 1):
            item = _alternative(
                jobs,
                _histogram_slowest(costs, jobs),
                pilot,
                "histogram",
            )
            alternatives.append(item)
            histogram.append(item)
        provisional = _choose_exact(histogram, pilot, settings)
        candidate_jobs = sorted(
            {
                candidate
                for candidate in (
                    provisional.jobs - 1,
                    provisional.jobs,
                    provisional.jobs + 1,
                )
                if lower <= candidate <= upper
            }
        )[: settings.planner_exact_lpt_candidates_max]
        with tempfile.TemporaryDirectory(
            prefix="aurora-lpt-",
            dir=str(Path(manifest.path).parent),
        ) as temporary:
            temporary_root = Path(temporary)
            for jobs in candidate_jobs:
                shard_plan = lpt_builder(
                    manifest,
                    jobs,
                    temporary_root / f"j{jobs:03d}",
                )
                slowest = max(
                    shard.estimated_seconds for shard in shard_plan.shards
                )
                item = _alternative(jobs, slowest, pilot, "exact_lpt")
                alternatives.append(item)
                exact.append(item)

    selected = _choose_exact(exact, pilot, settings)
    ordered = tuple(
        sorted(
            alternatives,
            key=lambda item: (
                item.jobs,
                {"analytical": 0, "histogram": 1, "exact_lpt": 2}[
                    item.estimate_kind
                ],
            ),
        )
    )
    return JobCountDecision(
        selected_jobs=selected.jobs,
        predicted_seconds=selected.predicted_seconds,
        alternatives=ordered,
    )


def _write_json(path: Path, payload: Any) -> Path:
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


def _transport_budget_check(
    spec: RunSpec,
    shard_plan: ShardPlan,
    output_dir: Path,
) -> None:
    resources = spec.resources
    performance = spec.performance
    budget_gb = float(resources["max_artifact_gb"])
    if budget_gb <= 0:
        return
    root = Path(output_dir)
    bundle_bytes = sum(
        path.stat().st_size
        for path in (root / "assignments").glob("*.parquet")
    )
    catalog = root / "balanced_unit_assignments.parquet"
    if catalog.is_file():
        bundle_bytes += catalog.stat().st_size
    repeated_bytes = bundle_bytes * shard_plan.selected_jobs
    budget_bytes = int(budget_gb * 1024**3)
    if (
        repeated_bytes > budget_bytes
        and performance["transport_mode"] != "snapshot_backend"
    ):
        raise AssignmentTransportBudgetExceeded(
            "ASSIGNMENT_TRANSPORT_BUDGET_EXCEEDED: one repeated Actions "
            "artifact exceeds resources.max_artifact_gb"
        )


def build_execution_plan(
    spec: RunSpec,
    manifest: WorkUnitManifest,
    pilot: PilotResult,
    output_dir: Path,
    *,
    mode: str = "optimized",
    forced_job_count: int | None = None,
) -> ExecutionPlan:
    """Build the only immutable execution plan accepted by fan-out jobs."""

    root = Path(output_dir)
    settings = _settings_from_spec(spec)

    class _SpecContract:
        planner_min_jobs = settings.planner_min_jobs
        planner_max_jobs = settings.planner_max_jobs
        planner_large_unit_threshold = settings.planner_large_unit_threshold
        planner_exact_lpt_candidates_max = (
            settings.planner_exact_lpt_candidates_max
        )
        target_setup_fraction_max = settings.target_setup_fraction_max
        target_checkpoint_fraction_max = (
            settings.target_checkpoint_fraction_max
        )

    decision = choose_job_count(
        manifest,
        _SpecContract(),
        pilot,
    )
    if forced_job_count is not None:
        units = read_work_units(manifest)
        if forced_job_count < 1 or forced_job_count > min(
            len(units),
            settings.planner_max_jobs,
            360,
        ):
            raise ValueError("forced job count is outside planner bounds")
        keyed_costs = tuple(
            (unit.unit_key, unit.estimated_seconds) for unit in units
        )
        selected = _alternative(
            forced_job_count,
            _exact_lpt_slowest(keyed_costs, forced_job_count),
            pilot,
            "exact_lpt",
        )
        alternatives = tuple(
            item
            for item in decision.alternatives
            if not (
                item.jobs == forced_job_count
                and item.estimate_kind == "exact_lpt"
            )
        ) + (selected,)
        decision = JobCountDecision(
            selected_jobs=forced_job_count,
            predicted_seconds=selected.predicted_seconds,
            alternatives=tuple(
                sorted(
                    alternatives,
                    key=lambda item: (
                        item.jobs,
                        {
                            "analytical": 0,
                            "histogram": 1,
                            "exact_lpt": 2,
                        }[item.estimate_kind],
                    ),
                )
            ),
        )
    if mode == "optimized":
        shard_plan = weighted_lpt(
            manifest,
            decision.selected_jobs,
            root,
        )
        assignment_strategy = "weighted_lpt_hierarchical"
    elif mode == "baseline":
        shard_plan = equal_count(
            manifest,
            decision.selected_jobs,
            root,
        )
        assignment_strategy = "equal_count_flat"
    else:
        raise ValueError("execution mode must be optimized or baseline")
    actual_selected = _alternative(
        decision.selected_jobs,
        max(shard.estimated_seconds for shard in shard_plan.shards),
        pilot,
        "exact_lpt",
    )
    alternatives = tuple(
        item
        for item in decision.alternatives
        if not (
            item.jobs == decision.selected_jobs
            and item.estimate_kind == "exact_lpt"
        )
    ) + (actual_selected,)
    decision = JobCountDecision(
        selected_jobs=decision.selected_jobs,
        predicted_seconds=actual_selected.predicted_seconds,
        alternatives=tuple(
            sorted(
                alternatives,
                key=lambda item: (
                    item.jobs,
                    {
                        "analytical": 0,
                        "histogram": 1,
                        "exact_lpt": 2,
                    }[item.estimate_kind],
                ),
            )
        ),
    )
    _transport_budget_check(spec, shard_plan, root)
    matrix_split = split_matrices(
        shard_plan.shards,
        matrix_ceiling=int(spec.performance["matrix_max_jobs"]),
    )
    encode_matrix_outputs(
        matrix_split,
        max_bytes=int(spec.performance["max_github_output_kb"]) * 1024,
    )
    slowest = max(
        shard.estimated_seconds for shard in shard_plan.shards
    )
    target_checkpoint = settings.target_checkpoint_fraction_max
    minimum_interval = (
        pilot.checkpoint_seconds / target_checkpoint
        if target_checkpoint > 0 and pilot.checkpoint_seconds > 0
        else slowest
    )
    checkpoint_interval = min(
        slowest,
        max(1.0, minimum_interval),
    )
    exact_alternatives = [
        item
        for item in decision.alternatives
        if item.estimate_kind == "exact_lpt"
        and item.jobs != decision.selected_jobs
    ]
    fallback = min(
        exact_alternatives,
        key=lambda item: (item.predicted_seconds, item.jobs),
        default=None,
    )
    fallback_payload: Mapping[str, Any] = (
        deep_thaw_json(fallback)
        if fallback is not None
        else {
            "jobs": decision.selected_jobs,
            "predicted_seconds": decision.predicted_seconds,
        }
    )
    return ExecutionPlan(
        job_count=decision,
        shard_plan=shard_plan,
        matrix_split=matrix_split,
        assignment_strategy=assignment_strategy,
        numeric_threads=1,
        checkpoint_interval_seconds=checkpoint_interval,
        artifact_compression_level=int(
            spec.performance["artifact_compression_precompressed"]
        ),
        fallback_plan_sha256=canonical_sha256(fallback_payload),
    )


def write_execution_plan(
    plan: ExecutionPlan,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    root = Path(output_dir)
    return (
        _write_json(root / "performance_plan.json", plan.job_count),
        _write_json(root / "execution_plan.json", plan),
        _write_json(root / "balanced_shard_plan.json", plan.shard_plan),
    )


def write_pilot_result(pilot: PilotResult, path: Path) -> Path:
    return _write_json(Path(path), pilot)
