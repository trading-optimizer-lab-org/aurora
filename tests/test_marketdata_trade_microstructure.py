"""Tests for quantforge.marketdata.trade_microstructure."""
from __future__ import annotations

import pandas as pd
import pytest

from aurora.marketdata.trade_microstructure import (
    TradeMicrostructureAnalyzer,
    MicrostructureConfig,
)


@pytest.fixture
def analyzer() -> TradeMicrostructureAnalyzer:
    return TradeMicrostructureAnalyzer()


def test_analyze_signs_buy_above_midpoint(analyzer: TradeMicrostructureAnalyzer):
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01 10:00", "2025-01-01 10:01"], utc=True),
        "price": [100.10, 99.90],
        "size": [100, 200],
        "exchange": ["N", "N"],
    })
    quotes = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01 09:59"], utc=True),
        "bid": [100.0],
        "ask": [100.0],
    })
    out = analyzer.analyze(trades, quotes)
    assert out.iloc[0]["aggressor_side"] == "buy"
    assert out.iloc[1]["aggressor_side"] == "sell"


def test_signed_dollar_uses_signed_size(analyzer: TradeMicrostructureAnalyzer):
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01 10:00"], utc=True),
        "price": [101.0],
        "size": [100],
        "exchange": ["N"],
    })
    quotes = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01 09:59"], utc=True),
        "bid": [100.0],
        "ask": [100.0],
    })
    out = analyzer.analyze(trades, quotes)
    # Buy aggressor: signed_dollar = +100 * 101 = 10100.
    assert out["signed_dollar"].iloc[0] == pytest.approx(101.0 * 100)


def test_venue_type_tags_dark_codes():
    analyzer = TradeMicrostructureAnalyzer(MicrostructureConfig(
        dark_venue_codes=("D", "FINRA"),
    ))
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01 10:00", "2025-01-01 10:01"], utc=True),
        "price": [100.0, 100.0],
        "size": [100, 100],
        "exchange": ["D", "N"],
    })
    out = analyzer.analyze(trades)
    assert out.iloc[0]["venue_type"] == "dark"
    assert out.iloc[1]["venue_type"] == "lit"


def test_aggregate_returns_buy_sell_totals(analyzer: TradeMicrostructureAnalyzer):
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(
            ["2025-01-01 10:00", "2025-01-01 10:01", "2025-01-01 10:02"], utc=True,
        ),
        "price": [101.0, 99.0, 102.0],
        "size": [100, 200, 50],
        "exchange": ["N", "N", "D"],
    })
    quotes = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01 09:59"], utc=True),
        "bid": [100.0],
        "ask": [100.0],
    })
    signed = analyzer.analyze(trades, quotes)
    agg = analyzer.aggregate(signed)
    assert agg["buy_volume"] == 150  # 100 + 50
    assert agg["sell_volume"] == 200
    assert agg["dark_pct"] > 0


def test_analyze_handles_empty(analyzer: TradeMicrostructureAnalyzer):
    out = analyzer.analyze(pd.DataFrame())
    assert out.empty
    assert "aggressor_side" in out.columns
