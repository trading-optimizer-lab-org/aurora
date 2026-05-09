"""Canonical broker lifecycle events.

Phase 3 -- Candidate A. These dataclasses are the *only* schema by which
brokers (paper or live) are allowed to communicate state changes upstream.
They are pure data: construction performs no I/O and never reaches a
network. ``BrokerEvent`` is an abstract base providing the ``event_type``
property used by replay and reconciliation modules.

Every event carries:

* ``order_id`` -- the engine-side order identifier (string), so replay
  can scope events to a single order without parsing broker-specific
  payloads.
* ``timestamp_iso`` -- ISO-8601 timestamp string. Strings (not
  ``datetime``) are deliberate: events crossing the broker boundary tend
  to arrive serialised, and stringly-typed timestamps survive JSON round
  trips without timezone surprises.

All event classes are ``frozen=True`` -- once emitted they are
immutable. Downstream code that needs to mutate state should build a
new event, not edit an existing one.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerEvent(ABC):
    """Abstract base for every broker lifecycle event.

    Subclasses must be frozen dataclasses and must include
    ``order_id: str`` and ``timestamp_iso: str`` fields. The
    ``event_type`` property returns the concrete class name, which is
    used as the discriminator in serialised event streams.
    """

    @property
    @abstractmethod
    def event_type(self) -> str:
        """Class-name discriminator for serialised event streams."""


@dataclass(frozen=True)
class OrderCreated(BrokerEvent):
    """Order built locally; not yet sent to the broker."""

    order_id: str
    timestamp_iso: str
    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    order_type: str  # "market", "limit", "stop", ...
    limit_price: float | None = None
    stop_price: float | None = None

    @property
    def event_type(self) -> str:
        return "OrderCreated"


@dataclass(frozen=True)
class OrderSubmitted(BrokerEvent):
    """Order sent to the broker. Awaiting acknowledgement."""

    order_id: str
    timestamp_iso: str
    venue: str = ""

    @property
    def event_type(self) -> str:
        return "OrderSubmitted"


@dataclass(frozen=True)
class OrderAcknowledged(BrokerEvent):
    """Broker accepted the order and assigned a broker-side id."""

    order_id: str
    timestamp_iso: str
    broker_order_id: str = ""

    @property
    def event_type(self) -> str:
        return "OrderAcknowledged"


@dataclass(frozen=True)
class OrderPartiallyFilled(BrokerEvent):
    """Single partial fill on an open order."""

    order_id: str
    timestamp_iso: str
    fill_qty: float
    fill_price: float
    side: str  # "buy" or "sell"
    fill_seq: int = 0  # monotonic per-order sequence
    remaining_qty: float = 0.0

    @property
    def event_type(self) -> str:
        return "OrderPartiallyFilled"


@dataclass(frozen=True)
class OrderFilled(BrokerEvent):
    """Final fill that closes the order. ``fill_qty`` is the residual."""

    order_id: str
    timestamp_iso: str
    fill_qty: float
    fill_price: float
    side: str
    fill_seq: int = 0
    avg_fill_price: float = 0.0  # cumulative average for the order

    @property
    def event_type(self) -> str:
        return "OrderFilled"


@dataclass(frozen=True)
class CancelRequested(BrokerEvent):
    """Engine asked the broker to cancel an order."""

    order_id: str
    timestamp_iso: str

    @property
    def event_type(self) -> str:
        return "CancelRequested"


@dataclass(frozen=True)
class OrderCancelled(BrokerEvent):
    """Broker confirmed cancellation."""

    order_id: str
    timestamp_iso: str
    cancelled_qty: float = 0.0

    @property
    def event_type(self) -> str:
        return "OrderCancelled"


@dataclass(frozen=True)
class ReplaceRequested(BrokerEvent):
    """Engine asked the broker to replace an order (price or qty change)."""

    order_id: str
    timestamp_iso: str
    new_qty: float | None = None
    new_limit_price: float | None = None

    @property
    def event_type(self) -> str:
        return "ReplaceRequested"


@dataclass(frozen=True)
class OrderReplaced(BrokerEvent):
    """Broker confirmed the replace."""

    order_id: str
    timestamp_iso: str
    new_qty: float | None = None
    new_limit_price: float | None = None

    @property
    def event_type(self) -> str:
        return "OrderReplaced"


@dataclass(frozen=True)
class OrderRejected(BrokerEvent):
    """Broker rejected the order. ``reason`` is broker-supplied text."""

    order_id: str
    timestamp_iso: str
    reason: str = ""

    @property
    def event_type(self) -> str:
        return "OrderRejected"


@dataclass(frozen=True)
class OrderExpired(BrokerEvent):
    """Order expired by venue rules (time-in-force)."""

    order_id: str
    timestamp_iso: str

    @property
    def event_type(self) -> str:
        return "OrderExpired"


@dataclass(frozen=True)
class CommissionReported(BrokerEvent):
    """Broker booked commissions / fees against an order."""

    order_id: str
    timestamp_iso: str
    commission: float = 0.0
    fees: float = 0.0
    currency: str = "USD"

    @property
    def event_type(self) -> str:
        return "CommissionReported"


@dataclass(frozen=True)
class CashUpdated(BrokerEvent):
    """Broker pushed an authoritative cash balance.

    ``order_id`` is allowed to be empty for account-level updates that
    are not tied to a specific order.
    """

    order_id: str
    timestamp_iso: str
    cash: float = 0.0
    currency: str = "USD"

    @property
    def event_type(self) -> str:
        return "CashUpdated"


@dataclass(frozen=True)
class PositionUpdated(BrokerEvent):
    """Broker pushed an authoritative position quantity for one symbol."""

    order_id: str
    timestamp_iso: str
    symbol: str = ""
    quantity: float = 0.0
    avg_cost: float = 0.0

    @property
    def event_type(self) -> str:
        return "PositionUpdated"


@dataclass(frozen=True)
class Disconnected(BrokerEvent):
    """Broker connection lost. ``order_id`` may be empty (session-level)."""

    order_id: str
    timestamp_iso: str
    reason: str = ""

    @property
    def event_type(self) -> str:
        return "Disconnected"


@dataclass(frozen=True)
class Reconnected(BrokerEvent):
    """Broker connection restored."""

    order_id: str
    timestamp_iso: str

    @property
    def event_type(self) -> str:
        return "Reconnected"


__all__ = [
    "BrokerEvent",
    "OrderCreated",
    "OrderSubmitted",
    "OrderAcknowledged",
    "OrderPartiallyFilled",
    "OrderFilled",
    "CancelRequested",
    "OrderCancelled",
    "ReplaceRequested",
    "OrderReplaced",
    "OrderRejected",
    "OrderExpired",
    "CommissionReported",
    "CashUpdated",
    "PositionUpdated",
    "Disconnected",
    "Reconnected",
]
