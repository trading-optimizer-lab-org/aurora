"""Genetic-programming style strategy breeder.

Crosses two parent strategies into an offspring by:
  1. Mixing scalar parameters (uniform crossover with optional jitter).
  2. Splicing the parent signal-logic functions at the AST level — pick a
     random subtree from parent A's body and graft it into the matching
     position in parent B's body.

The AST layer uses the standard library ``ast`` module so there is no extra
dependency. Offspring are returned as compiled Python callables ready for
backtesting. This is intentionally simple (no semantic safety net beyond
parse/compile success); callers should still validate the offspring on a
holdout before promoting it.
"""
from __future__ import annotations

import ast
import random
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Strategy:
    """A breedable strategy: scalar params + a single-function source."""

    name: str
    params: dict
    source: str  # must define a function called ``signal(prices)``
    fn: Optional[Callable] = field(default=None, repr=False)

    def compile(self) -> Callable:
        if self.fn is not None:
            return self.fn
        ns: dict = {}
        exec(compile(self.source, f"<strategy:{self.name}>", "exec"), ns)
        if "signal" not in ns or not callable(ns["signal"]):
            raise ValueError(f"strategy {self.name!r} must define signal(prices)")
        self.fn = ns["signal"]
        return self.fn


def _function_def(tree: ast.Module, name: str = "signal") -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise ValueError(f"no function named {name!r} in source")


def _collect_statements(fn: ast.FunctionDef) -> list[ast.stmt]:
    return list(fn.body)


@dataclass
class StrategyBreeder:
    """Genetic-programming crossover for two parent strategies.

    Parameters
    ----------
    seed : int
        RNG seed for reproducible crossover.
    param_jitter : float
        Optional Gaussian jitter applied to averaged scalar params.
    """

    seed: int = 42
    param_jitter: float = 0.0
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _cross_params(self, a: dict, b: dict) -> dict:
        keys = set(a) | set(b)
        out: dict = {}
        for k in keys:
            va = a.get(k)
            vb = b.get(k)
            if va is None:
                out[k] = vb
            elif vb is None:
                out[k] = va
            elif isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                # uniform crossover: pick mean, optionally jitter
                m = (float(va) + float(vb)) / 2.0
                if self.param_jitter:
                    m += self._rng.gauss(0.0, self.param_jitter * abs(m or 1.0))
                out[k] = type(va)(m) if isinstance(va, int) else m
            else:
                out[k] = self._rng.choice([va, vb])
        return out

    def _cross_source(self, src_a: str, src_b: str) -> str:
        tree_a = ast.parse(src_a)
        tree_b = ast.parse(src_b)
        fn_a = _function_def(tree_a)
        fn_b = _function_def(tree_b)
        stmts_a = _collect_statements(fn_a)
        stmts_b = _collect_statements(fn_b)
        if not stmts_a or not stmts_b:
            raise ValueError("both parents must have at least one statement")

        # Pick a single statement index from B and splice it into A at the
        # same relative position. This is one of the simplest GP crossover
        # operators and keeps the offspring syntactically valid.
        idx_b = self._rng.randrange(len(stmts_b))
        idx_a = self._rng.randrange(len(stmts_a))
        new_body = list(stmts_a)
        new_body[idx_a] = stmts_b[idx_b]
        fn_a.body = new_body

        # ast.unparse is the canonical round-trip in 3.9+.
        return ast.unparse(tree_a)

    def breed(
        self,
        parent_a: Strategy,
        parent_b: Strategy,
        child_name: str = "offspring",
    ) -> Strategy:
        """Return a Strategy whose params and source mix both parents."""
        new_params = self._cross_params(parent_a.params, parent_b.params)
        try:
            new_src = self._cross_source(parent_a.source, parent_b.source)
        except SyntaxError as exc:  # pragma: no cover - parents already parsed
            raise ValueError(f"crossover produced invalid source: {exc}") from exc

        child = Strategy(name=child_name, params=new_params, source=new_src)
        # Sanity: must compile to a callable named ``signal``.
        child.compile()
        return child
