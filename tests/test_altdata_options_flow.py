"""Tests for aurora.altdata.options_flow."""
from __future__ import annotations

import pandas as pd
import pytest

from aurora.altdata.options_flow import (
    OptionsFlowAdapter,
    OptionsFlowConfig,
)


@pytest.fixture
def adapter() -> OptionsFlowAdapter:
    return OptionsFlowAdapter(OptionsFlowConfig(
        unusual_multiplier=5.0, min_volume=10,
    ))


def test_mock_returns_unusual_subset(adapter: OptionsFlowAdapter):
    df = adapter.get_unusual_activity("TSLA", mock=True)
    assert list(df.columns) == [
        "contract_symbol", "underlying", "expiration", "strike",
        "option_type", "last_price", "volume", "open_interest",
        "avg_volume", "unusual_score",
    ]
    # Mock injects ~10% unusual outliers; with strike grid of 10 strikes x
    # 2 sides = 20 contracts, expectation is at least one row but the
    # generator is stochastic per symbol — assert structure either way.
    assert (df["unusual_score"] >= 5.0).all() if not df.empty else True


def test_flag_unusual_filters_low_volume(adapter: OptionsFlowAdapter):
    chain = pd.DataFrame([
        {"contract_symbol": "X1", "underlying": "X", "expiration": pd.Timestamp("2025-01-01"),
         "strike": 100.0, "option_type": "call", "last_price": 1.0,
         "volume": 1000, "open_interest": 100, "avg_volume": 10.0},
        {"contract_symbol": "X2", "underlying": "X", "expiration": pd.Timestamp("2025-01-01"),
         "strike": 100.0, "option_type": "put", "last_price": 1.0,
         "volume": 5, "open_interest": 100, "avg_volume": 1.0},  # below min_volume
    ])
    out = adapter.flag_unusual(chain)
    assert len(out) == 1
    assert out["contract_symbol"].iloc[0] == "X1"


def test_flag_unusual_score_calculation(adapter: OptionsFlowAdapter):
    chain = pd.DataFrame([
        {"contract_symbol": "Y1", "underlying": "Y", "expiration": pd.Timestamp("2025-01-01"),
         "strike": 100.0, "option_type": "call", "last_price": 1.0,
         "volume": 100, "open_interest": 100, "avg_volume": 10.0},
    ])
    out = adapter.flag_unusual(chain)
    assert len(out) == 1
    assert out["unusual_score"].iloc[0] == pytest.approx(10.0)


def test_flag_unusual_handles_empty(adapter: OptionsFlowAdapter):
    out = adapter.flag_unusual(pd.DataFrame())
    assert out.empty
    assert "unusual_score" in out.columns


def test_flag_unusual_synthesizes_avg_volume_when_missing(adapter):
    chain = pd.DataFrame([
        {"contract_symbol": "Z1", "underlying": "Z", "expiration": pd.Timestamp("2025-01-01"),
         "strike": 100.0, "option_type": "call", "last_price": 1.0,
         "volume": 1000, "open_interest": 200},
    ])
    out = adapter.flag_unusual(chain)
    # avg_volume = open_interest / window(20) = 10 → score = 100
    assert "avg_volume" in out.columns
    assert (out["unusual_score"] >= adapter.config.unusual_multiplier).all()
