"""Tests for FXHedger.

Run: pytest quantforge/tests/test_fx_hedger.py -v
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
import pytest

from quantforge.deployment.fx_hedger import (
    FXHedgeResult,
    FXHedger,
    FXHedgerConfig,
)


@pytest.fixture
def positions():
    return pd.Series({
        "AAPL": 100_000.0,    # USD
        "BMW.DE": 50_000.0,   # EUR
        "TSCO.L": 30_000.0,   # GBP
        "7203.T": 25_000.0,   # JPY
    })


@pytest.fixture
def cfg():
    return FXHedgerConfig(
        base_currency="USD",
        asset_currencies={
            "AAPL": "USD",
            "BMW.DE": "EUR",
            "TSCO.L": "GBP",
            "7203.T": "JPY",
        },
        spot_rates={"EUR": 1.10, "GBP": 1.25, "JPY": 0.0067},
        base_rate=0.05,
        foreign_rates={"EUR": 0.04, "GBP": 0.045, "JPY": 0.001},
        days_to_expiry=30,
        hedge_ratio=1.0,
    )


def test_returns_dataframe(positions, cfg):
    hedger = FXHedger(cfg)
    res = hedger.allocate(positions)
    assert isinstance(res, FXHedgeResult)
    assert isinstance(res.weights, pd.DataFrame)


def test_excludes_base_currency(positions, cfg):
    hedger = FXHedger(cfg)
    res = hedger.allocate(positions)
    assert "USD" not in res.weights.columns


def test_three_foreign_currencies(positions, cfg):
    hedger = FXHedger(cfg)
    res = hedger.allocate(positions)
    assert set(res.weights.columns) == {"EUR", "GBP", "JPY"}


def test_full_hedge_matches_exposure(positions, cfg):
    hedger = FXHedger(cfg)
    res = hedger.allocate(positions)
    # Full hedge means hedge notional == foreign exposure
    np.testing.assert_allclose(res.weights.iloc[0]["EUR"], 50_000.0)
    np.testing.assert_allclose(res.weights.iloc[0]["GBP"], 30_000.0)


def test_partial_hedge():
    cfg = FXHedgerConfig(
        base_currency="USD",
        asset_currencies={"X": "EUR"},
        spot_rates={"EUR": 1.10},
        foreign_rates={"EUR": 0.0},
        hedge_ratio=0.5,
    )
    hedger = FXHedger(cfg)
    res = hedger.allocate(pd.Series({"X": 100.0}))
    np.testing.assert_allclose(res.weights.iloc[0]["EUR"], 50.0)


def test_forward_rates_match_cip():
    """Covered interest parity: F = S * exp((r_b - r_f) * T)."""
    cfg = FXHedgerConfig(
        base_currency="USD",
        asset_currencies={"X": "EUR"},
        spot_rates={"EUR": 1.10},
        base_rate=0.05,
        foreign_rates={"EUR": 0.02},
        days_to_expiry=365,
    )
    hedger = FXHedger(cfg)
    res = hedger.allocate(pd.Series({"X": 1.0}))
    expected = 1.10 * math.exp((0.05 - 0.02) * 1.0)
    np.testing.assert_allclose(res.forward_rates["EUR"], expected, rtol=1e-9)


def test_invalid_hedge_ratio_rejected():
    with pytest.raises(ValueError):
        FXHedger(FXHedgerConfig(hedge_ratio=1.5))


def test_invalid_days_rejected():
    with pytest.raises(ValueError):
        FXHedger(FXHedgerConfig(days_to_expiry=0))


def test_requires_series():
    hedger = FXHedger()
    with pytest.raises(TypeError):
        hedger.allocate({"X": 1.0})
