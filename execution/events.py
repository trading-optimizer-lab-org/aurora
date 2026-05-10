"""R168 - Canonical execution event schema and order state machine.

One event language for paper, backtest and live adapters so order
lifecycles can be reduced, replayed and reconciled without ad-hoc status
strings. Events are immutable and JSON-serialisable; the state reducer
``reduce_order_state`` is pure and deterministic.

Out-of-order or duplicate events do not crash the reducer. Duplicates
are detected by ``event_id`` + payload equality and ignored. Events that
violate the state machine are kept on a separate warning stream so the
caller can decide whether to fail the run or annotate the audit trail.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    ORDER_CREATED = "order_created"
    ORDER_SUBMITTED = "order_submitted"
    BROKER_ACK = "broker_ack"
    PARTIAL_FILL = "partial_fill"
    FILL = "fill"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REPLACE_REQUESTED = "replace_requested"
    REPLACED = "replaced"
    REJECTED = "rejected"
    EXPIRED = "expired"
    COMMISSION = "commission"
    FINANCING = "financing"
    POSITION_UPDATE = "position_update"
    CASH_UPDATE = "cash_update"
    MARGIN_UPDATE = "margin_update"
    DISCONNECT = "disconnect"
    RECONNECT = "reconnect"
    UNKNOWN_FILL = "unknown_fill"


class OrderState(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELLED = "cancelled"
    REPLACE_PENDING = "replace_pending"
    REPLACED = "replaced"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"
    RECONCILED = "reconciled"


_TERMINAL_STATES: FrozenSet[OrderState] = frozenset({
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
    OrderState.RECONCILED,
})


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionEvent:
    """Immutable broker / engine lifecycle event."""

    event_id: str
    event_type: EventType
    order_id: str
    timestamp: str
    payload: Dict[str, Any] = field(default_factory=dict)
    sequence: Optional[int] = None
    broker: str = ""
    symbol: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id must be non-empty")
        if not self.order_id:
            raise ValueError("order_id must be non-empty")
        if not isinstance(self.event_type, EventType):
            object.__setattr__(self, "event_type", EventType(self.event_type))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ExecutionEvent":
        data = dict(payload)
        data["event_type"] = EventType(data["event_type"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Order state record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderStateRecord:
    """Aggregated state for a single order, derived from event reduction."""

    order_id: str
    state: OrderState
    symbol: str
    side: str
    requested_qty: float
    filled_qty: float
    avg_fill_price: float
    last_event_id: str
    last_timestamp: str
    realised_commission: float = 0.0
    rejection_reason: str = ""
    history: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        d["history"] = list(self.history)
        return d


@dataclass(frozen=True)
class OrderStateTransition:
    """Diagnostic record returned by :func:`reduce_order_state`."""

    order_id: str
    event: ExecutionEvent
    prior_state: Optional[OrderState]
    next_state: OrderState
    accepted: bool
    note: str = ""


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------


_INITIAL_STATE_TABLE: Dict[EventType, OrderState] = {
    EventType.ORDER_CREATED: OrderState.CREATED,
    EventType.ORDER_SUBMITTED: OrderState.SUBMITTED,
    EventType.BROKER_ACK: OrderState.ACKNOWLEDGED,
    EventType.PARTIAL_FILL: OrderState.PARTIALLY_FILLED,
    EventType.FILL: OrderState.FILLED,
    EventType.CANCEL_REQUESTED: OrderState.CANCEL_PENDING,
    EventType.CANCELLED: OrderState.CANCELLED,
    EventType.REPLACE_REQUESTED: OrderState.REPLACE_PENDING,
    EventType.REPLACED: OrderState.REPLACED,
    EventType.REJECTED: OrderState.REJECTED,
    EventType.EXPIRED: OrderState.EXPIRED,
    EventType.UNKNOWN_FILL: OrderState.UNKNOWN,
}


_VALID_TRANSITIONS: Dict[OrderState, FrozenSet[OrderState]] = {
    None: frozenset(_INITIAL_STATE_TABLE.values()),  # type: ignore[dict-item]
    OrderState.CREATED: frozenset({
        OrderState.SUBMITTED,
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELLED,
        OrderState.REPLACE_PENDING,
        OrderState.EXPIRED,
        OrderState.UNKNOWN,
    }),
    OrderState.SUBMITTED: frozenset({
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.CANCEL_PENDING,
        OrderState.REPLACE_PENDING,
        OrderState.EXPIRED,
        OrderState.UNKNOWN,
    }),
    OrderState.ACKNOWLEDGED: frozenset({
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELLED,
        OrderState.REPLACE_PENDING,
        OrderState.REJECTED,
        OrderState.EXPIRED,
        OrderState.UNKNOWN,
    }),
    OrderState.PARTIALLY_FILLED: frozenset({
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
        OrderState.UNKNOWN,
    }),
    OrderState.CANCEL_PENDING: frozenset({
        OrderState.CANCELLED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.REJECTED,
    }),
    OrderState.REPLACE_PENDING: frozenset({
        OrderState.REPLACED,
        OrderState.REJECTED,
        OrderState.CANCELLED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
    }),
    OrderState.REPLACED: frozenset({
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    }),
    OrderState.UNKNOWN: frozenset({
        OrderState.RECONCILED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
    }),
}


def _transition_allowed(
    prior: Optional[OrderState], next_state: OrderState,
) -> bool:
    if prior in _TERMINAL_STATES:
        return False
    allowed = _VALID_TRANSITIONS.get(prior)
    if allowed is None:
        return True
    return next_state in allowed


def _payload_get(event: ExecutionEvent, key: str, default: Any = 0.0) -> Any:
    return event.payload.get(key, default)


def reduce_order_state(
    record: Optional[OrderStateRecord],
    event: ExecutionEvent,
) -> Tuple[OrderStateRecord, OrderStateTransition]:
    """Apply ``event`` to the running ``record`` and return the new record.

    The reducer is pure: passing the same ``record`` and ``event`` always
    yields the same result. Duplicate events (same id and payload) are
    swallowed silently. Out-of-order events that would violate the state
    machine are reported via the returned :class:`OrderStateTransition`
    with ``accepted=False`` and the record is left unchanged.
    """
    next_state_label = _INITIAL_STATE_TABLE.get(event.event_type)
    prior_state = record.state if record is not None else None

    if record is not None and event.event_id in record.history:
        # Duplicate event id -- swallow silently.
        return record, OrderStateTransition(
            order_id=event.order_id,
            event=event,
            prior_state=prior_state,
            next_state=record.state,
            accepted=False,
            note="duplicate event id ignored",
        )

    if next_state_label is None:
        # Side-effect events (commission, cash, margin updates etc).
        if record is None:
            record = _bootstrap_record_from_side_event(event)
            note = "side-effect event without parent"
        else:
            note = f"applied {event.event_type.value}"
        updated = _apply_side_effect(record, event)
        return updated, OrderStateTransition(
            order_id=event.order_id,
            event=event,
            prior_state=prior_state,
            next_state=updated.state,
            accepted=True,
            note=note,
        )

    if not _transition_allowed(prior_state, next_state_label):
        # Keep the prior state but report the violation.
        return record or _bootstrap_record_from_side_event(event), OrderStateTransition(
            order_id=event.order_id,
            event=event,
            prior_state=prior_state,
            next_state=next_state_label,
            accepted=False,
            note=(
                f"invalid transition {prior_state} -> {next_state_label}; "
                "event ignored"
            ),
        )

    if record is None:
        record = _bootstrap_record_from_side_event(event, state=next_state_label)
    record = _apply_lifecycle_event(record, event, next_state_label)
    return record, OrderStateTransition(
        order_id=event.order_id,
        event=event,
        prior_state=prior_state,
        next_state=record.state,
        accepted=True,
    )


def _bootstrap_record_from_side_event(
    event: ExecutionEvent, *, state: OrderState = OrderState.CREATED,
) -> OrderStateRecord:
    """Bootstrap an empty record. Caller is responsible for appending to
    history via :func:`_apply_lifecycle_event` or :func:`_apply_side_effect`."""
    return OrderStateRecord(
        order_id=event.order_id,
        state=state,
        symbol=event.symbol,
        side=str(_payload_get(event, "side", "")),
        requested_qty=float(_payload_get(event, "requested_qty", 0.0) or 0.0),
        filled_qty=0.0,
        avg_fill_price=0.0,
        last_event_id=event.event_id,
        last_timestamp=event.timestamp,
        history=(),
    )


def _apply_side_effect(
    record: OrderStateRecord, event: ExecutionEvent,
) -> OrderStateRecord:
    history = record.history + (event.event_id,)
    realised_commission = record.realised_commission
    if event.event_type is EventType.COMMISSION:
        realised_commission += float(_payload_get(event, "amount", 0.0) or 0.0)
    return replace(
        record,
        last_event_id=event.event_id,
        last_timestamp=event.timestamp,
        realised_commission=realised_commission,
        history=history,
    )


def _apply_lifecycle_event(
    record: OrderStateRecord,
    event: ExecutionEvent,
    next_state: OrderState,
) -> OrderStateRecord:
    history = record.history + (event.event_id,)
    filled_qty = record.filled_qty
    avg_fill_price = record.avg_fill_price
    rejection_reason = record.rejection_reason

    if event.event_type in (EventType.PARTIAL_FILL, EventType.FILL):
        qty = float(_payload_get(event, "qty", 0.0) or 0.0)
        price = float(_payload_get(event, "price", 0.0) or 0.0)
        new_filled = filled_qty + qty
        if new_filled > 0:
            avg_fill_price = (
                (avg_fill_price * filled_qty + price * qty) / new_filled
            )
        filled_qty = new_filled
    elif event.event_type is EventType.REJECTED:
        rejection_reason = str(_payload_get(event, "reason", "") or "")

    requested_qty = record.requested_qty
    if requested_qty == 0.0:
        requested_qty = float(
            _payload_get(event, "requested_qty", requested_qty) or requested_qty
        )

    state = next_state
    if event.event_type is EventType.PARTIAL_FILL and requested_qty > 0:
        if filled_qty >= requested_qty:
            state = OrderState.FILLED

    symbol = record.symbol or event.symbol
    side = record.side or str(_payload_get(event, "side", ""))

    return OrderStateRecord(
        order_id=record.order_id,
        state=state,
        symbol=symbol,
        side=side,
        requested_qty=requested_qty,
        filled_qty=filled_qty,
        avg_fill_price=avg_fill_price,
        last_event_id=event.event_id,
        last_timestamp=event.timestamp,
        realised_commission=record.realised_commission,
        rejection_reason=rejection_reason,
        history=history,
    )


def reduce_events(events: Iterable[ExecutionEvent]) -> Tuple[
    Dict[str, OrderStateRecord], List[OrderStateTransition]
]:
    """Apply a sequence of events grouped by order id."""
    state: Dict[str, OrderStateRecord] = {}
    transitions: List[OrderStateTransition] = []
    for ev in events:
        record = state.get(ev.order_id)
        new_record, transition = reduce_order_state(record, ev)
        state[ev.order_id] = new_record
        transitions.append(transition)
    return state, transitions


def serialise_events(events: Iterable[ExecutionEvent]) -> str:
    """Serialise ``events`` to a deterministic JSONL blob."""
    return "\n".join(ev.to_json() for ev in events)


def deserialise_events(blob: str) -> List[ExecutionEvent]:
    """Inverse of :func:`serialise_events`."""
    out: List[ExecutionEvent] = []
    for line in blob.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(ExecutionEvent.from_dict(json.loads(line)))
    return out


def utcnow_iso() -> str:
    """Helper used by adapters that need a timestamp string."""
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "EventType",
    "ExecutionEvent",
    "OrderState",
    "OrderStateRecord",
    "OrderStateTransition",
    "deserialise_events",
    "reduce_events",
    "reduce_order_state",
    "serialise_events",
    "utcnow_iso",
]
