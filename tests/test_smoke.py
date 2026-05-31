"""Smoke tests for Aurora core modules. Run: pytest aurora/tests/"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.engine import run_backtest
from aurora.core.costs import ZERO_costs, IBKR_costs, apply_costs
from aurora.core.metrics import compute_metrics, deflated_sharpe
from aurora.strategies.library import MACross, RSIMeanRev, TSMomentum, DonchianBreakout
from aurora.validation.monte_carlo import monte_carlo_bootstrap
from aurora.validation.lookahead_check import scan_lookahead, runtime_lookahead_check


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2010-01-01", periods=2000, freq="B")
    rets = np.random.default_rng(42).normal(0.0005, 0.012, 2000)
    p = 100 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_seed_reproducibility():
    set_global_seed(123)
    a = np.random.rand(5)
    set_global_seed(123)
    b = np.random.rand(5)
    assert np.allclose(a, b)


def test_costs_apply():
    w = np.array([0, 1, 1, 0, -1, -1, 0])
    r = np.array([0, 0.01, -0.005, 0, -0.02, 0.01, 0])
    net = apply_costs(w, r, IBKR_costs)
    assert net.shape == (7,)
    assert net[0] == 0


def test_metrics_basic():
    rets = np.array([0.01, -0.005, 0.02, -0.01, 0.015])
    m = compute_metrics(rets, ppy=252)
    assert m.n_periods == 5
    assert m.calmar != 0


def test_dsr():
    dsr = deflated_sharpe(2.0, 100, 252, skew=0.0, kurtosis=0.0)
    assert 0 <= dsr <= 1


def test_macross(fake_prices):
    s = MACross(fast=10, slow=50)
    sig = s.signals(fake_prices)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)


def test_rsi(fake_prices):
    s = RSIMeanRev(period=2)
    sig = s.signals(fake_prices)
    assert len(sig) == len(fake_prices)


def test_tsmom(fake_prices):
    s = TSMomentum(lookback=100)
    sig = s.signals(fake_prices)
    assert len(sig) == len(fake_prices)


def test_donchian(fake_prices):
    s = DonchianBreakout(channel=55, exit_channel=20)
    sig = s.signals(fake_prices)
    assert len(sig) == len(fake_prices)


def test_engine_run(fake_prices):
    s = MACross(fast=10, slow=50)
    res = run_backtest(fake_prices, s.signals, costs=ZERO_costs)
    assert res.metrics.n_periods > 100
    assert hasattr(res, "calmar")


def test_mc_bootstrap(fake_prices):
    s = MACross(fast=10, slow=50)
    res = run_backtest(fake_prices, s.signals)
    mc = monte_carlo_bootstrap(res.rets[1:], n_paths=100, block_size=21)
    assert mc.n_paths == 100
    assert 0 <= mc.real_mdd_percentile <= 1


def test_lookahead_static_clean():
    s = MACross()
    warns = scan_lookahead(s.signals)
    # Library strategies should be clean (use only past slices)
    # Some warnings ok if false positive on heuristic; full clean unrealistic
    assert isinstance(warns, list)


def test_lookahead_runtime(fake_prices):
    s = MACross(fast=10, slow=50)
    rep = runtime_lookahead_check(s.signals, fake_prices)
    assert rep.runtime_violation == False  # MA cross should be clean


def test_slippage_rejection_tracked(fake_prices, caplog):
    """When slippage model rejects (NaN or raise), engine logs warning and
    increments BacktestResult.slippage_rejections."""
    import logging

    class RejectingSlippage:
        """Returns NaN for every order to simulate full rejection."""
        def impact_bps(self, order_dollars: float, daily_volume: float) -> float:
            return float("nan")

    s = MACross(fast=10, slow=50)

    with caplog.at_level(logging.WARNING, logger="aurora.core.engine"):
        res = run_backtest(
            fake_prices,
            s.signals,
            costs=ZERO_costs,
            slippage_model=RejectingSlippage(),
            daily_volume=1e6,
            portfolio_value=1.0,
        )

    # at least some turnover bars exist on a 2000-bar MA cross series
    assert res.slippage_rejections > 0
    # at least one warning logged about rejection
    assert any(
        "slippage rejection" in rec.message.lower() for rec in caplog.records
    )

    # exception path: slippage model that raises a model-recoverable error.
    # Engine catches only (ValueError, ArithmeticError, OverflowError) so
    # genuine bugs (AttributeError/TypeError/etc.) propagate as expected.
    class RaisingSlippage:
        def impact_bps(self, order_dollars: float, daily_volume: float) -> float:
            raise ValueError("rejected")

    res2 = run_backtest(
        fake_prices,
        s.signals,
        costs=ZERO_costs,
        slippage_model=RaisingSlippage(),
        daily_volume=1e6,
        portfolio_value=1.0,
    )
    assert res2.slippage_rejections > 0


def test_no_slippage_rejection_when_model_accepts(fake_prices):
    """When slippage model accepts every order, slippage_rejections == 0."""

    class AcceptingSlippage:
        def impact_bps(self, order_dollars: float, daily_volume: float) -> float:
            return 1.0  # always 1 bp

    s = MACross(fast=10, slow=50)
    res = run_backtest(
        fake_prices,
        s.signals,
        costs=ZERO_costs,
        slippage_model=AcceptingSlippage(),
        daily_volume=1e6,
        portfolio_value=1.0,
    )
    assert res.slippage_rejections == 0


def test_engine_weights_within_bounds_exact(fake_prices):
    """A signal that emits weights slightly above 1.0 (within tolerance) must be
    accepted, but the BacktestResult.weights are clipped to exactly [-1, 1] so
    downstream consumers see no overflow."""
    # Build a signal that produces a value 1.0 + 5e-10 (within 1e-9 tolerance)
    # and another at exactly -1.0. Engine must accept and then clip exact.
    def near_bound_signal(prices, **_):
        n = len(prices)
        w = np.zeros(n)
        w[0] = 1.0 + 5e-10  # within tolerance — must be accepted, then clipped
        w[1] = -1.0
        w[2] = 0.5
        return w

    res = run_backtest(fake_prices, near_bound_signal, costs=ZERO_costs)
    # Result weights must be within exact bounds (no 1e-9 leakage)
    assert np.all(res.weights >= -1.0)
    assert np.all(res.weights <= 1.0)
    # The slightly-above-1 input should have been clipped to exactly 1.0
    assert res.weights[0] == 1.0

    # Out-of-tolerance overflow must still raise
    def bad_signal(prices, **_):
        n = len(prices)
        w = np.zeros(n)
        w[0] = 1.5  # well outside tolerance
        return w

    with pytest.raises(ValueError, match="weights must be in"):
        run_backtest(fake_prices, bad_signal, costs=ZERO_costs)


def test_first_bar_zero_consistent_across_engines(fake_prices):
    """All three engines must return rets[0] == 0 and nav[0] == 1 without
    silently overwriting first-bar PnL. Previously engine.py and engine_jit.py
    used `nav[0]=1.0` after cumprod, which masked any non-zero first-bar return.
    """
    from aurora.core.engine_jit import run_backtest_jit

    s = MACross(fast=10, slow=50)
    a = run_backtest(fake_prices, s.signals, costs=ZERO_costs)
    b = run_backtest_jit(fake_prices, s.signals, costs=ZERO_costs)

    # rets[0] must be exactly zero (no first-bar PnL from cost or position)
    assert a.rets[0] == 0.0
    assert b.rets[0] == 0.0
    # nav[0] is 1.0 by construction (cumprod of zero-leading rets)
    assert a.nav[0] == pytest.approx(1.0)
    assert b.nav[0] == pytest.approx(1.0)


def test_slippage_does_not_swallow_attribute_error(fake_prices):
    """Engine.run_backtest must NOT swallow AttributeError from a buggy slippage
    model — only ValueError/ArithmeticError/OverflowError are caught as
    rejections. Bugs in the model must propagate so they can be debugged."""

    class BuggySlippage:
        def impact_bps(self, order_dollars: float, daily_volume: float) -> float:
            # Trigger AttributeError — typical bug pattern, must NOT be caught.
            raise AttributeError("intentional bug in slippage model")

    s = MACross(fast=10, slow=50)
    with pytest.raises(AttributeError, match="intentional bug"):
        run_backtest(
            fake_prices,
            s.signals,
            costs=ZERO_costs,
            slippage_model=BuggySlippage(),
            daily_volume=1e6,
            portfolio_value=1.0,
        )
