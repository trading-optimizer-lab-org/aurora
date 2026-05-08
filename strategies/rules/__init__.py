"""Visual rule editor IR (R78).

Operators want to write `IF RSI(14) > 30 AND price > MA(50) THEN buy`
without learning Python. This package ships:

- the AST-like IR (:mod:`ir`),
- the compiler that turns the IR into a callable
  ``signals(prices)`` function (:mod:`compiler`),
- the YAML serialiser so rules round-trip through text files
  (:mod:`yaml_io`).

The UI is deliberately a separate roadmap item (deferred).
"""
from __future__ import annotations

from .compiler import compile_rule
from .ir import (
    Action,
    ActionKind,
    Comparator,
    ComparisonOp,
    Indicator,
    Logical,
    LogicalOp,
    PriceRef,
    Rule,
)
from .yaml_io import rule_from_yaml, rule_to_yaml


__all__ = [
    "Action",
    "ActionKind",
    "Comparator",
    "ComparisonOp",
    "Indicator",
    "Logical",
    "LogicalOp",
    "PriceRef",
    "Rule",
    "compile_rule",
    "rule_from_yaml",
    "rule_to_yaml",
]
