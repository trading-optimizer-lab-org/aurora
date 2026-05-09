"""Order lifecycle state machine.

Phase 3 -- Candidate A. The transition table is intentionally explicit
and only encodes legal moves; anything else returns ``None`` so the
caller can emit a reconciliation diff rather than silently stepping
into garbage state.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Tuple

from aurora.execution.events import (
    BrokerEvent,
    CancelRequested,
    Disconnected,
    OrderAcknowledged,
    OrderCancelled,
    OrderCreated,
    OrderExpired,
    OrderFilled,
    OrderPartiallyFilled,
    OrderRejected,
    OrderReplaced,
    OrderSubmitted,
    Reconnected,
    ReplaceRequested,
)


class OrderLifecycleState(Enum):
    """States an order can occupy."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REPLACE_PENDING = "REPLACE_PENDING"
    REPLACED = "REPLACED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    RECONCILED = "RECONCILED"


# Transition table keyed by (current_state, event_class).
# Only legal moves are listed. Everything else returns None.
_TRANSITIONS: Dict[Tuple[OrderLifecycleState, type], OrderLifecycleState] = {
    # CREATED -> SUBMITTED on OrderSubmitted; or fail fast on Reject.
    (OrderLifecycleState.CREATED, OrderSubmitted): OrderLifecycleState.SUBMITTED,
    (OrderLifecycleState.CREATED, OrderRejected): OrderLifecycleState.REJECTED,
    # SUBMITTED -> ACKNOWLEDGED is the canonical happy path.
    (OrderLifecycleState.SUBMITTED, OrderAcknowledged): OrderLifecycleState.ACKNOWLEDGED,
    (OrderLifecycleState.SUBMITTED, OrderRejected): OrderLifecycleState.REJECTED,
    (OrderLifecycleState.SUBMITTED, OrderExpired): OrderLifecycleState.EXPIRED,
    # ACKNOWLEDGED -> partial / full / cancel_pending / replace_pending / expire.
    (OrderLifecycleState.ACKNOWLEDGED, OrderPartiallyFilled):
        OrderLifecycleState.PARTIALLY_FILLED,
    (OrderLifecycleState.ACKNOWLEDGED, OrderFilled): OrderLifecycleState.FILLED,
    (OrderLifecycleState.ACKNOWLEDGED, CancelRequested):
        OrderLifecycleState.CANCEL_PENDING,
    (OrderLifecycleState.ACKNOWLEDGED, ReplaceRequested):
        OrderLifecycleState.REPLACE_PENDING,
    (OrderLifecycleState.ACKNOWLEDGED, OrderExpired): OrderLifecycleState.EXPIRED,
    (OrderLifecycleState.ACKNOWLEDGED, OrderRejected): OrderLifecycleState.REJECTED,
    # PARTIALLY_FILLED -> more partials, full fill, cancel, replace, expire.
    (OrderLifecycleState.PARTIALLY_FILLED, OrderPartiallyFilled):
        OrderLifecycleState.PARTIALLY_FILLED,
    (OrderLifecycleState.PARTIALLY_FILLED, OrderFilled): OrderLifecycleState.FILLED,
    (OrderLifecycleState.PARTIALLY_FILLED, CancelRequested):
        OrderLifecycleState.CANCEL_PENDING,
    (OrderLifecycleState.PARTIALLY_FILLED, ReplaceRequested):
        OrderLifecycleState.REPLACE_PENDING,
    (OrderLifecycleState.PARTIALLY_FILLED, OrderExpired):
        OrderLifecycleState.EXPIRED,
    # CANCEL_PENDING -> resolved by cancel / late fill.
    (OrderLifecycleState.CANCEL_PENDING, OrderCancelled): OrderLifecycleState.CANCELLED,
    (OrderLifecycleState.CANCEL_PENDING, OrderFilled): OrderLifecycleState.FILLED,
    (OrderLifecycleState.CANCEL_PENDING, OrderPartiallyFilled):
        OrderLifecycleState.PARTIALLY_FILLED,
    (OrderLifecycleState.CANCEL_PENDING, OrderRejected): OrderLifecycleState.REJECTED,
    # REPLACE_PENDING -> resolved by replace / cancel / fill.
    (OrderLifecycleState.REPLACE_PENDING, OrderReplaced): OrderLifecycleState.REPLACED,
    (OrderLifecycleState.REPLACE_PENDING, OrderCancelled):
        OrderLifecycleState.CANCELLED,
    (OrderLifecycleState.REPLACE_PENDING, OrderRejected): OrderLifecycleState.REJECTED,
    (OrderLifecycleState.REPLACE_PENDING, OrderFilled): OrderLifecycleState.FILLED,
    # REPLACED behaves like ACKNOWLEDGED for further fills/cancels.
    (OrderLifecycleState.REPLACED, OrderPartiallyFilled):
        OrderLifecycleState.PARTIALLY_FILLED,
    (OrderLifecycleState.REPLACED, OrderFilled): OrderLifecycleState.FILLED,
    (OrderLifecycleState.REPLACED, CancelRequested): OrderLifecycleState.CANCEL_PENDING,
    (OrderLifecycleState.REPLACED, ReplaceRequested):
        OrderLifecycleState.REPLACE_PENDING,
    (OrderLifecycleState.REPLACED, OrderExpired): OrderLifecycleState.EXPIRED,
    # UNKNOWN -> recovered by an OrderCreated replay (rare).
    (OrderLifecycleState.UNKNOWN, OrderCreated): OrderLifecycleState.CREATED,
    (OrderLifecycleState.UNKNOWN, OrderAcknowledged): OrderLifecycleState.ACKNOWLEDGED,
    (OrderLifecycleState.UNKNOWN, OrderPartiallyFilled):
        OrderLifecycleState.PARTIALLY_FILLED,
    (OrderLifecycleState.UNKNOWN, OrderFilled): OrderLifecycleState.FILLED,
}


def transition(
    current_state: OrderLifecycleState, event: BrokerEvent
) -> OrderLifecycleState | None:
    """Return next state for ``current_state`` given ``event``.

    Returns ``None`` for an illegal or unknown transition. Two events
    deliberately do not change the lifecycle state: ``Disconnected`` and
    ``Reconnected`` are session-level and the caller may keep the
    current state. They return the current state unchanged.
    """
    if isinstance(event, (Disconnected, Reconnected)):
        return current_state
    return _TRANSITIONS.get((current_state, type(event)))


__all__ = ["OrderLifecycleState", "transition"]
