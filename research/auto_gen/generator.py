"""Atomic-block strategy generator (R77 + R108).

Combines indicators (R86 block library) + comparators + logical
connectors into syntactically-valid candidate strategies.

Two generation modes:

- :class:`AtomicBlockGenerator` -- random sampling from the block
  pool. Plugs into the ``HypothesisGenerator`` protocol (factory +
  R10 auto-loop consume the output).
- :func:`combinatorial_pairs` -- exhaustive enumeration of all
  (block_a OP block_b) pairs for small block pools. Used when K is
  small enough that exhaustive search beats random.

Output: deterministic ``StrategySpec`` instances. Each generated
strategy is a single boolean entry rule + a stop-style exit:
``IF block_a OP block_b THEN long``. Wrapper-style strategies and
pattern-based strategies are out of scope here -- they ship as
separate generators that share the protocol.

Anti-lookahead is enforced at compute time: the indicator blocks
themselves never look ahead (R86 require_anti_lookahead helper);
the rule executes on already-computed indicator arrays.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from quantforge.research.factory.spec import StrategySpec
from quantforge.strategies.blocks.indicators import (
    STANDARD_REGISTRY,
    IndicatorBlock,
    IndicatorRegistry,
)


# --------------------------------------------------------------------------
# Comparator semantics
# --------------------------------------------------------------------------


class Comparator:
    """Comparator name registry."""

    GT = "gt"
    LT = "lt"
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"

    ALL = (GT, LT, CROSSES_ABOVE, CROSSES_BELOW)


def _apply_comparator(name: str, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Return the boolean signal series for the named comparator."""
    if name == Comparator.GT:
        return a > b
    if name == Comparator.LT:
        return a < b
    if name == Comparator.CROSSES_ABOVE:
        out = np.zeros_like(a, dtype=bool)
        out[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
        return out
    if name == Comparator.CROSSES_BELOW:
        out = np.zeros_like(a, dtype=bool)
        out[1:] = (a[1:] < b[1:]) & (a[:-1] >= b[:-1])
        return out
    raise ValueError(f"unknown comparator: {name!r}")


# --------------------------------------------------------------------------
# Generated rule
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockSpec:
    """A fully-specified indicator-block instance."""

    name: str
    params: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "params": dict(self.params)}


@dataclass(frozen=True)
class GeneratedRule:
    """A generated entry rule expressed as
    ``IF block_a OP block_b THEN long [ELSE flat]``.
    """

    block_a: BlockSpec
    comparator: str
    block_b: BlockSpec
    allow_short: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_a": self.block_a.to_dict(),
            "comparator": self.comparator,
            "block_b": self.block_b.to_dict(),
            "allow_short": bool(self.allow_short),
        }

    def stable_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")
        ).hexdigest()

    def signals(self, prices: pd.Series, registry: IndicatorRegistry) -> np.ndarray:
        a_block = registry.get(self.block_a.name)
        b_block = registry.get(self.block_b.name)
        a = np.asarray(a_block.compute(prices, **self.block_a.params), dtype=float)
        b = np.asarray(b_block.compute(prices, **self.block_b.params), dtype=float)
        long_sig = _apply_comparator(self.comparator, a, b)
        if not self.allow_short:
            return long_sig.astype(float)
        # Long when condition holds, short when inverse holds (where
        # well-defined: GT <-> LT, CROSSES_ABOVE <-> CROSSES_BELOW).
        if self.comparator == Comparator.GT:
            short_sig = a < b
        elif self.comparator == Comparator.LT:
            short_sig = a > b
        elif self.comparator == Comparator.CROSSES_ABOVE:
            short_sig = _apply_comparator(Comparator.CROSSES_BELOW, a, b)
        else:
            short_sig = _apply_comparator(Comparator.CROSSES_ABOVE, a, b)
        out = np.where(long_sig, 1.0, np.where(short_sig, -1.0, 0.0))
        return out.astype(float)


# --------------------------------------------------------------------------
# Generator
# --------------------------------------------------------------------------


@dataclass
class AtomicBlockGenerator:
    """Random sampler over the block library (R77).

    Implements the ``HypothesisGenerator`` protocol:

        name: str
        def generate(self, n: int, seed: int) -> list[StrategySpec]: ...
    """

    name: str = "atomic-block-generator"
    registry: IndicatorRegistry = field(default_factory=lambda: STANDARD_REGISTRY)
    block_names: Optional[List[str]] = None
    comparators: List[str] = field(default_factory=lambda: list(Comparator.ALL))
    universe: List[str] = field(default_factory=lambda: ["SPY"])
    rebalance: str = "1d"
    allow_short_prob: float = 0.30

    def _block_pool(self) -> List[str]:
        return self.block_names or self.registry.names()

    def _sample_block(self, rng: np.random.Generator) -> BlockSpec:
        pool = self._block_pool()
        name = pool[rng.integers(0, len(pool))]
        params = self.registry.get(name).sample_params(rng)
        return BlockSpec(name=name, params=params)

    def _sample_rule(self, rng: np.random.Generator) -> GeneratedRule:
        a = self._sample_block(rng)
        # Force the second block to differ in (name, params) so the rule
        # does not collapse to a constant.
        for _ in range(10):
            b = self._sample_block(rng)
            if (b.name, b.params) != (a.name, a.params):
                break
        comp = self.comparators[rng.integers(0, len(self.comparators))]
        allow_short = bool(rng.random() < self.allow_short_prob)
        return GeneratedRule(
            block_a=a, comparator=comp, block_b=b, allow_short=allow_short,
        )

    def generate(self, n: int, seed: int) -> List[StrategySpec]:
        rng = np.random.default_rng(seed)
        out: List[StrategySpec] = []
        for _ in range(n):
            rule = self._sample_rule(rng)
            spec = StrategySpec.make(
                name=f"AutoGen_{rule.stable_hash()[:8]}",
                hypothesis=(
                    f"Auto-generated atomic-block rule: "
                    f"{rule.block_a.name}({rule.block_a.params}) "
                    f"{rule.comparator} "
                    f"{rule.block_b.name}({rule.block_b.params})"
                ),
                strategy_class="quantforge.research.auto_gen.generator.GeneratedRule",
                params=rule.to_dict(),
                expected_edge_bps=0.0,
                regime_dependence=[],
                failure_modes=["overfit", "regime_specific"],
                universe=list(self.universe),
                rebalance=self.rebalance,
                generator=self.name,
            )
            out.append(spec)
        return out


# --------------------------------------------------------------------------
# Combinatorial helper (R108)
# --------------------------------------------------------------------------


def combinatorial_pairs(
    registry: IndicatorRegistry,
    block_names: List[str],
    comparators: Optional[List[str]] = None,
) -> Iterable[GeneratedRule]:
    """Yield every (block_a, comparator, block_b) combination over the
    given block names with each block sampled at its parameter midpoint.

    Useful when the block pool is small enough (< 10) that exhaustive
    enumeration beats random search.
    """
    comps = list(comparators or Comparator.ALL)
    for a_name, b_name in combinations(block_names, 2):
        a_block = registry.get(a_name)
        b_block = registry.get(b_name)
        a_params = {n: (r.low + r.high) / 2 for n, r in a_block.params.items()}
        b_params = {n: (r.low + r.high) / 2 for n, r in b_block.params.items()}
        for ap in a_block.params:
            if a_block.params[ap].is_integer:
                a_params[ap] = int(a_params[ap])
        for bp in b_block.params:
            if b_block.params[bp].is_integer:
                b_params[bp] = int(b_params[bp])
        for comp in comps:
            yield GeneratedRule(
                block_a=BlockSpec(name=a_name, params=a_params),
                comparator=comp,
                block_b=BlockSpec(name=b_name, params=b_params),
            )


__all__ = [
    "Comparator",
    "BlockSpec",
    "GeneratedRule",
    "AtomicBlockGenerator",
    "combinatorial_pairs",
]
