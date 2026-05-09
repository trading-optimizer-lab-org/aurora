"""Tests for StatArbMeanRev."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.strategies.library import StatArbMeanRev, StatArbMRConfig
from aurora.strategies.base import StrategySpec


@pytest.fixture
def factor_panel():
    """5 assets sharing 1 dominant factor + idiosyncratic noise."""
    rng = np.random.default_rng(11)
    n = 250
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    factor_ret = rng.normal(0.0, 0.01, n)
    noise = rng.normal(0.0, 0.005, (n, 5))
    rets = factor_ret[:, None] + noise
    prices = 100.0 * np.cumprod(1.0 + rets, axis=0)
    return pd.DataFrame(prices, index=idx, columns=[f"S{i}" for i in range(5)])


def test_signals_shape_and_values(factor_panel):
    sig = StatArbMeanRev(lookback=30, n_factors=1, entry_z=1.5, exit_z=0.5)
    out = sig.signals(factor_panel)
    assert out.shape == factor_panel.shape
    vals = np.unique(out.values)
    assert set(vals).issubset({-1, 0, 1})


def test_warmup_zeros(factor_panel):
    sig = StatArbMeanRev(lookback=40, n_factors=1, entry_z=1.5, exit_z=0.4)
    out = sig.signals(factor_panel)
    # First lookback-1 rows are zero
    assert (out.iloc[:39] == 0).all().all()


def test_predict_alias(factor_panel):
    sig = StatArbMeanRev(lookback=30, n_factors=1)
    a = sig.signals(factor_panel)
    b = sig.predict(factor_panel)
    pd.testing.assert_frame_equal(a, b)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        StatArbMeanRev(lookback=5)
    with pytest.raises(ValueError):
        StatArbMeanRev(n_factors=0)
    with pytest.raises(ValueError):
        StatArbMeanRev(entry_z=0)


def test_exit_z_projection():
    sig = StatArbMeanRev(lookback=30, entry_z=1.0, exit_z=2.0)
    assert sig.exit_z < sig.entry_z


def test_signals_requires_dataframe():
    sig = StatArbMeanRev(lookback=30)
    with pytest.raises(TypeError):
        sig.signals(np.zeros((100, 5)))


def test_signals_requires_two_assets():
    sig = StatArbMeanRev(lookback=30)
    df = pd.DataFrame({"A": np.arange(100, dtype=float)},
                      index=pd.date_range("2020-01-01", periods=100, freq="B"))
    with pytest.raises(ValueError):
        sig.signals(df)


def test_spec_returns_strategyspec():
    sp = StatArbMeanRev.spec()
    assert isinstance(sp, StrategySpec)
    assert sp.name == "StatArbMeanRev"
    assert "lookback" in sp.params
