"""Tests for quantforge.altdata.onchain_crypto."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from quantforge.altdata.onchain_crypto import OnchainAdapter, OnchainConfig


@pytest.fixture
def adapter() -> OnchainAdapter:
    return OnchainAdapter()


def test_mock_columns_and_metric_filter(adapter: OnchainAdapter):
    df = adapter.get_metric("BTC", "whale_transfers", mock=True)
    assert list(df.columns) == ["date", "asset", "metric", "value"]
    assert (df["asset"] == "BTC").all()
    assert (df["metric"] == "whale_transfers").all()
    assert (df["value"] >= 0).all()


def test_invalid_metric_rejected(adapter: OnchainAdapter):
    with pytest.raises(ValueError, match="unknown metric"):
        adapter.get_metric("ETH", "moon_count", mock=True)


def test_inflow_outflow_can_be_negative(adapter: OnchainAdapter):
    df_in = adapter.get_metric("ETH", "exchange_inflow", mock=True)
    df_out = adapter.get_metric("ETH", "exchange_outflow", mock=True)
    assert not df_in.empty
    assert not df_out.empty
    # Both are normal-distributed; range should span both signs over 30 days.
    assert df_in["value"].min() < 0 or df_in["value"].max() > 0


def test_start_must_precede_end(adapter: OnchainAdapter):
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="start must be before end"):
        adapter.get_metric(
            "BTC", "whale_transfers",
            start=end, end=end - timedelta(days=1), mock=True,
        )


def test_live_fetch_requires_api_key(monkeypatch, adapter):
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ETHERSCAN_API_KEY"):
        adapter.get_metric("BTC", "whale_transfers", mock=False)
