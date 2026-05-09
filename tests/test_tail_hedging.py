"""Tests for TailHedgingOverlay.

Run: pytest quantforge/tests/test_tail_hedging.py -v
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
import pytest

from aurora.deployment.tail_hedging import (
    TailHedgeConfig,
    TailHedgeResult,
    TailHedgingOverlay,
    black_scholes_put,
)


@pytest.fixture
def synthetic_prices():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2020-01-01", periods=250, freq="B")
    data = {
        "AAPL": 100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.012, 250)),
        "MSFT": 200.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.011, 250)),
        "GOOG": 150.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.013, 250)),
    }
    return pd.DataFrame(data, index=idx)


# ----- Black-Scholes sanity ------------------------------------------------ #
def test_atm_put_price_positive():
    bs = black_scholes_put(spot=100.0, strike=100.0, ttm=0.25, sigma=0.2)
    assert bs["price"] > 0


def test_put_delta_in_minus_one_zero():
    bs = black_scholes_put(spot=100.0, strike=90.0, ttm=0.5, sigma=0.25)
    assert -1.0 <= bs["delta"] <= 0.0


def test_otm_put_cheaper_than_atm():
    atm = black_scholes_put(spot=100.0, strike=100.0, ttm=0.25, sigma=0.2)
    otm = black_scholes_put(spot=100.0, strike=80.0, ttm=0.25, sigma=0.2)
    assert otm["price"] < atm["price"]


def test_zero_ttm_intrinsic_only():
    # Out-of-the-money put with no time has no value.
    bs = black_scholes_put(spot=100.0, strike=80.0, ttm=0.0, sigma=0.2)
    assert bs["price"] == 0.0


def test_put_call_parity_sanity():
    # Put price always >= max(K - S, 0)
    bs = black_scholes_put(spot=100.0, strike=120.0, ttm=0.5, sigma=0.2)
    assert bs["price"] >= max(120.0 - 100.0, 0.0) - 1e-9


# ----- TailHedgingOverlay -------------------------------------------------- #
def test_returns_dataframe(synthetic_prices):
    overlay = TailHedgingOverlay()
    res = overlay.allocate(synthetic_prices)
    assert isinstance(res, TailHedgeResult)
    assert isinstance(res.weights, pd.DataFrame)


def test_premium_within_budget(synthetic_prices):
    overlay = TailHedgingOverlay(TailHedgeConfig(budget_pct_nav=0.005))
    res = overlay.allocate(synthetic_prices)
    assert res.premium_spent <= 0.005 + 1e-12


def test_greeks_present(synthetic_prices):
    overlay = TailHedgingOverlay()
    res = overlay.allocate(synthetic_prices)
    assert set(res.put_greeks.columns) == {"delta", "gamma", "vega", "theta"}
    assert (res.put_greeks["delta"] <= 0).all()


def test_invalid_budget_rejected():
    with pytest.raises(ValueError):
        TailHedgingOverlay(TailHedgeConfig(budget_pct_nav=0.0))


def test_invalid_moneyness_rejected():
    with pytest.raises(ValueError):
        TailHedgingOverlay(TailHedgeConfig(moneyness=1.5))


def test_requires_dataframe():
    overlay = TailHedgingOverlay()
    with pytest.raises(TypeError):
        overlay.allocate([1, 2])
