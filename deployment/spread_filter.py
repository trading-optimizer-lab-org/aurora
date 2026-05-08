"""Spread protection filter (R119).

Pause trading when the live bid-ask spread exceeds a configured
multiple of the average spread for the symbol. Cheap defence against
thin-market lockups and pre-market quote anomalies.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional


@dataclass
class SpreadFilterConfig:
    """Knobs for the spread filter.

    Attributes:
        max_multiple_over_avg: trip when current spread exceeds
            ``max_multiple_over_avg * average_spread``. Default 3.0.
        min_observations: require at least this many bid-ask
            observations before any decision. Default 30.
        ema_alpha: exponential moving average weight for the rolling
            average. Default 0.1 (favours recent data without
            ignoring older).
    """

    max_multiple_over_avg: float = 3.0
    min_observations: int = 30
    ema_alpha: float = 0.1


@dataclass
class SpreadFilter:
    """Per-symbol spread filter."""

    config: SpreadFilterConfig
    _ema: Dict[str, float] = field(default_factory=dict)
    _counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def observe(self, symbol: str, bid: float, ask: float) -> float:
        """Record one bid / ask observation. Return updated EMA."""
        if ask <= 0 or bid <= 0 or ask < bid:
            raise ValueError(
                f"invalid quote for {symbol}: bid={bid} ask={ask}"
            )
        spread = (ask - bid) / ((ask + bid) / 2.0)
        prev = self._ema.get(symbol)
        a = self.config.ema_alpha
        self._ema[symbol] = (
            spread if prev is None else a * spread + (1 - a) * prev
        )
        self._counts[symbol] += 1
        return self._ema[symbol]

    def is_blocked(self, symbol: str, current_spread: float) -> bool:
        """True iff ``current_spread`` exceeds the trip multiple."""
        if self._counts.get(symbol, 0) < self.config.min_observations:
            return False
        avg = self._ema.get(symbol, 0.0)
        if avg <= 0.0:
            return False
        return current_spread >= self.config.max_multiple_over_avg * avg

    def average(self, symbol: str) -> Optional[float]:
        return self._ema.get(symbol)


__all__ = [
    "SpreadFilterConfig",
    "SpreadFilter",
]
