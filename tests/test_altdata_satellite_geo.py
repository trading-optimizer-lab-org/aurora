"""Tests for quantforge.altdata.satellite_geo."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quantforge.altdata.satellite_geo import (
    AOI,
    SatelliteAdapter,
    SatelliteConfig,
)


@pytest.fixture
def adapter() -> SatelliteAdapter:
    return SatelliteAdapter()


@pytest.fixture
def aois() -> list[AOI]:
    return [
        AOI(aoi_id="walmart_001", aoi_type="parking_lot",
            lat=37.0, lon=-122.0, capacity=500.0),
        AOI(aoi_id="cushing_t1", aoi_type="oil_tank",
            lat=35.9, lon=-96.7, capacity=350_000.0),
    ]


def test_invalid_aoi_type_rejected():
    with pytest.raises(ValueError, match="unknown aoi_type"):
        AOI(aoi_id="x", aoi_type="airport", lat=0.0, lon=0.0)


def test_mock_columns_and_value_bounds(adapter: SatelliteAdapter, aois):
    df = adapter.get_metrics(aois, mock=True)
    assert list(df.columns) == [
        "date", "aoi_id", "aoi_type", "metric", "value",
    ]
    # Value must respect each AOI's capacity ceiling.
    for aoi in aois:
        sub = df[df["aoi_id"] == aoi.aoi_id]
        assert (sub["value"] <= aoi.capacity).all()
        assert (sub["value"] >= 0).all()


def test_metric_label_per_aoi_type(adapter: SatelliteAdapter, aois):
    df = adapter.get_metrics(aois, mock=True)
    assert df.loc[df["aoi_type"] == "parking_lot",
                  "metric"].iloc[0] == "fill_pct_count"
    assert df.loc[df["aoi_type"] == "oil_tank",
                  "metric"].iloc[0] == "barrels"


def test_empty_aois_returns_empty(adapter: SatelliteAdapter):
    df = adapter.get_metrics([], mock=True)
    assert df.empty
    assert list(df.columns) == [
        "date", "aoi_id", "aoi_type", "metric", "value",
    ]


def test_start_must_precede_end(adapter: SatelliteAdapter, aois):
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="start must be before end"):
        adapter.get_metrics(
            aois, start=end, end=end - timedelta(days=1), mock=True,
        )
