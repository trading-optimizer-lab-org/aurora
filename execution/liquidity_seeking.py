"""Liquidity-seeking algorithm.

Probes a list of venues. Each tick, queries available size and price at
each venue, ranks them, and routes child orders to the best venue(s)
until either ``parent_qty`` is filled or the algorithm runs out of
opportunities.

This is a deterministic ranking algorithm. No latency simulation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class VenueQuote:
    """Snapshot from one venue at one point in time."""
    venue: str
    side_size: float          # liquidity available on the side we want
    price: float              # quoted price
    fee_bps: float = 0.0      # exchange/maker fee, in bps


@dataclass(frozen=True)
class LiquiditySeekingConfig:
    """Configuration for :class:`LiquiditySeekingAlgo`."""
    side: str = "buy"
    max_venues_per_tick: int = 3
    min_venue_size: float = 1.0
    aggressive: bool = False  # if True, take all displayed liquidity at each venue

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.max_venues_per_tick < 1:
            raise ValueError("max_venues_per_tick must be >= 1")


@dataclass
class _Allocation:
    """One venue allocation produced at a single tick."""
    venue: str
    qty: float
    price: float
    effective_price: float


class LiquiditySeekingAlgo:
    """Routes order quantity to whichever venues display liquidity first."""

    def __init__(self, config: Optional[LiquiditySeekingConfig] = None):
        self.config = config or LiquiditySeekingConfig()

    def _effective_price(self, q: VenueQuote) -> float:
        sign = 1.0 if self.config.side == "buy" else -1.0
        return q.price * (1.0 + sign * q.fee_bps / 1e4)

    def schedule(
        self,
        parent_qty: float,
        venue_snapshots: Sequence[Sequence[VenueQuote]],
    ) -> List[List[_Allocation]]:
        """Plan allocations across a sequence of venue snapshots.

        ``venue_snapshots[t]`` is the list of venues observed at tick ``t``.
        Returns a list of per-tick allocations.
        """
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        cfg = self.config
        remaining = float(parent_qty)
        plan: List[List[_Allocation]] = []
        for snapshot in venue_snapshots:
            if remaining <= 0:
                plan.append([])
                continue
            # rank: best (cheapest for buy, richest for sell) effective price
            ranked = sorted(
                [v for v in snapshot if v.side_size >= cfg.min_venue_size],
                key=lambda q: (self._effective_price(q)
                               if cfg.side == "buy"
                               else -self._effective_price(q)),
            )[: cfg.max_venues_per_tick]
            allocations: List[_Allocation] = []
            for q in ranked:
                if remaining <= 0:
                    break
                take = q.side_size if cfg.aggressive else min(q.side_size, remaining)
                take = min(take, remaining)
                if take < cfg.min_venue_size:
                    continue
                eff = self._effective_price(q)
                allocations.append(
                    _Allocation(venue=q.venue, qty=float(take),
                                price=float(q.price),
                                effective_price=float(eff))
                )
                remaining -= take
            plan.append(allocations)
        return plan

    def execute(
        self,
        plan: Sequence[Sequence[_Allocation]],
        broker,
    ) -> List[dict]:
        """Submit each allocation in each tick's plan."""
        results = []
        for tick_idx, allocations in enumerate(plan):
            for alloc in allocations:
                order = {
                    "symbol": getattr(broker, "symbol", "TEST"),
                    "qty": alloc.qty,
                    "side": self.config.side,
                    "order_type": "limit",
                    "limit_price": alloc.price,
                    "venue": alloc.venue,
                    "tick": tick_idx,
                }
                results.append(broker.submit_order(order))
        return results
