"""Fill models for paper / simulation execution.

Phase 3 -- Candidate A. The :class:`FillModel` ABC enforces a single
``simulate_fill(order, market) -> FillResult`` surface so any algorithm
in :mod:`quantforge.execution` can swap between simple and adversarial
fill behaviours without touching its scheduling logic.

Concrete models cover the cases called out in the playbook:

* :class:`MarketOrderFillModel` -- mid +/- half-spread; refuses fill on
  zero-depth markets.
* :class:`LimitOrderFillModel` -- explicit fill probability based on
  price improvement, queue position and depth.
* :class:`PartialFillModel` -- slices the parent into ``n`` pieces
  governed by a participation rate.
* :class:`LatencyFillModel` -- delays the resulting fill by ``n`` bars.
* :class:`RejectingFillModel` -- rejects with probability ``p``.
* :class:`StaleQuoteFillModel` -- refuses to fill when the quote age is
  over ``max_quote_age_seconds``.

``order`` and ``market`` are loose dicts here: the broker / paper
simulator already speaks dicts, and the alternative (importing every
order-shape dataclass into this module) would create circular imports
with the existing schedulers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np


@dataclass(frozen=True)
class FillResult:
    """Outcome of a single ``simulate_fill`` call."""

    qty: float
    price: float
    accepted: bool
    reason: str = ""


def fill_probability(
    limit_price: float,
    mid: float,
    depth: float,
    queue_pos: float,
    side: str = "buy",
) -> float:
    """Return a probability in ``[0, 1]`` that a limit order fills.

    Heuristic:

    * Marketable orders (buy >= mid, sell <= mid) get full probability
      modulated by queue position.
    * Non-marketable orders fall off as the price gap grows; a deeper
      book and a closer queue position both raise the probability.
    """
    mid = float(mid)
    limit_price = float(limit_price)
    depth = max(float(depth), 0.0)
    queue_pos = max(float(queue_pos), 0.0)
    if mid <= 0:
        return 0.0
    if side == "buy":
        gap = (mid - limit_price) / mid
    elif side == "sell":
        gap = (limit_price - mid) / mid
    else:
        return 0.0
    # Marketable: gap <= 0 means the price crosses the spread.
    if gap <= 0:
        base = 1.0
    else:
        # Exponential decay scaled by depth. Larger depth -> faster decay
        # (more competition ahead of you).
        base = float(np.exp(-gap * (1.0 + depth)))
    queue_penalty = 1.0 / (1.0 + queue_pos)
    return float(max(0.0, min(1.0, base * queue_penalty)))


class FillModel(ABC):
    """Base class for all fill models."""

    @abstractmethod
    def simulate_fill(
        self, order: Dict[str, Any], market: Dict[str, Any]
    ) -> FillResult:
        """Return a :class:`FillResult` for ``order`` against ``market``."""


class MarketOrderFillModel(FillModel):
    """Crosses the spread; refuses if depth is zero."""

    def simulate_fill(
        self, order: Dict[str, Any], market: Dict[str, Any]
    ) -> FillResult:
        bid = float(market.get("bid", 0.0))
        ask = float(market.get("ask", 0.0))
        depth = float(market.get("depth", 0.0))
        side = str(order.get("side", "buy"))
        qty = float(order.get("qty", 0.0))
        if depth <= 0 or bid <= 0 or ask <= 0:
            return FillResult(qty=0.0, price=0.0, accepted=False, reason="no_liquidity")
        mid = 0.5 * (bid + ask)
        half_spread = 0.5 * (ask - bid)
        price = mid + half_spread if side == "buy" else mid - half_spread
        return FillResult(qty=qty, price=price, accepted=True, reason="market_full_fill")


class LimitOrderFillModel(FillModel):
    """Probabilistic limit fill; rejects when probability is below threshold."""

    def __init__(self, fill_threshold: float = 0.5) -> None:
        if not 0.0 <= fill_threshold <= 1.0:
            raise ValueError("fill_threshold must be in [0, 1]")
        self.fill_threshold = fill_threshold

    def simulate_fill(
        self, order: Dict[str, Any], market: Dict[str, Any]
    ) -> FillResult:
        bid = float(market.get("bid", 0.0))
        ask = float(market.get("ask", 0.0))
        depth = float(market.get("depth", 0.0))
        queue_pos = float(market.get("queue_pos", 0.0))
        side = str(order.get("side", "buy"))
        qty = float(order.get("qty", 0.0))
        limit_price = float(order.get("limit_price", 0.0))
        if bid <= 0 or ask <= 0 or limit_price <= 0:
            return FillResult(qty=0.0, price=0.0, accepted=False, reason="bad_quote")
        mid = 0.5 * (bid + ask)
        prob = fill_probability(limit_price, mid, depth, queue_pos, side)
        if prob < self.fill_threshold:
            return FillResult(
                qty=0.0,
                price=0.0,
                accepted=False,
                reason=f"low_fill_probability={prob:.3f}",
            )
        # Marketable side fills at the touch; non-marketable at limit.
        if side == "buy":
            price = ask if limit_price >= ask else limit_price
        else:
            price = bid if limit_price <= bid else limit_price
        return FillResult(qty=qty, price=price, accepted=True, reason="limit_fill")


class PartialFillModel(FillModel):
    """Splits the parent qty into ``slices`` chunks governed by participation."""

    def __init__(self, slices: int = 4, participation_rate: float = 0.1) -> None:
        if slices <= 0:
            raise ValueError("slices must be > 0")
        if not 0.0 < participation_rate <= 1.0:
            raise ValueError("participation_rate must be in (0, 1]")
        self.slices = slices
        self.participation_rate = participation_rate

    def simulate_fill(
        self, order: Dict[str, Any], market: Dict[str, Any]
    ) -> FillResult:
        qty = float(order.get("qty", 0.0))
        bar_volume = float(market.get("bar_volume", 0.0))
        bid = float(market.get("bid", 0.0))
        ask = float(market.get("ask", 0.0))
        side = str(order.get("side", "buy"))
        if qty <= 0 or bar_volume <= 0 or bid <= 0 or ask <= 0:
            return FillResult(qty=0.0, price=0.0, accepted=False, reason="no_liquidity")
        max_per_slice = bar_volume * self.participation_rate
        slice_qty = min(qty / self.slices, max_per_slice)
        mid = 0.5 * (bid + ask)
        half_spread = 0.5 * (ask - bid)
        price = mid + half_spread if side == "buy" else mid - half_spread
        return FillResult(
            qty=slice_qty, price=price, accepted=True, reason="partial_slice"
        )


class LatencyFillModel(FillModel):
    """Wraps another model and tags the result with a delay in bars."""

    def __init__(self, inner: FillModel, delay_bars: int = 1) -> None:
        if delay_bars < 0:
            raise ValueError("delay_bars must be >= 0")
        self.inner = inner
        self.delay_bars = delay_bars

    def simulate_fill(
        self, order: Dict[str, Any], market: Dict[str, Any]
    ) -> FillResult:
        result = self.inner.simulate_fill(order, market)
        if not result.accepted:
            return result
        # Replace reason to encode the delay; downstream replay can use
        # this reason string to schedule the fill on a later bar.
        return FillResult(
            qty=result.qty,
            price=result.price,
            accepted=True,
            reason=f"delayed_by={self.delay_bars}",
        )


class RejectingFillModel(FillModel):
    """Rejects ``p`` of the time; otherwise defers to ``inner``."""

    def __init__(
        self,
        inner: FillModel,
        reject_rate: float = 0.0,
        rng: Optional[np.random.Generator] = None,
    ) -> None:
        if not 0.0 <= reject_rate <= 1.0:
            raise ValueError("reject_rate must be in [0, 1]")
        self.inner = inner
        self.reject_rate = reject_rate
        self.rng = rng if rng is not None else np.random.default_rng(0)

    def simulate_fill(
        self, order: Dict[str, Any], market: Dict[str, Any]
    ) -> FillResult:
        if self.rng.random() < self.reject_rate:
            return FillResult(
                qty=0.0, price=0.0, accepted=False, reason="rejected_by_venue"
            )
        return self.inner.simulate_fill(order, market)


class StaleQuoteFillModel(FillModel):
    """Refuses the fill if the market quote is older than the threshold."""

    def __init__(
        self, inner: FillModel, max_quote_age_seconds: float = 1.0
    ) -> None:
        if max_quote_age_seconds < 0:
            raise ValueError("max_quote_age_seconds must be >= 0")
        self.inner = inner
        self.max_quote_age_seconds = max_quote_age_seconds

    def simulate_fill(
        self, order: Dict[str, Any], market: Dict[str, Any]
    ) -> FillResult:
        age = float(market.get("quote_age_seconds", 0.0))
        if age > self.max_quote_age_seconds:
            return FillResult(
                qty=0.0,
                price=0.0,
                accepted=False,
                reason=f"stale_quote age={age:.2f}s",
            )
        return self.inner.simulate_fill(order, market)


__all__ = [
    "FillResult",
    "FillModel",
    "MarketOrderFillModel",
    "LimitOrderFillModel",
    "PartialFillModel",
    "LatencyFillModel",
    "RejectingFillModel",
    "StaleQuoteFillModel",
    "fill_probability",
]
