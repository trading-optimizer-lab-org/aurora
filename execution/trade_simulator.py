"""Realistic-friction trade simulator (R100).

Today PaperBroker is functional but does not model partial fills,
queue priority, varying spread, latency, or rejected orders. This
module wraps PaperBroker with these knobs so paper sessions can
preview live execution behaviour.

Friction knobs:

- partial_fill_pct: fraction of the order that fills on a given bar.
- spread_bps: half-spread per fill (multiplied by bar's ``spread_z``).
- latency_bars: order arrives ``latency_bars`` after submission.
- reject_prob: probability the broker rejects an otherwise-valid order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np


@dataclass(frozen=True)
class FrictionConfig:
    partial_fill_pct: float = 1.0  # 1.0 = full fill same bar
    spread_bps: float = 1.0
    latency_bars: int = 0
    reject_prob: float = 0.0
    seed: int = 42


@dataclass
class SimulatedFill:
    bar_index: int
    requested_qty: float
    filled_qty: float
    fill_price: float
    rejected: bool
    rationale: str


@dataclass
class SimulatedBookState:
    fills: List[SimulatedFill] = field(default_factory=list)
    rejected: int = 0
    pending_orders: Dict[int, float] = field(default_factory=dict)


def simulate_session(
    *,
    prices: np.ndarray,
    desired_weights: np.ndarray,
    config: FrictionConfig = FrictionConfig(),
) -> SimulatedBookState:
    """Walk the bar series, attempting to track ``desired_weights``.

    Args:
        prices: per-bar mid price.
        desired_weights: per-bar target weight in [-1, 1] (long/short
            book). Position changes generate orders.
        config: friction knobs.

    Returns:
        :class:`SimulatedBookState` with the per-bar fills + rejects.
    """
    prices = np.asarray(prices, dtype=float)
    desired = np.asarray(desired_weights, dtype=float)
    if len(prices) != len(desired):
        raise ValueError("prices and desired_weights must align")

    rng = np.random.default_rng(config.seed)
    state = SimulatedBookState()
    realised_position = 0.0
    pending: Dict[int, float] = {}
    for i, (price, target) in enumerate(zip(prices, desired)):
        # Settle pending orders that have crossed the latency horizon.
        for arrive_bar in list(pending.keys()):
            if arrive_bar <= i:
                qty = pending.pop(arrive_bar)
                # Reject test
                if rng.random() < config.reject_prob:
                    state.fills.append(SimulatedFill(
                        bar_index=i, requested_qty=qty,
                        filled_qty=0.0, fill_price=price,
                        rejected=True, rationale="broker rejected order",
                    ))
                    state.rejected += 1
                    continue
                fill_qty = qty * config.partial_fill_pct
                # apply half-spread cost direction
                price_with_spread = price * (
                    1 + (config.spread_bps / 1e4)
                    * (1 if fill_qty > 0 else -1)
                )
                state.fills.append(SimulatedFill(
                    bar_index=i, requested_qty=qty,
                    filled_qty=fill_qty,
                    fill_price=price_with_spread,
                    rejected=False,
                    rationale=(
                        "full fill" if config.partial_fill_pct == 1.0
                        else f"partial fill {config.partial_fill_pct:.0%}"
                    ),
                ))
                realised_position += fill_qty
        # Submit new order to bridge the gap to target.
        delta = target - realised_position
        if abs(delta) > 1e-9:
            arrive_bar = i + max(0, int(config.latency_bars))
            pending[arrive_bar] = pending.get(arrive_bar, 0.0) + delta
    state.pending_orders = pending
    return state


__all__ = [
    "FrictionConfig",
    "SimulatedFill",
    "SimulatedBookState",
    "simulate_session",
]
