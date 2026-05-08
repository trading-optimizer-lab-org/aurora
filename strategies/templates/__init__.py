"""Strategy templates gallery (R87).

Curated starter strategies grouped by family. Each template ships
with:

- a one-page description in :file:`docs/STRATEGY_TEMPLATES.md`,
- a parameter cheat-sheet,
- a signal generator function callable from the engine.

Currently exposed:

- :func:`trend_following_ma_cross`
- :func:`mean_reversion_rsi`
- :func:`breakout_donchian`
"""
from __future__ import annotations

from .starters import (
    breakout_donchian,
    mean_reversion_rsi,
    trend_following_ma_cross,
)


__all__ = [
    "trend_following_ma_cross",
    "mean_reversion_rsi",
    "breakout_donchian",
]
