"""Combinatorial alpha generation (R108).

Companion to R77 (random GA-style generation): exhaustively try every
combination of M signals from a pool of K, with a K-choose-M cap.
Falls back to R77 when the search space exceeds the cap.

Pairs with R105 (per-signal contribution) so per-combination
attribution flags signal-driven combos vs noise-driven combos.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Sequence


@dataclass(frozen=True)
class CombinatorialBudget:
    """Knobs for the combinatorial sweep."""

    max_combos: int = 5_000
    min_signals_per_combo: int = 2
    max_signals_per_combo: int = 4


@dataclass(frozen=True)
class GeneratedCombination:
    """One produced combination + its fitness."""

    signal_names: List[str]
    fitness: float


def enumerate_combinations(
    signal_names: Sequence[str],
    *,
    budget: CombinatorialBudget = CombinatorialBudget(),
) -> List[List[str]]:
    """Yield every M-of-K combination within the budget.

    Args:
        signal_names: pool of available signals.
        budget: caps on (combo size range, max combos enumerated).

    Returns:
        list of name-lists. The list is truncated when ``max_combos``
        is reached.
    """
    out: List[List[str]] = []
    for m in range(budget.min_signals_per_combo,
                   budget.max_signals_per_combo + 1):
        for combo in itertools.combinations(signal_names, m):
            if len(out) >= budget.max_combos:
                return out
            out.append(list(combo))
    return out


def evaluate_combinations(
    *,
    signals: Dict[str, "object"],
    budget: CombinatorialBudget,
    fitness_fn: Callable[[List[str]], float],
) -> List[GeneratedCombination]:
    """Evaluate ``fitness_fn`` for every in-budget combination.

    Args:
        signals: pool of signal_name -> signal payload (the payload is
            opaque to this module; ``fitness_fn`` knows how to consume
            it).
        budget: caps.
        fitness_fn: callable that takes a list of signal names and
            returns a scalar fitness. Caller wires this to the
            existing GA fitness function.

    Returns:
        list of :class:`GeneratedCombination` sorted by fitness desc.
    """
    combos = enumerate_combinations(list(signals.keys()), budget=budget)
    out: List[GeneratedCombination] = []
    for combo in combos:
        fitness = float(fitness_fn(combo))
        out.append(GeneratedCombination(signal_names=combo, fitness=fitness))
    out.sort(key=lambda c: c.fitness, reverse=True)
    return out


__all__ = [
    "CombinatorialBudget",
    "GeneratedCombination",
    "enumerate_combinations",
    "evaluate_combinations",
]
