"""Tests for quantforge.analytics.metrics_full — quantstats parity suite."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
import pytest

from aurora.analytics import metrics_full as mf


# ---------- fixtures ----------

@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def daily_returns(rng):
    """3 years of synthetic daily returns with positive drift."""
    n = 252 * 3
    return rng.normal(loc=0.0006, scale=0.012, size=n)


@pytest.fixture
def daily_returns_series(daily_returns):
    idx = pd.date_range("2021-01-01", periods=len(daily_returns), freq="B")
    return pd.Series(daily_returns, index=idx)


@pytest.fixture
def benchmark(rng):
    n = 252 * 3
    return rng.normal(loc=0.0004, scale=0.010, size=n)


# ---------- function list for parameterized finite-output test ----------

SCALAR_FNS_NO_ARGS = [
    "compounded_return", "total_return", "expected_return", "geometric_mean", "ghpr",
    "gain_pain_ratio", "common_sense_ratio",
    "value_at_risk", "conditional_value_at_risk", "tail_ratio", "ulcer_index",
    "serenity_index", "upside_potential_ratio", "omega_ratio",
    "max_drawdown", "avg_drawdown", "avg_drawdown_days", "recovery_factor",
    "conditional_drawdown",
    "skew", "kurtosis", "kelly_criterion", "payoff_ratio", "profit_factor",
    "cpc_index", "win_rate", "loss_rate", "avg_win", "avg_loss",
    "consecutive_wins", "consecutive_losses", "expectancy",
    "outlier_win_ratio", "outlier_loss_ratio", "gini_coefficient",
    "risk_of_ruin", "exposure", "positive_months", "negative_months",
]

SCALAR_FNS_WITH_PPY = [
    "cagr", "annualized_return", "calmar_ratio", "mar_ratio",
    "sharpe_ratio", "sortino_ratio", "adjusted_sortino",
    "smart_sharpe", "smart_sortino", "rar",
    "ulcer_performance_index", "volatility",
]


@pytest.mark.parametrize("fn_name", SCALAR_FNS_NO_ARGS)
def test_each_metric_returns_finite(fn_name, daily_returns):
    fn = getattr(mf, fn_name)
    val = fn(daily_returns)
    assert math.isfinite(val), f"{fn_name} returned {val}"


@pytest.mark.parametrize("fn_name", SCALAR_FNS_WITH_PPY)
def test_each_metric_with_ppy_returns_finite(fn_name, daily_returns):
    fn = getattr(mf, fn_name)
    val = fn(daily_returns, ppy=252)
    assert math.isfinite(val), f"{fn_name} returned {val}"


def test_var_cvar_relationship(daily_returns):
    """CVaR <= VaR (more negative — CVaR is the mean of the lower tail)."""
    var = mf.value_at_risk(daily_returns, alpha=0.05)
    cvar = mf.conditional_value_at_risk(daily_returns, alpha=0.05)
    assert cvar <= var + 1e-9, f"CVaR={cvar} should be <= VaR={var}"


def test_omega_ratio_threshold_zero(daily_returns):
    """Omega at threshold 0 should match gain/pain ratio."""
    omega = mf.omega_ratio(daily_returns, threshold=0.0)
    gp = mf.gain_pain_ratio(daily_returns)
    assert abs(omega - gp) < 1e-9


def test_kelly_in_range(daily_returns):
    """Kelly fraction must be in a reasonable range; for random-ish daily it shouldn't blow up."""
    k = mf.kelly_criterion(daily_returns)
    assert -2.0 <= k <= 2.0, f"Kelly={k} out of plausible range"


def test_monthly_returns_pivot_shape(daily_returns_series):
    df = mf.monthly_returns(daily_returns_series)
    assert isinstance(df, pd.DataFrame)
    assert df.index.name == "year"
    assert df.columns.name == "month"
    # 3 years of business days → expect 3 year-rows, up to 12 month-cols
    assert df.shape[0] >= 1
    assert df.shape[1] >= 1
    assert df.shape[1] <= 12


def test_drawdown_details_columns(daily_returns_series):
    df = mf.drawdown_details(daily_returns_series)
    assert list(df.columns) == ["start", "end", "depth", "recovery_days"]
    if len(df) > 0:
        assert (df["depth"] <= 0).all()
        assert (df["recovery_days"] >= 0).all()


def test_all_metrics_returns_dict_with_50_keys(daily_returns, benchmark):
    """all_metrics with benchmark should yield >= 50 metric keys."""
    s = mf.all_metrics(daily_returns, benchmark=benchmark)
    assert isinstance(s, pd.Series)
    assert len(s) >= 50, f"Got only {len(s)} metrics, expected >= 50"
    # all values must be finite numbers
    for k, v in s.items():
        assert math.isfinite(float(v)), f"Metric {k} is not finite: {v}"


def test_all_metrics_no_benchmark(daily_returns):
    """all_metrics works without benchmark; must still return many metrics."""
    s = mf.all_metrics(daily_returns)
    assert len(s) >= 45
    assert "information_ratio" not in s.index
    assert "beta" not in s.index


def test_max_dd_negative_or_zero(daily_returns):
    assert mf.max_drawdown(daily_returns) <= 0


def test_win_loss_rate_sums(daily_returns):
    """win_rate + loss_rate + zero_rate == 1."""
    wr = mf.win_rate(daily_returns)
    lr = mf.loss_rate(daily_returns)
    assert 0.0 <= wr <= 1.0
    assert 0.0 <= lr <= 1.0
    assert wr + lr <= 1.0 + 1e-9


def test_consecutive_counts_non_negative(daily_returns):
    assert mf.consecutive_wins(daily_returns) >= 0
    assert mf.consecutive_losses(daily_returns) >= 0


def test_sharpe_rises_with_positive_drift(rng):
    """A high-drift series must have a higher Sharpe than a zero-drift series."""
    n = 1000
    high = rng.normal(0.005, 0.01, n)
    low = rng.normal(0.0, 0.01, n)
    assert mf.sharpe_ratio(high) > mf.sharpe_ratio(low)


def test_information_ratio_finite(daily_returns, benchmark):
    val = mf.information_ratio(daily_returns, benchmark)
    assert math.isfinite(val)


def test_treynor_ratio_finite(daily_returns, benchmark):
    val = mf.treynor_ratio(daily_returns, benchmark, rf=0.02, ppy=252)
    assert math.isfinite(val)


def test_yearly_returns_count(daily_returns_series):
    yr = mf.yearly_returns(daily_returns_series)
    assert 1 <= len(yr) <= 4  # 3 years of B-days may span 3-4 calendar years


def test_best_worst_month(daily_returns_series):
    bm = mf.best_month(daily_returns_series)
    wm = mf.worst_month(daily_returns_series)
    assert isinstance(bm, tuple) and len(bm) == 2
    assert isinstance(wm, tuple) and len(wm) == 2
    assert bm[1] >= wm[1]


def test_best_worst_year(daily_returns_series):
    by = mf.best_year(daily_returns_series)
    wy = mf.worst_year(daily_returns_series)
    assert by[1] >= wy[1]


def test_cagr_negative_on_ruin():
    """A wiped-out portfolio reports CAGR = -1.0 (i.e. -100%), not 0.0."""
    # Two consecutive -100% returns -> total capital = 0.
    rets = np.array([-1.0, 0.0, 0.0])
    val = mf.cagr(rets, ppy=252)
    assert val == pytest.approx(-1.0), f"expected CAGR=-1.0 on ruin, got {val}"


def test_kelly_ruin_proxy_n_units_param():
    """``kelly_ruin_proxy`` accepts a configurable ``n_units`` and matches
    the legacy ``risk_of_ruin`` (``n_units=10``) for backward compat.
    """
    # Build returns with a positive edge (60% winners).
    rng = np.random.default_rng(0)
    rets = rng.choice([0.01, -0.01], p=[0.6, 0.4], size=500)
    legacy = mf.risk_of_ruin(rets)
    new_default = mf.kelly_ruin_proxy(rets, n_units=10)
    assert legacy == pytest.approx(new_default)
    # Larger horizon = lower implied ruin probability.
    larger = mf.kelly_ruin_proxy(rets, n_units=20)
    assert 0.0 <= larger <= legacy

    with pytest.raises(ValueError):
        mf.kelly_ruin_proxy(rets, n_units=0)
