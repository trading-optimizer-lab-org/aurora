"""Vote-threshold ensemble combiner (R109).

Combine M sub-signals; emit ``+1`` only when at least X% agree on
long, ``-1`` when at least X% agree on short, ``0`` otherwise.
Pairs with R105 for contribution analysis and R98 for stability
scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

import numpy as np


@dataclass(frozen=True)
class VoteThresholdConfig:
    """Knobs for the vote ensemble."""

    long_threshold_pct: float = 0.60
    short_threshold_pct: float = 0.60
    abstain_when_split: bool = True


def vote_combine(
    signals: Dict[str, np.ndarray],
    *,
    config: Optional[VoteThresholdConfig] = None,
) -> np.ndarray:
    """Combine an arbitrary set of {-1, 0, +1} signals into one vector.

    Args:
        signals: dict of signal_name -> per-bar signal in {-1, 0, +1}.
        config: vote thresholds.

    Returns:
        per-bar combined signal in {-1, 0, +1}.
    """
    if config is None:
        config = VoteThresholdConfig()
    if not signals:
        raise ValueError("signals dict is empty")
    arr = np.vstack([np.asarray(v, dtype=float) for v in signals.values()])
    n_signals = arr.shape[0]
    if n_signals == 0:
        raise ValueError("no signal vectors supplied")

    long_votes = (arr > 0).sum(axis=0) / n_signals
    short_votes = (arr < 0).sum(axis=0) / n_signals

    long_emit = long_votes >= config.long_threshold_pct
    short_emit = short_votes >= config.short_threshold_pct

    out = np.zeros(arr.shape[1], dtype=float)
    out[long_emit] = 1.0
    out[short_emit] = -1.0
    if config.abstain_when_split:
        # Split = both conditions true (rare but possible if thresholds
        # sum to <= 1.0). Drop those bars.
        split = long_emit & short_emit
        out[split] = 0.0
    return out


__all__ = [
    "VoteThresholdConfig",
    "vote_combine",
]
