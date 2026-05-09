"""Tests for Task I.5 realistic slippage models."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from aurora.core.costs import ZERO_costs
from aurora.core.engine import run_backtest
from aurora.core.slippage import (
    FixedBasisPointsSlippage,
    LinearSlippage,
    SlippageModel,
    SquareRootSlippage,
    VolumeShareSlippage,
    apply_slippage_to_costs,
)


# ----------------------- FixedBasisPointsSlippage ---------------------------

def test_fixed_bps_slippage():
    m = FixedBasisPointsSlippage(basis_points=5.0)
    # impact independent of size and ADV
    assert m.impact_bps(1_000.0, 1_000_000.0) == pytest.approx(5.0)
    assert m.impact_bps(1.0, 1.0) == pytest.approx(5.0)
    assert m.impact_bps(0.0, 1_000_000.0) == pytest.approx(5.0)
    # buy fill > mid by 5 bps; sell fill < mid by 5 bps
    buy = m.fill_price(1_000.0, 100.0, 1_000_000.0, side=+1)
    sell = m.fill_price(1_000.0, 100.0, 1_000_000.0, side=-1)
    assert buy == pytest.approx(100.0 * (1 + 5e-4))
    assert sell == pytest.approx(100.0 * (1 - 5e-4))


# ----------------------- VolumeShareSlippage --------------------------------

def test_volume_share_small_order():
    """Order << ADV produces near-zero impact (quadratic small term)."""
    m = VolumeShareSlippage(volume_limit=0.025, price_impact=0.1)
    # 0.01% of ADV
    bps = m.impact_bps(order_size_dollars=100.0, daily_volume_dollars=1_000_000.0)
    # 0.1 * 1e4 * (1e-4)**2 = 1e-5 bps
    assert bps < 1e-3
    assert bps >= 0.0


def test_volume_share_big_order():
    """Order near volume_limit hits noticeable quadratic impact and big > small."""
    m = VolumeShareSlippage(volume_limit=0.025, price_impact=0.1)
    small = m.impact_bps(10_000.0, 1_000_000.0)        # 1% of ADV
    big = m.impact_bps(24_000.0, 1_000_000.0)          # 2.4% of ADV (just below cap)
    assert big > small > 0.0
    # quadratic check: doubling participation roughly 4x the impact
    a = m.impact_bps(5_000.0, 1_000_000.0)             # 0.5%
    b = m.impact_bps(10_000.0, 1_000_000.0)            # 1.0%
    assert b / a == pytest.approx(4.0, rel=1e-9)


def test_volume_share_exceeds_limit():
    """Order over volume_limit returns NaN sentinel."""
    m = VolumeShareSlippage(volume_limit=0.025, price_impact=0.1)
    bps = m.impact_bps(50_000.0, 1_000_000.0)          # 5% > 2.5% cap
    assert math.isnan(bps)
    fill = m.fill_price(50_000.0, 100.0, 1_000_000.0, side=+1)
    assert math.isnan(fill)


def test_volume_share_zero_volume():
    """Zero ADV -> participation 0 -> 0 bps (degenerate but well-defined)."""
    m = VolumeShareSlippage()
    assert m.impact_bps(1_000.0, 0.0) == pytest.approx(0.0)


# ----------------------- SquareRootSlippage ---------------------------------

def test_square_root_impact_scales_with_sqrt():
    """Doubling participation -> impact * sqrt(2)."""
    m = SquareRootSlippage(coefficient_bps=100.0, sigma_daily=0.02)
    a = m.impact_bps(10_000.0, 1_000_000.0)            # 1%
    b = m.impact_bps(20_000.0, 1_000_000.0)            # 2%
    assert b / a == pytest.approx(math.sqrt(2.0), rel=1e-9)
    # absolute value: 100 * 0.02 * sqrt(0.01) = 0.2
    assert a == pytest.approx(100.0 * 0.02 * math.sqrt(0.01), rel=1e-9)


# ----------------------- LinearSlippage -------------------------------------

def test_linear_slippage_proportional():
    """Doubling participation -> 2x impact exactly."""
    m = LinearSlippage(coefficient_bps=50.0)
    a = m.impact_bps(5_000.0, 1_000_000.0)             # 0.5%
    b = m.impact_bps(10_000.0, 1_000_000.0)            # 1%
    c = m.impact_bps(20_000.0, 1_000_000.0)            # 2%
    assert b / a == pytest.approx(2.0, rel=1e-9)
    assert c / a == pytest.approx(4.0, rel=1e-9)
    assert b == pytest.approx(50.0 * 0.01, rel=1e-9)


# ----------------------- helper / sign --------------------------------------

def test_apply_slippage_returns_extra_bps():
    """apply_slippage_to_costs returns slippage model's bps verbatim (not summed)."""
    m = LinearSlippage(coefficient_bps=100.0)
    bps = apply_slippage_to_costs(
        cost_model=ZERO_costs, slippage_model=m,
        order_size_dollars=10_000.0, mid_price=50.0,
        daily_volume=1_000_000.0, side=+1,
    )
    # 100 * 0.01 = 1.0 bps
    assert bps == pytest.approx(1.0, rel=1e-9)


def test_buy_vs_sell_sign():
    """Buy pays above mid, sell receives below mid; magnitude identical."""
    m = LinearSlippage(coefficient_bps=100.0)
    mid = 200.0
    buy = m.fill_price(10_000.0, mid, 1_000_000.0, side=+1)
    sell = m.fill_price(10_000.0, mid, 1_000_000.0, side=-1)
    assert buy > mid
    assert sell < mid
    assert (buy - mid) == pytest.approx(mid - sell, rel=1e-9)


def test_invalid_side_raises():
    m = LinearSlippage(coefficient_bps=10.0)
    with pytest.raises(ValueError):
        m.fill_price(1_000.0, 100.0, 1_000_000.0, side=0)
    with pytest.raises(ValueError):
        apply_slippage_to_costs(ZERO_costs, m, 1_000.0, 100.0, 1_000_000.0, side=2)


# ----------------------- Engine integration ---------------------------------

def _toy_prices(n: int = 60, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.01, size=n)
    px = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(px, index=idx)


def _flip_signal(prices, **_):
    """Alternate full long / full short every bar -> max turnover."""
    n = len(prices)
    w = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    return w


def test_engine_slippage_model_increases_costs():
    prices = _toy_prices()
    base = run_backtest(prices, _flip_signal, costs=ZERO_costs)
    # With LinearSlippage at 1% participation -> 1 bp per fill
    slip = LinearSlippage(coefficient_bps=100.0)
    impacted = run_backtest(
        prices, _flip_signal, costs=ZERO_costs,
        slippage_model=slip, daily_volume=100.0, portfolio_value=1.0,
    )
    # impacted final NAV must be < baseline because every flip eats bps
    assert impacted.nav[-1] < base.nav[-1]
    # mean returns should differ on bars where weight flipped
    assert not np.allclose(base.rets, impacted.rets)


def test_engine_slippage_requires_volume():
    prices = _toy_prices(n=20)
    with pytest.raises(ValueError):
        run_backtest(
            prices, _flip_signal, costs=ZERO_costs,
            slippage_model=LinearSlippage(), daily_volume=None,
        )


def test_engine_slippage_volume_share_cap_skipped():
    """When VolumeShareSlippage rejects (NaN), engine just skips extra cost."""
    prices = _toy_prices(n=30)
    # tiny ADV so every flip blows past volume_limit -> NaN every bar
    slip = VolumeShareSlippage(volume_limit=0.001, price_impact=0.1)
    res = run_backtest(
        prices, _flip_signal, costs=ZERO_costs,
        slippage_model=slip, daily_volume=1.0, portfolio_value=1.0,
    )
    # should equal the no-slippage baseline because every order was rejected
    base = run_backtest(prices, _flip_signal, costs=ZERO_costs)
    np.testing.assert_allclose(res.rets, base.rets)


def test_subclass_must_implement_impact_bps():
    """ABC enforcement."""
    with pytest.raises(TypeError):
        SlippageModel()  # type: ignore[abstract]


# ----------------------- intraday volume curve ------------------------------

def test_slippage_intraday_volume_curve():
    """VolumeShareSlippage can scale volume_limit via an intraday curve."""
    # Default behavior (no curve): 2.5% cap, 3% participation -> NaN
    flat = VolumeShareSlippage(volume_limit=0.025, price_impact=0.1)
    assert math.isnan(flat.impact_bps(30_000.0, 1_000_000.0))

    # Curve scales the cap mid-day (e.g. higher liquidity at midday)
    def midday_curve(tod: float) -> float:
        # 1.0 at open/close (tod=0 or 1), 2.0 at midday (tod=0.5)
        return 1.0 + (1.0 - abs(2.0 * tod - 1.0))

    curved = VolumeShareSlippage(
        volume_limit=0.025, price_impact=0.1, intraday_curve=midday_curve,
    )
    # At open (tod=0), multiplier=1 -> cap stays at 2.5%, 3% rejected
    assert math.isnan(curved.impact_bps(30_000.0, 1_000_000.0, time_of_day=0.0))
    # At midday (tod=0.5), multiplier=2 -> cap=5%, 3% accepted
    bps_mid = curved.impact_bps(30_000.0, 1_000_000.0, time_of_day=0.5)
    assert math.isfinite(bps_mid)
    assert bps_mid > 0.0
    # Quadratic value matches base formula (curve only affects the cap, not the cost)
    expected = 0.1 * 1e4 * (0.03 ** 2)
    assert bps_mid == pytest.approx(expected, rel=1e-9)

    # Without time_of_day, behaves as the flat default
    bps_no_tod = curved.impact_bps(10_000.0, 1_000_000.0)  # 1% within default 2.5% cap
    assert math.isfinite(bps_no_tod)
    # Larger order without tod still subject to default cap -> reject
    assert math.isnan(curved.impact_bps(30_000.0, 1_000_000.0))

    # Curve returning non-positive multiplier rejects (defensive)
    def kill_curve(tod: float) -> float:
        return 0.0

    killed = VolumeShareSlippage(
        volume_limit=0.025, price_impact=0.1, intraday_curve=kill_curve,
    )
    assert math.isnan(killed.impact_bps(100.0, 1_000_000.0, time_of_day=0.5))
