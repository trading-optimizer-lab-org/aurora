"""Property-based tests v2 — extended invariants for v4.0 spine.

Roadmap item #11 (extended). Adds Hypothesis-based invariants for:

- Strategy library extension (BollingerMR, DualMomentum, ATRBreakout,
  StopWrapper, VolTargetWrapper).
- ProtocolPolicy hash determinism and tamper detection.
- split_by_tier disjoint partition + monotonic ordering.
- Cost model identity / no-turnover / monotonicity.
- Metrics edge cases (constant returns).
- Engine output finiteness.

Skipped cleanly when hypothesis is not installed.
"""
from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")

from dataclasses import replace

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, assume, given, settings, strategies as st

from quantforge.core.costs import IBKR_costs, ZERO_costs, apply_costs
from quantforge.core.data_tiers import split_by_tier
from quantforge.core.engine import run_backtest
from quantforge.core.metrics import compute_metrics
from quantforge.core.protocol_policy import ProtocolPolicy
from quantforge.strategies.library import (
    ATRBreakout,
    BollingerMR,
    DualMomentum,
    MACross,
    StopWrapper,
    VolTargetWrapper,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_HC = [HealthCheck.too_slow, HealthCheck.function_scoped_fixture]


def _gbm(
    n: int,
    drift: float,
    vol: float,
    seed: int = 0,
    start: str = "2020-01-01",
) -> pd.Series:
    """Synthetic GBM price series with strictly positive prices."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    p = np.maximum(p, 1e-6)
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.Series(p, index=idx)


# ===========================================================================
# Phase 1: strategy library extension
# ===========================================================================


@given(
    n=st.integers(min_value=200, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
    period=st.integers(min_value=10, max_value=50),
    num_std=st.floats(min_value=1.5, max_value=3.0),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_bollinger_signals_in_set(n, drift, vol, seed, period, num_std):
    """BollingerMR signals always lie in {-1, 0, 1} for any input."""
    prices = _gbm(n, drift, vol, seed)
    sig = BollingerMR(period=period, num_std=num_std).signals(prices)
    assert len(sig) == len(prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    assert not np.any(np.isnan(sig))
    assert np.all(np.isin(sig, [-1.0, 0.0, 1.0])), (
        f"out-of-set values: {np.unique(sig)}"
    )


@given(
    n=st.integers(min_value=400, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
    lookback=st.integers(min_value=60, max_value=252),
    skip=st.integers(min_value=0, max_value=21),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_dual_momentum_signals_in_set(n, drift, vol, seed, lookback, skip):
    """DualMomentum signals always lie in {-1, 0, 1}."""
    assume(n > lookback + skip + 10)
    prices = _gbm(n, drift, vol, seed)
    sig = DualMomentum(
        lookback=lookback, skip=skip, allow_short=True
    ).signals(prices)
    assert len(sig) == len(prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    assert not np.any(np.isnan(sig))
    assert np.all(np.isin(sig, [-1.0, 0.0, 1.0]))


@given(
    n=st.integers(min_value=300, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
    period=st.integers(min_value=10, max_value=60),
    atr_period=st.integers(min_value=5, max_value=30),
    k=st.floats(min_value=0.5, max_value=3.0),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_atr_breakout_signals_in_set(
    n, drift, vol, seed, period, atr_period, k
):
    """ATRBreakout signals always lie in {-1, 0, 1}."""
    assume(n > max(period, atr_period) + 10)
    prices = _gbm(n, drift, vol, seed)
    sig = ATRBreakout(
        period=period, atr_period=atr_period, k=k, allow_short=True
    ).signals(prices)
    assert len(sig) == len(prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    assert not np.any(np.isnan(sig))
    assert np.all(np.isin(sig, [-1.0, 0.0, 1.0]))


@given(
    n=st.integers(min_value=300, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
    stop_pct=st.floats(min_value=0.01, max_value=0.10),
    take_pct=st.floats(min_value=0.05, max_value=0.50),
    lockout=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_stop_wrapper_signals_bounded(
    n, drift, vol, seed, stop_pct, take_pct, lockout
):
    """StopWrapper preserves length and signal bounds."""
    prices = _gbm(n, drift, vol, seed)
    base = MACross(fast=20, slow=100)
    sig = StopWrapper(
        base=base,
        stop_pct=stop_pct,
        take_pct=take_pct,
        lockout=lockout,
    ).signals(prices)
    assert len(sig) == len(prices)
    assert np.all(np.abs(sig) <= 1.0 + 1e-9)
    assert not np.any(np.isnan(sig))


@given(
    n=st.integers(min_value=300, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
    target_vol=st.floats(min_value=0.05, max_value=0.30),
    max_w=st.floats(min_value=0.05, max_value=1.0),
    vol_window=st.integers(min_value=10, max_value=120),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_voltarget_wrapper_capped_by_max_w(
    n, drift, vol, seed, target_vol, max_w, vol_window
):
    """VolTargetWrapper output magnitudes never exceed max_w."""
    assume(n > vol_window + 5)
    prices = _gbm(n, drift, vol, seed)
    base = MACross(fast=20, slow=100)
    sig = VolTargetWrapper(
        base=base,
        target_vol=target_vol,
        max_w=max_w,
        vol_window=vol_window,
    ).signals(prices)
    assert len(sig) == len(prices)
    finite = np.isfinite(sig)
    # ignore warmup NaN-only band; assert magnitude cap on finite values only.
    assert np.all(np.abs(sig[finite]) <= max_w + 1e-9), (
        f"max |sig| {np.abs(sig[finite]).max()} > max_w {max_w}"
    )


# ===========================================================================
# Phase 2: ProtocolPolicy hash invariants
# ===========================================================================


def test_protocol_policy_hash_deterministic():
    """Two independent default() instances produce the same hash."""
    p1 = ProtocolPolicy.default()
    p2 = ProtocolPolicy.default()
    assert p1.policy_hash == p2.policy_hash
    assert p1.policy_hash == p1.compute_hash()


def test_protocol_policy_verify_hash_positive():
    """A freshly constructed policy verifies its own hash."""
    p = ProtocolPolicy.default()
    assert p.verify_hash() is True


@given(new_lev=st.floats(min_value=1.5, max_value=10.0))
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_protocol_policy_hash_changes_on_risk_mutation(new_lev):
    """Any nontrivial change to risk_limits must change the hash."""
    p1 = ProtocolPolicy.default()
    new_risk = replace(p1.risk_limits, max_leverage=new_lev)
    p2 = replace(p1, risk_limits=new_risk)
    p2 = p2._with_hash()
    if abs(new_lev - p1.risk_limits.max_leverage) > 1e-9:
        assert p1.policy_hash != p2.policy_hash


@given(new_thresh=st.floats(min_value=0.05, max_value=0.95))
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_protocol_policy_hash_changes_on_promotion_threshold(new_thresh):
    """Mutating max_drawdown_promotion_threshold flips the hash."""
    p1 = ProtocolPolicy.default()
    new_risk = replace(
        p1.risk_limits, max_drawdown_promotion_threshold=new_thresh
    )
    p2 = replace(p1, risk_limits=new_risk)._with_hash()
    if abs(new_thresh - p1.risk_limits.max_drawdown_promotion_threshold) > 1e-9:
        assert p1.policy_hash != p2.policy_hash


# ===========================================================================
# Phase 2: tier split partition invariants
# ===========================================================================


@given(
    n=st.integers(min_value=300, max_value=3000),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_split_by_tier_disjoint_and_complete(n, seed):
    """Sum of per-tier lengths == input length; index union == input index."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1990-01-01", "2030-12-31", periods=n)
    prices = pd.Series(100.0 + rng.normal(0, 1, n).cumsum(), index=idx)
    s = split_by_tier(prices)
    total = (
        len(s.is_train)
        + len(s.is_valid)
        + len(s.oos_dev)
        + len(s.oos_locked)
        + len(s.forward)
    )
    assert total == len(prices), (
        f"tier coverage mismatch: {total} vs {len(prices)}"
    )
    union = (
        set(s.is_train.index)
        | set(s.is_valid.index)
        | set(s.oos_dev.index)
        | set(s.oos_locked.index)
        | set(s.forward.index)
    )
    assert len(union) == len(prices), "tier indices overlap or miss bars"


@given(
    n=st.integers(min_value=300, max_value=2500),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_split_by_tier_monotonic_ordering(n, seed):
    """Each tier ends strictly before the next begins (when both nonempty)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1990-01-01", "2030-12-31", periods=n)
    prices = pd.Series(100.0 + rng.normal(0, 1, n).cumsum(), index=idx)
    s = split_by_tier(prices)

    chain = [s.is_train, s.is_valid, s.oos_dev, s.oos_locked, s.forward]
    for left, right in zip(chain, chain[1:]):
        if len(left) and len(right):
            assert left.index.max() < right.index.min(), (
                f"tier overlap: {left.index.max()} >= {right.index.min()}"
            )


# ===========================================================================
# Phase 2: cost model invariants
# ===========================================================================


@given(
    n=st.integers(min_value=50, max_value=1000),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_zero_costs_identity_on_strategy_returns(n, drift, vol, seed):
    """ZERO_costs preserves gross returns: net[1:] == w[:-1] * rets[1:] exactly."""
    prices = _gbm(n, drift, vol, seed)
    p = prices.values.astype(float)
    rets = np.zeros(n)
    rets[1:] = p[1:] / p[:-1] - 1.0
    weights = MACross(fast=20, slow=100).signals(prices)
    net = apply_costs(weights, rets, ZERO_costs)
    expected = weights[:-1] * rets[1:]
    np.testing.assert_array_almost_equal(net[1:], expected, decimal=12)


@given(
    n=st.integers(min_value=50, max_value=600),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
    weight=st.floats(min_value=-1.0, max_value=1.0),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_constant_weight_no_turnover_cost(n, drift, vol, seed, weight):
    """Constant weights => turnover cost = 0 from bar 1 onward.

    apply_costs prepends 0 for delta_w[0], so the only cost shows up at bar 0
    (initial entry). For bars >= 1, net[i] == w * rets[i] - borrow_term.
    With ZERO_costs, borrow term is 0 too, so net[i] == w * rets[i] exactly.
    """
    prices = _gbm(n, drift, vol, seed)
    p = prices.values.astype(float)
    rets = np.zeros(n)
    rets[1:] = p[1:] / p[:-1] - 1.0
    weights = np.full(n, weight)
    net = apply_costs(weights, rets, ZERO_costs)
    expected = weight * rets
    # All bars must match (no turnover cost, no borrow under ZERO_costs).
    np.testing.assert_array_almost_equal(net[1:], expected[1:], decimal=12)


@given(
    n=st.integers(min_value=100, max_value=600),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_costs_monotone_in_turnover(n, drift, vol, seed):
    """Higher turnover => higher (or equal) total cost.

    Compares static weights w=0.5 (zero turnover) vs flipping weights
    w=±0.5 (max turnover). Costly model must show net_static_sum
    >= net_flip_sum.
    """
    prices = _gbm(n, drift, vol, seed)
    p = prices.values.astype(float)
    rets = np.zeros(n)
    rets[1:] = p[1:] / p[:-1] - 1.0
    static = np.full(n, 0.5)
    flipping = 0.5 * np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    s_net = apply_costs(static, rets, IBKR_costs).sum()
    f_net = apply_costs(flipping, rets, IBKR_costs).sum()
    # Flipping pays more turnover cost; gross PnL of the flipping signal can
    # be anything, so we measure cost specifically by subtracting gross.
    s_gross = (static[:-1] * rets[1:]).sum()
    f_gross = (flipping[:-1] * rets[1:]).sum()
    s_cost = s_gross - s_net
    f_cost = f_gross - f_net
    assert f_cost >= s_cost - 1e-12, (
        f"flipping cost {f_cost} not >= static cost {s_cost}"
    )


# ===========================================================================
# Phase 2: metrics edge cases
# ===========================================================================


@given(
    n=st.integers(min_value=50, max_value=500),
    c=st.floats(min_value=-0.005, max_value=0.005),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_metrics_constant_returns_no_inf(n, c):
    """Constant-return inputs produce sane metrics.

    Risk-free-like inputs (constant returns, zero realized variance) leave
    Calmar = CAGR / MDD with MDD = 0 -> mathematically inf for c > 0 and
    nan for c == 0. We exercise only metrics that should remain finite for
    any constant-rate input: cagr, mdd, sharpe, sortino. Calmar / MAR are
    intentionally permitted to take inf or nan in this degenerate regime.
    """
    rets = np.full(n, c)
    m = compute_metrics(rets)
    # cagr should be ~ (1+c)^ppy - 1, finite for any c in our range.
    assert np.isfinite(m.cagr), f"cagr={m.cagr} non-finite for c={c}"
    # mdd is 0 for non-decreasing nav; finite for any input.
    assert np.isfinite(m.mdd), f"mdd={m.mdd} non-finite for c={c}"
    # Sharpe / Sortino: zero-vol input forces 0/0 -> they may be NaN
    # (acceptable). They must NEVER be +/- inf, which would indicate a
    # silent division-by-zero bug.
    for key in ("sharpe", "sortino"):
        v = getattr(m, key, None)
        if v is None:
            continue
        if isinstance(v, float):
            assert not np.isinf(v), f"{key}={v} is inf for constant rets={c}"


# ===========================================================================
# Phase 2: engine output finiteness
# ===========================================================================


@given(
    n=st.integers(min_value=200, max_value=1500),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_engine_returns_finite_under_zero_costs(n, drift, vol, seed):
    """run_backtest produces finite returns for any positive GBM input."""
    prices = _gbm(n, drift, vol, seed)

    def signal_fn(p):
        return MACross(fast=20, slow=100).signals(p)

    res = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=252)
    rets = np.asarray(res.rets)
    assert np.all(np.isfinite(rets)), "engine returns contain non-finite values"
    assert len(rets) == len(prices), "engine returns length mismatch"


@given(
    n=st.integers(min_value=200, max_value=1000),
    drift=st.floats(min_value=-0.001, max_value=0.001),
    vol=st.floats(min_value=0.005, max_value=0.05),
    seed=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_engine_nav_positive_under_zero_costs(n, drift, vol, seed):
    """NAV stays strictly positive under realistic strategies + ZERO costs."""
    prices = _gbm(n, drift, vol, seed)

    def signal_fn(p):
        return MACross(fast=20, slow=100).signals(p)

    res = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=252)
    nav = np.asarray(res.nav)
    assert np.all(nav > 0.0), f"nav crossed zero: min {nav.min()}"
    assert np.all(np.isfinite(nav)), "nav has non-finite values"
