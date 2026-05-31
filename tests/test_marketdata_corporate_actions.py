"""Tests for aurora.marketdata.corporate_actions."""
from __future__ import annotations

import pandas as pd
import pytest

from aurora.marketdata.corporate_actions import (
    CorporateActionsAdjuster,
    CorporateActionsConfig,
)


@pytest.fixture
def adjuster() -> CorporateActionsAdjuster:
    return CorporateActionsAdjuster()


@pytest.fixture
def prices() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime([
            "2025-01-01", "2025-01-02", "2025-01-03",
            "2025-01-04", "2025-01-05",
        ]),
        "symbol": ["X"] * 5,
        "open": [100.0, 100.5, 200.0, 200.5, 201.0],
        "high": [101.0, 101.5, 201.0, 201.5, 202.0],
        "low": [99.0, 99.5, 199.0, 199.5, 200.0],
        "close": [100.5, 101.0, 200.5, 201.0, 201.5],
        "volume": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0],
    })


def test_2_for_1_split_halves_pre_split_prices(
    adjuster: CorporateActionsAdjuster, prices: pd.DataFrame,
):
    actions = pd.DataFrame({
        "date": [pd.Timestamp("2025-01-03")],
        "symbol": ["X"],
        "action_type": ["split"],
        "factor": [2.0],
    })
    out = adjuster.adjust(prices, actions)
    # Pre-split rows (Jan 1, 2): adj_close = close / 2.
    pre = out[out["date"] < "2025-01-03"]
    assert (pre["adj_close"] == pre["close"] / 2.0).all()
    # Post-split rows unchanged.
    post = out[out["date"] >= "2025-01-03"]
    assert (post["adj_close"] == post["close"]).all()


def test_dividend_proportional_adjustment(
    adjuster: CorporateActionsAdjuster, prices: pd.DataFrame,
):
    actions = pd.DataFrame({
        "date": [pd.Timestamp("2025-01-03")],
        "symbol": ["X"],
        "action_type": ["dividend"],
        "factor": [1.0],  # $1 cash dividend
    })
    out = adjuster.adjust(prices, actions)
    pre = out[out["date"] < "2025-01-03"]
    # Pre-dividend factor < 1, so adj_close < close.
    assert (pre["adj_close"] < pre["close"]).all()
    # Post-dividend rows unchanged.
    post = out[out["date"] >= "2025-01-03"]
    assert (post["adj_factor"] == 1.0).all()


def test_no_actions_returns_unadjusted(
    adjuster: CorporateActionsAdjuster, prices: pd.DataFrame,
):
    out = adjuster.adjust(prices, pd.DataFrame())
    assert (out["adj_close"] == out["close"]).all()
    assert (out["adj_factor"] == 1.0).all()


def test_empty_prices_returns_empty(adjuster: CorporateActionsAdjuster):
    out = adjuster.adjust(pd.DataFrame({
        "date": [], "symbol": [], "open": [], "high": [],
        "low": [], "close": [], "volume": [],
    }), pd.DataFrame())
    assert out.empty


def test_volume_adjusted_by_split_when_enabled(
    prices: pd.DataFrame,
):
    adj = CorporateActionsAdjuster(CorporateActionsConfig(adjust_volume=True))
    actions = pd.DataFrame({
        "date": [pd.Timestamp("2025-01-03")],
        "symbol": ["X"],
        "action_type": ["split"],
        "factor": [2.0],
    })
    out = adj.adjust(prices, actions)
    pre_vol = out[out["date"] < "2025-01-03"]["volume"]
    # Pre-split volumes scaled by 1/(1/2) = 2 (we divide volume by factor;
    # factor here is 0.5 so volume * 2).
    orig_pre_vol = prices[prices["date"] < "2025-01-03"]["volume"].values
    assert all(v == round(o * 2.0) for v, o in zip(pre_vol.values, orig_pre_vol))
