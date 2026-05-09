"""Tests for RiskPremiaHarvester."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.signals import RiskPremiaHarvester, RiskPremiaConfig


@pytest.fixture
def equity_panel():
    rng = np.random.default_rng(2)
    n = 400
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    drifts = [0.0008, 0.0005, 0.0002, 0.0, -0.0003]
    panel = {}
    for i, d in enumerate(drifts):
        rets = rng.normal(d, 0.01, n)
        panel[f"S{i}"] = 100.0 * np.cumprod(1.0 + rets)
    return pd.DataFrame(panel, index=idx)


def test_signals_shape(equity_panel):
    rh = RiskPremiaHarvester()
    out = rh.signals(equity_panel)
    assert out.shape == equity_panel.shape


def test_signals_values(equity_panel):
    rh = RiskPremiaHarvester()
    out = rh.signals(equity_panel)
    assert set(np.unique(out.values)).issubset({-1, 0, 1})


def test_with_fundamentals(equity_panel):
    idx = equity_panel.index
    cols = equity_panel.columns
    rng = np.random.default_rng(7)
    funds = {
        "carry": pd.DataFrame(rng.uniform(0.01, 0.05, equity_panel.shape), index=idx, columns=cols),
        "value": pd.DataFrame(rng.uniform(0.5, 2.0, equity_panel.shape), index=idx, columns=cols),
        "quality": pd.DataFrame(rng.uniform(0.05, 0.3, equity_panel.shape), index=idx, columns=cols),
    }
    rh = RiskPremiaHarvester()
    out = rh.signals(equity_panel, fundamentals=funds)
    assert out.shape == equity_panel.shape


def test_invalid_quantiles():
    with pytest.raises(ValueError):
        RiskPremiaHarvester(RiskPremiaConfig(short_quantile=0.5, long_quantile=0.5))


def test_zero_weights_returns_zero(equity_panel):
    rh = RiskPremiaHarvester(RiskPremiaConfig(weights={}))
    out = rh.signals(equity_panel)
    assert (out == 0).all().all()


def test_requires_dataframe():
    rh = RiskPremiaHarvester()
    with pytest.raises(TypeError):
        rh.signals(np.zeros((10, 5)))
