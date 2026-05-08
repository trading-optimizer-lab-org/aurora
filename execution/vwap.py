"""Volume-weighted average price (VWAP) execution algorithm.

Splits parent quantity proportionally to a historical intraday volume
curve. Each bucket gets ``parent_qty * vol_share[i]`` shares scheduled at
the bucket center.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class VWAPConfig:
    """Configuration for :class:`VWAPAlgo`."""
    side: str = "buy"
    min_slice_qty: float = 1.0
    smooth_alpha: float = 0.0  # 0 = no smoothing; >0 = EMA blend with uniform

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if not (0.0 <= self.smooth_alpha <= 1.0):
            raise ValueError("smooth_alpha must be in [0, 1]")


@dataclass
class VWAPSchedule:
    """A scheduled child order produced by :class:`VWAPAlgo`."""
    slice_index: int
    scheduled_at: datetime
    qty: float
    side: str
    parent_qty: float
    vol_share: float


class VWAPAlgo:
    """Volume-weighted average price scheduler.

    Parameters
    ----------
    volume_curve
        Sequence of non-negative numbers describing historical volume
        per bucket. They are normalized to sum to 1.
    config
        :class:`VWAPConfig`.
    """

    def __init__(
        self,
        volume_curve: Sequence[float],
        config: Optional[VWAPConfig] = None,
    ):
        if len(volume_curve) == 0:
            raise ValueError("volume_curve must not be empty")
        arr = np.asarray(volume_curve, dtype=float)
        if np.any(arr < 0):
            raise ValueError("volume_curve must be non-negative")
        if arr.sum() <= 0:
            raise ValueError("volume_curve sum must be > 0")
        self.config = config or VWAPConfig()
        if self.config.smooth_alpha > 0:
            uniform = np.ones_like(arr) / len(arr)
            arr = (1 - self.config.smooth_alpha) * arr / arr.sum() + (
                self.config.smooth_alpha * uniform
            )
        else:
            arr = arr / arr.sum()
        self.volume_share = arr

    def schedule(
        self,
        parent_qty: float,
        start: datetime,
        end: datetime,
    ) -> List[VWAPSchedule]:
        """Allocate ``parent_qty`` proportionally to the volume curve."""
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        if end <= start:
            raise ValueError("end must be > start")

        n = len(self.volume_share)
        total_seconds = (end - start).total_seconds()
        step = total_seconds / n
        slices: List[VWAPSchedule] = []
        cumulative = 0.0
        for i, share in enumerate(self.volume_share):
            offset = step * i + step / 2.0
            ts = start + timedelta(seconds=offset)
            qty = parent_qty * share
            if i == n - 1:
                # absorb rounding error
                qty = parent_qty - cumulative
            cumulative += qty
            qty = max(self.config.min_slice_qty, qty) if qty > 0 else qty
            slices.append(
                VWAPSchedule(
                    slice_index=i,
                    scheduled_at=ts,
                    qty=qty,
                    side=self.config.side,
                    parent_qty=parent_qty,
                    vol_share=float(share),
                )
            )
        return slices

    def execute(self, schedule: List[VWAPSchedule], broker) -> List[dict]:
        """Submit each scheduled slice via ``broker.submit_order``."""
        results = []
        for s in schedule:
            order = {
                "symbol": getattr(broker, "symbol", "TEST"),
                "qty": s.qty,
                "side": s.side,
                "order_type": "market",
                "scheduled_at": s.scheduled_at,
                "vol_share": s.vol_share,
            }
            res = broker.submit_order(order)
            results.append(res)
        return results
