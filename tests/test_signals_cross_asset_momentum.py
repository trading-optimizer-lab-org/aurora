"""Tests for CrossAssetMomentum."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.signals import CrossAssetMomentum, CrossAssetMomentumConfig


@pytest.fixture
def diverse_panel():
    """6 assets with varied drifts."""
    rng = np.random.default_rng(3)
    n = 400
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    drifts = [0.0008, 0.0005, 0.0002, 0.0, -0.0003, -0.0006]
    cols = []
    for i, d in enumerate(drifts):
        rets = rng.normal(d, 0.01, n)
        cols.append(pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name=f"A{i}"))
    return pd.concat(cols, axis=1)


def test_signals_shape(diverse_panel):
    sig = CrossAssetMomentum()
    out = sig.signals(diverse_panel)
    assert out.shape == diverse_panel.shape


def test_signals_values(diverse_panel):
    sig = CrossAssetMomentum()
    out = sig.signals(diverse_panel)
    assert set(np.unique(out.values)).issubset({-1, 0, 1})


def test_top_drifts_get_long(diverse_panel):
    sig = CrossAssetMomentum()
    out = sig.signals(diverse_panel)
    last = out.iloc[-1]
    # Highest drift asset (A0) should appear in long set or at least non-negative
    assert last["A0"] >= last["A5"]


def test_invalid_quantiles():
    with pytest.raises(ValueError):
        CrossAssetMomentum(CrossAssetMomentumConfig(short_quantile=0.5, long_quantile=0.4))


def test_too_few_assets_raises():
    sig = CrossAssetMomentum(CrossAssetMomentumConfig(min_assets=5))
    df = pd.DataFrame({"A": np.arange(400, dtype=float),
                       "B": np.arange(400, dtype=float)},
                      index=pd.date_range("2018-01-01", periods=400, freq="B"))
    with pytest.raises(ValueError):
        sig.signals(df)


def test_too_few_bars_raises(diverse_panel):
    sig = CrossAssetMomentum()
    with pytest.raises(ValueError):
        sig.signals(diverse_panel.iloc[:50])
