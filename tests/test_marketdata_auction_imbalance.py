"""Tests for quantforge.marketdata.auction_imbalance."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from quantforge.marketdata.auction_imbalance import (
    AuctionImbalanceTracker,
    AuctionConfig,
)


@pytest.fixture
def tracker() -> AuctionImbalanceTracker:
    return AuctionImbalanceTracker(AuctionConfig(n_updates=10))


def test_close_imbalance_feed_columns(tracker: AuctionImbalanceTracker):
    feed = tracker.get_imbalance_feed("AAPL", auction_type="close",
                                      as_of=datetime(2025, 1, 15, tzinfo=timezone.utc))
    assert list(feed.columns) == [
        "timestamp", "symbol", "auction_type", "paired_volume",
        "imbalance_volume", "imbalance_side", "indicative_price",
        "reference_price",
    ]
    assert (feed["auction_type"] == "close").all()
    assert (feed["imbalance_side"].isin(["buy", "sell"])).all()


def test_paired_volume_grows_over_time(tracker: AuctionImbalanceTracker):
    feed = tracker.get_imbalance_feed("AAPL", auction_type="close",
                                      as_of=datetime(2025, 1, 15, tzinfo=timezone.utc))
    feed = feed.sort_values("timestamp")
    assert feed["paired_volume"].iloc[-1] > feed["paired_volume"].iloc[0]


def test_open_auction_starts_earlier_than_close(tracker: AuctionImbalanceTracker):
    open_feed = tracker.get_imbalance_feed("AAPL", "open",
                                           as_of=datetime(2025, 1, 15, tzinfo=timezone.utc))
    close_feed = tracker.get_imbalance_feed("AAPL", "close",
                                            as_of=datetime(2025, 1, 15, tzinfo=timezone.utc))
    assert open_feed["timestamp"].iloc[0] < close_feed["timestamp"].iloc[0]


def test_invalid_auction_type_raises(tracker: AuctionImbalanceTracker):
    with pytest.raises(ValueError):
        tracker.get_imbalance_feed("AAPL", auction_type="midday")


def test_latest_signal_reports_side(tracker: AuctionImbalanceTracker):
    feed = tracker.get_imbalance_feed("AAPL", "close",
                                      as_of=datetime(2025, 1, 15, tzinfo=timezone.utc))
    sig = tracker.latest_signal(feed)
    assert sig["side"] in ("buy", "sell", "none")
    assert sig["imbalance_volume"] >= 0
