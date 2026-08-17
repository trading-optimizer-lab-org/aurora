"""Safe empirical selection of one-, two- or four-process runner topology."""

from __future__ import annotations

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel


class ProcessBenchmarkV1(FrozenModel):
    processes: int = Field(ge=1, le=4)
    wall_seconds: float = Field(gt=0)
    peak_memory_bytes: int = Field(ge=1)


class ProcessTopologyV1(FrozenModel):
    processes: int = Field(ge=1, le=4)
    wall_seconds: float = Field(gt=0)
    peak_memory_fraction: float = Field(gt=0)
    speedup_vs_one: float = Field(gt=0)
    selected_reason: str


def select_process_topology(
    benchmarks: list[ProcessBenchmarkV1],
    *,
    available_memory_bytes: int,
    max_memory_fraction: float = 0.70,
    minimum_parallel_speedup: float = 1.50,
) -> ProcessTopologyV1:
    by_process = {item.processes: item for item in benchmarks}
    if 1 not in by_process or available_memory_bytes < 1:
        raise ValueError("CATALOG_PROCESS_BASELINE_MISSING")
    baseline = by_process[1]
    safe = [
        item
        for item in benchmarks
        if item.peak_memory_bytes / available_memory_bytes <= max_memory_fraction
    ]
    eligible = [
        item
        for item in safe
        if item.processes == 1
        or baseline.wall_seconds / item.wall_seconds >= minimum_parallel_speedup
    ]
    selected = min(eligible, key=lambda item: (item.wall_seconds, item.processes))
    speedup = baseline.wall_seconds / selected.wall_seconds
    return ProcessTopologyV1(
        processes=selected.processes,
        wall_seconds=selected.wall_seconds,
        peak_memory_fraction=selected.peak_memory_bytes / available_memory_bytes,
        speedup_vs_one=speedup,
        selected_reason=(
            "measured_parallel_gain" if selected.processes > 1 else "safe_single_process"
        ),
    )


__all__ = ["ProcessBenchmarkV1", "ProcessTopologyV1", "select_process_topology"]
