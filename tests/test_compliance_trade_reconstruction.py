"""Tests for aurora.compliance.trade_reconstruction."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aurora.compliance.trade_reconstruction import (
    ReconstructionConfig,
    TradeReconstructor,
)


@pytest.fixture
def reconstructor() -> TradeReconstructor:
    return TradeReconstructor(ReconstructionConfig(
        max_age_days=5, price_tolerance_bps=50.0,
    ))


@pytest.fixture
def trades() -> list[dict]:
    base = datetime(2025, 4, 1, 14, 30, tzinfo=timezone.utc)
    return [
        {"trade_id": "T-1", "timestamp": base, "symbol": "AAPL",
         "side": "BUY", "quantity": 100, "price": 175.50},
        {"trade_id": "T-2", "timestamp": base, "symbol": "MSFT",
         "side": "SELL", "quantity": 50, "price": 410.00},
    ]


@pytest.fixture
def market() -> dict:
    return {
        "AAPL": {"mid": 175.40, "bid": 175.30, "ask": 175.50},
        "MSFT": {"mid": 415.00, "bid": 414.90, "ask": 415.10},
    }


def test_reconstruct_returns_record_per_trade(reconstructor, trades, market):
    as_of = datetime(2025, 4, 2, tzinfo=timezone.utc)
    rec = reconstructor.reconstruct(trades, market, as_of=as_of)
    assert rec["n_trades"] == 2
    assert len(rec["trades"]) == 2


def test_fingerprint_is_deterministic(reconstructor, trades, market):
    as_of = datetime(2025, 4, 2, tzinfo=timezone.utc)
    a = reconstructor.reconstruct(trades, market, as_of=as_of)
    b = reconstructor.reconstruct(trades, market, as_of=as_of)
    assert a["fingerprint"] == b["fingerprint"]


def test_fingerprint_changes_with_input(reconstructor, trades, market):
    as_of = datetime(2025, 4, 2, tzinfo=timezone.utc)
    a = reconstructor.reconstruct(trades, market, as_of=as_of)
    altered = trades + [{"trade_id": "T-3", "timestamp": as_of, "symbol": "AAPL",
                         "side": "BUY", "quantity": 1, "price": 1.0}]
    b = reconstructor.reconstruct(altered, market, as_of=as_of)
    assert a["fingerprint"] != b["fingerprint"]


def test_outside_tolerance_flagged(reconstructor, trades, market):
    as_of = datetime(2025, 4, 2, tzinfo=timezone.utc)
    rec = reconstructor.reconstruct(trades, market, as_of=as_of)
    msft_row = next(t for t in rec["trades"] if t["symbol"] == "MSFT")
    # 415 vs 410 -> ~120bps deviation > 50bps threshold
    assert msft_row["flag_outside_tolerance"] is True
    assert msft_row["trade_id"] in rec["flagged_trade_ids"]


def test_within_tolerance_not_flagged(reconstructor, trades, market):
    as_of = datetime(2025, 4, 2, tzinfo=timezone.utc)
    rec = reconstructor.reconstruct(trades, market, as_of=as_of)
    aapl_row = next(t for t in rec["trades"] if t["symbol"] == "AAPL")
    assert aapl_row["flag_outside_tolerance"] is False


def test_old_trades_flagged_outside_window(reconstructor):
    base = datetime(2025, 4, 10, tzinfo=timezone.utc)
    old = base - timedelta(days=10)
    trades = [{"trade_id": "OLD", "timestamp": old, "symbol": "AAPL",
               "side": "BUY", "quantity": 1, "price": 100.0}]
    rec = reconstructor.reconstruct(trades, {}, as_of=base)
    assert rec["trades"][0]["flag_outside_window"] is True
