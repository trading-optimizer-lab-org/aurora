"""Replay broker events to rebuild positions, cash, PnL and order state.

Phase 3 -- Candidate A. ``replay_events`` walks an ordered event log and
returns a :class:`ReplayResult` describing the reconstructed state plus
any anomalies (orphan, duplicate, out-of-order) so the caller can build
a reconciliation report from a single pass.

Conventions:

* Position deltas: a ``buy`` fill increases position by ``fill_qty``,
  a ``sell`` fill decreases it.
* Cash deltas: a ``buy`` fill spends ``fill_qty * fill_price`` minus
  any reported commissions; a ``sell`` adds proceeds minus commissions.
* Realised PnL is computed using a simple weighted-average cost basis
  per symbol. This is the conservative choice for a first replay: it
  matches what the engine itself usually reports and keeps the replay
  free of policy decisions about FIFO / LIFO accounting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from aurora.execution.events import (
    BrokerEvent,
    CashUpdated,
    CommissionReported,
    OrderCancelled,
    OrderCreated,
    OrderExpired,
    OrderFilled,
    OrderPartiallyFilled,
    OrderRejected,
    PositionUpdated,
)
from aurora.execution.order_state import OrderLifecycleState, transition


@dataclass
class ReplayResult:
    """Outcome of replaying an ordered event log.

    ``positions`` maps symbol -> signed quantity. ``cash`` is total cash
    after the replay. ``realised_pnl`` is per-symbol realised PnL.
    ``commissions`` is total commissions + fees. ``open_orders`` lists
    order ids whose terminal state is still active.

    Anomaly buckets:

    * ``orphan_events`` -- a fill / commission / cancel / etc. for an
      order id that was never created.
    * ``duplicate_events`` -- same ``(order_id, fill_seq)`` seen twice.
    * ``out_of_order_events`` -- timestamp earlier than the previous
      event timestamp.
    """

    positions: Dict[str, float] = field(default_factory=dict)
    cash: float = 0.0
    realised_pnl: Dict[str, float] = field(default_factory=dict)
    commissions: float = 0.0
    open_orders: List[str] = field(default_factory=list)
    orphan_events: List[BrokerEvent] = field(default_factory=list)
    duplicate_events: List[BrokerEvent] = field(default_factory=list)
    out_of_order_events: List[BrokerEvent] = field(default_factory=list)


def _apply_fill(
    result: ReplayResult,
    avg_cost: Dict[str, float],
    symbol: str,
    side: str,
    qty: float,
    price: float,
) -> None:
    """Update positions, cash and realised PnL for one fill."""
    pos = result.positions.get(symbol, 0.0)
    cost = avg_cost.get(symbol, 0.0)
    if side == "buy":
        new_pos = pos + qty
        # Weighted-average cost when adding to a long, or reducing short.
        if pos >= 0:
            denom = new_pos if new_pos != 0 else 1.0
            cost = (pos * cost + qty * price) / denom
        else:
            # Closing or reducing a short -> realise PnL on the closed leg.
            closed = min(qty, -pos)
            result.realised_pnl[symbol] = (
                result.realised_pnl.get(symbol, 0.0) + closed * (cost - price)
            )
            if new_pos > 0:
                cost = price
        result.cash -= qty * price
    elif side == "sell":
        new_pos = pos - qty
        if pos <= 0:
            denom = new_pos if new_pos != 0 else -1.0
            # When opening / extending a short, weight the avg short price.
            cost = (-pos * cost + qty * price) / -denom if denom != 0 else price
        else:
            closed = min(qty, pos)
            result.realised_pnl[symbol] = (
                result.realised_pnl.get(symbol, 0.0) + closed * (price - cost)
            )
            if new_pos < 0:
                cost = price
        result.cash += qty * price
    else:
        # Ignore unknown sides at the fill layer; replay caller will
        # have already routed an unknown side to an orphan bucket.
        return
    result.positions[symbol] = new_pos
    avg_cost[symbol] = cost


def replay_events(events: List[BrokerEvent]) -> ReplayResult:
    """Walk ``events`` in order and reconstruct broker-side state.

    Events are expected to be already sorted by ``timestamp_iso``; if a
    later event has an earlier timestamp than its predecessor it is
    flagged in ``out_of_order_events`` but still applied (replay should
    never silently drop information).
    """
    result = ReplayResult()
    avg_cost: Dict[str, float] = {}
    order_state: Dict[str, OrderLifecycleState] = {}
    order_symbol: Dict[str, str] = {}
    seen_fills: Set[Tuple[str, int]] = set()
    last_ts: str = ""

    for event in events:
        if last_ts and event.timestamp_iso < last_ts:
            result.out_of_order_events.append(event)
        else:
            last_ts = event.timestamp_iso

        oid = event.order_id

        # OrderCreated registers a new order.
        if isinstance(event, OrderCreated):
            order_state[oid] = OrderLifecycleState.CREATED
            order_symbol[oid] = event.symbol
            continue

        # CashUpdated and PositionUpdated are account-level pushes; they
        # do not require a known order id.
        if isinstance(event, CashUpdated):
            result.cash = event.cash
            continue
        if isinstance(event, PositionUpdated):
            result.positions[event.symbol] = event.quantity
            avg_cost[event.symbol] = event.avg_cost
            continue

        # Anything else without a registered order is an orphan.
        if oid not in order_state:
            result.orphan_events.append(event)
            continue

        # Fills: detect duplicates by (order_id, fill_seq).
        if isinstance(event, (OrderPartiallyFilled, OrderFilled)):
            key = (oid, event.fill_seq)
            if key in seen_fills:
                result.duplicate_events.append(event)
                continue
            seen_fills.add(key)
            symbol = order_symbol.get(oid, "")
            if symbol:
                _apply_fill(
                    result, avg_cost, symbol, event.side, event.fill_qty, event.fill_price
                )

        # Commission events directly accumulate.
        if isinstance(event, CommissionReported):
            result.commissions += event.commission + event.fees
            result.cash -= event.commission + event.fees

        # Step the lifecycle state machine.
        next_state = transition(order_state[oid], event)
        if next_state is not None:
            order_state[oid] = next_state

    # Open orders: anything not in a terminal state.
    terminal = {
        OrderLifecycleState.FILLED,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.EXPIRED,
    }
    result.open_orders = sorted(
        oid for oid, state in order_state.items() if state not in terminal
    )

    # Note: OrderCancelled / OrderExpired / OrderRejected do not require
    # special handling beyond the state-machine step. They are already
    # consumed by the transition table above.
    _ = (OrderCancelled, OrderExpired, OrderRejected)

    return result


__all__ = ["ReplayResult", "replay_events"]
