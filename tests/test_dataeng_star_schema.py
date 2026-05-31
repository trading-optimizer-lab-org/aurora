"""Tests for aurora.dataeng.star_schema."""
from __future__ import annotations

import pytest

from aurora.dataeng.star_schema import (
    StarSchemaConfig,
    StarSchemaWarehouse,
)


@pytest.fixture
def wh() -> StarSchemaWarehouse:
    return StarSchemaWarehouse(StarSchemaConfig())


def test_load_trades_grows_facts(wh: StarSchemaWarehouse):
    n = wh.load_trades([
        {"trade_id": "t1", "symbol": "AAPL", "date": "2025-01-02",
         "qty": 10.0, "price": 150.0, "side": "buy"},
        {"trade_id": "t2", "symbol": "AAPL", "date": "2025-01-03",
         "qty": 5.0, "price": 152.0, "side": "sell"},
    ])
    assert n == 2
    assert wh.schema_summary()["fact_trades"] == 2


def test_dim_symbol_dedupe(wh: StarSchemaWarehouse):
    wh.load_trades([
        {"symbol": "AAPL", "date": "2025-01-01", "qty": 1.0, "price": 1.0},
        {"symbol": "AAPL", "date": "2025-01-02", "qty": 1.0, "price": 1.0},
        {"symbol": "MSFT", "date": "2025-01-01", "qty": 1.0, "price": 1.0},
    ])
    assert wh.schema_summary()["dim_symbol"] == 2


def test_trades_by_symbol_aggregation(wh: StarSchemaWarehouse):
    wh.load_trades([
        {"trade_id": "t1", "symbol": "AAPL", "date": "2025-01-02",
         "qty": 10.0, "price": 150.0},
        {"trade_id": "t2", "symbol": "AAPL", "date": "2025-01-03",
         "qty": 20.0, "price": 152.0},
        {"trade_id": "t3", "symbol": "MSFT", "date": "2025-01-02",
         "qty": 5.0, "price": 300.0},
    ])
    df = wh.trades_by_symbol()
    aapl = df.loc[df["symbol"] == "AAPL"].iloc[0]
    assert aapl["n_trades"] == 2
    assert aapl["qty_total"] == 30.0


def test_market_load_and_query(wh: StarSchemaWarehouse):
    wh.load_market([
        {"symbol": "AAPL", "date": "2025-01-02", "open": 150.0,
         "high": 152.0, "low": 149.0, "close": 151.0, "volume": 1000},
        {"symbol": "AAPL", "date": "2025-01-03", "open": 151.0,
         "high": 153.0, "low": 150.0, "close": 152.0, "volume": 900},
    ])
    df = wh.daily_close()
    assert len(df) == 2
    assert list(df["symbol"].unique()) == ["AAPL"]


def test_empty_returns_empty_query(wh: StarSchemaWarehouse):
    assert wh.trades_by_symbol().empty
    assert wh.daily_close().empty


def test_schema_summary_zero_initial(wh: StarSchemaWarehouse):
    s = wh.schema_summary()
    assert s == {"dim_symbol": 0, "dim_date": 0,
                 "fact_trades": 0, "fact_market": 0}
