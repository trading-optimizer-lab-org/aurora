"""Auto research loop (R10).

Schedules a periodic ``generate -> submit -> archive`` cycle on top of
:class:`quantforge.research.factory.ResearchFactory`. The loop is the
operational outer wrapper around the factory; it does not touch tier
gates, hash chains or audit logs directly.

Public surface::

    AutoResearchLoop, AutoLoopConfig, run_one_cycle
"""
from __future__ import annotations

from quantforge.research.auto_loop.loop import (
    AutoLoopConfig,
    AutoResearchLoop,
    CycleSummary,
    run_one_cycle,
)


__all__ = [
    "AutoLoopConfig",
    "AutoResearchLoop",
    "CycleSummary",
    "run_one_cycle",
]
