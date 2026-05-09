"""Gap event simulation robustness test.

Inject simulated price gaps (sudden, permanent jumps) at random dates and
re-run the strategy. Unlike noise injection (transient per-bar perturbation),
a gap shifts ALL subsequent prices by the same factor: the jump is permanent
and propagates forward.

A robust strategy should not see its Calmar collapse or its MDD blow up
under modest gap regimes (e.g. 5 gaps of <=5% per path).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, ZERO_costs
from aurora.core.seed import child_rng


@dataclass
class GapSimResult:
    base_calmar: float
    base_mdd: float
    perturbed_calmars: np.ndarray
    perturbed_mdds: np.ndarray
    calmar_p5: float
    calmar_p50: float
    mdd_p5: float
    mdd_p50: float
    n_samples: int
    n_gaps_per_path: int
    gap_size_pct_max: float

    def passes(self, max_calmar_drop_pct: float = 40.0,
               max_mdd_increase_pct: float = 50.0) -> bool:
        """Pass if calmar drop < threshold AND mdd doesn't blow out.

        - Calmar drop: (base - p50) / |base| * 100 < max_calmar_drop_pct
        - MDD blow-out: |p5_mdd| / |base_mdd| - 1 < max_mdd_increase_pct/100
          (mdd is negative; p5 is the worst 5% so most negative)
        """
        if abs(self.base_calmar) > 1e-9:
            calmar_drop = (self.base_calmar - self.calmar_p50) / abs(self.base_calmar) * 100.0
        else:
            calmar_drop = 0.0
        calmar_ok = calmar_drop < max_calmar_drop_pct

        if abs(self.base_mdd) > 1e-9:
            # mdd is negative pct; "increase" = more negative
            mdd_increase_pct = (abs(self.mdd_p5) / abs(self.base_mdd) - 1.0) * 100.0
        else:
            mdd_increase_pct = 0.0
        mdd_ok = mdd_increase_pct < max_mdd_increase_pct

        return bool(calmar_ok and mdd_ok)


def gap_sim(strategy_factory: Callable, prices: pd.Series,
            costs: CostModel = ZERO_costs, n_samples: int = 100,
            n_gaps_per_path: int = 5, gap_size_pct_max: float = 0.05,
            ppy: int = 252, seed_name: str = "gap_sim") -> GapSimResult:
    """Inject simulated gap events at random dates, test resilience.

    Each path:
      - Sample n_gaps random bar indices (uniform, exclude first 100 bars warmup)
      - At each: multiply prices[gap_idx:] by (1 + sign * gap_size) where sign
        is random in {-1, +1} and gap_size is uniform in (0, gap_size_pct_max]
      - Run strategy on perturbed series, record Calmar and MDD

    Note: gap propagates FORWARD permanently (different from noise which is
    transient per bar).

    Args:
        strategy_factory: callable() -> Strategy (fresh instance per sample)
        prices: pd.Series of base prices (DatetimeIndex)
        costs: CostModel
        n_samples: number of perturbed paths
        n_gaps_per_path: gaps injected per path (0 = no perturbation)
        gap_size_pct_max: maximum |gap| as fraction of price (e.g. 0.05 = 5%)
        ppy: periods/year
        seed_name: child RNG name for reproducibility

    Returns:
        GapSimResult with distribution of metrics under gap regimes.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be pd.Series with DatetimeIndex")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be DatetimeIndex")
    if n_samples < 1:
        raise ValueError(f"n_samples must be >= 1 (got {n_samples})")
    if n_gaps_per_path < 0:
        raise ValueError(f"n_gaps_per_path must be >= 0 (got {n_gaps_per_path})")
    if gap_size_pct_max < 0:
        raise ValueError(f"gap_size_pct_max must be >= 0 (got {gap_size_pct_max})")

    # Baseline: gap-free run
    base_strat = strategy_factory()
    base_res = run_backtest(prices, base_strat.signals, costs=costs, ppy=ppy)
    base_calmar = float(base_res.calmar)
    base_mdd = float(base_res.mdd)

    rng = child_rng(seed_name)
    base_p = prices.values.astype(float)
    n = len(base_p)

    # warmup: skip first 100 bars (or 5% of series if shorter) for gap candidates
    warmup = min(100, max(1, n // 20))
    if warmup >= n:
        raise ValueError(f"prices too short ({n}) for warmup")

    perturbed_calmars = np.zeros(n_samples)
    perturbed_mdds = np.zeros(n_samples)

    for k in range(n_samples):
        perturbed = base_p.copy()
        if n_gaps_per_path > 0 and gap_size_pct_max > 0:
            # Sample UNIQUE gap indices in [warmup, n). Replacement would let
            # two gaps land on the same bar and double-multiply the forward
            # propagation, biasing tail outcomes. Cap n_gaps to the available
            # candidate count when the warmup window is unusually large.
            candidates = np.arange(warmup, n)
            n_take = min(n_gaps_per_path, len(candidates))
            gap_idxs = rng.choice(candidates, size=n_take, replace=False)
            signs = rng.choice([-1.0, 1.0], size=n_take)
            sizes = rng.uniform(0.0, gap_size_pct_max, size=n_take)
            # Apply gaps in chronological order so the multiplicative
            # propagation composes correctly even if rng.choice shuffles them.
            order = np.argsort(gap_idxs)
            for gi, sg, sz in zip(gap_idxs[order], signs[order], sizes[order]):
                factor = 1.0 + sg * sz
                # propagate: shift permanent, multiply forward
                perturbed[gi:] = perturbed[gi:] * factor
        # guard against non-positive prices (extreme cumulative downside)
        perturbed = np.maximum(perturbed, 1e-9)
        perturbed_prices = pd.Series(perturbed, index=prices.index, name=prices.name)
        strat = strategy_factory()
        res = run_backtest(perturbed_prices, strat.signals, costs=costs, ppy=ppy)
        perturbed_calmars[k] = float(res.calmar)
        perturbed_mdds[k] = float(res.mdd)

    calmar_p5 = float(np.percentile(perturbed_calmars, 5))
    calmar_p50 = float(np.percentile(perturbed_calmars, 50))
    # MDD is negative pct; p5 = worst (most negative) 5%
    mdd_p5 = float(np.percentile(perturbed_mdds, 5))
    mdd_p50 = float(np.percentile(perturbed_mdds, 50))

    return GapSimResult(
        base_calmar=base_calmar,
        base_mdd=base_mdd,
        perturbed_calmars=perturbed_calmars,
        perturbed_mdds=perturbed_mdds,
        calmar_p5=calmar_p5,
        calmar_p50=calmar_p50,
        mdd_p5=mdd_p5,
        mdd_p50=mdd_p50,
        n_samples=n_samples,
        n_gaps_per_path=n_gaps_per_path,
        gap_size_pct_max=gap_size_pct_max,
    )
