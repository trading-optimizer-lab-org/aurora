"""R170 -- Realistic fill models for paper / backtest sims.

The :class:`FillModel` protocol turns an idealised ``OrderRequest``
into a deterministic stream of :class:`ExecutionEvent` records that
respect spread, latency, partial fills, rejects, tick size, minimum lot
size and a maximum participation cap on bar volume.

All randomness is controlled by an explicit ``seed``; the same seed and
the same ``FillModelInput`` always produce the same ``FillModelOutput``.

The model intentionally does NOT replace the existing execution algos
under :mod:`aurora.execution` (TWAP, VWAP, POV, Almgren-Chriss, etc).
It sits one layer below: an algo decides how to slice an order and the
fill model decides what events the broker would have emitted for each
slice.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Mapping, Optional, Protocol, Tuple

from aurora.execution.events import EventType, ExecutionEvent


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


@dataclass(frozen=True)
class FillModelInput:
    """Idealised order request the model is asked to simulate."""

    order_id: str
    symbol: str
    side: str
    qty: float
    order_type: OrderType
    timestamp: str
    bid: float
    ask: float
    last_price: Optional[float] = None
    bar_volume: float = 0.0
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.order_id:
            raise ValueError("order_id must be non-empty")
        if not self.symbol:
            raise ValueError("symbol must be non-empty")
        if self.side.lower() not in {"buy", "sell"}:
            raise ValueError(f"side must be 'buy' or 'sell', got {self.side!r}")
        if self.qty <= 0:
            raise ValueError(f"qty must be positive, got {self.qty}")
        if self.bid < 0 or self.ask < 0:
            raise ValueError("bid/ask must be non-negative")
        if self.ask < self.bid:
            raise ValueError("ask must be >= bid")
        if not isinstance(self.order_type, OrderType):
            object.__setattr__(self, "order_type", OrderType(self.order_type))


@dataclass(frozen=True)
class FillModelOutput:
    """Deterministic outcome produced by a :class:`FillModel`."""

    events: Tuple[ExecutionEvent, ...]
    filled_qty: float
    avg_fill_price: float
    rejected: bool
    rejection_reason: str = ""
    seed: int = 0
    model_name: str = ""
    notes: Tuple[str, ...] = field(default_factory=tuple)


class FillModel(Protocol):
    """Pure simulator: ``simulate(input)`` -> ``FillModelOutput``."""

    def simulate(self, input: FillModelInput) -> FillModelOutput: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_seed(model_seed: int, order_id: str) -> int:
    """Mix a model-level seed with the order id so each order gets a
    stable but distinct PRNG stream. Pure, deterministic."""
    h = hashlib.sha256(f"{model_seed}|{order_id}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big", signed=False)


def _round_to_tick(price: float, tick_size: float, *, round_up: bool) -> float:
    if tick_size <= 0:
        return price
    n = price / tick_size
    rounded = math.ceil(n) if round_up else math.floor(n)
    return rounded * tick_size


def _round_qty_to_lot(qty: float, min_lot: float) -> float:
    if min_lot <= 0:
        return qty
    n = math.floor(qty / min_lot)
    return n * min_lot


# ---------------------------------------------------------------------------
# SpreadAwareFillModel
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpreadAwareFillModel:
    """Simple but realistic fill model.

    * Market orders cross the spread; buys hit ask, sells hit bid.
    * Limit orders only fill if the market touches the limit (ask <=
      limit for buys, bid >= limit for sells).
    * Partial fills happen with probability ``partial_fill_prob``; the
      filled fraction is drawn uniformly from ``[0.3, 0.95]``.
    * Rejects happen with probability ``reject_prob``.
    * Latency, tick size, minimum lot and max volume participation are
      enforced.
    """

    spread: float = 0.0
    latency_ms: float = 0.0
    partial_fill_prob: float = 0.0
    reject_prob: float = 0.0
    tick_size: float = 0.0
    min_lot: float = 0.0
    max_volume_participation: float = 1.0
    seed: int = 0
    model_name: str = "SpreadAwareFillModel"

    def __post_init__(self) -> None:
        if not (0.0 <= self.partial_fill_prob <= 1.0):
            raise ValueError("partial_fill_prob must be in [0,1]")
        if not (0.0 <= self.reject_prob <= 1.0):
            raise ValueError("reject_prob must be in [0,1]")
        if not (0.0 <= self.max_volume_participation <= 1.0):
            raise ValueError("max_volume_participation must be in [0,1]")
        if self.spread < 0:
            raise ValueError("spread must be non-negative")
        if self.tick_size < 0 or self.min_lot < 0 or self.latency_ms < 0:
            raise ValueError("tick_size / min_lot / latency_ms must be non-negative")

    def simulate(self, input: FillModelInput) -> FillModelOutput:
        rng = random.Random(_stable_seed(self.seed, input.order_id))
        notes: List[str] = []
        events: List[ExecutionEvent] = []
        side = input.side.lower()

        # Lot size gate -- before any randomness so the test surface is
        # easy to reason about.
        target_qty = _round_qty_to_lot(input.qty, self.min_lot)
        if target_qty <= 0:
            return _reject(
                input,
                seed=self.seed,
                model_name=self.model_name,
                reason=f"qty {input.qty} below min_lot {self.min_lot}",
                events=tuple(events),
            )

        # Volume participation cap -- also pre-randomness.
        if input.bar_volume > 0 and self.max_volume_participation > 0:
            cap = input.bar_volume * self.max_volume_participation
            if cap <= 0:
                return _reject(
                    input,
                    seed=self.seed,
                    model_name=self.model_name,
                    reason="max_volume_participation produces zero cap",
                    events=tuple(events),
                )
            if target_qty > cap:
                notes.append(
                    f"qty capped from {target_qty} to {cap} by participation"
                )
                target_qty = _round_qty_to_lot(cap, self.min_lot)
                if target_qty <= 0:
                    return _reject(
                        input,
                        seed=self.seed,
                        model_name=self.model_name,
                        reason="participation cap rounded qty to 0",
                        events=tuple(events),
                    )

        # Reject sample.
        if self.reject_prob > 0 and rng.random() < self.reject_prob:
            return _reject(
                input,
                seed=self.seed,
                model_name=self.model_name,
                reason="random reject sample",
                events=tuple(events),
            )

        # Effective quote with model spread overlay.
        bid = input.bid
        ask = input.ask
        if self.spread > 0:
            mid = (bid + ask) / 2 if (bid + ask) > 0 else max(bid, ask)
            bid = max(0.0, mid - self.spread / 2)
            ask = mid + self.spread / 2

        # Resolve fill price by order type.
        ref_price, can_fill, reject_reason = _resolve_price(
            input, bid=bid, ask=ask,
        )
        if not can_fill:
            return _reject(
                input,
                seed=self.seed,
                model_name=self.model_name,
                reason=reject_reason or "limit/stop did not trigger",
                events=tuple(events),
            )

        round_up = side == "buy"
        fill_price = _round_to_tick(ref_price, self.tick_size, round_up=round_up)

        # Decide partial vs full.
        do_partial = (
            self.partial_fill_prob > 0 and rng.random() < self.partial_fill_prob
        )
        filled_qty = target_qty
        if do_partial:
            frac = rng.uniform(0.3, 0.95)
            partial_qty = _round_qty_to_lot(target_qty * frac, self.min_lot)
            if partial_qty <= 0:
                # Partial would round to zero -- fall back to full fill.
                do_partial = False
            else:
                filled_qty = partial_qty

        # Build events.
        ack_ts = _shift_iso(input.timestamp, self.latency_ms)
        events.append(ExecutionEvent(
            event_id=f"{input.order_id}-ack",
            event_type=EventType.BROKER_ACK,
            order_id=input.order_id,
            timestamp=ack_ts,
            payload={
                "side": side,
                "requested_qty": input.qty,
                "latency_ms": self.latency_ms,
            },
            broker=self.model_name,
            symbol=input.symbol,
        ))

        fill_ts = _shift_iso(input.timestamp, self.latency_ms + 1.0)
        if do_partial:
            events.append(ExecutionEvent(
                event_id=f"{input.order_id}-partial",
                event_type=EventType.PARTIAL_FILL,
                order_id=input.order_id,
                timestamp=fill_ts,
                payload={
                    "side": side,
                    "qty": filled_qty,
                    "price": fill_price,
                    "requested_qty": input.qty,
                },
                broker=self.model_name,
                symbol=input.symbol,
            ))
        else:
            events.append(ExecutionEvent(
                event_id=f"{input.order_id}-fill",
                event_type=EventType.FILL,
                order_id=input.order_id,
                timestamp=fill_ts,
                payload={
                    "side": side,
                    "qty": filled_qty,
                    "price": fill_price,
                    "requested_qty": input.qty,
                },
                broker=self.model_name,
                symbol=input.symbol,
            ))

        return FillModelOutput(
            events=tuple(events),
            filled_qty=filled_qty,
            avg_fill_price=fill_price,
            rejected=False,
            seed=self.seed,
            model_name=self.model_name,
            notes=tuple(notes),
        )


def _resolve_price(
    input: FillModelInput, *, bid: float, ask: float,
) -> Tuple[float, bool, str]:
    side = input.side.lower()
    ot = input.order_type
    if ot is OrderType.MARKET:
        return (ask if side == "buy" else bid), True, ""

    if ot is OrderType.LIMIT:
        if input.limit_price is None:
            return 0.0, False, "limit order requires limit_price"
        if side == "buy" and ask <= input.limit_price:
            return min(ask, input.limit_price), True, ""
        if side == "sell" and bid >= input.limit_price:
            return max(bid, input.limit_price), True, ""
        return 0.0, False, "limit not crossed"

    if ot is OrderType.STOP:
        if input.stop_price is None:
            return 0.0, False, "stop order requires stop_price"
        last = input.last_price if input.last_price is not None else (
            ask if side == "buy" else bid
        )
        triggered = (
            (side == "buy" and last >= input.stop_price)
            or (side == "sell" and last <= input.stop_price)
        )
        if not triggered:
            return 0.0, False, "stop not triggered"
        return (ask if side == "buy" else bid), True, ""

    if ot is OrderType.STOP_LIMIT:
        if input.stop_price is None or input.limit_price is None:
            return 0.0, False, "stop_limit order requires stop_price and limit_price"
        last = input.last_price if input.last_price is not None else (
            ask if side == "buy" else bid
        )
        triggered = (
            (side == "buy" and last >= input.stop_price)
            or (side == "sell" and last <= input.stop_price)
        )
        if not triggered:
            return 0.0, False, "stop_limit not triggered"
        if side == "buy" and ask <= input.limit_price:
            return min(ask, input.limit_price), True, ""
        if side == "sell" and bid >= input.limit_price:
            return max(bid, input.limit_price), True, ""
        return 0.0, False, "stop_limit triggered but limit not crossed"

    return 0.0, False, f"unsupported order_type {ot!r}"


def _reject(
    input: FillModelInput,
    *,
    seed: int,
    model_name: str,
    reason: str,
    events: Tuple[ExecutionEvent, ...],
) -> FillModelOutput:
    rejected_event = ExecutionEvent(
        event_id=f"{input.order_id}-reject",
        event_type=EventType.REJECTED,
        order_id=input.order_id,
        timestamp=input.timestamp,
        payload={
            "side": input.side.lower(),
            "requested_qty": input.qty,
            "reason": reason,
        },
        broker=model_name,
        symbol=input.symbol,
    )
    return FillModelOutput(
        events=events + (rejected_event,),
        filled_qty=0.0,
        avg_fill_price=0.0,
        rejected=True,
        rejection_reason=reason,
        seed=seed,
        model_name=model_name,
    )


def _shift_iso(timestamp: str, ms: float) -> str:
    """Shift an ISO timestamp by ``ms`` milliseconds, best-effort.

    If parsing fails we fall back to ``f"{timestamp}+{ms}ms"`` so the
    caller still gets a deterministic, distinguishable string.
    """
    try:
        from datetime import datetime, timedelta
        ts = datetime.fromisoformat(timestamp)
        shifted = ts + timedelta(milliseconds=ms)
        return shifted.isoformat()
    except (ValueError, TypeError):
        return f"{timestamp}+{ms}ms"


# ---------------------------------------------------------------------------
# Helper: drive a sequence of orders through a model
# ---------------------------------------------------------------------------


def apply_fill_model(
    orders: Iterable[FillModelInput],
    model: FillModel,
) -> List[ExecutionEvent]:
    """Run each order through ``model.simulate`` and concatenate events."""
    out: List[ExecutionEvent] = []
    for order in orders:
        if not isinstance(order, FillModelInput):
            raise ValueError(
                f"apply_fill_model expects FillModelInput, got {type(order)!r}"
            )
        result = model.simulate(order)
        out.extend(result.events)
    return out


__all__ = [
    "FillModel",
    "FillModelInput",
    "FillModelOutput",
    "OrderType",
    "SpreadAwareFillModel",
    "apply_fill_model",
]
