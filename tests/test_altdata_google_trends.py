"""Tests for quantforge.altdata.google_trends."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.altdata.google_trends import (
    GoogleTrendsAdapter,
    GoogleTrendsConfig,
)


@pytest.fixture
def adapter() -> GoogleTrendsAdapter:
    return GoogleTrendsAdapter(GoogleTrendsConfig(zscore_window=10))


def test_mock_columns(adapter: GoogleTrendsAdapter):
    df = adapter.get_interest(["TSLA stock", "NVDA stock"], mock=True)
    assert list(df.columns) == ["date", "keyword", "search_volume", "zscore"]
    assert set(df["keyword"]) == {"TSLA stock", "NVDA stock"}


def test_search_volume_in_0_100(adapter: GoogleTrendsAdapter):
    df = adapter.get_interest(["AAPL"], mock=True)
    assert (df["search_volume"].between(0.0, 100.0)).all()


def test_zscore_zero_for_constant_series(adapter: GoogleTrendsAdapter):
    s = pd.Series([50.0] * 60, index=pd.date_range("2025-01-01", periods=60))
    z = adapter.compute_zscore(s)
    # constant series → std=0 → fillna(0) → all zero
    assert (z == 0.0).all()


def test_zscore_signs_track_movement(adapter: GoogleTrendsAdapter):
    rng = np.random.default_rng(0)
    base = np.concatenate([
        50.0 + rng.normal(0, 1.0, 40),
        80.0 + rng.normal(0, 1.0, 20),
    ])
    s = pd.Series(base, index=pd.date_range("2025-01-01", periods=60))
    z = adapter.compute_zscore(s)
    # Right after the regime shift the post-shift values are far above the
    # rolling mean ⇒ z should spike positive within a few bars.
    assert z.iloc[40:45].mean() > 0


def test_empty_keywords_returns_empty(adapter: GoogleTrendsAdapter):
    df = adapter.get_interest([], mock=True)
    assert df.empty
    assert list(df.columns) == ["date", "keyword", "search_volume", "zscore"]
