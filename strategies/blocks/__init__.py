"""Strategy building blocks (R86).

Catalogued, parameterised indicator library plus comparators / logical
connectors that R77 (auto-discovery generator), R78 (rule editor IR)
and R79 (pattern recognition) sample from.

Each indicator declares its parameter ranges and warmup window so a
random generator can sample valid configurations without producing
forward-looking strategies.

Public surface
--------------

- :class:`IndicatorBlock` -- frozen indicator definition.
- :class:`IndicatorRegistry` -- registry mapping names to blocks.
- :data:`STANDARD_REGISTRY` -- the canonical 17-indicator set.
"""
from __future__ import annotations

from aurora.strategies.blocks.indicators import (
    STANDARD_REGISTRY,
    IndicatorBlock,
    IndicatorRegistry,
    ParameterRange,
)


__all__ = [
    "IndicatorBlock",
    "IndicatorRegistry",
    "ParameterRange",
    "STANDARD_REGISTRY",
]
