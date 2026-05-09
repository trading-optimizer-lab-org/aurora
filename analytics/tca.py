"""Transaction cost analysis (TCA) for replayed broker events.

Phase 3 -- Candidate A. ``compute_tca`` decomposes realised execution
into the pieces operators actually argue about:

* arrival price -- the mid at decision time;
* avg fill price -- volume-weighted across all fills for the order;
* effective spread (bps) -- 2 * |fill - mid_at_decision| / mid_at_decision;
* slippage (bps) -- (avg fill - arrival) / arrival, sign-aware so a
  buy filled above arrival has positive slippage and vice versa;
* delay cost (bps) -- (mid_at_decision - arrival) / arrival, the cost
  of waiting from "decide" to "send to market";
* opportunity cost (bps) -- (arrival - last_fill) * unfilled / total,
  approximating the cost of the unfilled residual at end-of-period;
* unfilled qty -- residual after walking all fills.

bps are basis points (1e4 multiplier). All values are floats; the
``total_cost_bps`` property sums slippage + delay + opportunity to
give a single-number summary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from aurora.execution.events import (
    BrokerEvent,
    OrderCreated,
    OrderFilled,
    OrderPartiallyFilled,
)


@dataclass(frozen=True)
class TCAResult:
    """Decomposed transaction-cost result for one order."""

    arrival_price: float
    avg_fill_price: float
    effective_spread_bps: float
    slippage_bps: float
    delay_cost_bps: float
    opportunity_cost_bps: float
    unfilled_qty: float
    total_qty: float

    @property
    def total_cost_bps(self) -> float:
        """Sum of slippage + delay + opportunity cost in basis points."""
        return float(
            self.slippage_bps + self.delay_cost_bps + self.opportunity_cost_bps
        )


def compute_tca(
    events: List[BrokerEvent],
    arrival_price: float,
    mid_at_decision: float,
) -> TCAResult:
    """Compute :class:`TCAResult` from an order's event stream.

    ``events`` is the slice of events for a single order id. ``events``
    that are not fills or the originating ``OrderCreated`` are ignored
    here -- they contribute to replay/reconciliation but not to TCA.

    The function never raises on empty input: an order with no fills
    yields zero average price, zero filled qty, all costs zero except
    opportunity cost which equals the full slippage from arrival.
    """
    arrival_price = float(arrival_price)
    mid_at_decision = float(mid_at_decision)
    if arrival_price <= 0:
        # Caller passed a degenerate arrival price; return all zeros so
        # downstream aggregations stay finite.
        return TCAResult(
            arrival_price=arrival_price,
            avg_fill_price=0.0,
            effective_spread_bps=0.0,
            slippage_bps=0.0,
            delay_cost_bps=0.0,
            opportunity_cost_bps=0.0,
            unfilled_qty=0.0,
            total_qty=0.0,
        )

    total_qty = 0.0
    total_notional = 0.0
    side: str = "buy"
    last_fill_price = arrival_price

    parent_qty = 0.0
    for ev in events:
        if isinstance(ev, OrderCreated):
            parent_qty = float(ev.qty)
            side = ev.side
            continue
        if isinstance(ev, (OrderPartiallyFilled, OrderFilled)):
            total_qty += float(ev.fill_qty)
            total_notional += float(ev.fill_qty) * float(ev.fill_price)
            last_fill_price = float(ev.fill_price)
            side = ev.side

    avg_fill = total_notional / total_qty if total_qty > 0 else 0.0
    unfilled = max(0.0, parent_qty - total_qty)

    # Sign convention: a buy filled above arrival means positive slippage
    # (cost). A sell filled below arrival is also positive slippage.
    sign = 1.0 if side == "buy" else -1.0
    slippage_bps = (
        ((avg_fill - arrival_price) / arrival_price) * sign * 1e4
        if total_qty > 0
        else 0.0
    )
    delay_cost_bps = ((mid_at_decision - arrival_price) / arrival_price) * sign * 1e4
    effective_spread_bps = (
        abs(avg_fill - mid_at_decision) / arrival_price * 2.0 * 1e4
        if total_qty > 0 and mid_at_decision > 0
        else 0.0
    )
    if parent_qty > 0 and unfilled > 0:
        opportunity_cost_bps = (
            ((last_fill_price - arrival_price) / arrival_price)
            * sign
            * 1e4
            * (unfilled / parent_qty)
        )
    else:
        opportunity_cost_bps = 0.0

    return TCAResult(
        arrival_price=arrival_price,
        avg_fill_price=avg_fill,
        effective_spread_bps=float(effective_spread_bps),
        slippage_bps=float(slippage_bps),
        delay_cost_bps=float(delay_cost_bps),
        opportunity_cost_bps=float(opportunity_cost_bps),
        unfilled_qty=float(unfilled),
        total_qty=float(total_qty),
    )


__all__ = ["TCAResult", "compute_tca"]
