"""Bootstrap confidence intervals on metrics (R104).

Today ``compute_metrics`` returns point estimates. For ranking
strategies and especially for promotion decisions, callers need a
confidence interval too: a strategy whose 95% CI on Sharpe spans zero
is not actually a positive-edge strategy regardless of point
estimate.

This module wraps ``compute_metrics`` with a bootstrap resampler. The
bootstrap is the standard non-parametric CI: resample period returns
with replacement N times, recompute the metric on each resample,
report the (alpha/2, 1-alpha/2) percentile interval.

Default: 1000 resamples, alpha=0.05 -> 95% CI. Stationary block
bootstrap is available for return series with autocorrelation; the
default IID bootstrap is appropriate for daily-rebalance equity-curve
returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from quantforge.core.metrics import compute_metrics


@dataclass(frozen=True)
class MetricCI:
    """Point estimate plus bootstrap CI for a single metric."""

    name: str
    point: float
    lower: float
    upper: float
    n_resamples: int
    alpha: float

    @property
    def width(self) -> float:
        if not (np.isfinite(self.lower) and np.isfinite(self.upper)):
            return float("nan")
        return self.upper - self.lower

    @property
    def includes_zero(self) -> bool:
        return self.lower <= 0.0 <= self.upper


@dataclass(frozen=True)
class MetricCIBundle:
    """CI bundle for the headline metrics."""

    sharpe: MetricCI
    sortino: MetricCI
    calmar: MetricCI
    cagr: MetricCI
    mdd: MetricCI
    win_rate: MetricCI
    profit_factor: MetricCI


def _percentile_ci(
    samples: np.ndarray,
    alpha: float,
) -> tuple[float, float]:
    finite = samples[np.isfinite(samples)]
    if len(finite) < 2:
        return float("nan"), float("nan")
    lo = float(np.percentile(finite, 100.0 * alpha / 2))
    hi = float(np.percentile(finite, 100.0 * (1.0 - alpha / 2)))
    return lo, hi


def _iid_resample(returns: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    n = len(returns)
    idx = rng.integers(0, n, size=n)
    return returns[idx]


def _block_resample(
    returns: np.ndarray,
    rng: np.random.Generator,
    block_size: int,
) -> np.ndarray:
    n = len(returns)
    if block_size < 1:
        block_size = 1
    n_blocks = (n + block_size - 1) // block_size
    starts = rng.integers(0, n, size=n_blocks)
    out = np.concatenate([
        returns[start: start + block_size] for start in starts
    ])
    return out[:n]


def bootstrap_metric_cis(
    returns: np.ndarray,
    *,
    ppy: int = 252,
    n_resamples: int = 1000,
    alpha: float = 0.05,
    block_size: Optional[int] = None,
    seed: int = 42,
) -> MetricCIBundle:
    """Bootstrap confidence intervals for the headline metric set.

    Args:
        returns: 1-D period returns array.
        ppy: periods per year.
        n_resamples: bootstrap iterations.
        alpha: two-sided confidence level. Default 0.05 -> 95% CI.
        block_size: when set, use stationary block bootstrap with this
            block length (in bars). When None, use plain IID resampling.
        seed: RNG seed for reproducibility.

    Returns:
        :class:`MetricCIBundle` with one :class:`MetricCI` per headline
        metric.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    rng = np.random.default_rng(seed)
    point = compute_metrics(returns, ppy=ppy)
    arr = np.asarray(returns, dtype=float)

    sharpes: list[float] = []
    sortinos: list[float] = []
    calmars: list[float] = []
    cagrs: list[float] = []
    mdds: list[float] = []
    win_rates: list[float] = []
    profit_factors: list[float] = []

    for _ in range(n_resamples):
        if block_size is None:
            sample = _iid_resample(arr, rng)
        else:
            sample = _block_resample(arr, rng, block_size)
        m = compute_metrics(sample, ppy=ppy)
        sharpes.append(m.sharpe)
        sortinos.append(m.sortino)
        calmars.append(m.calmar)
        cagrs.append(m.cagr)
        mdds.append(m.mdd)
        win_rates.append(m.win_rate)
        profit_factors.append(m.profit_factor)

    def _bundle(name: str, point_value: float, samples: list[float]) -> MetricCI:
        lo, hi = _percentile_ci(np.asarray(samples), alpha)
        return MetricCI(
            name=name,
            point=float(point_value),
            lower=lo,
            upper=hi,
            n_resamples=n_resamples,
            alpha=alpha,
        )

    return MetricCIBundle(
        sharpe=_bundle("sharpe", point.sharpe, sharpes),
        sortino=_bundle("sortino", point.sortino, sortinos),
        calmar=_bundle("calmar", point.calmar, calmars),
        cagr=_bundle("cagr", point.cagr, cagrs),
        mdd=_bundle("mdd", point.mdd, mdds),
        win_rate=_bundle("win_rate", point.win_rate, win_rates),
        profit_factor=_bundle("profit_factor", point.profit_factor, profit_factors),
    )


__all__ = [
    "MetricCI",
    "MetricCIBundle",
    "bootstrap_metric_cis",
]
