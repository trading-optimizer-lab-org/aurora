"""Tests for MetaAllocator (allocator-of-allocators).

Run: pytest quantforge/tests/test_meta_allocator.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.deployment.meta_allocator import (
    MetaAllocator,
    MetaAllocatorConfig,
    MetaAllocatorResult,
)


@pytest.fixture
def synthetic_prices():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    data = {
        f"A{i}": 100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, 300))
        for i in range(4)
    }
    return pd.DataFrame(data, index=idx)


def test_default_config_valid():
    cfg = MetaAllocatorConfig()
    assert cfg.default_method in ("hrp", "risk_parity", "bl", "equal_weight")
    assert cfg.lookback >= 5


def test_invalid_method_rejected():
    with pytest.raises(ValueError):
        MetaAllocatorConfig(default_method="bogus")


def test_invalid_lookback_rejected():
    with pytest.raises(ValueError):
        MetaAllocatorConfig(lookback=2)


def test_equal_weight_branch(synthetic_prices):
    cfg = MetaAllocatorConfig(
        regime_to_method={"neutral": "equal_weight"},
        default_method="equal_weight",
    )
    ma = MetaAllocator(cfg)
    res = ma.allocate(synthetic_prices, regime="neutral")
    assert isinstance(res, MetaAllocatorResult)
    assert res.method_used == "equal_weight"
    row = res.weights.iloc[0]
    np.testing.assert_allclose(row.values, 0.25, atol=1e-9)
    assert pytest.approx(row.sum(), abs=1e-9) == 1.0


def test_hrp_branch(synthetic_prices):
    cfg = MetaAllocatorConfig(
        regime_to_method={"bull": "hrp"}, default_method="equal_weight",
    )
    ma = MetaAllocator(cfg)
    res = ma.allocate(synthetic_prices, regime="bull")
    assert res.method_used == "hrp"
    row = res.weights.iloc[0]
    assert (row >= -1e-12).all()
    assert pytest.approx(row.sum(), abs=1e-6) == 1.0


def test_risk_parity_branch(synthetic_prices):
    cfg = MetaAllocatorConfig(
        regime_to_method={"bear": "risk_parity"}, default_method="equal_weight",
    )
    ma = MetaAllocator(cfg)
    res = ma.allocate(synthetic_prices, regime="bear")
    assert res.method_used == "risk_parity"
    row = res.weights.iloc[0]
    assert (row >= -1e-9).all()
    assert pytest.approx(row.sum(), abs=1e-4) == 1.0


def test_bl_branch_no_views(synthetic_prices):
    cfg = MetaAllocatorConfig(
        regime_to_method={"bull": "bl"}, default_method="equal_weight",
    )
    ma = MetaAllocator(cfg)
    mc = pd.Series(1.0, index=synthetic_prices.columns)
    res = ma.allocate(synthetic_prices, regime="bull", market_caps=mc)
    assert res.method_used == "bl"
    row = res.weights.iloc[0]
    assert pytest.approx(row.sum(), abs=1e-4) == 1.0


def test_unknown_regime_falls_back(synthetic_prices):
    cfg = MetaAllocatorConfig(
        regime_to_method={"bull": "hrp"},
        default_method="equal_weight",
    )
    ma = MetaAllocator(cfg)
    res = ma.allocate(synthetic_prices, regime="quantum")
    assert res.method_used == "equal_weight"


def test_requires_at_least_two_assets(synthetic_prices):
    ma = MetaAllocator()
    with pytest.raises(ValueError):
        ma.allocate(synthetic_prices.iloc[:, :1], regime="neutral")


def test_requires_dataframe():
    ma = MetaAllocator()
    with pytest.raises(TypeError):
        ma.allocate([1, 2, 3], regime="neutral")
