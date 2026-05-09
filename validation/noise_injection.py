"""Noise injection robustness test.

Inject gaussian price noise, re-run strategy, measure metric stability.
A robust strategy should keep its Calmar within ~30% of the noise-free baseline
under modest noise (~10 bps per bar).
"""
from __future__ import annotations
import warnings
from dataclasses import dataclass
from typing import Callable
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, ZERO_costs
from aurora.core.seed import child_rng


@dataclass
class NoiseInjectionResult:
    base_calmar: float
    base_sharpe: float
    perturbed_calmars: np.ndarray  # one per noise sample
    perturbed_sharpes: np.ndarray
    calmar_p5: float   # 5th percentile (worst-case under noise)
    calmar_p50: float
    calmar_p95: float
    calmar_drop_pct: float  # (base - p50) / base * 100
    n_samples: int
    noise_sigma_bps: float

    def passes(self, max_drop_pct: float = 30.0) -> bool:
        """Robust if median Calmar dropped less than max_drop_pct vs base."""
        return self.calmar_drop_pct < max_drop_pct


def noise_injection(strategy_factory: Callable, prices: pd.Series,
                    costs: CostModel = ZERO_costs, n_samples: int = 100,
                    noise_sigma_bps: float = 10.0, ppy: int = 252,
                    seed_name: str = "noise_injection") -> NoiseInjectionResult:
    """Inject gaussian noise into prices, re-run strategy, measure metric stability.

    Args:
        strategy_factory: callable() -> Strategy (fresh instance per sample)
        prices: pd.Series of base prices (DatetimeIndex)
        costs: CostModel
        n_samples: noise paths
        noise_sigma_bps: gaussian sigma in basis points (10 = 0.1% per bar)
        ppy: periods/year
        seed_name: child RNG name for reproducibility

    Returns:
        NoiseInjectionResult with distribution of metrics under noise.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be pd.Series with DatetimeIndex")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be DatetimeIndex")
    if n_samples < 1:
        raise ValueError(f"n_samples must be >= 1 (got {n_samples})")
    if noise_sigma_bps < 0:
        raise ValueError(f"noise_sigma_bps must be >= 0 (got {noise_sigma_bps})")
    # Validate fractional noise magnitude: noise_pct = sigma_bps / 1e4 must lie
    # in [-0.5, 0.5]. Anything beyond that produces near-certain non-positive
    # prices and silent clipping that masks the strategy under test.
    noise_pct = noise_sigma_bps / 1e4
    if not (-0.5 <= noise_pct <= 0.5):
        raise ValueError(
            f"noise_pct (sigma_bps/1e4) must be in [-0.5, 0.5] "
            f"(got noise_pct={noise_pct:.4f}, sigma_bps={noise_sigma_bps})"
        )

    # Baseline: noise-free run
    base_strat = strategy_factory()
    base_res = run_backtest(prices, base_strat.signals, costs=costs, ppy=ppy)
    base_calmar = float(base_res.calmar)
    base_sharpe = float(base_res.sharpe)

    sigma = noise_sigma_bps / 1e4  # bps -> fractional
    rng = child_rng(seed_name)
    base_p = prices.values.astype(float)
    n = len(base_p)

    perturbed_calmars = np.zeros(n_samples)
    perturbed_sharpes = np.zeros(n_samples)

    # Clip warnings are aggregated and emitted once at the end so a noisy run
    # over hundreds of samples does not flood the caller's stderr with one
    # UserWarning per offending bar. We track total clipped bars and the
    # number of distinct paths affected so the single end-of-run warning has
    # enough information to act on.
    n_clipped_paths = 0
    n_clipped_bars_total = 0
    for k in range(n_samples):
        noise = rng.normal(0.0, sigma, n)
        noisy = base_p * (1.0 + noise)
        clip_mask = noisy <= 0
        if clip_mask.any():
            n_clipped_paths += 1
            n_clipped_bars_total += int(clip_mask.sum())
        noisy = np.maximum(noisy, 1e-9)
        noisy_prices = pd.Series(noisy, index=prices.index, name=prices.name)
        strat = strategy_factory()
        res = run_backtest(noisy_prices, strat.signals, costs=costs, ppy=ppy)
        perturbed_calmars[k] = float(res.calmar)
        perturbed_sharpes[k] = float(res.sharpe)

    if n_clipped_paths > 0:
        warnings.warn(
            f"noise_injection: {n_clipped_paths}/{n_samples} sample paths "
            f"required clipping ({n_clipped_bars_total} bars total clipped to "
            f"1e-9; noise_sigma_bps={noise_sigma_bps}). Consider lowering the "
            "noise sigma if the clip ratio exceeds a few percent.",
            UserWarning,
            stacklevel=2,
        )

    p5 = float(np.percentile(perturbed_calmars, 5))
    p50 = float(np.percentile(perturbed_calmars, 50))
    p95 = float(np.percentile(perturbed_calmars, 95))

    if abs(base_calmar) > 1e-9:
        drop_pct = float((base_calmar - p50) / base_calmar * 100.0)
    else:
        drop_pct = 0.0

    return NoiseInjectionResult(
        base_calmar=base_calmar,
        base_sharpe=base_sharpe,
        perturbed_calmars=perturbed_calmars,
        perturbed_sharpes=perturbed_sharpes,
        calmar_p5=p5,
        calmar_p50=p50,
        calmar_p95=p95,
        calmar_drop_pct=drop_pct,
        n_samples=n_samples,
        noise_sigma_bps=noise_sigma_bps,
    )
