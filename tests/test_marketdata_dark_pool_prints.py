"""Tests for quantforge.marketdata.dark_pool_prints."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from quantforge.marketdata.dark_pool_prints import (
    DarkPoolDetector,
    DarkPoolConfig,
)


@pytest.fixture
def detector() -> DarkPoolDetector:
    return DarkPoolDetector(DarkPoolConfig(n_ticks=100, dark_fraction=0.4))


def test_detect_marks_dark_codes(detector: DarkPoolDetector):
    trades = pd.DataFrame({
        "timestamp": pd.to_datetime(["2025-01-01"] * 4, utc=True),
        "symbol": ["X"] * 4,
        "price": [100.0] * 4,
        "size": [100, 200, 300, 400],
        "exchange": ["N", "D", "FINRA", "Q"],
    })
    out = detector.detect(trades)
    assert out.iloc[0]["is_dark"] is False or out.iloc[0]["is_dark"] == False  # noqa: E712
    assert out.iloc[1]["is_dark"]
    assert out.iloc[2]["is_dark"]
    assert out.iloc[3]["is_dark"] is False or out.iloc[3]["is_dark"] == False  # noqa: E712


def test_dark_prints_subset_only(detector: DarkPoolDetector):
    df = detector.get_dark_prints("AAPL", as_of=datetime(2025, 1, 15, tzinfo=timezone.utc))
    assert df["is_dark"].all()
    assert (df["dark_pool_id"] != "").all()


def test_dark_volume_share_within_bounds(detector: DarkPoolDetector):
    df = detector.get_dark_prints("MSFT", as_of=datetime(2025, 1, 15, tzinfo=timezone.utc))
    # Pull a fresh full panel and compute share
    trades = detector._mock_trades("MSFT", datetime(2025, 1, 15, tzinfo=timezone.utc))
    share = detector.dark_volume_share(trades)
    assert 0.0 <= share <= 1.0


def test_detect_handles_empty(detector: DarkPoolDetector):
    out = detector.detect(pd.DataFrame())
    assert out.empty
    assert "is_dark" in out.columns
