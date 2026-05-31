"""Tests for aurora.marketdata.taq_reconstruction."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aurora.marketdata.taq_reconstruction import (
    TAQReconstructor,
    TAQConfig,
)


@pytest.fixture
def taq() -> TAQReconstructor:
    return TAQReconstructor(TAQConfig(n_ticks=200, base_price=100.0))


def test_reconstruct_returns_trades_and_quotes(taq: TAQReconstructor):
    out = taq.reconstruct("AAPL", as_of=datetime(2025, 1, 15, tzinfo=timezone.utc))
    assert set(out.keys()) == {"trades", "quotes"}
    assert len(out["trades"]) == 200
    assert len(out["quotes"]) == 200


def test_trades_have_expected_columns(taq: TAQReconstructor):
    trades = taq.reconstruct("AAPL", mock=True)["trades"]
    assert list(trades.columns) == [
        "timestamp", "symbol", "price", "size", "exchange", "sale_condition",
    ]
    assert (trades["size"] > 0).all()
    assert (trades["price"] > 0).all()


def test_quotes_have_bid_ask_with_spread(taq: TAQReconstructor):
    quotes = taq.reconstruct("AAPL", mock=True)["quotes"]
    assert (quotes["ask"] > quotes["bid"]).all()
    assert list(quotes.columns) == [
        "timestamp", "symbol", "bid", "ask",
        "bid_size", "ask_size", "exchange",
    ]


def test_deterministic_for_same_inputs():
    taq1 = TAQReconstructor(TAQConfig(n_ticks=50))
    taq2 = TAQReconstructor(TAQConfig(n_ticks=50))
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
    out1 = taq1.reconstruct("MSFT", as_of=as_of)["trades"]
    out2 = taq2.reconstruct("MSFT", as_of=as_of)["trades"]
    assert (out1["price"].values == out2["price"].values).all()


def test_live_mode_raises():
    taq = TAQReconstructor()
    with pytest.raises(NotImplementedError):
        taq.reconstruct("AAPL", mock=False)
