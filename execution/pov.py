"""Percent-of-volume (POV) participation algorithm.

Targets a participation rate against realized market volume. Each step
sends ``min(remaining, observed_volume * rate)`` shares. Caps include
per-slice qty and overall remaining quantity.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class POVConfig:
    """Configuration for :class:`POVAlgo`."""
    target_rate: float = 0.10  # fraction of observed market volume
    side: str = "buy"
    max_slice_qty: float = 1e9
    min_slice_qty: float = 1.0

    def __post_init__(self):
        if not (0.0 < self.target_rate <= 1.0):
            raise ValueError("target_rate must be in (0, 1]")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")


@dataclass
class POVSchedule:
    """One bucket of a POV plan."""
    bucket_index: int
    timestamp: datetime
    market_volume: float
    qty: float
    side: str
    remaining_after: float


class POVAlgo:
    """Percent-of-volume scheduler.

    The schedule is data-driven: provide a sequence of (timestamp,
    market_volume) observations and the algorithm consumes them one at a
    time, slicing off ``rate * volume`` shares per bucket.
    """

    def __init__(self, config: Optional[POVConfig] = None):
        self.config = config or POVConfig()

    def schedule(
        self,
        parent_qty: float,
        market_volume: Sequence[tuple],
    ) -> List[POVSchedule]:
        """Build a participation schedule from observed market volume.

        Parameters
        ----------
        parent_qty
            Total quantity to execute.
        market_volume
            Iterable of ``(datetime, float)`` pairs giving observed
            volume per bucket.
        """
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        cfg = self.config
        remaining = float(parent_qty)
        out: List[POVSchedule] = []
        for i, (ts, vol) in enumerate(market_volume):
            if remaining <= 0:
                break
            if vol < 0:
                raise ValueError("market_volume must be non-negative")
            target = vol * cfg.target_rate
            qty = min(target, cfg.max_slice_qty, remaining)
            if qty < cfg.min_slice_qty and remaining > cfg.min_slice_qty:
                qty = 0.0  # skip this bucket — too small
            else:
                qty = max(qty, 0.0)
            if qty <= 0:
                continue
            remaining -= qty
            out.append(
                POVSchedule(
                    bucket_index=i,
                    timestamp=ts,
                    market_volume=float(vol),
                    qty=float(qty),
                    side=cfg.side,
                    remaining_after=float(max(remaining, 0.0)),
                )
            )
        return out

    def execute(self, schedule: List[POVSchedule], broker) -> List[dict]:
        """Submit every bucket's quantity through ``broker.submit_order``."""
        results = []
        for s in schedule:
            order = {
                "symbol": getattr(broker, "symbol", "TEST"),
                "qty": s.qty,
                "side": s.side,
                "order_type": "market",
                "timestamp": s.timestamp,
            }
            results.append(broker.submit_order(order))
        return results
