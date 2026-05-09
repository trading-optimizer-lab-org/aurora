"""Tests for StrategyAllocator. Run: pytest quantforge/tests/test_allocator.py -v"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.costs import ZERO_costs
from aurora.deployment.allocator import (
    StrategyAllocator,
    AllocatorResult,
    equal_weight,
    equal_vol,
    inverse_dd,
    risk_parity,
    rebalance_dates,
)
from aurora.strategies.library.ma_cross import MACross
from aurora.strategies.library.rsi_meanrev import RSIMeanRev


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def two_synth_prices():
    """Two synthetic series of 800 business days, different vol/drift."""
    set_global_seed(11)
    idx = pd.date_range("2015-01-01", periods=800, freq="B")
    rng = np.random.default_rng(11)
    # Asset A: low vol, mild positive drift -> trend-friendly
    rets_a = rng.normal(0.0005, 0.008, 800)
    pa = 100 * np.cumprod(1.0 + rets_a)
    # Asset B: high vol, mean-reverting style noise
    rets_b = rng.normal(0.0002, 0.020, 800)
    pb = 50 * np.cumprod(1.0 + rets_b)
    return {
        "STRAT_TREND": pd.Series(pa, index=idx, name="A"),
        "STRAT_MR": pd.Series(pb, index=idx, name="B"),
    }


# --------------------------------------------------------------------------- #
# Pure-function unit tests                                                    #
# --------------------------------------------------------------------------- #
def test_equal_weight_2strats():
    rets = {"a": np.array([0.01, -0.01, 0.02]),
            "b": np.array([0.0, 0.005, -0.003])}
    w = equal_weight(rets)
    assert w == {"a": 0.5, "b": 0.5}
    assert pytest.approx(sum(w.values()), abs=1e-12) == 1.0


def test_equal_weight_n_strats():
    rets = {f"s{i}": np.zeros(10) for i in range(5)}
    w = equal_weight(rets)
    assert all(v == pytest.approx(0.2) for v in w.values())
    assert pytest.approx(sum(w.values()), abs=1e-12) == 1.0


def test_equal_vol_high_vol_gets_less_weight():
    """High-vol strat should receive a SMALLER weight than the low-vol one."""
    rng = np.random.default_rng(0)
    rets = {
        "low_vol":  rng.normal(0.0, 0.005, 200),
        "high_vol": rng.normal(0.0, 0.030, 200),
    }
    w = equal_vol(rets, lookback=200)
    assert w["low_vol"] > w["high_vol"]
    assert pytest.approx(sum(w.values()), abs=1e-9) == 1.0
    # Sanity: ratio roughly proportional to inverse vols (~6x)
    assert w["low_vol"] / w["high_vol"] > 3.0


def test_inverse_dd_deeper_mdd_gets_less_weight():
    """Strategy with the deeper drawdown should get the smaller weight."""
    # Mild dd: small steady losses
    mild = np.array([-0.001] * 60 + [0.001] * 40)
    # Severe dd: one big crash early, then flat
    severe = np.concatenate([np.full(20, -0.02), np.zeros(80)])
    rets = {"mild": mild, "severe": severe}
    w = inverse_dd(rets, lookback=100)
    assert w["mild"] > w["severe"]
    assert pytest.approx(sum(w.values()), abs=1e-9) == 1.0


def test_risk_parity_basic_2strats():
    """RP should produce positive weights summing to 1 and tilt away from high vol."""
    rng = np.random.default_rng(3)
    rets = {
        "a": rng.normal(0.0, 0.01, 300),
        "b": rng.normal(0.0, 0.03, 300),
    }
    w = risk_parity(rets, lookback=300)
    assert all(v >= 0 for v in w.values())
    assert pytest.approx(sum(w.values()), abs=1e-6) == 1.0
    # Lower-vol asset should have larger weight under risk parity.
    assert w["a"] > w["b"]


# --------------------------------------------------------------------------- #
# Rebalance schedule                                                          #
# --------------------------------------------------------------------------- #
def test_rebalance_monthly():
    """Monthly rebalance: bar 0 + first bar of every subsequent calendar month."""
    idx = pd.date_range("2020-01-01", "2020-06-30", freq="B")
    mask = rebalance_dates(idx, "monthly")
    rb_dates = idx[mask]
    # Every flagged date should be the first occurrence within its (year, month).
    seen = set()
    for d in rb_dates:
        key = (d.year, d.month)
        assert key not in seen, f"two rebalances in same month: {d}"
        seen.add(key)
    # Should cover Jan-Jun 2020 -> 6 months
    assert len(rb_dates) == 6
    # First bar always rebalances
    assert mask[0]


def test_rebalance_weekly():
    idx = pd.date_range("2020-01-01", "2020-01-31", freq="B")
    mask = rebalance_dates(idx, "weekly")
    rb_dates = idx[mask]
    # First flag is bar 0; subsequent flags must be at week boundaries.
    assert mask[0]
    seen_weeks = set()
    for d in rb_dates:
        ic = d.isocalendar()
        key = (ic.year, ic.week)
        assert key not in seen_weeks
        seen_weeks.add(key)


def test_rebalance_daily():
    idx = pd.date_range("2020-01-01", "2020-01-10", freq="B")
    mask = rebalance_dates(idx, "daily")
    assert mask.all()


def test_rebalance_quarterly():
    idx = pd.date_range("2020-01-01", "2020-12-31", freq="B")
    mask = rebalance_dates(idx, "quarterly")
    rb_dates = idx[mask]
    # Q1, Q2, Q3, Q4 -> 4 rebalances
    assert len(rb_dates) == 4


# --------------------------------------------------------------------------- #
# End-to-end run() with real strategies                                       #
# --------------------------------------------------------------------------- #
def test_run_basic(two_synth_prices):
    """2 strategies, synthetic prices -> result with NAV + per-strategy attribution."""
    strategies = {
        "STRAT_TREND": MACross(fast=10, slow=50, allow_short=False),
        "STRAT_MR": RSIMeanRev(period=2, oversold=10, overbought=90, allow_short=False),
    }
    alloc = StrategyAllocator(
        strategies=strategies,
        prices=two_synth_prices,
        method="equal_vol",
        rebalance="monthly",
        lookback=60,
    )
    result = alloc.run(ppy=252)

    assert isinstance(result, AllocatorResult)
    T = len(two_synth_prices["STRAT_TREND"])
    assert result.nav.shape == (T,)
    assert result.rets.shape == (T,)
    assert result.weights.shape == (T, 2)
    assert sorted(result.strategy_names) == ["STRAT_MR", "STRAT_TREND"]
    assert result.method == "equal_vol"
    assert result.rebalance == "monthly"
    assert result.lookback == 60

    # Weights at every bar should sum to ~1.0 (fully invested).
    row_sums = result.weights.sum(axis=1)
    assert np.allclose(row_sums, 1.0, atol=1e-9)
    # Weights should be non-negative for these long-only methods.
    assert (result.weights >= -1e-9).all()

    # Per-strategy attribution should sum to total portfolio return.
    total_attr = sum(result.per_strategy_attribution.values())
    total_port = float(result.rets.sum())
    assert np.isclose(total_attr, total_port, atol=1e-10)

    # NAV[0] = 1.0 by convention; rets[0] = 0.0
    assert result.nav[0] == pytest.approx(1.0)
    assert result.rets[0] == pytest.approx(0.0)


def test_run_equal_weight_method(two_synth_prices):
    """equal_weight: weights row identically (0.5, 0.5) for every bar."""
    strategies = {
        "STRAT_TREND": MACross(fast=10, slow=50, allow_short=False),
        "STRAT_MR": RSIMeanRev(period=2, oversold=10, overbought=90, allow_short=False),
    }
    alloc = StrategyAllocator(
        strategies=strategies, prices=two_synth_prices,
        method="equal_weight", rebalance="monthly", lookback=60,
    )
    res = alloc.run()
    assert np.allclose(res.weights, 0.5, atol=1e-12)


def test_run_rebalance_count(two_synth_prices):
    """Number of rebalance bars should match calendar months in the index."""
    strategies = {
        "STRAT_TREND": MACross(fast=10, slow=50, allow_short=False),
        "STRAT_MR": RSIMeanRev(period=2, oversold=10, overbought=90, allow_short=False),
    }
    alloc = StrategyAllocator(
        strategies=strategies, prices=two_synth_prices,
        method="equal_vol", rebalance="monthly", lookback=60,
    )
    res = alloc.run()
    rb_count = int(res.rebalance_mask.sum())
    idx = pd.DatetimeIndex(res.timestamps)
    expected = len({(d.year, d.month) for d in idx})
    assert rb_count == expected


def test_validation_errors(two_synth_prices):
    strategies = {
        "STRAT_TREND": MACross(),
        "STRAT_MR": RSIMeanRev(),
    }
    # Mismatched keys
    with pytest.raises(ValueError):
        StrategyAllocator(strategies, {"X": two_synth_prices["STRAT_TREND"]})
    # Bad method
    with pytest.raises(ValueError):
        StrategyAllocator(strategies, two_synth_prices, method="bogus")
    # Bad schedule
    with pytest.raises(ValueError):
        StrategyAllocator(strategies, two_synth_prices, rebalance="hourly")
    # Bad lookback
    with pytest.raises(ValueError):
        StrategyAllocator(strategies, two_synth_prices, lookback=1)
    # Empty
    with pytest.raises(ValueError):
        StrategyAllocator({}, {})
    # Wrong type
    with pytest.raises(TypeError):
        StrategyAllocator({"a": "not_a_strategy"}, {"a": two_synth_prices["STRAT_TREND"]})
    # Negative rebalance cost
    with pytest.raises(ValueError):
        StrategyAllocator(strategies, two_synth_prices, rebalance_cost_bps=-1.0)


def test_allocator_rebalance_cost_charged(two_synth_prices):
    """Non-zero rebalance_cost_bps charges cost proportional to turnover.

    Verifies:
        - rebalance_cost_bps=0 -> zero total cost, returns unchanged from
          the zero-cost path.
        - rebalance_cost_bps>0 -> total_rebalance_cost > 0 and final NAV drops
          relative to the zero-cost run (cost is bps/10000 * sum |dw|).
        - Total return drag matches the reported total rebalance cost.
        - Cost scales linearly with bps (10 bps run yields ~2x the cost of 5 bps).
        - Weight matrix and rebalance schedule are unchanged by the cost setting.
    """
    strategies = {
        "STRAT_TREND": MACross(fast=10, slow=50, allow_short=False),
        "STRAT_MR": RSIMeanRev(period=2, oversold=10, overbought=90,
                               allow_short=False),
    }

    base = StrategyAllocator(
        strategies=strategies, prices=two_synth_prices,
        method="equal_vol", rebalance="monthly", lookback=60,
        rebalance_cost_bps=0.0,
    ).run()

    charged = StrategyAllocator(
        strategies=strategies, prices=two_synth_prices,
        method="equal_vol", rebalance="monthly", lookback=60,
        rebalance_cost_bps=25.0,
    ).run()

    # No cost at zero bps.
    assert base.total_rebalance_cost == pytest.approx(0.0, abs=1e-15)
    assert base.rebalance_cost_bps == 0.0

    # Cost is positive at non-zero bps and propagates into the result.
    assert charged.rebalance_cost_bps == pytest.approx(25.0, abs=1e-12)
    assert charged.total_rebalance_cost > 0.0

    # NAV with cost should be < NAV without cost (cost is a drag).
    assert charged.nav[-1] < base.nav[-1]

    # The applied weight matrix and rebalance schedule are independent of cost.
    assert np.array_equal(charged.rebalance_mask, base.rebalance_mask)
    assert np.allclose(charged.weights, base.weights, atol=1e-12)

    # Total return drag equals reported total cost (cost subtracted in
    # return-space at the rebalance bar).
    diff = base.rets - charged.rets
    assert diff.sum() == pytest.approx(charged.total_rebalance_cost, rel=1e-9)
    # Drag concentrated on rebalance bars only.
    non_rb_diff = diff[~charged.rebalance_mask]
    assert np.allclose(non_rb_diff, 0.0, atol=1e-15)

    # Cost scales linearly with bps.
    half = StrategyAllocator(
        strategies=strategies, prices=two_synth_prices,
        method="equal_vol", rebalance="monthly", lookback=60,
        rebalance_cost_bps=12.5,
    ).run()
    assert half.total_rebalance_cost == pytest.approx(
        0.5 * charged.total_rebalance_cost, rel=1e-9,
    )
