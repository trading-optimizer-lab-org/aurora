"""Tests for quantforge.marketdata.extended_hours."""
from __future__ import annotations

import pandas as pd
import pytest

from quantforge.marketdata.extended_hours import (
    ExtendedHoursBars,
    ExtendedHoursConfig,
)


@pytest.fixture
def builder() -> ExtendedHoursBars:
    return ExtendedHoursBars(ExtendedHoursConfig(bar_minutes=30))


@pytest.fixture
def trades() -> pd.DataFrame:
    # Build trades across pre-market (10:00 UTC ~ 05:00 ET),
    # regular (15:00 UTC ~ 10:00 ET), after-hours (22:00 UTC ~ 17:00 ET).
    return pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2025-01-15 10:00:00",
            "2025-01-15 10:15:00",
            "2025-01-15 15:00:00",  # regular session - excluded
            "2025-01-15 22:00:00",
            "2025-01-15 22:30:00",
        ], utc=True),
        "symbol": ["X"] * 5,
        "price": [100.0, 100.5, 101.0, 102.0, 102.5],
        "size": [100, 200, 1000, 300, 400],
    })


def test_build_excludes_regular_session(
    builder: ExtendedHoursBars, trades: pd.DataFrame,
):
    bars = builder.build(trades)
    assert (bars["session"] != "regular").all()


def test_build_creates_bars_per_session(
    builder: ExtendedHoursBars, trades: pd.DataFrame,
):
    bars = builder.build(trades)
    sessions = set(bars["session"])
    assert "premarket" in sessions
    assert "afterhours" in sessions


def test_volume_aggregation_correct(
    builder: ExtendedHoursBars, trades: pd.DataFrame,
):
    bars = builder.build(trades)
    pre_vol = bars.loc[bars["session"] == "premarket", "volume"].sum()
    after_vol = bars.loc[bars["session"] == "afterhours", "volume"].sum()
    # Pre-market trades: 100 + 200 = 300; after-hours: 300 + 400 = 700.
    assert pre_vol == 300
    assert after_vol == 700


def test_get_session_volume_returns_three_keys(
    builder: ExtendedHoursBars, trades: pd.DataFrame,
):
    out = builder.get_session_volume(trades)
    assert set(out.keys()) == {"premarket", "afterhours", "regular"}
    assert out["regular"] == 1000


def test_build_handles_empty(builder: ExtendedHoursBars):
    bars = builder.build(pd.DataFrame())
    assert bars.empty
