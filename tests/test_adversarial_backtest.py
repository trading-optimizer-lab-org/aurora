"""Tests for AdversarialBacktester."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.core.costs import ZERO_costs
from aurora.strategies.library.ma_cross import MACross
from aurora.validation.adversarial_backtest import AdversarialBacktester


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2015-01-01", periods=400, freq="B")
    rets = np.random.default_rng(0).normal(0.0005, 0.01, 400)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _factory():
    return lambda: MACross(fast=5, slow=20)


def test_basic_run(fake_prices):
    set_global_seed(42)
    ab = AdversarialBacktester(n_scenarios=2, n_blocks=4, n_iterations=2,
                               max_shock_pct=0.02)
    out = ab.run(_factory(), fake_prices, costs=ZERO_costs)
    assert out is ab
    assert len(ab.adversarial_calmars) == 2
    assert len(ab.adversarial_shocks) == 2
    assert ab.adversarial_shocks[0].shape == (4,)


def test_shocks_within_bound(fake_prices):
    set_global_seed(42)
    ab = AdversarialBacktester(n_scenarios=1, n_blocks=3, n_iterations=2,
                               max_shock_pct=0.03)
    ab.run(_factory(), fake_prices, costs=ZERO_costs)
    s = ab.adversarial_shocks[0]
    assert np.all(np.abs(s) <= 0.03 + 1e-9)


def test_invalid_inputs_raise(fake_prices):
    with pytest.raises(TypeError):
        AdversarialBacktester(n_scenarios=1).run(_factory(), [1, 2, 3])
    with pytest.raises(ValueError):
        AdversarialBacktester(n_scenarios=0).run(_factory(), fake_prices)
    with pytest.raises(ValueError):
        AdversarialBacktester(n_scenarios=1, max_shock_pct=0.0).run(_factory(), fake_prices)
