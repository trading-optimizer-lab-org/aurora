"""R170 -- Transaction Cost Analysis (TCA) report.

Decomposes the total cost of a fill stream against an arrival reference
into the standard components defined in Kissell & Glantz:

    * effective spread = 2 * |execution - midquote|
    * realised spread  = 2 * (execution - benchmark) * side
    * slippage         = (execution - arrival) * side * filled_qty
    * delay cost       = (arrival - decision) * side * filled_qty
                         (collapsed to slippage when decision is unknown)
    * opportunity cost = (benchmark - arrival) * side * unfilled_qty
    * unfilled qty
    * commissions
    * fees

The :class:`TCAReport` is a pure dataclass; the :func:`compute_tca`
function is deterministic in its inputs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, List, Mapping, Optional

from aurora.execution.events import EventType, ExecutionEvent


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TCAReport:
    arrival_price: float
    execution_price: float
    benchmark_price: float
    effective_spread: float
    realised_spread: float
    slippage: float
    delay_cost: float
    opportunity_cost: float
    unfilled_qty: float
    requested_qty: float
    filled_qty: float
    commissions: float
    fees: float
    side: str = "buy"

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        rows: List[tuple[str, str]] = [
            ("side", self.side),
            ("requested_qty", _fmt(self.requested_qty)),
            ("filled_qty", _fmt(self.filled_qty)),
            ("unfilled_qty", _fmt(self.unfilled_qty)),
            ("arrival_price", _fmt(self.arrival_price)),
            ("execution_price", _fmt(self.execution_price)),
            ("benchmark_price", _fmt(self.benchmark_price)),
            ("effective_spread", _fmt(self.effective_spread)),
            ("realised_spread", _fmt(self.realised_spread)),
            ("slippage", _fmt(self.slippage)),
            ("delay_cost", _fmt(self.delay_cost)),
            ("opportunity_cost", _fmt(self.opportunity_cost)),
            ("commissions", _fmt(self.commissions)),
            ("fees", _fmt(self.fees)),
        ]
        lines = ["| metric | value |", "|---|---|"]
        for k, v in rows:
            lines.append(f"| {k} | {v} |")
        return "\n".join(lines)


def _fmt(x: float) -> str:
    if x == int(x):
        return f"{int(x)}"
    return f"{x:.6f}"


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def compute_tca(
    events: Iterable[ExecutionEvent],
    arrival_price: float,
    benchmark_price: float,
    requested_qty: float,
    *,
    side: Optional[str] = None,
    decision_price: Optional[float] = None,
    fees: float = 0.0,
) -> TCAReport:
    """Compute TCA against a single benchmark.

    Parameters
    ----------
    events:
        The :class:`ExecutionEvent` sequence for the order(s) under
        review. ``FILL`` and ``PARTIAL_FILL`` contribute to fill metrics.
        ``COMMISSION`` events accumulate.
    arrival_price:
        Mid-quote at the moment the order arrived at the trader / venue.
    benchmark_price:
        Reference price used for realised spread and opportunity cost.
        Often a post-trade VWAP or a midquote some seconds later.
    requested_qty:
        Total intended quantity, used to compute ``unfilled_qty``.
    side:
        ``"buy"`` or ``"sell"``. If omitted, inferred from the first fill
        payload or defaults to ``"buy"``.
    decision_price:
        Mid-quote at the original decision moment, before the order was
        sent. If supplied, ``delay_cost`` is computed against it; if not,
        ``delay_cost`` collapses to zero.
    fees:
        Optional venue fees (separate from commissions tracked via
        :class:`EventType.COMMISSION`).
    """

    if requested_qty <= 0:
        raise ValueError(f"requested_qty must be positive, got {requested_qty}")
    if arrival_price <= 0:
        raise ValueError(f"arrival_price must be positive, got {arrival_price}")
    if benchmark_price <= 0:
        raise ValueError(f"benchmark_price must be positive, got {benchmark_price}")

    fills: List[Mapping] = []
    commissions = 0.0
    inferred_side: Optional[str] = None

    for ev in events:
        if ev.event_type in (EventType.FILL, EventType.PARTIAL_FILL):
            qty = float(ev.payload.get("qty", 0.0) or 0.0)
            price = float(ev.payload.get("price", 0.0) or 0.0)
            if qty <= 0 or price <= 0:
                continue
            fills.append({"qty": qty, "price": price})
            if inferred_side is None:
                raw = ev.payload.get("side")
                if isinstance(raw, str) and raw.lower() in {"buy", "sell"}:
                    inferred_side = raw.lower()
        elif ev.event_type is EventType.COMMISSION:
            commissions += float(ev.payload.get("amount", 0.0) or 0.0)

    resolved_side = (side or inferred_side or "buy").lower()
    if resolved_side not in {"buy", "sell"}:
        raise ValueError(f"side must be 'buy' or 'sell', got {resolved_side!r}")
    sign = 1.0 if resolved_side == "buy" else -1.0

    filled_qty = sum(f["qty"] for f in fills)
    if filled_qty > 0:
        weighted = sum(f["qty"] * f["price"] for f in fills)
        execution_price = weighted / filled_qty
    else:
        execution_price = 0.0

    unfilled_qty = max(0.0, requested_qty - filled_qty)

    # Effective spread: 2 * |exec - midquote|. Use arrival as the midquote
    # proxy when no separate midquote is supplied.
    if execution_price > 0:
        effective_spread = 2.0 * abs(execution_price - arrival_price)
        realised_spread = 2.0 * (execution_price - benchmark_price) * sign
        slippage = (execution_price - arrival_price) * sign * filled_qty
    else:
        effective_spread = 0.0
        realised_spread = 0.0
        slippage = 0.0

    if decision_price is not None and decision_price > 0:
        delay_cost = (arrival_price - decision_price) * sign * filled_qty
    else:
        delay_cost = 0.0

    opportunity_cost = (benchmark_price - arrival_price) * sign * unfilled_qty

    return TCAReport(
        arrival_price=float(arrival_price),
        execution_price=float(execution_price),
        benchmark_price=float(benchmark_price),
        effective_spread=float(effective_spread),
        realised_spread=float(realised_spread),
        slippage=float(slippage),
        delay_cost=float(delay_cost),
        opportunity_cost=float(opportunity_cost),
        unfilled_qty=float(unfilled_qty),
        requested_qty=float(requested_qty),
        filled_qty=float(filled_qty),
        commissions=float(commissions),
        fees=float(fees),
        side=resolved_side,
    )


__all__ = ["TCAReport", "compute_tca"]
