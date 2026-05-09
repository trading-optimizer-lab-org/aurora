"""Return-based metrics."""
from __future__ import annotations
import math
import numpy as np

from aurora.analytics.metrics_full._helpers import _to_array


def compounded_return(returns) -> float:
    """Total compounded return: prod(1 + r) - 1."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    return float(np.prod(1.0 + r) - 1.0)


def total_return(returns) -> float:
    """Alias of compounded_return."""
    return compounded_return(returns)


def cagr(returns, ppy: int = 252) -> float:
    """Compound annual growth rate.

    A wiped-out portfolio (``final <= 0``) returns ``-1.0`` (i.e. -100%)
    rather than 0.0 so callers do not mistake ruin for a zero return.

    Note: this differs from ``core.metrics.compute_metrics`` (cagr branch),
    which annualizes against the *raw* input length (warm-up NaN bars count
    as calendar time). This standalone function annualizes against the
    cleaned, finite-only series length. Pick the function that matches the
    series the caller is feeding in.
    """
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    final = float(np.prod(1.0 + r))
    years = len(r) / ppy
    if years <= 0:
        return 0.0
    if final <= 0.0:
        # Total ruin: the portfolio is worthless. CAGR is mathematically
        # undefined for non-positive terminal wealth; report -100% so
        # downstream Calmar / MAR comparisons reflect the loss.
        return -1.0
    return final ** (1.0 / years) - 1.0


def annualized_return(returns, ppy: int = 252) -> float:
    """Arithmetic annualized return: mean(r) * ppy."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    return float(r.mean() * ppy)


def expected_return(returns, freq: str = "daily") -> float:
    """Geometric mean per period (geometric expected return)."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    return float(np.prod(1.0 + r) ** (1.0 / len(r)) - 1.0)


def geometric_mean(returns) -> float:
    """Geometric mean of returns (per-period)."""
    return expected_return(returns)


def ghpr(returns) -> float:
    """Geometric holding period return — same as geometric_mean."""
    return expected_return(returns)


def gain_pain_ratio(returns) -> float:
    """Sum of gains / abs(sum of losses)."""
    r = _to_array(returns)
    losses = r[r < 0]
    gains_sum = r[r > 0].sum()
    losses_abs = abs(losses.sum())
    if losses_abs < 1e-12:
        return float("inf") if gains_sum > 0 else 0.0
    return float(gains_sum / losses_abs)


def common_sense_ratio(returns) -> float:
    """Profit factor * tail_ratio."""
    # Local imports to avoid circular dependencies between submodules.
    from aurora.analytics.metrics_full.distribution import profit_factor
    from aurora.analytics.metrics_full.risk import tail_ratio
    pf = profit_factor(returns)
    tr = tail_ratio(returns)
    if not math.isfinite(pf) or not math.isfinite(tr):
        return 0.0
    return float(pf * tr)
