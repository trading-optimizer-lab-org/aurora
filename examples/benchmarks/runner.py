"""Benchmark runner primitives (R40).

Each ``bench_*`` function exercises one slice of the pipeline at a
representative size, runs deterministically (fixed seed), and returns
a :class:`BenchmarkResult`. The CI nightly compares the latest run to
a committed baseline and flags regressions outside the tolerance.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np

from aurora.core.costs import IBKR_costs
from aurora.core.metrics import compute_metrics


@dataclass(frozen=True)
class BenchmarkResult:
    """One benchmark run."""

    name: str
    wall_seconds: float
    output_hash: str
    extra: Dict[str, Any]


def _hash_array(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def bench_triage_10k(*, seed: int = 42) -> BenchmarkResult:
    """Score 10,000 random strategy variants against a fixed return path.

    Stand-in for the real triage step: compute a Sharpe per random
    weight permutation. The cost dominates real triage too (Sharpe is
    O(N) in the permutation count).
    """
    rng = np.random.default_rng(seed)
    asset_returns = rng.normal(0.0005, 0.01, size=2_500)
    sharpes = np.zeros(10_000, dtype=float)
    t0 = time.perf_counter()
    for i in range(10_000):
        weights = rng.choice([-1.0, 0.0, 1.0], size=len(asset_returns))
        net = weights * asset_returns
        sharpes[i] = compute_metrics(net, ppy=252).sharpe
    wall = time.perf_counter() - t0
    return BenchmarkResult(
        name="triage_10k",
        wall_seconds=wall,
        output_hash=_hash_array(sharpes),
        extra={"n_variants": 10_000, "n_bars": len(asset_returns)},
    )


def bench_validation_pipeline(*, seed: int = 42) -> BenchmarkResult:
    """Stand-in for the full validation pipeline.

    The full pipeline drives nine validation gates; this scaffold
    exercises a representative single-gate compute (Monte Carlo on
    bootstrap returns + metrics) at the size the real pipeline uses.
    """
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0005, 0.01, size=2_500)
    n_resamples = 1_000
    t0 = time.perf_counter()
    sharpes = np.zeros(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, len(base), size=len(base))
        sharpes[i] = compute_metrics(base[idx], ppy=252).sharpe
    wall = time.perf_counter() - t0
    return BenchmarkResult(
        name="validation_pipeline",
        wall_seconds=wall,
        output_hash=_hash_array(sharpes),
        extra={"n_resamples": n_resamples},
    )


def bench_ga_loop(*, seed: int = 42, generations: int = 20,
                  population: int = 50) -> BenchmarkResult:
    """One GA fitness loop at a representative population / generation count."""
    rng = np.random.default_rng(seed)
    base_returns = rng.normal(0.0005, 0.01, size=1_000)
    best = -np.inf
    best_history: List[float] = []
    t0 = time.perf_counter()
    for _ in range(generations):
        gen_best = -np.inf
        for _ in range(population):
            weights = rng.choice([-1.0, 0.0, 1.0], size=len(base_returns))
            sharpe = float(compute_metrics(weights * base_returns, ppy=252).sharpe)
            if sharpe > gen_best:
                gen_best = sharpe
        if gen_best > best:
            best = gen_best
        best_history.append(best)
    wall = time.perf_counter() - t0
    return BenchmarkResult(
        name="ga_loop",
        wall_seconds=wall,
        output_hash=_hash_array(np.asarray(best_history)),
        extra={"generations": generations, "population": population},
    )


def bench_single_asset_30y(*, seed: int = 42) -> BenchmarkResult:
    """30-year daily backtest on a synthetic single asset with realistic costs."""
    n_bars = 252 * 30
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.01, size=n_bars)
    weights = (np.cumsum(rets) > 0).astype(float)
    from aurora.core.costs import apply_costs
    t0 = time.perf_counter()
    net = apply_costs(weights, rets, IBKR_costs)
    metrics = compute_metrics(net, ppy=252)
    wall = time.perf_counter() - t0
    return BenchmarkResult(
        name="single_asset_30y",
        wall_seconds=wall,
        output_hash=_hash_array(net),
        extra={
            "n_bars": n_bars,
            "sharpe": float(metrics.sharpe),
            "calmar": float(metrics.calmar),
        },
    )


def run_all(*, seed: int = 42) -> List[BenchmarkResult]:
    """Run every benchmark and return the result list."""
    return [
        bench_triage_10k(seed=seed),
        bench_validation_pipeline(seed=seed),
        bench_ga_loop(seed=seed),
        bench_single_asset_30y(seed=seed),
    ]


__all__ = [
    "BenchmarkResult",
    "bench_triage_10k",
    "bench_validation_pipeline",
    "bench_ga_loop",
    "bench_single_asset_30y",
    "run_all",
]
