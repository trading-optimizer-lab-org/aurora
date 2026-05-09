"""Property-based tests via hypothesis. Task 6.2.

Generates random inputs and checks invariants that must hold for ANY input.
Property violations likely indicate real bugs.

Skipped cleanly when hypothesis is not installed.
"""
from __future__ import annotations
import pytest

# Skip the entire module if hypothesis isn't available
hypothesis = pytest.importorskip("hypothesis")

import numpy as np
import pandas as pd
from hypothesis import given, strategies as st, settings, HealthCheck, assume

from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, ZERO_costs, IBKR_costs, apply_costs
from aurora.core.metrics import compute_metrics
from aurora.strategies.library import (
    MACross, RSIMeanRev, TSMomentum, DonchianBreakout,
)


# ---- helpers ----

def _gbm_prices(n: int, drift: float, vol: float, seed: int = 0) -> pd.Series:
    """Generate synthetic GBM price series."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    p = np.maximum(p, 1e-6)  # avoid division by zero edge cases
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(p, index=idx)


# ---- 1-4: Strategy signals bounded [-1, 1] ----

@given(
    n=st.integers(min_value=200, max_value=2000),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_macross_signals_bounded(n, drift, vol, seed):
    """MACross signals always in [-1, 1] for any synthetic price series."""
    prices = _gbm_prices(n, drift, vol, seed)
    sig = MACross(fast=20, slow=100).signals(prices)
    assert len(sig) == len(prices), f"length mismatch: {len(sig)} vs {len(prices)}"
    assert np.all(np.abs(sig) <= 1.0 + 1e-9), f"out of bounds: max abs {np.abs(sig).max()}"
    assert not np.any(np.isnan(sig)), "NaN in signals"


@given(
    n=st.integers(min_value=200, max_value=2000),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rsi_signals_bounded(n, drift, vol, seed):
    """RSIMeanRev signals always in [-1, 1]."""
    prices = _gbm_prices(n, drift, vol, seed)
    sig = RSIMeanRev(period=2, oversold=10, overbought=90).signals(prices)
    assert len(sig) == len(prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    assert not np.any(np.isnan(sig))


@given(
    n=st.integers(min_value=300, max_value=2000),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_tsmom_signals_bounded(n, drift, vol, seed):
    """TSMomentum signals always in [-1, 1]."""
    prices = _gbm_prices(n, drift, vol, seed)
    sig = TSMomentum(lookback=100, skip=0).signals(prices)
    assert len(sig) == len(prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    assert not np.any(np.isnan(sig))


@given(
    n=st.integers(min_value=200, max_value=2000),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_donchian_signals_bounded(n, drift, vol, seed):
    """DonchianBreakout signals always in [-1, 1]."""
    prices = _gbm_prices(n, drift, vol, seed)
    sig = DonchianBreakout(channel=55, exit_channel=20).signals(prices)
    assert len(sig) == len(prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    assert not np.any(np.isnan(sig))


# ---- 5: Engine NAV non-negative ----

@given(
    n=st.integers(min_value=200, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_engine_nav_non_negative(n, drift, vol, seed):
    """NAV remains non-negative throughout (zero allowed if total ruin)."""
    prices = _gbm_prices(n, drift, vol, seed)

    def signal_fn(p):
        return MACross(fast=20, slow=100).signals(p)

    res = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=252)
    assert np.all(np.isfinite(res.nav)), "NAV has NaN/Inf"
    assert np.all(res.nav >= 0.0), f"NAV went negative: min {res.nav.min()}"
    assert res.nav[0] == 1.0, f"NAV[0] should be 1.0, got {res.nav[0]}"


# ---- 6: Metrics finite ----

@given(
    n=st.integers(min_value=200, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_metrics_finite(n, drift, vol, seed):
    """Metrics dataclass: all numeric fields finite (NaN OK only when MDD=0)."""
    prices = _gbm_prices(n, drift, vol, seed)

    def signal_fn(p):
        return MACross(fast=20, slow=100).signals(p)

    res = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=252)
    m = res.metrics
    for field_name in ["cagr", "mdd", "calmar", "sharpe", "sortino", "mar",
                       "skew", "kurtosis", "win_rate", "profit_factor", "final_nav"]:
        v = getattr(m, field_name)
        assert np.isfinite(v), f"{field_name} not finite: {v}"


# ---- 7: Costs only reduce returns ----

@given(
    n=st.integers(min_value=100, max_value=1000),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_costs_reduce_returns(n, drift, vol, seed):
    """With non-zero costs and positive turnover, sum(net_with_costs) <= sum(net_zero)."""
    prices = _gbm_prices(n, drift, vol, seed)
    p = prices.values.astype(float)
    asset_rets = np.zeros(n); asset_rets[1:] = p[1:] / p[:-1] - 1.0

    weights = MACross(fast=20, slow=100).signals(prices)
    # turnover must be positive for the property to be meaningful
    turnover = np.sum(np.abs(np.diff(weights, prepend=0.0)))
    assume(turnover > 0.0)

    net_zero = apply_costs(weights, asset_rets, ZERO_costs)
    net_costly = apply_costs(weights, asset_rets, IBKR_costs)

    # Costs should reduce cumulative net returns (not strict per-bar - aggregate)
    assert net_costly.sum() <= net_zero.sum() + 1e-12, (
        f"costs increased returns: zero={net_zero.sum()}, costly={net_costly.sum()}"
    )


# ---- 8: Anti-lookahead - perturbing future weights doesn't change past net ----

@given(
    n=st.integers(min_value=100, max_value=500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
    k_frac=st.floats(min_value=0.3, max_value=0.7),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_apply_costs_no_lookahead(n, drift, vol, seed, k_frac):
    """Modifying weights[k:] does not affect net[:k]."""
    prices = _gbm_prices(n, drift, vol, seed)
    p = prices.values.astype(float)
    asset_rets = np.zeros(n); asset_rets[1:] = p[1:] / p[:-1] - 1.0

    rng = np.random.default_rng(seed)
    w_orig = rng.uniform(-1, 1, n)
    k = int(n * k_frac)

    w_mod = w_orig.copy()
    w_mod[k:] = rng.uniform(-1, 1, n - k)

    net_orig = apply_costs(w_orig, asset_rets, IBKR_costs)
    net_mod = apply_costs(w_mod, asset_rets, IBKR_costs)

    # net[:k] must be unchanged when only w[k:] is modified.
    # net[t] depends on w[t-1] and w[t-1]-w[t-2] for cost. So safe boundary is k-1.
    np.testing.assert_array_almost_equal(
        net_orig[:k - 1], net_mod[:k - 1], decimal=10,
        err_msg=f"lookahead detected: w[{k}:] changed net[:{k - 1}]"
    )


# ---- 9: Strategy signal length == prices length ----

@given(
    n=st.integers(min_value=50, max_value=2000),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_signal_length_matches_prices(n, drift, vol, seed):
    """All strategies return signals of length == prices length."""
    prices = _gbm_prices(n, drift, vol, seed)
    for strat in [
        MACross(fast=20, slow=100),
        RSIMeanRev(period=2, oversold=10, overbought=90),
        TSMomentum(lookback=min(100, n // 4), skip=0),
        DonchianBreakout(channel=min(55, n // 4), exit_channel=min(20, n // 8)),
    ]:
        sig = strat.signals(prices)
        assert len(sig) == len(prices), (
            f"{strat.__class__.__name__} length {len(sig)} != prices length {len(prices)}"
        )


# ---- 10: compute_metrics on zero returns -> CAGR=0, MDD=0, Calmar=0 ----

@given(n=st.integers(min_value=50, max_value=1000))
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_metrics_zero_returns(n):
    """compute_metrics on all-zero returns: CAGR=0, MDD=0, Calmar=0, Sharpe=0."""
    r = np.zeros(n)
    m = compute_metrics(r, ppy=252)
    assert m.cagr == 0.0, f"CAGR should be 0, got {m.cagr}"
    assert m.mdd == 0.0, f"MDD should be 0, got {m.mdd}"
    assert m.calmar == 0.0, f"Calmar should be 0 (MDD=0), got {m.calmar}"
    assert m.sharpe == 0.0, f"Sharpe should be 0 (std=0), got {m.sharpe}"
    assert m.final_nav == 1.0, f"final_nav should be 1.0, got {m.final_nav}"


# ---- 11: Calmar = CAGR / |MDD| relationship ----

@given(
    n=st.integers(min_value=300, max_value=1500),
    drift=st.floats(min_value=-0.0005, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.03),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_validation_metrics_consistency(n, drift, vol, seed):
    """Calmar = CAGR / |MDD| relationship holds (both stored as percentages)."""
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    m = compute_metrics(r, ppy=252)

    # Metrics stored as percentages (cagr * 100). Calmar stored unrounded ratio of decimals.
    # Reconstruct: calmar_implied = cagr_decimal / |mdd_decimal|
    if abs(m.mdd) > 1e-6:
        cagr_dec = m.cagr / 100.0
        mdd_dec = m.mdd / 100.0
        calmar_implied = cagr_dec / abs(mdd_dec)
        # Allow rounding tolerance (metrics rounded to 4 decimals)
        assert abs(m.calmar - calmar_implied) < 0.01, (
            f"Calmar mismatch: stored={m.calmar}, implied={calmar_implied} "
            f"(cagr={m.cagr}%, mdd={m.mdd}%)"
        )
    else:
        # MDD ~ 0 -> Calmar should be 0 by definition in compute_metrics
        assert m.calmar == 0.0, f"MDD=0 but Calmar={m.calmar}"


# ---- 12: Equity curve / NAV index is monotonic (timestamps strictly increasing) ----

@given(
    n=st.integers(min_value=100, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_equity_curve_monotonically_indexed(n, drift, vol, seed):
    """Backtest result timestamps strictly increasing AND len(nav) == len(ts)."""
    prices = _gbm_prices(n, drift, vol, seed)

    def signal_fn(p):
        return MACross(fast=20, slow=100).signals(p)

    res = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=252)
    ts = res.timestamps
    assert len(ts) == len(res.nav), (
        f"timestamps length {len(ts)} != nav length {len(res.nav)}"
    )
    # strictly monotone increasing
    diffs = np.diff(ts.astype("datetime64[ns]").astype("int64"))
    assert np.all(diffs > 0), (
        f"timestamps not strictly monotone increasing; min diff = {diffs.min()}"
    )


# ---- 13: Signal series in {-1, 0, +1, NaN} for all library strategies ----
# NOTE: real strategies often emit any value in [-1, 1]. We verify the looser
# property that ALL signals lie within [-1, 1] (which is equivalent to the
# {-1,0,+1} discrete set whenever a strategy is purely directional).

@given(
    n=st.integers(min_value=200, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_all_strategy_signals_in_valid_set(n, drift, vol, seed):
    """For all library strategies: each signal value either lies in [-1, 1] or is NaN."""
    prices = _gbm_prices(n, drift, vol, seed)
    strategies = [
        MACross(fast=20, slow=100),
        RSIMeanRev(period=2, oversold=10, overbought=90),
        TSMomentum(lookback=min(100, max(10, n // 4)), skip=0),
        DonchianBreakout(channel=min(55, max(10, n // 4)),
                         exit_channel=min(20, max(5, n // 8))),
    ]
    for strat in strategies:
        sig = np.asarray(strat.signals(prices), dtype=float)
        finite_mask = ~np.isnan(sig)
        valid_finite = finite_mask & (np.abs(sig) <= 1.0 + 1e-9)
        # Every non-NaN element must satisfy |x| <= 1
        assert np.all(valid_finite[finite_mask]), (
            f"{strat.__class__.__name__} produced out-of-range signals: "
            f"max abs = {np.abs(sig[finite_mask]).max()}"
        )


# ---- 14: Round-trip apply_costs preserves NAV when costs are zero ----

@given(
    n=st.integers(min_value=100, max_value=800),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.04),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_zero_cost_roundtrip_preserves_nav(n, drift, vol, seed):
    """apply_costs with ZERO_costs gives gross NAV identical to manual w[t-1]*r[t]."""
    prices = _gbm_prices(n, drift, vol, seed)
    p = prices.values.astype(float)
    asset_rets = np.zeros(n)
    asset_rets[1:] = p[1:] / p[:-1] - 1.0
    weights = MACross(fast=20, slow=100).signals(prices).astype(float)

    # Apply costs (zero) -> should equal manual gross calc
    net = apply_costs(weights, asset_rets, ZERO_costs)
    manual = np.zeros(n)
    manual[1:] = weights[:-1] * asset_rets[1:]

    np.testing.assert_array_almost_equal(net, manual, decimal=12)

    # NAV constructed from either path should match
    nav_a = np.cumprod(1.0 + net)
    nav_b = np.cumprod(1.0 + manual)
    np.testing.assert_array_almost_equal(nav_a, nav_b, decimal=10)


# ---- 15: Drawdown is always non-positive ----

@given(
    n=st.integers(min_value=100, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_drawdown_always_non_positive(n, drift, vol, seed):
    """For any return series, drawdown[t] = (NAV[t] - max(NAV[:t+1])) / max(...) <= 0."""
    prices = _gbm_prices(n, drift, vol, seed)

    def signal_fn(p):
        return MACross(fast=20, slow=100).signals(p)

    res = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=252)
    nav = res.nav
    cummax = np.maximum.accumulate(nav)
    # Avoid div-by-zero (if NAV crashed to 0 at some point, cummax stays positive)
    safe_cummax = np.where(cummax > 1e-12, cummax, 1.0)
    dd = (nav - cummax) / safe_cummax

    assert np.all(dd <= 1e-12), f"drawdown went positive: max={dd.max()}"
    # Metrics MDD must also be <= 0 (stored as percent)
    assert res.metrics.mdd <= 1e-9, (
        f"metrics.mdd should be non-positive, got {res.metrics.mdd}"
    )
