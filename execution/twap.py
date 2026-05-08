"""Time-weighted average price (TWAP) execution algorithm.

Splits a parent order into ``n_slices`` equal child orders evenly spaced
across ``[start, end]``. Optionally applies uniform jitter (in seconds) to
each slice to obscure the schedule from market participants.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np


@dataclass(frozen=True)
class TWAPConfig:
    """Configuration for :class:`TWAPAlgo`."""
    n_slices: int = 10
    jitter_seconds: float = 0.0
    side: str = "buy"  # "buy" or "sell"
    min_slice_qty: float = 1.0

    def __post_init__(self):
        if self.n_slices <= 0:
            raise ValueError("n_slices must be > 0")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds must be >= 0")


@dataclass
class TWAPSchedule:
    """A scheduled child order produced by :class:`TWAPAlgo`."""
    slice_index: int
    scheduled_at: datetime
    qty: float
    side: str
    parent_qty: float


class TWAPAlgo:
    """Time-weighted average price scheduler."""

    def __init__(self, config: Optional[TWAPConfig] = None):
        self.config = config or TWAPConfig()

    def schedule(
        self,
        parent_qty: float,
        start: datetime,
        end: datetime,
        rng: Optional[np.random.Generator] = None,
    ) -> List[TWAPSchedule]:
        """Build ``n_slices`` evenly-spaced child orders."""
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        if end <= start:
            raise ValueError("end must be > start")

        cfg = self.config
        rng = rng or np.random.default_rng(0)
        total_seconds = (end - start).total_seconds()
        step = total_seconds / cfg.n_slices

        # Slice quantities: split evenly, push residual into final slice
        base_qty = parent_qty / cfg.n_slices
        slices: List[TWAPSchedule] = []
        for i in range(cfg.n_slices):
            offset = step * i + step / 2.0
            if cfg.jitter_seconds > 0:
                offset += rng.uniform(-cfg.jitter_seconds, cfg.jitter_seconds)
                offset = max(0.0, min(total_seconds, offset))
            ts = start + timedelta(seconds=offset)
            qty = base_qty
            if i == cfg.n_slices - 1:
                qty = parent_qty - base_qty * (cfg.n_slices - 1)
            qty = max(cfg.min_slice_qty, qty) if qty > 0 else qty
            slices.append(
                TWAPSchedule(
                    slice_index=i,
                    scheduled_at=ts,
                    qty=qty,
                    side=cfg.side,
                    parent_qty=parent_qty,
                )
            )
        return slices

    def execute(self, schedule: List[TWAPSchedule], broker) -> List[dict]:
        """Send each slice to a broker-like object exposing ``submit_order``."""
        results = []
        for s in schedule:
            order = {
                "symbol": getattr(broker, "symbol", "TEST"),
                "qty": s.qty,
                "side": s.side,
                "order_type": "market",
                "scheduled_at": s.scheduled_at,
            }
            res = broker.submit_order(order)
            results.append(res)
        return results
