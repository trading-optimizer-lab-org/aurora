"""Tests for R169 -- execution replay engine."""
from __future__ import annotations

import pytest

from aurora.execution.events import EventType, ExecutionEvent, OrderState
from aurora.execution.replay import ExecutionReplayState, replay_execution_events


def _ev(
    event_id: str,
    order_id: str,
    event_type: EventType,
    *,
    payload: dict | None = None,
    timestamp: str = "2026-05-10T00:00:00+00:00",
    symbol: str = "SPY",
) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=event_id,
        event_type=event_type,
        order_id=order_id,
        timestamp=timestamp,
        payload=payload or {},
        broker="paper",
        symbol=symbol,
    )


def test_empty_events_returns_zero_state():
    state = replay_execution_events([], starting_cash=0.0)
    assert isinstance(state, ExecutionReplayState)
    assert state.cash == 0.0
    assert state.realised_pnl == 0.0
    assert state.commissions == 0.0
    assert state.positions == {}
    assert state.open_orders == 0
    assert state.warnings == ()


def test_starting_cash_propagates_when_no_events():
    state = replay_execution_events([], starting_cash=100_000.0)
    assert state.cash == 100_000.0


def test_one_buy_fill_updates_position_and_cash():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED,
            payload={"requested_qty": 10, "side": "buy"}),
        _ev("e2", "o1", EventType.FILL,
            payload={"qty": 10, "price": 100, "side": "buy"}),
    ]
    state = replay_execution_events(events, starting_cash=10_000.0)
    assert state.positions == {"SPY": 10.0}
    # Cash drops by 10 * 100 = 1000.
    assert state.cash == pytest.approx(9_000.0)
    assert state.realised_pnl == 0.0
    assert state.open_orders == 0


def test_round_trip_buy_then_sell_realises_pnl():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED,
            payload={"requested_qty": 10, "side": "buy"}),
        _ev("e2", "o1", EventType.FILL,
            payload={"qty": 10, "price": 100, "side": "buy"}),
        _ev("e3", "o2", EventType.ORDER_CREATED,
            payload={"requested_qty": 10, "side": "sell"}),
        _ev("e4", "o2", EventType.FILL,
            payload={"qty": 10, "price": 110, "side": "sell"}),
    ]
    state = replay_execution_events(events, starting_cash=10_000.0)
    # Sold the same 10 units at 110 -> realised PnL = 10 * (110 - 100) = 100.
    assert state.realised_pnl == pytest.approx(100.0)
    # Net cash = 10_000 - 1_000 + 1_100 = 10_100.
    assert state.cash == pytest.approx(10_100.0)
    assert state.positions == {}


def test_short_then_cover_realises_pnl():
    events = [
        _ev("e1", "o1", EventType.FILL,
            payload={"qty": 5, "price": 100, "side": "sell"}),
        _ev("e2", "o2", EventType.FILL,
            payload={"qty": 5, "price": 90, "side": "buy"}),
    ]
    state = replay_execution_events(events)
    # Short at 100, cover at 90 -> realised PnL = 5 * (100 - 90) = 50.
    assert state.realised_pnl == pytest.approx(50.0)
    # Cash = +500 (short proceeds) - 450 (cover cost) = 50.
    assert state.cash == pytest.approx(50.0)
    assert state.positions == {}


def test_commission_events_accumulate_and_reduce_cash():
    events = [
        _ev("e1", "o1", EventType.FILL,
            payload={"qty": 1, "price": 100, "side": "buy"}),
        _ev("e2", "o1", EventType.COMMISSION, payload={"amount": 0.5}),
        _ev("e3", "o1", EventType.COMMISSION, payload={"amount": 0.7}),
    ]
    state = replay_execution_events(events, starting_cash=1_000.0)
    assert state.commissions == pytest.approx(1.2)
    # Cash = 1_000 - 100 (buy) - 1.2 (commissions) = 898.8.
    assert state.cash == pytest.approx(898.8)


def test_unknown_external_fill_is_warned_not_raised():
    events = [
        _ev("e1", "o1", EventType.UNKNOWN_FILL,
            payload={"qty": 1, "price": 100}),
    ]
    state = replay_execution_events(events)
    assert any("unknown_external_fill" in w for w in state.warnings)
    assert state.open_orders == 1
    # Cash stays untouched -- we cannot trust an unknown fill to move books.
    assert state.cash == 0.0


def test_restart_between_ack_and_fill_recovers_state():
    """Simulate a session interrupted between BROKER_ACK and FILL.

    Replay must be able to resume by feeding the FILL alone, against the
    state already produced by the first run.
    """
    first_run = [
        _ev("e1", "o1", EventType.ORDER_CREATED,
            payload={"requested_qty": 5, "side": "buy"}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.BROKER_ACK),
    ]
    state_after_ack = replay_execution_events(first_run, starting_cash=1_000.0)
    assert state_after_ack.open_orders == 1
    assert state_after_ack.positions == {}
    assert state_after_ack.cash == pytest.approx(1_000.0)

    # Resume with the full log including the fill.
    full = first_run + [
        _ev("e4", "o1", EventType.FILL,
            payload={"qty": 5, "price": 50, "side": "buy"}),
    ]
    state_after_fill = replay_execution_events(full, starting_cash=1_000.0)
    assert state_after_fill.open_orders == 0
    assert state_after_fill.positions == {"SPY": 5.0}
    assert state_after_fill.cash == pytest.approx(1_000.0 - 250.0)


def test_replay_is_deterministic_for_same_input():
    events = [
        _ev("e1", "o1", EventType.FILL,
            payload={"qty": 2, "price": 100, "side": "buy"}),
        _ev("e2", "o1", EventType.COMMISSION, payload={"amount": 1.0}),
        _ev("e3", "o2", EventType.FILL,
            payload={"qty": 1, "price": 50, "side": "sell"}),
    ]
    a = replay_execution_events(events, starting_cash=500.0)
    b = replay_execution_events(events, starting_cash=500.0)
    assert a.cash == b.cash
    assert a.realised_pnl == b.realised_pnl
    assert a.positions == b.positions
    assert a.commissions == b.commissions


def test_partial_fills_track_fractional_position():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED,
            payload={"requested_qty": 10, "side": "buy"}),
        _ev("e2", "o1", EventType.PARTIAL_FILL,
            payload={"qty": 4, "price": 100, "side": "buy"}),
        _ev("e3", "o1", EventType.PARTIAL_FILL,
            payload={"qty": 6, "price": 105, "side": "buy"}),
    ]
    state = replay_execution_events(events)
    assert state.positions == {"SPY": 10.0}
    # 4*100 + 6*105 = 1030 cash out.
    assert state.cash == pytest.approx(-1_030.0)
    # Order is fully filled now -> no open orders.
    assert state.open_orders == 0


def test_multiple_symbols_tracked_independently():
    events = [
        _ev("e1", "o1", EventType.FILL,
            payload={"qty": 1, "price": 100, "side": "buy"}, symbol="AAPL"),
        _ev("e2", "o2", EventType.FILL,
            payload={"qty": 2, "price": 50, "side": "buy"}, symbol="MSFT"),
    ]
    state = replay_execution_events(events)
    assert state.positions == {"AAPL": 1.0, "MSFT": 2.0}


def test_duplicate_event_id_does_not_double_count_position():
    events = [
        _ev("e1", "o1", EventType.FILL,
            payload={"qty": 5, "price": 100, "side": "buy"}),
        _ev("e1", "o1", EventType.FILL,
            payload={"qty": 5, "price": 100, "side": "buy"}),
    ]
    state = replay_execution_events(events)
    # Reducer drops the dup; replay must not move books on the second one.
    assert state.positions == {"SPY": 5.0}
    assert any("duplicate" in w.lower() for w in state.warnings)


def test_open_orders_counter_excludes_terminal_states():
    events = [
        _ev("e1", "o1", EventType.FILL,
            payload={"qty": 1, "price": 100, "side": "buy"}),
        _ev("e2", "o2", EventType.ORDER_CREATED,
            payload={"requested_qty": 5, "side": "buy"}),
        _ev("e3", "o2", EventType.ORDER_SUBMITTED),
    ]
    state = replay_execution_events(events)
    assert state.orders["o1"].state is OrderState.FILLED
    assert state.open_orders == 1  # only o2 is non-terminal.
