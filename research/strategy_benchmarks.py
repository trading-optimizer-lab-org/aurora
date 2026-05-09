"""Benchmark catalogue (Candidate E).

Each strategy atlas entry declares an explicit ``benchmark_expectation``.
The benchmarks themselves are enumerated here so the comparison cannot
silently drift between callers.

A strategy is acceptable for promotion only if it *meaningfully* beats
its declared benchmark on out-of-sample data. "Meaningfully" is the
caller's policy decision; this module returns the raw metrics
(``sharpe_diff``, ``alpha_annualised``) and the boolean ``beats_benchmark``
that uses a small positive Sharpe-difference threshold by default.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np


class BenchmarkExpectation(Enum):
    """Comparison baselines that an atlas entry can declare."""

    CASH = "cash"
    BUY_AND_HOLD = "buy_and_hold"
    EQUAL_WEIGHT = "equal_weight"
    SIMPLE_MOMENTUM = "simple_momentum"
    SIMPLE_MEAN_REVERSION = "simple_mean_reversion"
    RANDOM_COMPARABLE_TURNOVER = "random_comparable_turnover"
    CURRENT_PRODUCTION = "current_production"


@dataclass(frozen=True)
class BenchmarkResult:
    """Outcome of a single strategy-vs-benchmark comparison."""

    beats_benchmark: bool
    sharpe_diff: float
    alpha_annualised: float


_PERIODS_PER_YEAR_DEFAULT = 252


def _to_array(returns: Any) -> np.ndarray:
    arr = np.asarray(returns, dtype=float).ravel()
    return arr


def _annualised_sharpe(returns: np.ndarray, periods_per_year: int) -> float:
    if returns.size == 0:
        return 0.0
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=0))
    if std == 0.0 or not np.isfinite(std):
        return 0.0
    return mean / std * np.sqrt(periods_per_year)


def _safe_align(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if a.size == 0 or b.size == 0:
        return a, b
    m = min(a.size, b.size)
    return a[:m], b[:m]


def _simple_momentum_returns(
    asset_returns: np.ndarray, lookback: int = 20
) -> np.ndarray:
    """Long if trailing ``lookback``-period sum-return is positive, else flat."""
    n = asset_returns.size
    if n == 0:
        return asset_returns.copy()
    out = np.zeros(n, dtype=float)
    for i in range(lookback, n):
        window = asset_returns[i - lookback:i]
        if np.sum(window) > 0:
            out[i] = asset_returns[i]
    return out


def _simple_mean_reversion_returns(
    asset_returns: np.ndarray, lookback: int = 5
) -> np.ndarray:
    """Long if trailing ``lookback``-period sum-return is negative, else flat."""
    n = asset_returns.size
    if n == 0:
        return asset_returns.copy()
    out = np.zeros(n, dtype=float)
    for i in range(lookback, n):
        window = asset_returns[i - lookback:i]
        if np.sum(window) < 0:
            out[i] = asset_returns[i]
    return out


def _random_comparable_turnover(
    asset_returns: np.ndarray, seed: int = 0
) -> np.ndarray:
    """Random sign sequence with the same magnitude as ``asset_returns``."""
    n = asset_returns.size
    if n == 0:
        return asset_returns.copy()
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=n)
    return signs * asset_returns


def _benchmark_returns(
    benchmark: BenchmarkExpectation,
    asset_returns: np.ndarray,
    *,
    production_returns: np.ndarray | None = None,
) -> np.ndarray:
    if benchmark is BenchmarkExpectation.CASH:
        return np.zeros_like(asset_returns)
    if benchmark is BenchmarkExpectation.BUY_AND_HOLD:
        return asset_returns.copy()
    if benchmark is BenchmarkExpectation.EQUAL_WEIGHT:
        # Single-asset case degrades to buy-and-hold; multi-asset callers
        # should pre-aggregate into ``asset_returns``.
        return asset_returns.copy()
    if benchmark is BenchmarkExpectation.SIMPLE_MOMENTUM:
        return _simple_momentum_returns(asset_returns)
    if benchmark is BenchmarkExpectation.SIMPLE_MEAN_REVERSION:
        return _simple_mean_reversion_returns(asset_returns)
    if benchmark is BenchmarkExpectation.RANDOM_COMPARABLE_TURNOVER:
        return _random_comparable_turnover(asset_returns)
    if benchmark is BenchmarkExpectation.CURRENT_PRODUCTION:
        if production_returns is None:
            # No production reference supplied; treat as cash so the
            # comparison still produces finite numbers.
            return np.zeros_like(asset_returns)
        prod = _to_array(production_returns)
        if prod.size != asset_returns.size:
            prod, _ = _safe_align(prod, asset_returns)
            pad = asset_returns.size - prod.size
            if pad > 0:
                prod = np.concatenate([np.zeros(pad), prod])
        return prod
    raise ValueError(f"Unhandled BenchmarkExpectation: {benchmark!r}")


def evaluate_against_benchmark(
    strategy_returns: Any,
    benchmark: BenchmarkExpectation,
    asset_returns: Any,
    *,
    periods_per_year: int = _PERIODS_PER_YEAR_DEFAULT,
    production_returns: Any | None = None,
    sharpe_diff_threshold: float = 0.0,
) -> BenchmarkResult:
    """Compare ``strategy_returns`` against the chosen benchmark.

    Parameters
    ----------
    strategy_returns:
        Per-period strategy returns (decimal, e.g. 0.001 = 10bps).
    benchmark:
        Which baseline to compare against.
    asset_returns:
        Per-period underlying-asset returns. Used to construct the
        benchmark series for momentum / mean-reversion / random
        baselines.
    periods_per_year:
        Annualisation factor for Sharpe / alpha. Defaults to 252.
    production_returns:
        Required only when ``benchmark`` is
        :attr:`BenchmarkExpectation.CURRENT_PRODUCTION`.
    sharpe_diff_threshold:
        ``beats_benchmark`` is True iff
        ``sharpe_diff > sharpe_diff_threshold``.
    """
    s = _to_array(strategy_returns)
    a = _to_array(asset_returns)
    s, a = _safe_align(s, a)

    prod = _to_array(production_returns) if production_returns is not None else None
    b = _benchmark_returns(benchmark, a, production_returns=prod)
    s, b = _safe_align(s, b)

    sharpe_strategy = _annualised_sharpe(s, periods_per_year)
    sharpe_benchmark = _annualised_sharpe(b, periods_per_year)
    sharpe_diff = float(sharpe_strategy - sharpe_benchmark)

    if s.size == 0:
        alpha_annualised = 0.0
    else:
        excess = s - b
        alpha_annualised = float(np.mean(excess) * periods_per_year)

    if not np.isfinite(sharpe_diff):
        sharpe_diff = 0.0
    if not np.isfinite(alpha_annualised):
        alpha_annualised = 0.0

    return BenchmarkResult(
        beats_benchmark=bool(sharpe_diff > sharpe_diff_threshold),
        sharpe_diff=sharpe_diff,
        alpha_annualised=alpha_annualised,
    )


__all__ = [
    "BenchmarkExpectation",
    "BenchmarkResult",
    "evaluate_against_benchmark",
]
