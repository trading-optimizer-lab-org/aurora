"""Distribution and trade-stat metrics."""
from __future__ import annotations
import math
import numpy as np
from scipy import stats

from aurora.analytics.metrics_full._helpers import _to_array


def skew(returns) -> float:
    """Sample skewness."""
    r = _to_array(returns)
    if len(r) < 3:
        return 0.0
    return float(stats.skew(r))


def kurtosis(returns) -> float:
    """Excess kurtosis (Fisher)."""
    r = _to_array(returns)
    if len(r) < 4:
        return 0.0
    return float(stats.kurtosis(r))


def autocorrelation(returns, lag: int = 1) -> float:
    """Lag-k autocorrelation."""
    r = _to_array(returns)
    if len(r) <= lag:
        return 0.0
    c = np.corrcoef(r[:-lag], r[lag:])[0, 1]
    return float(c) if math.isfinite(c) else 0.0


def kelly_criterion(returns) -> float:
    """Kelly fraction = win_rate - (1 - win_rate) / payoff_ratio."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    wins = r[r > 0]
    losses = r[r < 0]
    if len(wins) == 0 or len(losses) == 0:
        return 0.0
    wr = len(wins) / len(r)
    payoff = wins.mean() / abs(losses.mean())
    if payoff < 1e-12:
        return 0.0
    return float(wr - (1.0 - wr) / payoff)


def payoff_ratio(returns) -> float:
    """avg_win / |avg_loss|."""
    r = _to_array(returns)
    wins = r[r > 0]
    losses = r[r < 0]
    if len(wins) == 0 or len(losses) == 0:
        return 0.0
    avg_l = abs(losses.mean())
    if avg_l < 1e-12:
        return 0.0
    return float(wins.mean() / avg_l)


def profit_factor(returns) -> float:
    """sum(wins) / |sum(losses)|."""
    r = _to_array(returns)
    wins = r[r > 0].sum()
    losses_abs = abs(r[r < 0].sum())
    if losses_abs < 1e-12:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses_abs)


def cpc_index(returns) -> float:
    """CPC index = profit_factor * win_rate * payoff_ratio."""
    return float(profit_factor(returns) * win_rate(returns) * payoff_ratio(returns))


def win_rate(returns) -> float:
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    return float((r > 0).sum() / len(r))


def loss_rate(returns) -> float:
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    return float((r < 0).sum() / len(r))


def avg_win(returns) -> float:
    r = _to_array(returns)
    wins = r[r > 0]
    return float(wins.mean()) if len(wins) else 0.0


def avg_loss(returns) -> float:
    r = _to_array(returns)
    losses = r[r < 0]
    return float(losses.mean()) if len(losses) else 0.0


def consecutive_wins(returns) -> int:
    r = _to_array(returns)
    if len(r) == 0:
        return 0
    best = cur = 0
    for x in r:
        if x > 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return int(best)


def consecutive_losses(returns) -> int:
    r = _to_array(returns)
    if len(r) == 0:
        return 0
    best = cur = 0
    for x in r:
        if x < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return int(best)


def expectancy(returns) -> float:
    """E[R] = win_rate * avg_win + loss_rate * avg_loss."""
    return float(win_rate(returns) * avg_win(returns) + loss_rate(returns) * avg_loss(returns))


def outlier_win_ratio(returns, quantile: float = 0.99) -> float:
    """avg of top-quantile wins / avg_win."""
    r = _to_array(returns)
    wins = r[r > 0]
    if len(wins) == 0:
        return 0.0
    cutoff = np.quantile(wins, quantile)
    tail = wins[wins >= cutoff]
    avg_w = wins.mean()
    if abs(avg_w) < 1e-12:
        return 0.0
    return float(tail.mean() / avg_w)


def outlier_loss_ratio(returns, quantile: float = 0.01) -> float:
    """avg of bottom-quantile losses / avg_loss."""
    r = _to_array(returns)
    losses = r[r < 0]
    if len(losses) == 0:
        return 0.0
    cutoff = np.quantile(losses, quantile)
    tail = losses[losses <= cutoff]
    avg_l = losses.mean()
    if abs(avg_l) < 1e-12:
        return 0.0
    return float(tail.mean() / avg_l)


def gini_coefficient(returns) -> float:
    """Gini on absolute returns — concentration of P&L."""
    r = np.abs(_to_array(returns))
    if len(r) == 0:
        return 0.0
    r_sorted = np.sort(r)
    n = len(r_sorted)
    s = r_sorted.sum()
    if s < 1e-12:
        return 0.0
    idx = np.arange(1, n + 1)
    return float((2.0 * (idx * r_sorted).sum() - (n + 1) * s) / (n * s))


def kelly_ruin_proxy(returns, n_units: int = 10) -> float:
    """Heuristic Kelly-style risk-of-ruin proxy.

    Returns the probability of dropping ``n_units`` consecutive Kelly-bet
    units before recovery, using ``((1 - edge) / (1 + edge)) ** n_units`` as
    a closed-form bound. ``edge = 2 * win_rate - 1``.

    Notes
    -----
    This is a crude lookup table approximation — it ignores trade size
    distribution, autocorrelation, and tail asymmetry. Use it for screening
    only, not as a true risk-of-ruin estimate. The unit count was previously
    hardcoded to 10; it is now an explicit parameter so callers can pick a
    horizon that matches their bankroll. ``n_units`` must be >= 1.
    """
    if n_units < 1:
        raise ValueError(f"n_units must be >= 1, got {n_units}")
    wr = win_rate(returns)
    edge = 2.0 * wr - 1.0
    if edge <= 0:
        return 1.0
    return float(((1.0 - edge) / (1.0 + edge)) ** int(n_units))


def risk_of_ruin(returns) -> float:  # noqa: D401 - kept for backward compat
    """Backward-compat alias of :func:`kelly_ruin_proxy` with ``n_units=10``.

    Prefer :func:`kelly_ruin_proxy` in new code.
    """
    return kelly_ruin_proxy(returns, n_units=10)


def exposure(returns) -> float:
    """Fraction of periods with non-zero return."""
    r = _to_array(returns)
    if len(r) == 0:
        return 0.0
    return float((r != 0).sum() / len(r))
