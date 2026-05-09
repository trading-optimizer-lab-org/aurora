"""Auto strategy generator (R77 + R108).

Combines indicator blocks (R86) + comparators + entry/exit rules into
candidate ``StrategySpec`` instances. Plugs into the
``HypothesisGenerator`` protocol consumed by R10 auto-loop and the
factory.
"""
from __future__ import annotations

from aurora.research.auto_gen.generator import (
    AtomicBlockGenerator,
    BlockSpec,
    Comparator,
    GeneratedRule,
    combinatorial_pairs,
)


__all__ = [
    "AtomicBlockGenerator",
    "BlockSpec",
    "Comparator",
    "GeneratedRule",
    "combinatorial_pairs",
]
