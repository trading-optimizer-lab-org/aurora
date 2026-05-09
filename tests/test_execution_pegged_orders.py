"""Tests for quantforge.execution.pegged_orders."""
from __future__ import annotations

import pytest

from aurora.execution.pegged_orders import (
    PeggedConfig,
    PeggedOrderTypes,
    PeggedQuote,
)


class MockBroker:
    symbol = "GOOG"
    def __init__(self):
        self.orders = []
        self.canceled = []
        self._next = 1
    def submit_order(self, order):
        oid = f"o{self._next}"
        self._next += 1
        self.orders.append({**order, "order_id": oid})
        return {"status": "submitted", "order_id": oid}
    def cancel_order(self, oid):
        self.canceled.append(oid)


def test_pegged_invalid_config():
    with pytest.raises(ValueError):
        PeggedConfig(peg_type="bogus")
    with pytest.raises(ValueError):
        PeggedConfig(side="x")


def test_pegged_mid_price():
    p = PeggedOrderTypes(PeggedConfig(peg_type="mid", side="buy"))
    q = PeggedQuote(bid=99.0, ask=101.0)
    assert p.reference_price(q) == pytest.approx(100.0)
    assert p.limit_price(q) == pytest.approx(100.0)


def test_pegged_primary_side_aware():
    buy = PeggedOrderTypes(PeggedConfig(peg_type="primary", side="buy"))
    sell = PeggedOrderTypes(PeggedConfig(peg_type="primary", side="sell"))
    q = PeggedQuote(bid=99.0, ask=101.0)
    assert buy.reference_price(q) == pytest.approx(99.0)
    assert sell.reference_price(q) == pytest.approx(101.0)


def test_pegged_market_peg_uses_opposite_side():
    buy = PeggedOrderTypes(PeggedConfig(peg_type="market", side="buy"))
    q = PeggedQuote(bid=99.0, ask=101.0)
    assert buy.reference_price(q) == pytest.approx(101.0)


def test_pegged_offset_buy_more_aggressive():
    p = PeggedOrderTypes(PeggedConfig(peg_type="mid", side="buy",
                                       offset=0.5))
    q = PeggedQuote(bid=99.0, ask=101.0)
    assert p.limit_price(q) == pytest.approx(100.5)


def test_pegged_offset_sell_more_aggressive():
    p = PeggedOrderTypes(PeggedConfig(peg_type="mid", side="sell",
                                       offset=0.5))
    q = PeggedQuote(bid=99.0, ask=101.0)
    # sell aggressive = lower price
    assert p.limit_price(q) == pytest.approx(99.5)


def test_pegged_cap_for_buy():
    p = PeggedOrderTypes(PeggedConfig(peg_type="mid", side="buy",
                                       offset=10.0, cap_price=100.5))
    q = PeggedQuote(bid=99, ask=101)
    assert p.limit_price(q) == pytest.approx(100.5)


def test_pegged_floor_for_sell():
    p = PeggedOrderTypes(PeggedConfig(peg_type="mid", side="sell",
                                       offset=10.0, floor_price=99.5))
    q = PeggedQuote(bid=99, ask=101)
    assert p.limit_price(q) == pytest.approx(99.5)


def test_pegged_crossed_book_rejected():
    p = PeggedOrderTypes()
    with pytest.raises(ValueError):
        p.reference_price(PeggedQuote(bid=101, ask=99))


def test_pegged_schedule_marks_reprice_events():
    p = PeggedOrderTypes(PeggedConfig(peg_type="mid"))
    quotes = [
        PeggedQuote(bid=99, ask=101),
        PeggedQuote(bid=99, ask=101),  # no reprice
        PeggedQuote(bid=100, ask=102),  # reprice
    ]
    out = p.schedule(quotes)
    assert out[0]["reprice"]
    assert not out[1]["reprice"]
    assert out[2]["reprice"]


def test_pegged_execute_cancels_and_resubmits():
    p = PeggedOrderTypes()
    broker = MockBroker()
    quotes = [
        PeggedQuote(bid=99, ask=101),
        PeggedQuote(bid=100, ask=102),  # reprice triggers cancel + resubmit
    ]
    res = p.execute(quotes, qty=10, broker=broker)
    assert len(res) == 2
    assert len(broker.canceled) == 1


def test_pegged_invalid_qty():
    p = PeggedOrderTypes()
    with pytest.raises(ValueError):
        p.execute([PeggedQuote(99, 101)], qty=0, broker=MockBroker())
