"""Tests for CapacityEstimator."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library.ma_cross import MACross
from quantforge.validation.capacity_estimator import CapacityEstimator


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2015-01-01", periods=600, freq="B")
    rets = np.random.default_rng(0).normal(0.001, 0.012, 600)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _factory():
    return lambda: MACross(fast=10, slow=50)


def test_basic(fake_prices):
    set_global_seed(42)
    ce = CapacityEstimator(aum_grid=(1e5, 1e7, 1e9), avg_daily_volume=1e6,
                           slippage_coef=1.0)
    out = ce.run(_factory(), fake_prices, costs=ZERO_costs)
    assert out is ce
    assert len(ce.capacity_curve_calmars) == 3
    assert len(ce.capacity_curve_sharpes) == 3


def test_alpha_decreases_with_aum(fake_prices):
    """Higher AUM should produce equal-or-lower Sharpe via slippage erosion."""
    set_global_seed(42)
    ce = CapacityEstimator(aum_grid=(1e3, 1e6, 1e8), avg_daily_volume=1e6,
                           slippage_coef=5.0)
    ce.run(_factory(), fake_prices, costs=ZERO_costs)
    # Last point should be no better than first (use Sharpe to avoid Calmar/MDD edge cases)
    assert ce.capacity_curve_sharpes[-1] <= ce.capacity_curve_sharpes[0] + 1e-6


def test_invalid_inputs_raise(fake_prices):
    with pytest.raises(ValueError):
        CapacityEstimator(avg_daily_volume=0).run(_factory(), fake_prices)
    with pytest.raises(ValueError):
        CapacityEstimator(slippage_coef=-1).run(_factory(), fake_prices)
    with pytest.raises(ValueError):
        CapacityEstimator(alpha_floor_pct=2.0).run(_factory(), fake_prices)
