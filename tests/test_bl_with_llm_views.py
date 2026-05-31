"""Tests for BLLLMViews.

Run: pytest aurora/tests/test_bl_with_llm_views.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.deployment.bl_with_llm_views import (
    BLLLMConfig,
    BLLLMResult,
    BLLLMViews,
)


@pytest.fixture
def synthetic_prices():
    rng = np.random.default_rng(11)
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    data = {f"S{i}": 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.012, 300))
            for i in range(3)}
    return pd.DataFrame(data, index=idx)


def _stub_no_views(assets, news_text, macro_text):
    return None, None


def _stub_one_view(assets, news_text, macro_text):
    """Strong positive view on the first asset."""
    p = pd.DataFrame([[1.0] + [0.0] * (len(assets) - 1)], columns=assets)
    q = pd.Series([0.05])
    return p, q


def test_no_views_falls_back_to_prior(synthetic_prices):
    cfg = BLLLMConfig(view_generator=_stub_no_views)
    bl = BLLLMViews(cfg)
    res = bl.allocate(synthetic_prices)
    assert isinstance(res, BLLLMResult)
    assert res.used_llm_views is False
    s = res.weights.iloc[0].sum()
    assert pytest.approx(s, abs=1e-4) == 1.0


def test_one_view_increases_target_weight(synthetic_prices):
    """Asset with a strong positive view gets the largest weight."""
    cfg = BLLLMConfig(view_generator=_stub_one_view, view_confidence=0.9)
    bl = BLLLMViews(cfg)
    mc = pd.Series(1.0, index=synthetic_prices.columns)
    res = bl.allocate(synthetic_prices, market_caps=mc)
    assert res.used_llm_views is True
    row = res.weights.iloc[0]
    assert row.iloc[0] >= row.iloc[1]
    assert row.iloc[0] >= row.iloc[2]


def test_weights_non_negative(synthetic_prices):
    cfg = BLLLMConfig(view_generator=_stub_one_view, view_confidence=0.6)
    bl = BLLLMViews(cfg)
    res = bl.allocate(synthetic_prices)
    assert (res.weights.iloc[0] >= -1e-9).all()


def test_market_caps_default_equal(synthetic_prices):
    cfg = BLLLMConfig(view_generator=_stub_no_views)
    bl = BLLLMViews(cfg)
    res = bl.allocate(synthetic_prices, market_caps=None)
    s = res.weights.iloc[0].sum()
    assert pytest.approx(s, abs=1e-4) == 1.0


def test_requires_dataframe():
    bl = BLLLMViews()
    with pytest.raises(TypeError):
        bl.allocate([1, 2, 3])


def test_requires_two_assets(synthetic_prices):
    bl = BLLLMViews()
    with pytest.raises(ValueError):
        bl.allocate(synthetic_prices.iloc[:, :1])


def test_posterior_returns_present(synthetic_prices):
    cfg = BLLLMConfig(view_generator=_stub_one_view)
    bl = BLLLMViews(cfg)
    res = bl.allocate(synthetic_prices)
    assert isinstance(res.posterior_returns, pd.Series)
    assert len(res.posterior_returns) == synthetic_prices.shape[1]


def test_views_dataframe_present_when_views_used(synthetic_prices):
    cfg = BLLLMConfig(view_generator=_stub_one_view)
    bl = BLLLMViews(cfg)
    res = bl.allocate(synthetic_prices)
    assert isinstance(res.views_p, pd.DataFrame)
    assert isinstance(res.views_q, pd.Series)
    assert len(res.views_p) >= 1
