"""Rule IR -- AST-like nodes for the visual rule editor (R78)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple, Union


class ComparisonOp(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"


class LogicalOp(str, Enum):
    AND = "and"
    OR = "or"
    NOT = "not"


class ActionKind(str, Enum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"


@dataclass(frozen=True)
class PriceRef:
    """Reference to the closing price of the input series."""

    field: str = "close"


@dataclass(frozen=True)
class Indicator:
    """Indicator expression: name + parameters.

    Example: ``Indicator(name="RSI", args=(14,))`` -> RSI(14).
    """

    name: str
    args: Tuple[float, ...] = field(default_factory=tuple)


# A "value" expression yields a per-bar number when compiled.
ValueExpr = Union[Indicator, PriceRef, float]


@dataclass(frozen=True)
class Comparator:
    """Compare a value expression to a threshold or to another value."""

    left: ValueExpr
    op: ComparisonOp
    right: ValueExpr


# A "boolean" expression yields a per-bar truth array when compiled.
BoolExpr = Union[Comparator, "Logical"]


@dataclass(frozen=True)
class Logical:
    """Logical combination of boolean sub-expressions."""

    op: LogicalOp
    operands: Tuple[BoolExpr, ...]


@dataclass(frozen=True)
class Action:
    """What to emit when a condition is true."""

    kind: ActionKind


@dataclass(frozen=True)
class Rule:
    """One rule: when CONDITION fires, emit ACTION."""

    name: str
    condition: BoolExpr
    action: Action


__all__ = [
    "Action",
    "ActionKind",
    "BoolExpr",
    "Comparator",
    "ComparisonOp",
    "Indicator",
    "Logical",
    "LogicalOp",
    "PriceRef",
    "Rule",
    "ValueExpr",
]
