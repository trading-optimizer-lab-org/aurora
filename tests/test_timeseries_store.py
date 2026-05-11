"""Tests for :mod:`aurora.data_contracts.timeseries_store`.

Covers the Phase-1 versioned parquet+sqlite store: round-trip fidelity,
date-range read, replace semantics, namespace isolation, and the
``default_store`` singleton.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from aurora.data_contracts import (
    TimeSeriesRecord,
    TimeSeriesStore,
    default_store,
)
from aurora.data_contracts.timeseries_store import _reset_default_store_for_tests


def _utc_index(rows: int = 5) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [pd.Timestamp(datetime(2024, 1, d, tzinfo=timezone.utc)) for d in range(1, rows + 1)],
        name="timestamp",
    )


def _sample_df(rows: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
        },
        index=_utc_index(rows),
    )


# --------------------------------------------------------------------------
# 1. round-trip preserves index / columns / metadata / content hash
# --------------------------------------------------------------------------


def test_roundtrip_preserves_payload(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df = _sample_df()
    rec = store.put("raw", "AAPL", df, metadata={"source": "test"})
    assert isinstance(rec, TimeSeriesRecord)
    assert rec.library == "raw"
    assert rec.symbol == "AAPL"
    assert rec.columns == ("open", "close")
    assert dict(rec.metadata) == {"source": "test"}
    assert rec.content_hash and len(rec.content_hash) == 64
    assert rec.n_rows == 5

    out = store.read("raw", "AAPL")
    pd.testing.assert_frame_equal(out, df)


# --------------------------------------------------------------------------
# 2. date-range read returns only the requested range (inclusive)
# --------------------------------------------------------------------------


def test_date_range_read_inclusive(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df = _sample_df(rows=10)
    store.put("raw", "AAPL", df)

    sub = store.read(
        "raw",
        "AAPL",
        start=pd.Timestamp(datetime(2024, 1, 3, tzinfo=timezone.utc)),
        end=pd.Timestamp(datetime(2024, 1, 7, tzinfo=timezone.utc)),
    )
    assert list(sub.index) == [
        pd.Timestamp(datetime(2024, 1, d, tzinfo=timezone.utc)) for d in (3, 4, 5, 6, 7)
    ]
    # sanity: same columns and same per-row payload as the originating df
    pd.testing.assert_frame_equal(sub, df.loc[sub.index])


# --------------------------------------------------------------------------
# 3. replacing a series changes the content hash but keeps the version key
# --------------------------------------------------------------------------


def test_replace_changes_content_hash(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df_v1 = _sample_df()
    rec1 = store.put("raw", "AAPL", df_v1, version="v1")

    df_v2 = df_v1.copy()
    df_v2.loc[df_v2.index[0], "close"] = 999.0
    rec2 = store.put("raw", "AAPL", df_v2, version="v1", replace=True)

    assert rec1.version == rec2.version == "v1"
    assert rec1.content_hash != rec2.content_hash

    out = store.read("raw", "AAPL", version="v1")
    assert out.loc[out.index[0], "close"] == 999.0


# --------------------------------------------------------------------------
# 4. list_versions returns sorted ISO order
# --------------------------------------------------------------------------


def test_list_versions_sorted(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df = _sample_df()
    # Deliberately insert out of order.
    store.put("raw", "AAPL", df, version="2024-01-03T00:00:00.000Z")
    store.put("raw", "AAPL", df, version="2024-01-01T00:00:00.000Z")
    store.put("raw", "AAPL", df, version="2024-01-02T00:00:00.000Z")
    versions = store.list_versions("raw", "AAPL")
    assert versions == (
        "2024-01-01T00:00:00.000Z",
        "2024-01-02T00:00:00.000Z",
        "2024-01-03T00:00:00.000Z",
    )


# --------------------------------------------------------------------------
# 5. append (default replace=False) on an existing version raises
# --------------------------------------------------------------------------


def test_append_existing_version_raises(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df = _sample_df()
    store.put("raw", "AAPL", df, version="v1")
    with pytest.raises(ValueError, match="already exists"):
        store.put("raw", "AAPL", df, version="v1")


# --------------------------------------------------------------------------
# 6. read latest when version is omitted
# --------------------------------------------------------------------------


def test_read_latest_default(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df_a = _sample_df()
    df_b = df_a.copy()
    df_b.loc[df_b.index[0], "close"] = 555.0
    store.put("raw", "AAPL", df_a, version="2024-01-01T00:00:00.000Z")
    store.put("raw", "AAPL", df_b, version="2024-02-01T00:00:00.000Z")

    out = store.read("raw", "AAPL")  # latest by lexicographic order
    assert out.loc[out.index[0], "close"] == 555.0


# --------------------------------------------------------------------------
# 7. library namespace isolation
# --------------------------------------------------------------------------


def test_library_namespace_isolation(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df_raw = _sample_df()
    df_adj = df_raw.copy()
    df_adj["close"] = df_adj["close"] * 0.5  # simulate adjusted prices
    store.put("raw", "AAPL", df_raw, version="v1")
    store.put("adjusted", "AAPL", df_adj, version="v1")

    raw_out = store.read("raw", "AAPL", version="v1")
    adj_out = store.read("adjusted", "AAPL", version="v1")
    pd.testing.assert_frame_equal(raw_out, df_raw)
    pd.testing.assert_frame_equal(adj_out, df_adj)
    assert not raw_out.equals(adj_out)


# --------------------------------------------------------------------------
# 8. default_store round-trip is deterministic across instantiations
# --------------------------------------------------------------------------


def test_default_store_roundtrip(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    _reset_default_store_for_tests()
    store_a = default_store()
    df = _sample_df()
    rec = store_a.put("raw", "MSFT", df, version="v1")

    # New singleton lookup must hit the same on-disk store.
    store_b = default_store()
    assert store_a is store_b
    out = store_b.read("raw", "MSFT", version="v1")
    pd.testing.assert_frame_equal(out, df)
    assert rec.content_hash == store_b.list_records("raw", "MSFT")[0].content_hash
    _reset_default_store_for_tests()


# --------------------------------------------------------------------------
# 9. soft delete (tombstone) prevents reads but keeps the row for audit
# --------------------------------------------------------------------------


def test_delete_tombstones_version(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df = _sample_df()
    store.put("raw", "AAPL", df, version="v1")
    rec = store.delete("raw", "AAPL", "v1")
    assert rec.is_tombstone
    assert "v1" not in store.list_versions("raw", "AAPL")
    with pytest.raises(KeyError, match="tombstoned|no readable"):
        store.read("raw", "AAPL", version="v1")
    # the row still exists in the audit listing
    records = store.list_records("raw", "AAPL")
    assert len(records) == 1
    assert records[0].version == "v1"
    assert records[0].is_tombstone


# --------------------------------------------------------------------------
# 10. invalid inputs are rejected loudly
# --------------------------------------------------------------------------


def test_put_rejects_empty_library_or_symbol(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    df = _sample_df()
    with pytest.raises(ValueError):
        store.put("", "AAPL", df)
    with pytest.raises(ValueError):
        store.put("raw", "", df)


def test_put_requires_dataframe(tmp_path) -> None:
    store = TimeSeriesStore(root_dir=tmp_path)
    with pytest.raises(TypeError):
        store.put("raw", "AAPL", [1, 2, 3])  # type: ignore[arg-type]
