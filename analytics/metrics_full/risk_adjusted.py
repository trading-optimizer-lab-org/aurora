"""Risk-adjusted metrics: Sharpe, Sortino, info ratio, alpha/beta."""
from __future__ import annotations
import math
import numpy as np

from aurora.analytics.metrics_full._helpers import (
    _autocorr_penalty,
    _to_array,
)


def sharpe_ratio(returns, ppy: int = 252, rf: float = 0.0) -> float:
    """Annualized Sharpe ratio."""
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    excess = r - rf / ppy
    std = excess.std(ddof=1)
    if std < 1e-12:
        return 0.0
    return float(excess.mean() / std * math.sqrt(ppy))


def sortino_ratio(returns, ppy: int = 252, rf: float = 0.0) -> float:
    """Annualized Sortino: only downside deviation in denominator.

    Denominator choice
    ------------------
    The downside semi-deviation here is

        sqrt( sum(downside_i^2) / (N - 1) )

    where ``N`` is the size of the *full* excess-return sample (not just
    the count of downside observations). This is the Sharpe-consistent
    convention: it uses the same unbiased (``ddof=1``) denominator as
    :func:`sharpe_ratio`, so when returns are symmetric around zero the
    Sortino ratio reduces to the Sharpe ratio scaled by sqrt(2).

    Note: this differs from quantstats' parity formula, which divides by
    ``N`` (population denominator) rather than ``N - 1``. We deliberately
    pick Sharpe-consistency over quantstats-parity here so that the two
    risk-adjusted metrics share an estimator family.
    """
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    excess = r - rf / ppy
    downside = excess[excess < 0]
    if len(downside) < 1:
        # No downside observations: positive-mean excess returns are
        # infinitely "Sortino-good" (no downside risk to penalize).
        # Mirror tail_ratio / gain_pain_ratio which return inf in the
        # all-positive degenerate case. If excess.mean() is non-positive,
        # the ratio is undefined / zero by convention.
        if excess.mean() > 0:
            return float("inf")
        return 0.0
    # Sharpe-consistent denominator: full-sample (N - 1).
    n_full = len(excess)
    dstd = math.sqrt(float(np.sum(downside ** 2)) / (n_full - 1))
    if dstd < 1e-12:
        return 0.0
    return float(excess.mean() / dstd * math.sqrt(ppy))


def adjusted_sortino(returns, ppy: int = 252, rf: float = 0.0) -> float:
    """Sortino divided by sqrt(2) — adjusts for using only downside obs."""
    return sortino_ratio(returns, ppy, rf) / math.sqrt(2)


def smart_sharpe(returns, ppy: int = 252, rf: float = 0.0) -> float:
    """Sharpe with autocorrelation penalty (quantstats formula)."""
    sr = sharpe_ratio(returns, ppy, rf)
    if sr == 0.0:
        return 0.0
    r = _to_array(returns)
    if len(r) < 4:
        return sr
    # Sum of |autocorr| at lags 1..N, penalize
    penalty = _autocorr_penalty(r)
    return float(sr / penalty) if penalty > 0 else sr


def smart_sortino(returns, ppy: int = 252, rf: float = 0.0) -> float:
    """Sortino with autocorrelation penalty."""
    so = sortino_ratio(returns, ppy, rf)
    if so == 0.0:
        return 0.0
    r = _to_array(returns)
    if len(r) < 4:
        return so
    penalty = _autocorr_penalty(r)
    return float(so / penalty) if penalty > 0 else so


def information_ratio(returns, benchmark) -> float:
    """(mean(r - b)) / std(r - b)."""
    r = _to_array(returns)
    b = _to_array(benchmark)
    n = min(len(r), len(b))
    if n < 2:
        return 0.0
    diff = r[-n:] - b[-n:]
    std = diff.std(ddof=1)
    if std < 1e-12:
        return 0.0
    return float(diff.mean() / std)


def treynor_ratio(returns, benchmark, rf: float = 0.0, ppy: int = 252) -> float:
    """(mean(r) - rf/ppy) / beta."""
    r = _to_array(returns)
    b = _to_array(benchmark)
    n = min(len(r), len(b))
    if n < 2:
        return 0.0
    r, b = r[-n:], b[-n:]
    var_b = b.var(ddof=1)
    if var_b < 1e-12:
        return 0.0
    beta_v = np.cov(r, b, ddof=1)[0, 1] / var_b
    if abs(beta_v) < 1e-12:
        return 0.0
    return float((r.mean() - rf / ppy) * ppy / beta_v)


def beta(returns, benchmark) -> float:
    """OLS beta vs benchmark."""
    r = _to_array(returns)
    b = _to_array(benchmark)
    n = min(len(r), len(b))
    if n < 2:
        return 0.0
    r, b = r[-n:], b[-n:]
    var_b = b.var(ddof=1)
    if var_b < 1e-12:
        return 0.0
    return float(np.cov(r, b, ddof=1)[0, 1] / var_b)


def alpha(returns, benchmark, rf: float = 0.0, ppy: int = 252) -> float:
    """Jensen's alpha (annualized)."""
    r = _to_array(returns)
    b = _to_array(benchmark)
    n = min(len(r), len(b))
    if n < 2:
        return 0.0
    r, b = r[-n:], b[-n:]
    bt = beta(r, b)
    rf_p = rf / ppy
    return float((r.mean() - rf_p - bt * (b.mean() - rf_p)) * ppy)


def rar(returns, ppy: int = 252) -> float:
    """Risk-Adjusted Return: CAGR / volatility (annualized)."""
    from aurora.analytics.metrics_full.returns import cagr
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    vol = r.std(ddof=1) * math.sqrt(ppy)
    if vol < 1e-12:
        return 0.0
    return float(cagr(returns, ppy) / vol)
