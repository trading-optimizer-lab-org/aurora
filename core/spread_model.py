"""Bid-ask spread stochastic model (R128).

Real spreads are regime-dependent: wider in vol spikes, in pre-open,
around news. This module models spread as a stochastic process keyed
off realised vol or session phase. Pluggable so the existing
constant-spread CostModel path stays as the default.

Two ready-to-use models:

- :class:`ConstantSpreadModel` -- baseline, matches today's behaviour.
- :class:`VolDrivenSpreadModel` -- spread = base * (1 + k * realised_vol_z).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class ConstantSpreadModel:
    """Spread independent of state. Same behaviour as CostModel.spread_bps."""

    spread_bps: float

    def spread_for(self, *, vol_z: float = 0.0) -> float:
        return float(self.spread_bps)


@dataclass(frozen=True)
class VolDrivenSpreadModel:
    """spread = base_bps * max(1 + sensitivity * vol_z, floor_multiplier).

    Args:
        base_bps: baseline spread when realised-vol z-score is zero.
        sensitivity: how much the spread widens per unit z.
        floor_multiplier: lower bound on the multiplier so spread
            never goes negative.
    """

    base_bps: float
    sensitivity: float = 0.5
    floor_multiplier: float = 0.5

    def spread_for(self, *, vol_z: float) -> float:
        mult = max(self.floor_multiplier, 1.0 + self.sensitivity * float(vol_z))
        return float(self.base_bps * mult)


def realised_vol_zscore(
    returns: np.ndarray,
    window: int = 20,
    long_window: int = 252,
) -> float:
    """Compute the latest realised-vol z-score vs a longer baseline."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) < window + 5:
        return 0.0
    recent = arr[-window:].std()
    long_ref = arr[-min(len(arr), long_window):]
    if len(long_ref) < 30:
        return 0.0
    long_std = long_ref.std()
    if long_std <= 1e-12:
        return 0.0
    return float((recent - long_std) / long_std)


__all__ = [
    "ConstantSpreadModel",
    "VolDrivenSpreadModel",
    "realised_vol_zscore",
]
