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
import pandas as pd

# Re-export canonical implementations from core.metrics to keep both modules
# in lockstep without duplicating logic. See module docstring "Dedup policy".
from aurora.core.metrics import (
    compute_metrics,
    deflated_sharpe,
    probabilistic_sharpe,
)

from aurora.analytics.metrics_full.distribution import (
    autocorrelation,
    avg_loss,
    avg_win,
    consecutive_losses,
    consecutive_wins,
    cpc_index,
    expectancy,
    exposure,
    gini_coefficient,
    kelly_criterion,
    kelly_ruin_proxy,
    kurtosis,
    loss_rate,
    outlier_loss_ratio,
    outlier_win_ratio,
    payoff_ratio,
    profit_factor,
    risk_of_ruin,
    skew,
    win_rate,
)
from aurora.analytics.metrics_full.drawdown import (
    avg_drawdown,
    avg_drawdown_days,
    calmar_ratio,
    conditional_drawdown,
    drawdown_details,
    mar_ratio,
    max_drawdown,
    recovery_factor,
)
from aurora.analytics.metrics_full.returns import (
    annualized_return,
    cagr,
    common_sense_ratio,
    compounded_return,
    expected_return,
    gain_pain_ratio,
    geometric_mean,
    ghpr,
    total_return,
)
from aurora.analytics.metrics_full.risk import (
    conditional_value_at_risk,
    omega_ratio,
    serenity_index,
    tail_ratio,
    ulcer_index,
    ulcer_performance_index,
    upside_potential_ratio,
    value_at_risk,
    volatility,
)
from aurora.analytics.metrics_full.risk_adjusted import (
    adjusted_sortino,
    alpha,
    beta,
    information_ratio,
    rar,
    sharpe_ratio,
    smart_sharpe,
    smart_sortino,
    sortino_ratio,
    treynor_ratio,
)
from aurora.analytics.metrics_full.time_based import (
    best_month,
    best_year,
    monthly_returns,
    negative_months,
    positive_months,
    worst_month,
    worst_year,
    yearly_returns,
)


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


__all__ = [
    # canonical re-exports from core.metrics
    "compute_metrics",
    "deflated_sharpe",
    "probabilistic_sharpe",
    # returns
    "compounded_return",
    "total_return",
    "cagr",
    "annualized_return",
    "expected_return",
    "geometric_mean",
    "ghpr",
    "gain_pain_ratio",
    "common_sense_ratio",
    # risk
    "value_at_risk",
    "conditional_value_at_risk",
    "tail_ratio",
    "ulcer_index",
    "ulcer_performance_index",
    "serenity_index",
    "upside_potential_ratio",
    "omega_ratio",
    "volatility",
    # drawdown
    "max_drawdown",
    "avg_drawdown",
    "avg_drawdown_days",
    "recovery_factor",
    "calmar_ratio",
    "mar_ratio",
    "conditional_drawdown",
    "drawdown_details",
    # risk-adjusted
    "sharpe_ratio",
    "sortino_ratio",
    "adjusted_sortino",
    "smart_sharpe",
    "smart_sortino",
    "information_ratio",
    "treynor_ratio",
    "beta",
    "alpha",
    "rar",
    # distribution
    "skew",
    "kurtosis",
    "autocorrelation",
    "kelly_criterion",
    "payoff_ratio",
    "profit_factor",
    "cpc_index",
    "win_rate",
    "loss_rate",
    "avg_win",
    "avg_loss",
    "consecutive_wins",
    "consecutive_losses",
    "expectancy",
    "outlier_win_ratio",
    "outlier_loss_ratio",
    "gini_coefficient",
    "kelly_ruin_proxy",
    "risk_of_ruin",
    "exposure",
    # time-based
    "monthly_returns",
    "yearly_returns",
    "best_month",
    "worst_month",
    "best_year",
    "worst_year",
    "positive_months",
    "negative_months",
    # convenience
    "all_metrics",
]
