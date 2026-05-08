"""Tests for quantforge.infra.timescaledb.TimescaleAdapter (mock mode)."""
from __future__ import annotations

import pandas as pd
import pytest

from quantforge.infra.timescaledb import TimescaleAdapter, TimescaleConfig


@pytest.fixture
def adapter() -> TimescaleAdapter:
    return TimescaleAdapter(TimescaleConfig(), mock=True)


def _ticks(symbol: str = "SPY", n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01 09:30", periods=n, freq="10s", tz="UTC")
    return pd.DataFrame({
        "timestamp": idx,
        "symbol": symbol,
        "price": [100.0 + i * 0.1 for i in range(n)],
        "size": [10.0] * n,
    })


def _bars(symbol: str = "SPY", n: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": idx,
        "symbol": symbol,
        "open": [100.0] * n,
        "high": [101.0] * n,
        "low": [99.0] * n,
        "close": [100.5] * n,
        "volume": [1000.0] * n,
    })


def test_ingest_and_query_ticks(adapter):
    n = adapter.ingest_ticks(_ticks("SPY", 5))
    assert n == 5
    out = adapter.query_ticks("SPY")
    assert len(out) == 5
    assert (out["symbol"] == "SPY").all()


def test_ingest_and_query_bars(adapter):
    n = adapter.ingest_bars(_bars("SPY", 3))
    assert n == 3
    out = adapter.query_bars("SPY")
    assert len(out) == 3
    assert "open" in out.columns


def test_query_filters_by_symbol(adapter):
    adapter.ingest_ticks(_ticks("SPY", 3))
    adapter.ingest_ticks(_ticks("QQQ", 4))
    assert len(adapter.query_ticks("QQQ")) == 4
    assert len(adapter.query_ticks("SPY")) == 3


def test_aggregate_to_bars(adapter):
    adapter.ingest_ticks(_ticks("SPY", 60))
    bars = adapter.aggregate_to_bars("SPY", freq="1min")
    assert not bars.empty
    assert {"open", "high", "low", "close", "volume"}.issubset(bars.columns)


def test_missing_columns_raise(adapter):
    bad = pd.DataFrame({"timestamp": ["2024-01-01"], "symbol": ["SPY"]})
    with pytest.raises(ValueError):
        adapter.ingest_ticks(bad)
    with pytest.raises(ValueError):
        adapter.ingest_bars(bad)


def test_empty_df_returns_zero(adapter):
    assert adapter.ingest_ticks(pd.DataFrame()) == 0
    assert adapter.ingest_bars(pd.DataFrame()) == 0
