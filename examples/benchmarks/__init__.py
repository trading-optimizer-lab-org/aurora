"""Performance benchmark scaffold (R40).

Contains the four representative benchmarks the project uses to gate
R5 (GPU triage) and R6 (Rust core engine) against measurement, not
enthusiasm:

- :func:`bench_triage_10k` -- triage 10,000 variants.
- :func:`bench_validation_pipeline` -- full validation gate run.
- :func:`bench_ga_loop` -- single GA fitness loop.
- :func:`bench_single_asset_30y` -- 30-year backtest on one asset.

Each entrypoint returns a :class:`BenchmarkResult` with wall-clock
timing, peak RSS, and a deterministic content hash so regressions are
flaggable in CI.

Run directly:

    python -m quantforge.examples.benchmarks all

or import for ad-hoc profiling:

    from quantforge.examples.benchmarks import bench_single_asset_30y
    res = bench_single_asset_30y(seed=42)
"""
from __future__ import annotations

from .runner import (
    BenchmarkResult,
    bench_ga_loop,
    bench_single_asset_30y,
    bench_triage_10k,
    bench_validation_pipeline,
    run_all,
)


__all__ = [
    "BenchmarkResult",
    "bench_triage_10k",
    "bench_validation_pipeline",
    "bench_ga_loop",
    "bench_single_asset_30y",
    "run_all",
]
