# ruff: noqa: N806
"""Risk measures used by portfolio optimisation and validation.

Pure functions, no state. All inputs are numpy arrays of returns (per-period
fractional returns, e.g. 0.01 = 1%) or weights / cost values.

Conventions
-----------
- ``returns`` is either a 1-D vector (single asset / portfolio path) or a
  2-D matrix shape (T, N) with rows = time, columns = assets.
- All loss-style risk measures are reported as positive numbers
  (downside ``cvar`` returns a positive loss; max drawdown returns a
  positive fraction).
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _as_1d(x: Sequence[float]) -> np.ndarray:
    arr = np.asarray(x, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    return arr


def variance(returns: Sequence[float]) -> float:
    """Sample variance (ddof=1) of a return series. Empty -> 0.0."""
    r = _as_1d(returns)
    if r.size < 2:
        return 0.0
    return float(np.var(r, ddof=1))


def semi_variance(returns: Sequence[float], threshold: float = 0.0) -> float:
    """Semi-variance below ``threshold`` (mean of squared shortfall).

    Returns 0.0 if no observations are below threshold or the series is
    too small to estimate.
    """
    r = _as_1d(returns)
    if r.size == 0:
        return 0.0
    downside = r[r < threshold]
    if downside.size == 0:
        return 0.0
    diff = downside - threshold
    return float(np.mean(diff * diff))


def cvar(returns: Sequence[float], alpha: float = 0.05) -> float:
    """Conditional VaR (expected shortfall) at the ``alpha`` left tail.

    Returns a *positive* loss number. ``alpha=0.05`` => mean of the worst
    5% of returns flipped sign. Empty input returns 0.0.
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    r = _as_1d(returns)
    if r.size == 0:
        return 0.0
    # Threshold is the alpha-quantile of returns (a negative number for
    # losing distributions).
    q = float(np.quantile(r, alpha))
    tail = r[r <= q]
    if tail.size == 0:
        return float(-q)
    return float(-np.mean(tail))


def max_drawdown(returns: Sequence[float]) -> float:
    """Maximum drawdown of a return path, reported as a positive fraction.

    Equity curve starts at 1.0 with cumulative product. MDD is the worst
    peak-to-trough loss along that path.
    """
    r = _as_1d(returns)
    if r.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    return float(np.max(drawdown))


def avg_drawdown(returns: Sequence[float]) -> float:
    """Average drawdown over the whole path (positive fraction)."""
    r = _as_1d(returns)
    if r.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    return float(np.mean(drawdown))


def turnover_aware_net_return(
    weights: Sequence[Sequence[float]] | np.ndarray,
    returns: Sequence[Sequence[float]] | np.ndarray,
    costs_bps: float = 0.0,
) -> dict[str, float]:
    """Return gross/net portfolio summary including turnover costs.

    Parameters
    ----------
    weights
        2-D array shape (T, N): allocation in effect at the start of each
        period. ``weights[0]`` is the initial allocation; the implied
        previous weight vector is zeros (full turnover from cash).
    returns
        2-D array shape (T, N): per-period asset returns aligned with
        ``weights``.
    costs_bps
        Round-trip transaction cost in basis points applied to the
        absolute weight change. Same number of bps for buys and sells.

    Returns
    -------
    dict with ``gross_return``, ``net_return``, ``turnover``, ``cost``,
    where returns are total compounded fractions over the path.
    """
    W = np.asarray(weights, dtype=float)
    R = np.asarray(returns, dtype=float)
    if W.ndim != 2 or R.ndim != 2:
        raise ValueError("weights and returns must be 2-D")
    if W.shape != R.shape:
        raise ValueError(
            f"weights shape {W.shape} != returns shape {R.shape}"
        )
    if costs_bps < 0:
        raise ValueError("costs_bps must be >= 0")

    cost_rate = float(costs_bps) / 1e4

    # Gross per-period portfolio return: w_t . r_t
    gross_per_period = np.sum(W * R, axis=1)

    # Turnover: |W_t - W_{t-1}| with W_{-1} = 0
    prev = np.vstack([np.zeros((1, W.shape[1])), W[:-1]])
    turnover_per_period = np.sum(np.abs(W - prev), axis=1)
    cost_per_period = turnover_per_period * cost_rate

    net_per_period = gross_per_period - cost_per_period

    gross_total = float(np.prod(1.0 + gross_per_period) - 1.0)
    net_total = float(np.prod(1.0 + net_per_period) - 1.0)
    turnover_total = float(np.sum(turnover_per_period))
    cost_total = float(np.sum(cost_per_period))

    return {
        "gross_return": gross_total,
        "net_return": net_total,
        "turnover": turnover_total,
        "cost": cost_total,
    }
