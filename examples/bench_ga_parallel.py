"""Benchmark: sequential vs joblib-parallel GA on MACross.

Run:
    uv run --with vectorbt --with deap --with joblib --with scipy --with pyarrow \
        python aurora/examples/bench_ga_parallel.py
"""
from __future__ import annotations
import os
import sys
import time

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
import pandas as pd

from aurora.core.seed import set_global_seed
from aurora.strategies.library import MACross
from aurora.ga.runner import run_ga, GAConfig
from aurora.ga.fitness import multi_objective_fitness


def _synthetic_prices(n: int = 1500, seed: int = 7) -> pd.Series:
    """Build a deterministic synthetic price series so the bench is repeatable."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.011, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2014-01-01", periods=n, freq="B")
    return pd.Series(p, index=idx, name="SYN")


def main():
    set_global_seed(42)
    prices = _synthetic_prices(1500)
    is_p = prices.iloc[:1000]
    oos_p = prices.iloc[1000:]

    pop, gens = 80, 10
    n_workers = 4

    print(f"Bench: pop={pop} gens={gens} workers={n_workers}")
    print(f"IS bars: {len(is_p)}, OOS bars: {len(oos_p)}")
    print("note: joblib speedup grows with per-individual cost. Light")
    print("      strategies (MACross) may be IPC-bound at small pop.\n")

    # Sequential
    cfg_seq = GAConfig(
        population=pop, generations=gens, seed=42, backend="sequential"
    )
    t0 = time.perf_counter()
    pareto_seq = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                       cfg_seq, verbose=False)
    t_seq = time.perf_counter() - t0
    print(f"sequential : {t_seq:7.2f}s  pareto={len(pareto_seq)}")

    # Joblib parallel
    cfg_par = GAConfig(
        population=pop, generations=gens, seed=42,
        backend="joblib", n_workers=n_workers,
    )
    t0 = time.perf_counter()
    pareto_par = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                       cfg_par, verbose=False)
    t_par = time.perf_counter() - t0
    print(f"joblib (x{n_workers}): {t_par:7.2f}s  pareto={len(pareto_par)}")

    speedup = t_seq / t_par if t_par > 0 else float("nan")
    print(f"\nspeedup    : {speedup:.2f}x")


if __name__ == "__main__":
    main()
