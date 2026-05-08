"""Borrow availability simulation (R129).

Short-side trades may not be executable when borrow is unavailable
or rates spike. Model borrow availability as a Poisson on/off process
with HTB tagging.

Two primitives:

- :class:`BorrowAvailability` -- per-symbol stochastic toggle.
- :func:`apply_borrow_constraint` -- masks weight series where borrow
  was unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np


@dataclass(frozen=True)
class BorrowConfig:
    """Knobs for a per-symbol borrow availability process.

    Attributes:
        availability_rate: long-run probability the symbol is available
            for short. 0.95 = 95% of the time.
        rate_spike_prob: probability a symbol enters an HTB regime per
            bar (higher rates, possibly unavailable).
        htb_duration_bars: average HTB regime length (Poisson rate).
        htb_rate_multiplier: borrow-rate multiplier during HTB.
    """

    availability_rate: float = 0.95
    rate_spike_prob: float = 0.005
    htb_duration_bars: int = 20
    htb_rate_multiplier: float = 5.0


@dataclass
class BorrowAvailability:
    """Stochastic borrow availability over a period."""

    config: BorrowConfig
    seed: int = 42

    def simulate(self, n_bars: int) -> np.ndarray:
        """Return a boolean array: True iff borrow is available at bar i."""
        rng = np.random.default_rng(self.seed)
        out = np.ones(n_bars, dtype=bool)
        i = 0
        while i < n_bars:
            available = rng.random() < self.config.availability_rate
            if available:
                out[i] = True
                i += 1
            else:
                # Block: symbol unavailable for a Poisson-style burst.
                burst = max(1, int(rng.poisson(self.config.htb_duration_bars)))
                end = min(i + burst, n_bars)
                out[i:end] = False
                i = end
        return out


def apply_borrow_constraint(
    weights: np.ndarray,
    *,
    borrow_available: np.ndarray,
) -> np.ndarray:
    """Zero out short-side weights on bars where borrow is unavailable."""
    weights = np.asarray(weights, dtype=float)
    mask = np.asarray(borrow_available, dtype=bool)
    if len(weights) != len(mask):
        raise ValueError("weights and borrow_available length mismatch")
    out = weights.copy()
    short_mask = (out < 0) & ~mask
    out[short_mask] = 0.0
    return out


__all__ = [
    "BorrowConfig",
    "BorrowAvailability",
    "apply_borrow_constraint",
]
