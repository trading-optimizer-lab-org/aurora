"""R169 -- Execution replay engine.

Walks an :class:`~aurora.execution.events.ExecutionEvent` stream through
the R168 reducer and accumulates the bookkeeping that the reducer alone
does not track: per-symbol positions, cash, realised PnL and commissions.

The replay is pure: same events, same starting cash -> same state, and
no reliance on wall-clock time. The replay never raises on data quality
issues; instead each anomaly is recorded as a string in the
``warnings`` tuple so callers can decide what to do with it.

Sign convention:
    * Buy fills add to position and reduce cash by ``qty * price``.
    * Sell fills reduce the position and increase cash by
      ``qty * price``. ``side`` is read from the event payload first
      (``"buy"`` / ``"sell"``); if unset, the reducer's stored side on
      the parent :class:`OrderStateRecord` is used. Anything else falls
      back to ``+1`` (buy) and emits a warning.
    * Realised PnL is calculated from offsetting fills using a running
      weighted-average cost basis per symbol. Closing or reducing a
      position realises the slice that was unwound; opening or adding
      simply rolls the basis forward.
    * Commission events accumulate into ``commissions`` and reduce
      ``cash`` symmetrically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from aurora.execution.events import (
    EventType,
    ExecutionEvent,
    OrderState,
    OrderStateRecord,
    reduce_order_state,
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionReplayState:
    """Snapshot of the books rebuilt from an event log."""

    orders: Dict[str, OrderStateRecord] = field(default_factory=dict)
    positions: Dict[str, float] = field(default_factory=dict)
    cash: float = 0.0
    realised_pnl: float = 0.0
    commissions: float = 0.0
    open_orders: int = 0
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "orders": {k: v.to_dict() for k, v in self.orders.items()},
            "positions": dict(self.positions),
            "cash": self.cash,
            "realised_pnl": self.realised_pnl,
            "commissions": self.commissions,
            "open_orders": self.open_orders,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_TERMINAL_STATES = frozenset({
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
    OrderState.RECONCILED,
})


def _resolve_side(event: ExecutionEvent, record: OrderStateRecord | None) -> int:
    """Return ``+1`` for a buy or ``-1`` for a sell."""
    raw = event.payload.get("side")
    if raw is None and record is not None:
        raw = record.side
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in {"buy", "b", "long", "+1", "1"}:
            return 1
        if s in {"sell", "s", "short", "-1"}:
            return -1
    if isinstance(raw, (int, float)) and raw != 0:
        return 1 if raw > 0 else -1
    return 0


def _apply_fill(
    positions: Dict[str, float],
    cost_basis: Dict[str, float],
    cash: float,
    realised: float,
    symbol: str,
    side: int,
    qty: float,
    price: float,
) -> Tuple[float, float]:
    """Update positions / cost basis / cash / realised PnL in place.

    Returns the updated ``(cash, realised)`` pair.
    """
    if qty <= 0 or price < 0:
        return cash, realised

    signed_qty = side * qty
    current_qty = positions.get(symbol, 0.0)
    current_basis = cost_basis.get(symbol, 0.0)

    new_qty = current_qty + signed_qty

    # Same-side trade -> roll the weighted-average basis forward.
    if current_qty == 0 or (current_qty > 0) == (signed_qty > 0):
        if new_qty != 0:
            cost_basis[symbol] = (
                current_basis * abs(current_qty) + price * abs(signed_qty)
            ) / abs(new_qty)
        else:
            cost_basis[symbol] = 0.0
    else:
        # Offsetting trade -> realise PnL on the unwound slice.
        unwound = min(abs(current_qty), abs(signed_qty))
        if current_qty > 0:
            # Long being reduced; we sold ``unwound`` units at ``price``.
            realised += (price - current_basis) * unwound
        else:
            # Short being covered; we bought ``unwound`` units at ``price``.
            realised += (current_basis - price) * unwound
        if abs(signed_qty) > abs(current_qty):
            # Position flipped; remainder establishes the new basis.
            cost_basis[symbol] = price
        elif new_qty == 0:
            cost_basis[symbol] = 0.0
        # else: basis unchanged for the residual original position.

    positions[symbol] = new_qty
    cash -= signed_qty * price
    return cash, realised


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def replay_execution_events(
    events: Iterable[ExecutionEvent],
    starting_cash: float = 0.0,
) -> ExecutionReplayState:
    """Replay ``events`` deterministically and return the final state."""

    if starting_cash != starting_cash:  # NaN guard
        raise ValueError("starting_cash must be a finite float")

    orders: Dict[str, OrderStateRecord] = {}
    positions: Dict[str, float] = {}
    cost_basis: Dict[str, float] = {}
    cash = float(starting_cash)
    realised = 0.0
    commissions = 0.0
    warnings: List[str] = []
    unknown_external_fills = 0

    for ev in events:
        record = orders.get(ev.order_id)
        new_record, transition = reduce_order_state(record, ev)
        orders[ev.order_id] = new_record
        if not transition.accepted:
            # Reducer rejected the event (duplicate or invalid). Skip the
            # cash/position effect to avoid double-counting and surface
            # the diagnostic so the caller can audit.
            warnings.append(
                f"reducer rejected event {ev.event_id} ({ev.event_type.value}): "
                f"{transition.note}"
            )
            continue

        if ev.event_type in (EventType.FILL, EventType.PARTIAL_FILL):
            qty = float(ev.payload.get("qty", 0.0) or 0.0)
            price = float(ev.payload.get("price", 0.0) or 0.0)
            symbol = ev.symbol or new_record.symbol
            if qty <= 0:
                warnings.append(
                    f"fill event {ev.event_id} has non-positive qty {qty}; ignored"
                )
                continue
            if not symbol:
                warnings.append(
                    f"fill event {ev.event_id} has empty symbol; ignored"
                )
                continue
            side = _resolve_side(ev, new_record)
            if side == 0:
                warnings.append(
                    f"fill event {ev.event_id} has unknown side; assumed buy"
                )
                side = 1
            cash, realised = _apply_fill(
                positions, cost_basis, cash, realised,
                symbol, side, qty, price,
            )

        elif ev.event_type is EventType.COMMISSION:
            amount = float(ev.payload.get("amount", 0.0) or 0.0)
            commissions += amount
            cash -= amount

        elif ev.event_type is EventType.UNKNOWN_FILL:
            unknown_external_fills += 1
            warnings.append(
                f"unknown_external_fill recorded for order {ev.order_id} "
                f"(event {ev.event_id})"
            )

    if unknown_external_fills:
        warnings.append(
            f"total unknown_external_fills={unknown_external_fills}"
        )

    open_orders = sum(
        1 for rec in orders.values() if rec.state not in _TERMINAL_STATES
    )

    return ExecutionReplayState(
        orders=dict(orders),
        positions={k: v for k, v in positions.items() if v != 0.0},
        cash=cash,
        realised_pnl=realised,
        commissions=commissions,
        open_orders=open_orders,
        warnings=tuple(warnings),
    )


__all__ = ["ExecutionReplayState", "replay_execution_events"]
