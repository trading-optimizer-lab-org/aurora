"""Tests for quantforge.marketdata.level3_book."""
from __future__ import annotations

import pytest

from quantforge.marketdata.level3_book import (
    Level3OrderBook,
    Level3Order,
    Level3Config,
)


@pytest.fixture
def book() -> Level3OrderBook:
    return Level3OrderBook("AAPL", Level3Config(max_levels=5))


def test_add_and_top_of_book(book: Level3OrderBook):
    book.add(Level3Order(order_id="A1", side="bid", price=100.0, size=100))
    book.add(Level3Order(order_id="A2", side="bid", price=99.5, size=200))
    book.add(Level3Order(order_id="B1", side="ask", price=100.5, size=150))
    bb = book.best_bid()
    ba = book.best_ask()
    assert bb == (100.0, 100)
    assert ba == (100.5, 150)


def test_cancel_removes_order(book: Level3OrderBook):
    book.add(Level3Order(order_id="X", side="bid", price=100.0, size=100))
    book.add(Level3Order(order_id="Y", side="bid", price=100.0, size=200))
    cancelled = book.cancel("X")
    assert cancelled is not None
    assert cancelled.order_id == "X"
    assert book.queue_position("X") is None
    assert book.queue_position("Y") == 0


def test_match_consumes_liquidity_in_priority(book: Level3OrderBook):
    book.add(Level3Order(order_id="A1", side="ask", price=100.0, size=100))
    book.add(Level3Order(order_id="A2", side="ask", price=100.0, size=200))
    book.add(Level3Order(order_id="A3", side="ask", price=101.0, size=500))
    # Buy aggressor for 250 shares should consume A1 fully + 150 from A2.
    fills = book.match(side="bid", size=250)
    assert len(fills) == 2
    assert fills[0]["order_id"] == "A1"
    assert fills[0]["size"] == 100
    assert fills[1]["order_id"] == "A2"
    assert fills[1]["size"] == 150


def test_queue_position_reflects_fifo(book: Level3OrderBook):
    book.add(Level3Order(order_id="A", side="bid", price=100.0, size=10))
    book.add(Level3Order(order_id="B", side="bid", price=100.0, size=20))
    book.add(Level3Order(order_id="C", side="bid", price=100.0, size=30))
    assert book.queue_position("A") == 0
    assert book.queue_position("B") == 1
    assert book.queue_position("C") == 2


def test_snapshot_reports_aggregated_levels(book: Level3OrderBook):
    book.add(Level3Order(order_id="A", side="bid", price=100.0, size=50))
    book.add(Level3Order(order_id="B", side="bid", price=100.0, size=50))
    book.add(Level3Order(order_id="C", side="ask", price=101.0, size=300))
    snap = book.snapshot()
    assert snap["symbol"] == "AAPL"
    assert (100.0, 100) in snap["bids"]
    assert (101.0, 300) in snap["asks"]
    assert snap["n_orders"] == 3


def test_duplicate_order_id_raises(book: Level3OrderBook):
    book.add(Level3Order(order_id="DUP", side="bid", price=100.0, size=10))
    with pytest.raises(ValueError):
        book.add(Level3Order(order_id="DUP", side="bid", price=100.0, size=20))
