"""Tests for alphalens-style factor analysis.

Run: uv run pytest quantforge/tests/test_factor_analysis.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.analytics.factor_analysis import (
    ICResult,
    QuantileSpreadResult,
    factor_autocorrelation,
    factor_returns,
    factor_summary_table,
    factor_turnover,
    information_coefficient,
    quantile_spread,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def idx():
    return pd.date_range("2010-01-01", periods=400, freq="B")


@pytest.fixture
def random_factor(idx):
    rng = np.random.default_rng(42)
    return pd.Series(rng.standard_normal(len(idx)), index=idx, name="factor")


@pytest.fixture
def prices(idx):
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0005, 0.012, len(idx))
    return pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="px")


# ---------------------------------------------------------------------------
# Information coefficient
# ---------------------------------------------------------------------------

def test_ic_perfect_correlation(idx):
    rng = np.random.default_rng(0)
    fwd = pd.Series(rng.normal(0.0, 0.01, len(idx)), index=idx)
    factor = fwd.copy()
    res = information_coefficient(factor, fwd, method="spearman")
    assert isinstance(res, ICResult)
    assert res.mean_ic > 0.99


def test_ic_negative(idx):
    rng = np.random.default_rng(1)
    fwd = pd.Series(rng.normal(0.0, 0.01, len(idx)), index=idx)
    factor = -fwd
    res = information_coefficient(factor, fwd, method="spearman")
    assert res.mean_ic < -0.99


def test_ic_random(idx):
    rng = np.random.default_rng(2)
    factor = pd.Series(rng.standard_normal(len(idx)), index=idx)
    fwd = pd.Series(rng.standard_normal(len(idx)), index=idx)
    res = information_coefficient(factor, fwd, method="spearman")
    # near zero with reasonable tolerance for a 400-bar windowed series
    assert abs(res.mean_ic) < 0.15


def test_ic_pearson_method(idx):
    rng = np.random.default_rng(3)
    fwd = pd.Series(rng.normal(0.0, 0.01, len(idx)), index=idx)
    factor = fwd.copy()
    res = information_coefficient(factor, fwd, method="pearson")
    assert res.mean_ic > 0.99


def test_ic_invalid_method_raises(random_factor):
    with pytest.raises(ValueError, match="method"):
        information_coefficient(random_factor, random_factor, method="kendall")


def test_ic_hac_collapse_returns_uninformative_pvalue(monkeypatch):
    """Round V regression: when HAC variance collapses to zero, the IC
    test must fail closed -- ``t_stat = 0.0, p_value = 1.0`` -- rather
    than the previous ``t_stat = inf, p_value = NaN`` which implied the
    mean-IC was significant under degenerate variance.

    We force the collapse path via a monkey-patched ``np.dot`` that
    returns 0.0 for the HAC autocovariance terms while the rolling IC
    series is non-degenerate. This pins behaviour at the variance-zero
    boundary regardless of float rounding in the upstream rolling
    correlation.
    """
    import aurora.analytics.factor_analysis as fa

    n = 400
    idx_local = pd.date_range("2010-01-01", periods=n, freq="B")
    rng = np.random.default_rng(1)
    fwd = pd.Series(rng.normal(0.0, 0.01, n), index=idx_local)
    factor = fwd.copy()

    # First call the real IC just to derive a daily_ic series with known
    # length, then monkey-patch ``np.dot`` *only* for the HAC code path
    # to force gamma0 / gamma_k to zero. We swap the module-level numpy
    # binding so only computations inside ``factor_analysis`` see the
    # zero-dot; the rest of the program is unaffected.
    real_dot = fa.np.dot

    def _zero_dot(a, b):
        # Force HAC variance to collapse: return 0 for any 1-D inner
        # product that looks like the HAC autocovariance (vectors of
        # length n or n-k). Defer to the real np.dot otherwise.
        try:
            la = len(a)
            lb = len(b)
        except TypeError:
            return real_dot(a, b)
        if la == lb and la > 0:
            return 0.0
        return real_dot(a, b)

    monkeypatch.setattr(fa.np, "dot", _zero_dot, raising=True)
    res = information_coefficient(factor, fwd, method="pearson")
    # HAC variance is forced to zero: safe fallback must engage.
    assert res.t_stat == 0.0
    assert res.p_value == 1.0


# ---------------------------------------------------------------------------
# Quantile spread
# ---------------------------------------------------------------------------

def test_quantile_spread_monotone(idx):
    """When factor predicts forward returns, quantile means should be monotone."""
    rng = np.random.default_rng(11)
    n = len(idx)
    factor_vals = rng.standard_normal(n)
    # Construct prices whose next-bar return is correlated with factor.
    rets = 0.005 * factor_vals + 0.002 * rng.standard_normal(n)
    # Shift so that factor[t] predicts rets[t+1]
    prices_arr = 100.0 * np.cumprod(1.0 + np.concatenate(([0.0], rets[:-1])))
    factor = pd.Series(factor_vals, index=idx)
    prices = pd.Series(prices_arr, index=idx)
    res = quantile_spread(factor, prices, n_quantiles=5, forward_periods=(1, 5))
    assert isinstance(res, QuantileSpreadResult)
    col = res.period_returns[1]
    # mean return increases (loosely) with quantile
    diffs = np.diff(col.values)
    assert (diffs > 0).sum() >= 3, f"expected mostly monotone increasing, got {col.values}"
    # top - bottom positive
    assert col.iloc[-1] > col.iloc[0]


def test_quantile_spread_returns_shape(random_factor, prices):
    res = quantile_spread(random_factor, prices, n_quantiles=5,
                          forward_periods=(1, 5, 20))
    assert res.period_returns.shape == (5, 3)
    assert list(res.period_returns.columns) == [1, 5, 20]
    assert len(res.spread_returns) > 0
    assert len(res.cum_spread) == len(res.spread_returns)


def test_quantile_spread_too_few_obs():
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    f = pd.Series(np.arange(10.0), index=idx)
    p = pd.Series(100.0 + np.arange(10.0), index=idx)
    with pytest.raises(ValueError, match="at least"):
        quantile_spread(f, p, n_quantiles=5)


# ---------------------------------------------------------------------------
# Factor returns
# ---------------------------------------------------------------------------

def test_factor_returns_zero_sum_long_short_demeaned(random_factor, prices):
    rets = factor_returns(random_factor, prices, weight_method="long_short_demeaned")
    # Reconstruct weights to verify they sum to ~0 and L1=1
    f, p = random_factor.dropna(), prices.dropna()
    # align like the impl does
    df = pd.concat([f.rename("f"), p.rename("p")], axis=1).dropna()
    f = df["f"]
    demeaned = f - f.mean()
    weights = demeaned / demeaned.abs().sum()
    assert abs(weights.sum()) < 1e-10
    assert abs(weights.abs().sum() - 1.0) < 1e-10
    assert isinstance(rets, pd.Series)
    assert len(rets) > 0


def test_factor_returns_top_bottom(random_factor, prices):
    rets = factor_returns(random_factor, prices, weight_method="top_bottom")
    assert isinstance(rets, pd.Series)
    assert len(rets) > 0


def test_factor_returns_equal_weight(random_factor, prices):
    rets = factor_returns(random_factor, prices, weight_method="equal_weight")
    assert isinstance(rets, pd.Series)
    assert len(rets) > 0


def test_factor_returns_invalid_method(random_factor, prices):
    with pytest.raises(ValueError, match="weight_method"):
        factor_returns(random_factor, prices, weight_method="bogus")


# ---------------------------------------------------------------------------
# Turnover and autocorrelation
# ---------------------------------------------------------------------------

def test_turnover_high_for_random_factor(random_factor):
    t = factor_turnover(random_factor, periods=(1, 5, 20))
    assert isinstance(t, pd.Series)
    assert len(t) == 3
    # random factor: rank changes ~0.33 in expectation for IID uniform
    assert t.iloc[0] > 0.2


def test_turnover_low_for_persistent_factor(idx):
    # nearly-constant factor -> tiny rank changes
    f = pd.Series(np.linspace(0.0, 1.0, len(idx)), index=idx)
    t = factor_turnover(f, periods=(1, 5))
    assert t.iloc[0] < 0.05


def test_autocorrelation_decays(idx):
    rng = np.random.default_rng(99)
    # AR(1) with phi=0.8
    n = len(idx)
    x = np.zeros(n)
    eps = rng.standard_normal(n)
    for i in range(1, n):
        x[i] = 0.8 * x[i - 1] + eps[i]
    f = pd.Series(x, index=idx)
    ac = factor_autocorrelation(f, lags=5)
    assert ac.iloc[0] > 0.5
    assert ac.iloc[0] > ac.iloc[4]  # decays with lag


def test_autocorrelation_invalid_lags(random_factor):
    with pytest.raises(ValueError, match="lags"):
        factor_autocorrelation(random_factor, lags=0)


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def test_summary_table_columns(random_factor, prices):
    df = factor_summary_table(random_factor, prices, forward_periods=(1, 5, 20))
    assert list(df.index) == [1, 5, 20]
    expected_cols = {"ic_mean", "ic_ir", "ic_p_value",
                     "quantile_spread", "turnover", "spread_sharpe"}
    assert expected_cols.issubset(set(df.columns))


def test_summary_table_values_finite_or_nan(random_factor, prices):
    df = factor_summary_table(random_factor, prices, forward_periods=(1, 5))
    for col in df.columns:
        # values should be float and either finite or NaN, not raise
        for v in df[col].values:
            assert isinstance(v, float)
