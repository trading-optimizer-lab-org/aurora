"""Tests for TaxLossHarvester.

Run: pytest quantforge/tests/test_tax_loss_harvester.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.deployment.tax_loss_harvester import (
    TLHConfig,
    TLHResult,
    TaxLossHarvester,
)


@pytest.fixture
def synthetic_prices():
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    # AAPL drops, MSFT rises, NVDA flat.
    aapl = np.linspace(200.0, 100.0, 200)
    msft = np.linspace(300.0, 400.0, 200)
    nvda = np.linspace(500.0, 510.0, 200)
    return pd.DataFrame({"AAPL": aapl, "MSFT": msft, "NVDA": nvda}, index=idx)


@pytest.fixture
def positions():
    return pd.DataFrame({
        "ticker": ["AAPL", "MSFT", "NVDA"],
        "shares": [100.0, 50.0, 25.0],
        "cost_basis": [180.0, 320.0, 510.0],   # AAPL big loss, MSFT gain, NVDA tiny loss
        "purchase_date": [
            pd.Timestamp("2023-01-01"),
            pd.Timestamp("2023-06-01"),
            pd.Timestamp("2023-09-01"),
        ],
    })


def test_returns_dataframe(synthetic_prices, positions):
    tlh = TaxLossHarvester()
    res = tlh.allocate(synthetic_prices, positions)
    assert isinstance(res, TLHResult)
    assert isinstance(res.weights, pd.DataFrame)


def test_aapl_flagged(synthetic_prices, positions):
    cfg = TLHConfig(replacement_map={"AAPL": "VTI"})
    tlh = TaxLossHarvester(cfg)
    res = tlh.allocate(synthetic_prices, positions)
    # AAPL has a $100 / share loss * 100 shares = $10k loss, well above threshold.
    assert "AAPL" in res.realized_loss.index
    assert res.realized_loss["AAPL"] < 0


def test_msft_not_flagged(synthetic_prices, positions):
    tlh = TaxLossHarvester()
    res = tlh.allocate(synthetic_prices, positions)
    # MSFT is at gain -> no suggestion.
    assert "MSFT" not in res.realized_loss.index


def test_replacement_used(synthetic_prices, positions):
    cfg = TLHConfig(replacement_map={"AAPL": "VTI"})
    tlh = TaxLossHarvester(cfg)
    res = tlh.allocate(synthetic_prices, positions)
    assert res.replacements.get("AAPL") == "VTI"


def test_wash_sale_blocks_recent_purchase(synthetic_prices):
    """Position purchased inside the wash-sale window should be blocked."""
    pos = pd.DataFrame({
        "ticker": ["AAPL"],
        "shares": [100.0],
        "cost_basis": [200.0],
        "purchase_date": [pd.Timestamp("2024-09-15")],  # within 30d of 2024-10-...
    })
    cfg = TLHConfig(wash_sale_days=30)
    tlh = TaxLossHarvester(cfg)
    res = tlh.allocate(synthetic_prices, pos, as_of=pd.Timestamp("2024-09-25"))
    assert "AAPL" in res.wash_sale_blocked


def test_recent_buys_block(synthetic_prices, positions):
    cfg = TLHConfig(wash_sale_days=30)
    tlh = TaxLossHarvester(cfg)
    recent = pd.DataFrame({
        "ticker": ["AAPL"],
        "purchase_date": [synthetic_prices.index[-2]],
    })
    res = tlh.allocate(synthetic_prices, positions, recent_buys=recent)
    assert "AAPL" in res.wash_sale_blocked


def test_min_loss_filters_small_positions(synthetic_prices):
    pos = pd.DataFrame({
        "ticker": ["AAPL"],
        "shares": [1.0],     # tiny -> total loss <$ min
        "cost_basis": [105.0],
        "purchase_date": [pd.Timestamp("2023-01-01")],
    })
    cfg = TLHConfig(min_loss_usd=500.0)
    tlh = TaxLossHarvester(cfg)
    res = tlh.allocate(synthetic_prices, pos)
    assert res.realized_loss.empty


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        TaxLossHarvester(TLHConfig(wash_sale_days=-1))


def test_missing_columns_rejected(synthetic_prices):
    bad = pd.DataFrame({"ticker": ["AAPL"], "shares": [10]})  # missing cols
    tlh = TaxLossHarvester()
    with pytest.raises(ValueError):
        tlh.allocate(synthetic_prices, bad)


def test_requires_dataframe_prices(positions):
    tlh = TaxLossHarvester()
    with pytest.raises(TypeError):
        tlh.allocate([1, 2], positions)
