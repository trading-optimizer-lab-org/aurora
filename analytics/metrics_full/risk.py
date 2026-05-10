"""Risk-based metrics: VaR, CVaR, ulcer, omega, etc."""
from __future__ import annotations
import math
import numpy as np

from aurora.analytics.metrics_full._helpers import (
    _drawdown_series,
    _to_array,
)


def value_at_risk(returns, alpha: float = 0.05) -> float:
    """Historical VaR at level alpha (lower-tail, returned as a return value, typically negative)."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    return float(np.quantile(r, alpha))


def conditional_value_at_risk(returns, alpha: float = 0.05) -> float:
    """CVaR / Expected Shortfall: mean of returns at or below VaR(alpha)."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    var = np.quantile(r, alpha)
    tail = r[r <= var]
    if len(tail) == 0:
        return float(var)
    return float(tail.mean())


def tail_ratio(returns, cutoff: float = 0.95) -> float:
    """abs(quantile(cutoff)) / abs(quantile(1 - cutoff))."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    upper = abs(np.quantile(r, cutoff))
    lower = abs(np.quantile(r, 1.0 - cutoff))
    if lower < 1e-12:
        return float("inf") if upper > 0 else 0.0
    return float(upper / lower)


def ulcer_index(returns) -> float:
    """Sqrt(mean(drawdown^2)) — Martin's Ulcer Index."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0.0
    return float(np.sqrt(np.mean(dd ** 2)))


def ulcer_performance_index(returns, ppy: int = 252, rf: float = 0.0) -> float:
    """UPI: (CAGR - rf) / Ulcer Index. Also called Martin Ratio."""
    from aurora.analytics.metrics_full.returns import cagr
    ui = ulcer_index(returns)
    if ui < 1e-12:
        return 0.0
    return float((cagr(returns, ppy) - rf) / ui)


def serenity_index(returns, rf: float = 0.0) -> float:
    """Serenity = (mean(r) - rf) / (ulcer * cvar_penalty). Keller's Serenity Ratio."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    ui = ulcer_index(returns)
    cvar = conditional_value_at_risk(returns, 0.01)
    pitfall = ui * abs(cvar) if cvar < 0 else ui
    if pitfall < 1e-12:
        return 0.0
    return float((r.mean() - rf) / pitfall)


def upside_potential_ratio(returns, threshold: float = 0.0) -> float:
    """Upside potential / downside risk (Sortino-style with threshold)."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    upside = np.maximum(r - threshold, 0)
    downside = np.minimum(r - threshold, 0)
    upside_mean = upside.mean()
    downside_dev = math.sqrt(np.mean(downside ** 2))
    if downside_dev < 1e-12:
        return float("inf") if upside_mean > 0 else 0.0
    return float(upside_mean / downside_dev)


def omega_ratio(returns, threshold: float = 0.0, ppy: int = 252) -> float:
    """Omega ratio: sum(r > threshold) / abs(sum(r < threshold)). ppy unused (kept for API parity)."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    excess = r - threshold
    gains = excess[excess > 0].sum()
    losses = abs(excess[excess < 0].sum())
    if losses < 1e-12:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def volatility(returns, ppy: int = 252) -> float:
    """Annualized volatility."""
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    return float(r.std(ddof=1) * math.sqrt(ppy))
