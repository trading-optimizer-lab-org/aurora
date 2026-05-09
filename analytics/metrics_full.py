"""Comprehensive metrics suite — quantstats parity (50+ metrics).

Source reference: https://github.com/ranaroussi/quantstats/blob/main/quantstats/stats.py

All functions accept either np.ndarray or pd.Series of period returns.
Frequency-neutral; pass `ppy` (periods/year) for annualization.

Dedup policy
------------
Three symbols (`compute_metrics`, `deflated_sharpe`, `probabilistic_sharpe`) live
in :mod:`aurora.core.metrics` as the canonical implementation and are
re-exported here so callers can import them from either module without code
duplication. All other quantstats-parity helpers below are exclusive to this
module (extended metrics not present in core).

Categories:
- Return-based: compounded_return, cagr, total_return, expected_return, gain_pain, common_sense
- Risk-based: VaR, CVaR, tail_ratio, ulcer_index, serenity_index, upside_potential, omega
- Drawdown: max_dd, avg_dd, avg_dd_days, recovery_factor, calmar, drawdown_details
- Risk-adjusted: sharpe, sortino, smart_sharpe, smart_sortino, adjusted_sortino, info_ratio, treynor
- Distribution: skew, kurtosis, autocorrelation, kelly, payoff_ratio, profit_factor, cpc_index,
  win_rate, loss_rate, avg_win, avg_loss, consecutive_wins, consecutive_losses
- Time-based: monthly_returns, best/worst month, yearly_returns, best/worst year, pos/neg months
- Extras: gini_coefficient, conditional_drawdown, rar, mar_ratio, risk_of_ruin, ror, expectancy,
  outlier_win_ratio, outlier_loss_ratio, exposure, geometric_mean, ghpr
- Convenience: all_metrics
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy import stats

# Re-export canonical implementations from core.metrics to keep both modules
# in lockstep without duplicating logic. See module docstring "Dedup policy".
from aurora.core.metrics import (
    compute_metrics,
    deflated_sharpe,
    probabilistic_sharpe,
)


# ---------- helpers ----------

def _to_series(returns) -> pd.Series:
    """Coerce to pd.Series; preserve DatetimeIndex if present, else use RangeIndex."""
    if isinstance(returns, pd.Series):
        s = returns.dropna().astype(float)
    else:
        arr = np.asarray(returns, dtype=float)
        arr = arr[~np.isnan(arr)]
        s = pd.Series(arr)
    return s


def _to_array(returns) -> np.ndarray:
    if isinstance(returns, pd.Series):
        return returns.dropna().to_numpy(dtype=float)
    arr = np.asarray(returns, dtype=float)
    return arr[~np.isnan(arr)]


def _equity_curve(returns) -> np.ndarray:
    r = _to_array(returns)
    return np.cumprod(1.0 + r) if len(r) else np.array([1.0])


def _drawdown_series(returns) -> np.ndarray:
    eq = _equity_curve(returns)
    if len(eq) == 0:
        return np.array([0.0])
    cummax = np.maximum.accumulate(eq)
    return (eq - cummax) / cummax


# ---------- return-based ----------

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
    pf = profit_factor(returns)
    tr = tail_ratio(returns)
    if not math.isfinite(pf) or not math.isfinite(tr):
        return 0.0
    return float(pf * tr)


# ---------- risk-based ----------

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


# ---------- drawdown ----------

def max_drawdown(returns) -> float:
    """Worst peak-to-trough drawdown (negative)."""
    dd = _drawdown_series(returns)
    return float(dd.min()) if len(dd) else 0.0


def avg_drawdown(returns) -> float:
    """Average drawdown depth across all distinct drawdowns."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0.0
    in_dd = dd < 0
    if not in_dd.any():
        return 0.0
    troughs = []
    cur_min = 0.0
    for i, d in enumerate(dd):
        if d < 0:
            cur_min = min(cur_min, d)
        elif cur_min < 0:
            troughs.append(cur_min)
            cur_min = 0.0
    if cur_min < 0:
        troughs.append(cur_min)
    if not troughs:
        return 0.0
    return float(np.mean(troughs))


def avg_drawdown_days(returns) -> float:
    """Average drawdown duration in periods."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0.0
    durations = []
    cur = 0
    for d in dd:
        if d < 0:
            cur += 1
        else:
            if cur > 0:
                durations.append(cur)
                cur = 0
    if cur > 0:
        durations.append(cur)
    return float(np.mean(durations)) if durations else 0.0


def recovery_factor(returns) -> float:
    """Total return / |max drawdown|."""
    mdd = max_drawdown(returns)
    if abs(mdd) < 1e-12:
        return 0.0
    return float(compounded_return(returns) / abs(mdd))


def calmar_ratio(returns, ppy: int = 252) -> float:
    """CAGR / |max drawdown|."""
    mdd = max_drawdown(returns)
    if abs(mdd) < 1e-12:
        return 0.0
    return float(cagr(returns, ppy) / abs(mdd))


def mar_ratio(returns, ppy: int = 252) -> float:
    """Same as calmar_ratio (managed-account ratio)."""
    return calmar_ratio(returns, ppy)


def conditional_drawdown(returns, alpha: float = 0.05) -> float:
    """Mean of worst alpha-quantile drawdowns."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0.0
    cutoff = np.quantile(dd, alpha)
    tail = dd[dd <= cutoff]
    return float(tail.mean()) if len(tail) else 0.0


def drawdown_details(returns) -> pd.DataFrame:
    """Per-drawdown details: start, end, depth, recovery_days."""
    s = _to_series(returns)
    if len(s) == 0:
        return pd.DataFrame(columns=["start", "end", "depth", "recovery_days"])
    eq = (1.0 + s).cumprod()
    cummax = eq.cummax()
    dd = (eq - cummax) / cummax

    rows = []
    in_dd = False
    start_idx = 0
    trough_val = 0.0
    for i, d in enumerate(dd.values):
        if d < 0 and not in_dd:
            in_dd = True
            start_idx = i
            trough_val = d
        elif d < 0 and in_dd:
            trough_val = min(trough_val, d)
        elif d >= 0 and in_dd:
            in_dd = False
            rows.append({
                "start": s.index[start_idx],
                "end": s.index[i],
                "depth": float(trough_val),
                "recovery_days": int(i - start_idx),
            })
    if in_dd:
        rows.append({
            "start": s.index[start_idx],
            "end": s.index[-1],
            "depth": float(trough_val),
            "recovery_days": int(len(s) - 1 - start_idx),
        })
    return pd.DataFrame(rows, columns=["start", "end", "depth", "recovery_days"])


# ---------- risk-adjusted ----------

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


def _autocorr_penalty(r: np.ndarray) -> float:
    """quantstats-style penalty: sqrt(1 + 2 * sum_{i=1..N} ((N - i)/N) * |corr_i|)."""
    n = len(r)
    coef = 0.0
    for i in range(1, min(n, 21)):  # cap at lag 20 for stability
        c = np.corrcoef(r[:-i], r[i:])[0, 1]
        if not math.isfinite(c):
            continue
        coef += ((n - i) / n) * abs(c)
    return math.sqrt(1.0 + 2.0 * coef)


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
    beta = np.cov(r, b, ddof=1)[0, 1] / var_b
    if abs(beta) < 1e-12:
        return 0.0
    return float((r.mean() - rf / ppy) * ppy / beta)


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
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    vol = r.std(ddof=1) * math.sqrt(ppy)
    if vol < 1e-12:
        return 0.0
    return float(cagr(returns, ppy) / vol)


# ---------- distribution ----------

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


def volatility(returns, ppy: int = 252) -> float:
    """Annualized volatility."""
    r = _to_array(returns)
    if len(r) < 2:
        return 0.0
    return float(r.std(ddof=1) * math.sqrt(ppy))


# ---------- time-based aggregations ----------

def _resample_returns(returns, freq: str) -> pd.Series:
    """Resample returns to given frequency by compounding.

    When the input does not carry a DatetimeIndex, a synthetic daily index
    is fabricated so that bar-count aggregations (``positive_months``,
    ``negative_months``) still work. Calendar-labelled outputs
    (``monthly_returns`` pivot, ``yearly_returns``, ``best_month``,
    ``worst_month``, ``best_year``, ``worst_year``) must NOT trust the
    fabricated labels and should bail out instead -- see ``_has_real_dt``.
    """
    s = _to_series(returns)
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.date_range("2000-01-01", periods=len(s), freq="D")
    return (1.0 + s).resample(freq).prod() - 1.0


def _has_real_dt(returns) -> bool:
    """True only when caller supplied a real DatetimeIndex. Calendar-
    labelled outputs are meaningless without one."""
    s = _to_series(returns) if not isinstance(returns, pd.Series) else returns
    return isinstance(s.index, pd.DatetimeIndex)


def monthly_returns(returns) -> pd.DataFrame:
    """Year x month matrix of compounded monthly returns.

    Returns an empty DataFrame when no DatetimeIndex is present, since the
    year/month axis labels would otherwise be fabricated.
    """
    if not _has_real_dt(returns):
        return pd.DataFrame()
    monthly = _resample_returns(returns, "ME")
    if len(monthly) == 0:
        return pd.DataFrame()
    df = pd.DataFrame({"year": monthly.index.year, "month": monthly.index.month, "ret": monthly.values})
    return df.pivot(index="year", columns="month", values="ret")


def yearly_returns(returns) -> pd.Series:
    """Compounded yearly returns. Empty Series if no DatetimeIndex."""
    if not _has_real_dt(returns):
        return pd.Series(dtype=float)
    return _resample_returns(returns, "YE")


def best_month(returns) -> tuple:
    if not _has_real_dt(returns):
        return ("", 0.0)
    monthly = _resample_returns(returns, "ME")
    if len(monthly) == 0:
        return ("", 0.0)
    idx = monthly.idxmax()
    return (str(idx.strftime("%Y-%m")), float(monthly.max()))


def worst_month(returns) -> tuple:
    if not _has_real_dt(returns):
        return ("", 0.0)
    monthly = _resample_returns(returns, "ME")
    if len(monthly) == 0:
        return ("", 0.0)
    idx = monthly.idxmin()
    return (str(idx.strftime("%Y-%m")), float(monthly.min()))


def best_year(returns) -> tuple:
    if not _has_real_dt(returns):
        return (0, 0.0)
    yearly = yearly_returns(returns)
    if len(yearly) == 0:
        return (0, 0.0)
    return (int(yearly.idxmax().year), float(yearly.max()))


def worst_year(returns) -> tuple:
    if not _has_real_dt(returns):
        return (0, 0.0)
    yearly = yearly_returns(returns)
    if len(yearly) == 0:
        return (0, 0.0)
    return (int(yearly.idxmin().year), float(yearly.min()))


def positive_months(returns) -> int:
    monthly = _resample_returns(returns, "ME")
    return int((monthly > 0).sum())


def negative_months(returns) -> int:
    monthly = _resample_returns(returns, "ME")
    return int((monthly < 0).sum())


# ---------- convenience ----------

def all_metrics(returns, benchmark=None, rf: float = 0.0, ppy: int = 252) -> pd.Series:
    """Compute all scalar metrics; return as pd.Series."""
    out = {
        # return-based
        "compounded_return": compounded_return(returns),
        "total_return": total_return(returns),
        "cagr": cagr(returns, ppy),
        "annualized_return": annualized_return(returns, ppy),
        "expected_return": expected_return(returns),
        "geometric_mean": geometric_mean(returns),
        "ghpr": ghpr(returns),
        "gain_pain_ratio": gain_pain_ratio(returns),
        "common_sense_ratio": common_sense_ratio(returns),
        # risk
        "value_at_risk": value_at_risk(returns),
        "conditional_value_at_risk": conditional_value_at_risk(returns),
        "tail_ratio": tail_ratio(returns),
        "ulcer_index": ulcer_index(returns),
        "ulcer_performance_index": ulcer_performance_index(returns, ppy, rf),
        "serenity_index": serenity_index(returns, rf),
        "upside_potential_ratio": upside_potential_ratio(returns),
        "omega_ratio": omega_ratio(returns),
        "volatility": volatility(returns, ppy),
        # drawdown
        "max_drawdown": max_drawdown(returns),
        "avg_drawdown": avg_drawdown(returns),
        "avg_drawdown_days": avg_drawdown_days(returns),
        "recovery_factor": recovery_factor(returns),
        "calmar_ratio": calmar_ratio(returns, ppy),
        "mar_ratio": mar_ratio(returns, ppy),
        "conditional_drawdown": conditional_drawdown(returns),
        # risk-adjusted
        "sharpe_ratio": sharpe_ratio(returns, ppy, rf),
        "sortino_ratio": sortino_ratio(returns, ppy, rf),
        "adjusted_sortino": adjusted_sortino(returns, ppy, rf),
        "smart_sharpe": smart_sharpe(returns, ppy, rf),
        "smart_sortino": smart_sortino(returns, ppy, rf),
        "rar": rar(returns, ppy),
        # distribution
        "skew": skew(returns),
        "kurtosis": kurtosis(returns),
        "autocorrelation_lag1": autocorrelation(returns, 1),
        "kelly_criterion": kelly_criterion(returns),
        "payoff_ratio": payoff_ratio(returns),
        "profit_factor": profit_factor(returns),
        "cpc_index": cpc_index(returns),
        "win_rate": win_rate(returns),
        "loss_rate": loss_rate(returns),
        "avg_win": avg_win(returns),
        "avg_loss": avg_loss(returns),
        "consecutive_wins": consecutive_wins(returns),
        "consecutive_losses": consecutive_losses(returns),
        "expectancy": expectancy(returns),
        "outlier_win_ratio": outlier_win_ratio(returns),
        "outlier_loss_ratio": outlier_loss_ratio(returns),
        "gini_coefficient": gini_coefficient(returns),
        "risk_of_ruin": risk_of_ruin(returns),
        "exposure": exposure(returns),
        # time-based
        "positive_months": positive_months(returns),
        "negative_months": negative_months(returns),
    }
    if benchmark is not None:
        out["information_ratio"] = information_ratio(returns, benchmark)
        out["treynor_ratio"] = treynor_ratio(returns, benchmark, rf, ppy)
        out["beta"] = beta(returns, benchmark)
        out["alpha"] = alpha(returns, benchmark, rf, ppy)
    return pd.Series(out)
