"""Tests for SlippageStressTest."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import CostModel
from quantforge.strategies.library.ma_cross import MACross
from quantforge.validation.slippage_stress import SlippageStressTest


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2015-01-01", periods=400, freq="B")
    rets = np.random.default_rng(0).normal(0.001, 0.012, 400)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _factory():
    return lambda: MACross(fast=10, slow=40)


def test_basic(fake_prices):
    set_global_seed(42)
    costs = CostModel(commission_bps=1.0, spread_bps=2.0, slippage_bps=3.0)
    sst = SlippageStressTest(multipliers=(1.0, 2.0, 5.0))
    out = sst.run(_factory(), fake_prices, costs=costs)
    assert out is sst
    assert len(sst.stressed_calmars) == 3
    assert len(sst.survives) == 3


def test_higher_mult_lowers_calmar(fake_prices):
    set_global_seed(42)
    costs = CostModel(commission_bps=2.0, spread_bps=4.0, slippage_bps=8.0)
    sst = SlippageStressTest(multipliers=(1.0, 5.0)).run(_factory(), fake_prices, costs=costs)
    # With heavier costs, Calmar should be no better
    assert sst.stressed_calmars[1] <= sst.stressed_calmars[0] + 1e-6


def test_invalid_inputs_raise(fake_prices):
    costs = CostModel(slippage_bps=1.0)
    with pytest.raises(TypeError):
        SlippageStressTest().run(_factory(), [1, 2, 3], costs=costs)
    with pytest.raises(ValueError):
        SlippageStressTest(multipliers=()).run(_factory(), fake_prices, costs=costs)
    with pytest.raises(ValueError):
        SlippageStressTest(multipliers=(-1.0,)).run(_factory(), fake_prices, costs=costs)
