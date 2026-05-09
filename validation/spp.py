"""System Parameter Permutation (SPP).

For each integer/float parameter, perturb +-N% and re-run backtest.
Compute variance of metrics across perturbed neighborhood.
If variance > threshold -> parameter is "magic", strategy depends on exact value -> reject.

Approach:
- For each param, sample 5 values: -2*step, -1*step, 0, +1*step, +2*step
  where step = perturb * range_size
- Build full or random subset of parameter grid
- Compute Calmar, Sharpe for each combo
- Report std/mean ratio. If > threshold -> fragile.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
from itertools import product
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

from quantforge.core.engine import run_backtest
from quantforge.core.costs import CostModel, ZERO_costs


def _spp_worker(args):
    """Top-level worker: evaluate one parameter combo. Module-level so
    ProcessPoolExecutor can pickle it on Windows.
    Returns (calmar, sharpe) or None on failure.
    """
    factory, keys, combo, prices, costs, ppy = args
    try:
        params = dict(zip(keys, combo))
        strat = factory(**params)
        res = run_backtest(prices, strat.signals, costs=costs, ppy=ppy)
        return (float(res.calmar), float(res.sharpe))
    except Exception:
        return None


@dataclass
class SPPResult:
    base_calmar: float
    base_sharpe: float
    perturbed_calmars: list[float]
    perturbed_sharpes: list[float]
    calmar_mean: float
    calmar_std: float
    calmar_cv: float  # coefficient of variation = std / |mean|
    n_perturbations: int
    worker_seeds: list[int] = field(default_factory=list)

    def passes(self, max_cv: float = 0.30) -> bool:
        """Pass if coefficient of variation of Calmar < max_cv."""
        return self.calmar_cv < max_cv and self.calmar_mean > 0


def spp(strategy_factory_with_params: Callable, prices: pd.Series,
        param_ranges: dict, perturb: float = 0.10, n_steps: int = 3,
        costs: CostModel = ZERO_costs, ppy: int = 252,
        max_combinations: int = 100, seed_name: str = "spp",
        center_on: str = "midpoint",
        current_params: dict | None = None,
        n_workers: int = 1,
        parent_seed: int | None = None) -> SPPResult:
    """Run SPP test.

    Args:
        strategy_factory_with_params: callable(**params) -> Strategy
        prices: full price series (will be backtested as-is)
        param_ranges: dict[name -> (low, high) or list of values]
                     for current best params being tested
        perturb: fractional perturbation (0.10 = +-10%)
        n_steps: per-param values to sample (e.g. 3 = -1, 0, +1 step)
        costs: CostModel
        ppy: periods/year
        max_combinations: cap to avoid combinatorial explosion (random subset if exceeded)
        seed_name: child RNG name
        center_on: 'midpoint' (default) centers the grid around (lo+hi)/2.
                   'current' centers each grid around the corresponding key in
                   ``current_params`` (required when ``center_on='current'``).
        current_params: dict[name -> value] used when ``center_on='current'``.
        n_workers: number of parallel workers (1 = serial). When > 1, child seeds
                   are derived deterministically from ``parent_seed`` (or the
                   global seed via ``child_rng(seed_name)``) using
                   ``np.random.SeedSequence(parent_seed).spawn(n_workers)`` so
                   worker RNGs are independent (correlated arithmetic
                   "parent_seed + wid * 17" was replaced because adjacent
                   workers shared low bits and therefore correlated streams).
        parent_seed: explicit parent seed for worker child seeds. When None,
                     it is derived from ``child_rng(seed_name)`` so workers
                     remain reproducible across runs with the same global seed.

    Returns:
        SPPResult
    """
    if center_on not in ("midpoint", "current"):
        raise ValueError(f"center_on must be 'midpoint' or 'current' (got {center_on!r})")
    if center_on == "current" and not current_params:
        raise ValueError("center_on='current' requires current_params dict")
    active_params = current_params if current_params is not None else {}

    from quantforge.core.seed import child_rng
    rng = child_rng(seed_name)

    # Derive a deterministic parent seed for child workers when not provided.
    if parent_seed is None:
        parent_seed = int(rng.integers(0, 2**31 - 1))

    # Deterministic, independent child seeds for each worker id via numpy
    # SeedSequence.spawn. The earlier ``parent_seed + wid * 17`` recipe gave
    # correlated bit patterns across adjacent workers (low-order bits shared);
    # SeedSequence.spawn produces high-quality independent streams.
    n_w = max(1, int(n_workers))
    seed_seq = np.random.SeedSequence(parent_seed)
    worker_seeds = [int(s.generate_state(1, dtype=np.uint32)[0]) for s in seed_seq.spawn(n_w)]

    # base params = midpoint of each range (or current value if scalar)
    # For SPP we need a "current best" set. The caller should pass param_ranges
    # representing the neighborhood already centered on best.
    keys = list(param_ranges.keys())
    grids = []
    for k in keys:
        rng_k = param_ranges[k]
        if isinstance(rng_k, list):
            grids.append(rng_k[:n_steps])
        else:
            lo, hi = rng_k
            if center_on == "current":
                if k not in active_params:
                    raise ValueError(
                        f"center_on='current' but key {k!r} missing from current_params"
                    )
                mid = active_params[k]
            else:
                mid = (lo + hi) / 2
            step = (hi - lo) / 2 * perturb
            vals = np.linspace(mid - step, mid + step, n_steps)
            # cast to int if range bounds are ints
            if isinstance(lo, int) and isinstance(hi, int):
                vals = [int(round(v)) for v in vals]
            grids.append(list(vals))

    combos = list(product(*grids))
    if len(combos) > max_combinations:
        idx = rng.choice(len(combos), max_combinations, replace=False)
        combos = [combos[i] for i in idx]

    perturbed_calmars = []
    perturbed_sharpes = []
    use_parallel = n_w > 1
    if use_parallel:
        # Try ProcessPoolExecutor; fall back to serial if the factory or
        # arguments cannot be pickled (closures, inner functions, etc).
        worker_args = [
            (strategy_factory_with_params, keys, c, prices, costs, ppy)
            for c in combos
        ]
        results = []
        try:
            with ProcessPoolExecutor(max_workers=n_w) as ex:
                results = list(ex.map(_spp_worker, worker_args))
        except Exception:
            use_parallel = False
        else:
            for r in results:
                if r is None:
                    continue
                perturbed_calmars.append(r[0])
                perturbed_sharpes.append(r[1])
    if not use_parallel:
        for combo in combos:
            params = dict(zip(keys, combo))
            try:
                strat = strategy_factory_with_params(**params)
                res = run_backtest(prices, strat.signals, costs=costs, ppy=ppy)
                perturbed_calmars.append(res.calmar)
                perturbed_sharpes.append(res.sharpe)
            except Exception:
                continue

    if len(perturbed_calmars) == 0:
        return SPPResult(0, 0, [], [], 0, 0, np.inf, 0, worker_seeds=worker_seeds)

    arr = np.array(perturbed_calmars)
    mean = float(arr.mean()); std = float(arr.std())
    cv = std / abs(mean) if abs(mean) > 1e-9 else np.inf

    # base = central combo. When center_on='current' the user has supplied an
    # exact "current best" parameter set, so use those values directly rather
    # than the grid median (which can drift by half a step when current_params
    # falls between grid points). For 'midpoint' centering the grid median is
    # the desired centre, so the legacy choice is preserved.
    if center_on == "current":
        base_combo = tuple(active_params[k] for k in keys)
    else:
        base_combo = tuple((g[len(g)//2] if len(g) > 0 else None) for g in grids)
    try:
        base_strat = strategy_factory_with_params(**dict(zip(keys, base_combo)))
        base_res = run_backtest(prices, base_strat.signals, costs=costs, ppy=ppy)
        base_cal = base_res.calmar; base_sh = base_res.sharpe
    except Exception:
        base_cal = mean; base_sh = float(np.mean(perturbed_sharpes))

    return SPPResult(
        base_calmar=base_cal,
        base_sharpe=base_sh,
        perturbed_calmars=perturbed_calmars,
        perturbed_sharpes=perturbed_sharpes,
        calmar_mean=mean,
        calmar_std=std,
        calmar_cv=cv,
        n_perturbations=len(perturbed_calmars),
        worker_seeds=worker_seeds,
    )
