"""Tests for aurora.infra.parquet_partitioned.PartitionedParquetStore."""
from __future__ import annotations

import pandas as pd
import pytest

from aurora.infra.parquet_partitioned import (
    ParquetPartitionConfig,
    PartitionedParquetStore,
)


def _frame() -> pd.DataFrame:
    rows = []
    for sym in ("SPY", "QQQ"):
        for year in (2023, 2024):
            for i in range(3):
                rows.append({
                    "timestamp": f"{year}-01-0{i + 1}",
                    "symbol": sym,
                    "year": year,
                    "close": 100.0 + i,
                })
    return pd.DataFrame(rows)


@pytest.fixture
def store(tmp_path) -> PartitionedParquetStore:
    cfg = ParquetPartitionConfig(root=str(tmp_path / "store"))
    return PartitionedParquetStore(cfg)


def test_write_returns_row_count(store):
    df = _frame()
    n = store.write(df)
    assert n == len(df)


def test_read_all_returns_all_rows(store):
    df = _frame()
    store.write(df)
    out = store.read()
    assert len(out) == len(df)
    assert set(out["symbol"].unique()) == {"SPY", "QQQ"}


def test_filter_by_symbol(store):
    store.write(_frame())
    out = store.read(symbol="SPY")
    assert (out["symbol"] == "SPY").all()
    assert len(out) == 6


def test_filter_by_year(store):
    store.write(_frame())
    out = store.read(year=2024)
    assert set(int(y) for y in out["year"].unique()) == {2024}


def test_filter_by_symbol_and_year(store):
    store.write(_frame())
    out = store.read(symbol="QQQ", year=2023)
    assert (out["symbol"] == "QQQ").all()
    assert (out["year"].astype(int) == 2023).all()
    assert len(out) == 3


def test_list_partitions(store):
    store.write(_frame())
    parts = store.list_partitions()
    assert len(parts) == 4  # 2 symbols x 2 years
    keys = {(p.get("year"), p.get("symbol")) for p in parts}
    assert ("2023", "SPY") in keys


def test_empty_write_is_noop(store):
    assert store.write(pd.DataFrame()) == 0


def test_year_derived_from_timestamp_when_missing(tmp_path):
    cfg = ParquetPartitionConfig(root=str(tmp_path / "store2"))
    store = PartitionedParquetStore(cfg)
    df = pd.DataFrame({
        "timestamp": ["2022-06-01", "2023-06-01"],
        "symbol": ["SPY", "SPY"],
        "close": [100.0, 110.0],
    })
    n = store.write(df)
    assert n == 2
    out = store.read()
    assert set(int(y) for y in out["year"].unique()) == {2022, 2023}
