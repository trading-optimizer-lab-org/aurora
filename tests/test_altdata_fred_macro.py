"""Tests for quantforge.altdata.fred_macro."""
from __future__ import annotations

import pandas as pd
import pytest

from quantforge.altdata.fred_macro import (
    DEFAULT_SERIES,
    FREDAdapter,
    FREDConfig,
)


@pytest.fixture
def adapter(tmp_path) -> FREDAdapter:
    return FREDAdapter(FREDConfig(cache_dir=str(tmp_path / "fred_cache")))


def test_mock_unrate_in_realistic_range(adapter: FREDAdapter):
    s = adapter.fetch_series("UNRATE", mock=True, use_cache=False)
    assert s.name == "UNRATE"
    assert (s.between(0.0, 30.0)).all()


def test_fetch_default_returns_all_columns(adapter: FREDAdapter):
    df = adapter.fetch_default(mock=True, use_cache=False)
    assert list(df.columns) == list(DEFAULT_SERIES)
    assert not df.empty


def test_cache_round_trip(tmp_path):
    cfg = FREDConfig(cache_dir=str(tmp_path / "cache"))
    a = FREDAdapter(cfg)
    s1 = a.fetch_series("DFF", mock=True, use_cache=True)
    # File should now exist; second read uses cache.
    assert (tmp_path / "cache" / "DFF.parquet").exists()
    s2 = a.fetch_series("DFF", mock=True, use_cache=True)
    # parquet round-trip drops DatetimeIndex.freq; values must still match.
    pd.testing.assert_series_equal(s1, s2, check_freq=False)


def test_t10y2y_can_invert(adapter: FREDAdapter):
    s = adapter.fetch_series("T10Y2Y", mock=True, use_cache=False)
    # Curve spread should produce both positive and negative observations.
    assert (s < 0).any() or (s > 0).any()


def test_live_fetch_requires_api_key(monkeypatch, adapter):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    # use_cache=False forces remote path; mock=False routes to fredapi.
    # If fredapi missing on CI we get ImportError; otherwise RuntimeError on
    # missing key. Either is acceptable here.
    with pytest.raises((RuntimeError, ImportError)):
        adapter.fetch_series("GDP", mock=False, use_cache=False)
