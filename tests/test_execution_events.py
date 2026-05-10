"""Tests for R168 execution events + order state machine."""
from __future__ import annotations

import json

import pytest

from aurora.execution.events import (
    EventType,
    ExecutionEvent,
    OrderState,
    deserialise_events,
    reduce_events,
    reduce_order_state,
    serialise_events,
)


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


def _ev(
    event_id: str,
    order_id: str,
    event_type: EventType,
    *,
    payload: dict | None = None,
    timestamp: str = "2026-05-10T00:00:00+00:00",
    symbol: str = "SPY",
    sequence: int | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=event_id,
        event_type=event_type,
        order_id=order_id,
        timestamp=timestamp,
        payload=payload or {},
        sequence=sequence,
        broker="paper",
        symbol=symbol,
    )


def test_event_requires_event_id():
    with pytest.raises(ValueError):
        ExecutionEvent(
            event_id="",
            event_type=EventType.ORDER_CREATED,
            order_id="o1",
            timestamp="t",
        )


def test_event_requires_order_id():
    with pytest.raises(ValueError):
        ExecutionEvent(
            event_id="e1",
            event_type=EventType.ORDER_CREATED,
            order_id="",
            timestamp="t",
        )


def test_event_to_json_round_trip():
    ev = _ev("e1", "o1", EventType.PARTIAL_FILL, payload={"qty": 5, "price": 100})
    payload = json.loads(ev.to_json())
    assert payload["event_type"] == "partial_fill"
    assert payload["payload"]["qty"] == 5


def test_event_from_dict_accepts_string_event_type():
    ev = ExecutionEvent.from_dict({
        "event_id": "e1",
        "event_type": "fill",
        "order_id": "o1",
        "timestamp": "t",
        "payload": {},
        "sequence": None,
        "broker": "",
        "symbol": "",
    })
    assert ev.event_type is EventType.FILL


# ---------------------------------------------------------------------------
# Reducer happy paths
# ---------------------------------------------------------------------------


def test_create_then_submit_then_fill():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 10}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.BROKER_ACK),
        _ev("e4", "o1", EventType.FILL, payload={"qty": 10, "price": 100}),
    ]
    states, transitions = reduce_events(events)
    rec = states["o1"]
    assert rec.state is OrderState.FILLED
    assert rec.filled_qty == 10
    assert rec.avg_fill_price == 100
    assert all(t.accepted for t in transitions)


def test_partial_fill_then_full_fill():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 10}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.PARTIAL_FILL, payload={"qty": 4, "price": 100}),
        _ev("e4", "o1", EventType.PARTIAL_FILL, payload={"qty": 6, "price": 105}),
    ]
    states, _ = reduce_events(events)
    rec = states["o1"]
    assert rec.state is OrderState.FILLED
    assert rec.filled_qty == 10
    # Volume-weighted avg: (4*100 + 6*105)/10 = 103
    assert rec.avg_fill_price == pytest.approx(103.0)


def test_cancel_pending_resolves_to_cancelled():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.CANCEL_REQUESTED),
        _ev("e4", "o1", EventType.CANCELLED),
    ]
    states, _ = reduce_events(events)
    assert states["o1"].state is OrderState.CANCELLED
    assert states["o1"].is_terminal


def test_rejected_event_records_reason():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.REJECTED, payload={"reason": "insufficient buying power"}),
    ]
    states, _ = reduce_events(events)
    rec = states["o1"]
    assert rec.state is OrderState.REJECTED
    assert "insufficient" in rec.rejection_reason


def test_replace_pending_then_replaced():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.REPLACE_REQUESTED),
        _ev("e4", "o1", EventType.REPLACED),
    ]
    states, _ = reduce_events(events)
    assert states["o1"].state is OrderState.REPLACED


# ---------------------------------------------------------------------------
# Reducer defensive behaviour
# ---------------------------------------------------------------------------


def test_duplicate_event_id_is_ignored():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.FILL, payload={"qty": 5, "price": 100}),
        _ev("e3", "o1", EventType.FILL, payload={"qty": 5, "price": 100}),  # dup
    ]
    states, transitions = reduce_events(events)
    rec = states["o1"]
    # Filled qty stayed at 5, not 10.
    assert rec.filled_qty == 5
    assert any("duplicate" in t.note for t in transitions)


def test_invalid_transition_is_rejected():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
        _ev("e2", "o1", EventType.FILL, payload={"qty": 5, "price": 100}),
        # Try to go from FILLED back to SUBMITTED -- should be rejected.
        _ev("e3", "o1", EventType.ORDER_SUBMITTED),
    ]
    states, transitions = reduce_events(events)
    rec = states["o1"]
    assert rec.state is OrderState.FILLED
    assert transitions[-1].accepted is False
    assert "invalid transition" in transitions[-1].note


def test_unknown_fill_promotes_to_unknown_state():
    events = [
        _ev("e1", "o1", EventType.UNKNOWN_FILL, payload={"qty": 1, "price": 100}),
    ]
    states, _ = reduce_events(events)
    assert states["o1"].state is OrderState.UNKNOWN


def test_commission_event_accumulates():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
        _ev("e2", "o1", EventType.FILL, payload={"qty": 5, "price": 100}),
        _ev("e3", "o1", EventType.COMMISSION, payload={"amount": 0.5}),
        _ev("e4", "o1", EventType.COMMISSION, payload={"amount": 0.7}),
    ]
    states, transitions = reduce_events(events)
    rec = states["o1"]
    assert rec.realised_commission == pytest.approx(1.2)
    assert all(t.accepted for t in transitions)


def test_history_is_ordered_and_unique_when_no_dup():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.BROKER_ACK),
    ]
    states, _ = reduce_events(events)
    assert states["o1"].history == ("e1", "e2", "e3")


def test_reduce_order_state_initial_record_from_event():
    # Reducer accepts None record and bootstraps from the event payload.
    rec, transition = reduce_order_state(
        None,
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
    )
    assert rec.state is OrderState.CREATED
    assert rec.requested_qty == 5
    assert transition.accepted


def test_disconnect_event_does_not_corrupt_state():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.DISCONNECT),
        _ev("e4", "o1", EventType.RECONNECT),
        _ev("e5", "o1", EventType.FILL, payload={"qty": 5, "price": 100}),
    ]
    states, _ = reduce_events(events)
    assert states["o1"].state is OrderState.FILLED


def test_partial_fill_accumulates_to_filled_when_quantity_reaches_request():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 10}),
        _ev("e2", "o1", EventType.ORDER_SUBMITTED),
        _ev("e3", "o1", EventType.PARTIAL_FILL, payload={"qty": 10, "price": 100}),
    ]
    states, _ = reduce_events(events)
    assert states["o1"].state is OrderState.FILLED


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_serialise_round_trip():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
        _ev("e2", "o1", EventType.FILL, payload={"qty": 5, "price": 100}),
    ]
    blob = serialise_events(events)
    out = deserialise_events(blob)
    assert [e.event_id for e in out] == ["e1", "e2"]
    assert out[1].event_type is EventType.FILL


def test_serialise_is_deterministic():
    events = [
        _ev("e1", "o1", EventType.ORDER_CREATED, payload={"requested_qty": 5}),
    ]
    a = serialise_events(events)
    b = serialise_events(events)
    assert a == b
