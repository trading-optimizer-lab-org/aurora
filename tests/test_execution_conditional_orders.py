"""Tests for aurora.execution.conditional_orders."""
from __future__ import annotations

import pytest

from aurora.execution.conditional_orders import (
    BracketOrder,
    ConditionalOrderManager,
    StopLimit,
    TrailingStop,
)


class MockBroker:
    symbol = "NVDA"
    def __init__(self):
        self.orders = []
    def submit_order(self, order):
        self.orders.append(order)
        return {"status": "submitted"}


# ---------------------------------------------------------------------------
# StopLimit
# ---------------------------------------------------------------------------

def test_stop_limit_buy_triggers_when_price_rises_through_stop():
    sl = StopLimit(side="buy", qty=10, stop_price=100, limit_price=101)
    assert sl.on_tick(99) is None
    assert sl.on_tick(99.9) is None
    out = sl.on_tick(100.5)
    assert out is not None
    assert out["limit_price"] == 101


def test_stop_limit_sell_triggers_when_price_falls():
    sl = StopLimit(side="sell", qty=10, stop_price=100, limit_price=99)
    assert sl.on_tick(101) is None
    out = sl.on_tick(99)
    assert out is not None


def test_stop_limit_only_triggers_once():
    sl = StopLimit(side="buy", qty=5, stop_price=10, limit_price=11)
    assert sl.on_tick(11) is not None
    assert sl.on_tick(12) is None


# ---------------------------------------------------------------------------
# TrailingStop
# ---------------------------------------------------------------------------

def test_trailing_stop_invalid():
    with pytest.raises(ValueError):
        TrailingStop(side="x", qty=1, trail_amount=1)
    with pytest.raises(ValueError):
        TrailingStop(side="sell", qty=0, trail_amount=1)
    with pytest.raises(ValueError):
        TrailingStop(side="sell", qty=1, trail_amount=0)


def test_trailing_stop_sell_tracks_high_and_fires_on_pullback():
    ts = TrailingStop(side="sell", qty=10, trail_amount=2.0)
    assert ts.on_tick(100) is None
    assert ts.on_tick(105) is None  # new high, stop = 103
    assert ts.on_tick(104) is None
    out = ts.on_tick(102.99)
    assert out is not None
    assert out["side"] == "sell"


def test_trailing_stop_buy_tracks_low_and_fires_on_rally():
    ts = TrailingStop(side="buy", qty=10, trail_amount=2.0)
    assert ts.on_tick(100) is None
    assert ts.on_tick(95) is None     # new low, stop = 97
    out = ts.on_tick(97.5)
    assert out is not None


def test_trailing_stop_only_triggers_once():
    ts = TrailingStop(side="sell", qty=5, trail_amount=1)
    ts.on_tick(100)
    out = ts.on_tick(98)
    assert out is not None
    assert ts.on_tick(50) is None


# ---------------------------------------------------------------------------
# BracketOrder
# ---------------------------------------------------------------------------

def test_bracket_long_invalid_levels():
    with pytest.raises(ValueError):
        # exiting long: TP must be > SL
        BracketOrder(side="sell", qty=10, take_profit=100, stop_loss=105)


def test_bracket_short_invalid_levels():
    with pytest.raises(ValueError):
        # exiting short: TP must be < SL
        BracketOrder(side="buy", qty=10, take_profit=110, stop_loss=100)


def test_bracket_long_take_profit_hit():
    br = BracketOrder(side="sell", qty=10, take_profit=110, stop_loss=90)
    assert br.on_tick(100) is None
    out = br.on_tick(110)
    assert out is not None
    assert out["leg"] == "tp"
    assert out["cancels"] == "sl"


def test_bracket_long_stop_loss_hit():
    br = BracketOrder(side="sell", qty=10, take_profit=110, stop_loss=90)
    assert br.on_tick(100) is None
    out = br.on_tick(89)
    assert out is not None
    assert out["leg"] == "sl"
    assert out["cancels"] == "tp"


def test_bracket_short_take_profit_hit():
    br = BracketOrder(side="buy", qty=10, take_profit=90, stop_loss=110)
    out = br.on_tick(89)
    assert out is not None
    assert out["leg"] == "tp"


def test_bracket_only_triggers_once():
    br = BracketOrder(side="sell", qty=10, take_profit=110, stop_loss=90)
    br.on_tick(110)
    assert br.on_tick(89) is None
    assert br.on_tick(150) is None


# ---------------------------------------------------------------------------
# ConditionalOrderManager
# ---------------------------------------------------------------------------

def test_manager_register_and_dispatch():
    mgr = ConditionalOrderManager()
    sl_id = mgr.add_stop_limit(side="buy", qty=5, stop_price=100, limit_price=101)
    ts_id = mgr.add_trailing_stop(side="sell", qty=10, trail_amount=2.0)
    br_id = mgr.add_bracket(side="sell", qty=10, take_profit=110, stop_loss=90)

    triggered = mgr.on_tick(99)
    assert triggered == []

    triggered = mgr.on_tick(100.5)  # stop_limit fires
    assert any(t["order_id"] == sl_id for t in triggered)


def test_manager_schedule_replays_path():
    mgr = ConditionalOrderManager()
    mgr.add_bracket(side="sell", qty=10, take_profit=110, stop_loss=90)
    out = mgr.schedule([100, 105, 110])
    assert len(out) == 1
    assert out[0]["leg"] == "tp"


def test_manager_execute_pushes_to_broker():
    mgr = ConditionalOrderManager()
    mgr.add_stop_limit(side="buy", qty=5, stop_price=100, limit_price=101)
    broker = MockBroker()
    res = mgr.execute([99, 100.5], broker)
    assert len(res) == 1
    assert broker.orders[0]["order_type"] == "limit"


def test_manager_get_returns_registered_object():
    mgr = ConditionalOrderManager()
    oid = mgr.add_trailing_stop(side="sell", qty=1, trail_amount=1)
    obj = mgr.get(oid)
    assert isinstance(obj, TrailingStop)
