"""Chart pattern recognition (R79).

Detect chart patterns and emit standard signals arrays. Pairs with
R77 atomic-block generator so generated strategies can use a "pattern
detected" precondition block.

Currently exposed:

- :func:`detect_double_bottom`
- :func:`detect_double_top`
- :func:`detect_breakout_high`
- :func:`detect_breakout_low`

Each detector returns a boolean array aligned to the price input;
True bars indicate the pattern fired on that bar's close.
"""
from __future__ import annotations

from .detectors import (
    detect_breakout_high,
    detect_breakout_low,
    detect_double_bottom,
    detect_double_top,
)


__all__ = [
    "detect_double_bottom",
    "detect_double_top",
    "detect_breakout_high",
    "detect_breakout_low",
]
