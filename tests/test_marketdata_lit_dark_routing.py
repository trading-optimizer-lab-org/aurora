"""Tests for aurora.marketdata.lit_dark_routing."""
from __future__ import annotations

import pandas as pd
import pytest

from aurora.marketdata.lit_dark_routing import (
    LitDarkAnalyzer,
    LitDarkConfig,
)


@pytest.fixture
def analyzer() -> LitDarkAnalyzer:
    return LitDarkAnalyzer()


@pytest.fixture
def trades() -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2025-01-01 10:00:00", "2025-01-01 10:00:01",
            "2025-01-01 10:00:02", "2025-01-01 10:00:03",
        ], utc=True),
        "price": [100.05, 100.0, 100.10, 100.0],
        "size": [100, 200, 50, 300],
        "exchange": ["N", "D", "Q", "FINRA"],
    })


@pytest.fixture
def quotes() -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01 09:59:30"], utc=True),
        "bid": [100.0],
        "ask": [100.05],
    })


def test_compare_returns_per_venue_summary(
    analyzer: LitDarkAnalyzer, trades: pd.DataFrame, quotes: pd.DataFrame,
):
    out = analyzer.compare(trades, quotes)
    assert set(out["venue_type"]) == {"lit", "dark"}
    assert (out["n_trades"] >= 0).all()


def test_compare_volume_split(
    analyzer: LitDarkAnalyzer, trades: pd.DataFrame, quotes: pd.DataFrame,
):
    out = analyzer.compare(trades, quotes)
    lit_vol = out.loc[out["venue_type"] == "lit", "total_volume"].iloc[0]
    dark_vol = out.loc[out["venue_type"] == "dark", "total_volume"].iloc[0]
    assert lit_vol == 150  # N + Q
    assert dark_vol == 500  # D + FINRA


def test_routing_summary_picks_a_winner(
    analyzer: LitDarkAnalyzer, trades: pd.DataFrame, quotes: pd.DataFrame,
):
    summary = analyzer.routing_summary(trades, quotes)
    assert summary["preferred"] in ("lit", "dark", None)
    assert "lit_quality" in summary
    assert "dark_quality" in summary


def test_compare_handles_empty(analyzer: LitDarkAnalyzer):
    out = analyzer.compare(pd.DataFrame())
    assert out.empty


def test_compare_without_quotes_uses_proxy_midpoint(
    analyzer: LitDarkAnalyzer, trades: pd.DataFrame,
):
    out = analyzer.compare(trades)
    assert len(out) == 2  # lit + dark rows present
