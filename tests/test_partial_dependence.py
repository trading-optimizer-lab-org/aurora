"""Tests for PartialDependenceAnalysis."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library.ma_cross import MACross
from quantforge.validation.partial_dependence import PartialDependenceAnalysis


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2015-01-01", periods=400, freq="B")
    rets = np.random.default_rng(0).normal(0.001, 0.012, 400)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_basic(fake_prices):
    set_global_seed(42)
    pda = PartialDependenceAnalysis(n_grid=4)
    out = pda.run(
        lambda **kw: MACross(**kw),
        fake_prices,
        param_ranges={"fast": (5, 20), "slow": (50, 100)},
        costs=ZERO_costs,
    )
    assert out is pda
    assert "fast" in pda.results
    assert "slow" in pda.results
    assert pda.results["fast"]["grid"].shape[0] <= 4
    assert pda.results["fast"]["calmars"].shape == pda.results["fast"]["grid"].shape


def test_pinned_values_set(fake_prices):
    set_global_seed(42)
    pda = PartialDependenceAnalysis(n_grid=3).run(
        lambda **kw: MACross(**kw),
        fake_prices,
        param_ranges={"fast": (5, 25), "slow": (50, 150)},
    )
    # Median of (5, 25) = 15; median of (50, 150) = 100
    assert pda.pinned_values["fast"] == 15
    assert pda.pinned_values["slow"] == 100


def test_invalid_inputs(fake_prices):
    with pytest.raises(TypeError):
        PartialDependenceAnalysis().run(lambda **kw: MACross(**kw), [1, 2, 3], {"fast": (5, 10)})
    with pytest.raises(ValueError):
        PartialDependenceAnalysis().run(lambda **kw: MACross(**kw), fake_prices, {})
    with pytest.raises(ValueError):
        PartialDependenceAnalysis(n_grid=1).run(
            lambda **kw: MACross(**kw), fake_prices, {"fast": (5, 10)}
        )
