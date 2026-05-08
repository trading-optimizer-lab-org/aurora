"""Conditional asset rotation primitive (R113 + R115 + R116 + R118).

Symphony-style portfolio rules: ``IF condition THEN weights ELSE weights``.
Compiles to the per-asset weight contract the engine already consumes.

Pure-data IR. UI layer is out of scope (separate roadmap item if
needed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Group-based weighting (R115)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetGroup:
    """A named bucket of symbols and a per-bucket weight."""

    name: str
    symbols: List[str]
    weight: float = 1.0


def expand_groups(groups: List[AssetGroup]) -> Dict[str, float]:
    """Expand groups into a flat ``{symbol: weight}`` map.

    Each symbol receives ``group.weight / len(group.symbols)`` so the
    total weight per group equals ``group.weight``.
    """
    out: Dict[str, float] = {}
    for g in groups:
        if not g.symbols:
            continue
        per = g.weight / len(g.symbols)
        for sym in g.symbols:
            out[sym] = out.get(sym, 0.0) + per
    return out


# --------------------------------------------------------------------------
# Symphony rules (R113 + R116)
# --------------------------------------------------------------------------


# A condition is a callable that takes a snapshot dict and returns a bool.
Condition = Callable[[Dict[str, Any]], bool]


@dataclass(frozen=True)
class SymphonyRule:
    """One conditional branch in a symphony.

    Attributes:
        condition: callable returning True when this branch should fire.
        weights: ``{symbol: weight}`` to apply when the condition fires.
        cash_fraction: explicit cash hold (R116). Allocated to a "CASH"
            symbol that the engine treats as a no-position bucket.
        label: free-form name for logs and tearsheet.
    """

    condition: Condition
    weights: Dict[str, float]
    cash_fraction: float = 0.0
    label: str = ""


@dataclass
class Symphony:
    """A first-match-wins ladder of conditional rules with a default."""

    rules: List[SymphonyRule]
    default_weights: Dict[str, float] = field(default_factory=dict)
    default_cash_fraction: float = 0.0

    def evaluate(self, snapshot: Dict[str, Any]) -> Dict[str, float]:
        for rule in self.rules:
            try:
                fired = rule.condition(snapshot)
            except Exception:
                fired = False
            if fired:
                weights = dict(rule.weights)
                if rule.cash_fraction > 0:
                    weights["CASH"] = weights.get("CASH", 0.0) + rule.cash_fraction
                return weights
        weights = dict(self.default_weights)
        if self.default_cash_fraction > 0:
            weights["CASH"] = weights.get("CASH", 0.0) + self.default_cash_fraction
        return weights


# --------------------------------------------------------------------------
# Sector rotation primitive (R118)
# --------------------------------------------------------------------------


@dataclass
class SectorRotator:
    """Top-N rotator over a fixed universe.

    Args:
        universe: candidate symbols (e.g. SPDR sector ETFs).
        top_n: number of symbols to hold each rebalance.
        ranking_metric: callable taking a ``{symbol: value}`` mapping
            and returning a sorted ``[(symbol, score)]`` list with the
            preferred symbols first.
        equal_weight: when True, the top N hold equal weight; when
            False, weights are proportional to score above zero.
    """

    universe: List[str]
    top_n: int = 3
    ranking_metric: Callable[[Dict[str, float]], List[tuple[str, float]]] = field(
        default=lambda d: sorted(d.items(), key=lambda kv: kv[1], reverse=True)
    )
    equal_weight: bool = True

    def select(self, scores: Dict[str, float]) -> Dict[str, float]:
        ranked = self.ranking_metric(scores)
        chosen = [(sym, score) for sym, score in ranked if sym in self.universe]
        chosen = chosen[: self.top_n]
        if not chosen:
            return {}
        if self.equal_weight:
            w = 1.0 / len(chosen)
            return {sym: w for sym, _ in chosen}
        positive = [(s, v) for s, v in chosen if v > 0]
        if not positive:
            return {}
        total = sum(v for _, v in positive)
        return {s: v / total for s, v in positive}


__all__ = [
    "AssetGroup",
    "expand_groups",
    "SymphonyRule",
    "Symphony",
    "SectorRotator",
]
