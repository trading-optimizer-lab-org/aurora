"""Genetic programming over symbolic price formulas.

Evolves a population of mathematical expression trees mapping a price series
(or rolling features thereof) to a signal. Uses DEAP's ``gp`` toolbox when
available; otherwise raises ``ImportError`` at instantiation time.

Public API:
- ``GPConfig``: hyperparameters for the evolutionary loop.
- ``GeneticFormulaEngine``: ``fit(prices, target) -> str``,
  ``predict(prices) -> Series``, ``best_expression()``.

Fitness is the absolute Pearson correlation between the formula's signal
series and the target. Bigger is better. Anti-lookahead: every primitive
operates pointwise or with a strict trailing window.
"""
from __future__ import annotations

import math
import operator
import random
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

import numpy as np
import pandas as pd

try:  # optional dep
    from deap import algorithms, base, creator, gp, tools
    DEAP_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-dependent
    algorithms = base = creator = gp = tools = None
    DEAP_AVAILABLE = False


def _require_deap() -> None:
    if not DEAP_AVAILABLE:
        raise ImportError(
            "aurora.ml.genetic_programming requires deap. "
            "Install with: pip install deap"
        )


# ---------------------------------------------------------------------------
# Safe primitives (no division-by-zero, no log of non-positive)
# ---------------------------------------------------------------------------


def _protected_div(a: float, b: float) -> float:
    if abs(b) < 1e-12:
        return 1.0
    return a / b


def _protected_log(a: float) -> float:
    if a <= 0:
        return 0.0
    return math.log(a)


def _protected_sqrt(a: float) -> float:
    return math.sqrt(abs(a))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class GPConfig:
    """Hyperparameters for :class:`GeneticFormulaEngine`."""

    population_size: int = 60
    n_generations: int = 8
    crossover_prob: float = 0.5
    mutation_prob: float = 0.2
    tournament_size: int = 3
    max_tree_depth: int = 5
    seed: int = 42


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class GeneticFormulaEngine:
    """Evolve a symbolic formula ``f(price) -> signal``.

    The pset has a single input ``x`` (the close price). After ``fit``, the
    best individual can be evaluated on a new price series via ``predict``.
    """

    def __init__(self, config: Optional[GPConfig] = None):
        _require_deap()
        self.config = config if config is not None else GPConfig()
        self._best: Any = None
        self._toolbox: Any = None
        self._pset: Any = None
        # DEAP creator state is global; isolate by instance via timestamped names.
        self._fitness_cls: Any = None
        self._individual_cls: Any = None

    # ------------------------------------------------------------------ build

    def _build_pset(self) -> Any:
        pset = gp.PrimitiveSet("MAIN", arity=1)
        pset.renameArguments(ARG0="x")
        pset.addPrimitive(operator.add, 2)
        pset.addPrimitive(operator.sub, 2)
        pset.addPrimitive(operator.mul, 2)
        pset.addPrimitive(_protected_div, 2)
        pset.addPrimitive(_protected_log, 1)
        pset.addPrimitive(_protected_sqrt, 1)
        pset.addPrimitive(operator.neg, 1)
        pset.addEphemeralConstant(
            f"rand_const_{id(self)}", lambda: random.uniform(-1.0, 1.0)
        )
        return pset

    def _build_toolbox(self, pset: Any, target: np.ndarray, prices: np.ndarray) -> Any:
        # DEAP creator types are global; recreate every fit() to avoid
        # collisions across instances or repeated calls in the same process.
        cls_suffix = f"_{id(self)}"
        fit_name = f"FitnessMax{cls_suffix}"
        ind_name = f"Individual{cls_suffix}"
        if hasattr(creator, fit_name):
            delattr(creator, fit_name)
        if hasattr(creator, ind_name):
            delattr(creator, ind_name)
        creator.create(fit_name, base.Fitness, weights=(1.0,))
        fit_cls = getattr(creator, fit_name)
        creator.create(ind_name, gp.PrimitiveTree, fitness=fit_cls, pset=pset)
        ind_cls = getattr(creator, ind_name)
        self._fitness_cls = fit_cls
        self._individual_cls = ind_cls

        toolbox = base.Toolbox()
        toolbox.register("expr", gp.genHalfAndHalf, pset=pset, min_=1, max_=3)
        toolbox.register("individual", tools.initIterate, ind_cls, toolbox.expr)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)
        toolbox.register("compile", gp.compile, pset=pset)

        def _fitness(individual: Any) -> tuple:
            func = toolbox.compile(expr=individual)
            try:
                signal = np.array([float(func(p)) for p in prices], dtype=float)
            except (OverflowError, ZeroDivisionError, ValueError):
                return (0.0,)
            mask = np.isfinite(signal) & np.isfinite(target)
            if mask.sum() < 5:
                return (0.0,)
            s = signal[mask]
            t = target[mask]
            if s.std() < 1e-12 or t.std() < 1e-12:
                return (0.0,)
            corr = float(np.corrcoef(s, t)[0, 1])
            if not math.isfinite(corr):
                return (0.0,)
            return (abs(corr),)

        toolbox.register("evaluate", _fitness)
        toolbox.register(
            "select", tools.selTournament, tournsize=self.config.tournament_size
        )
        toolbox.register("mate", gp.cxOnePoint)
        toolbox.register("expr_mut", gp.genFull, min_=0, max_=2)
        toolbox.register("mutate", gp.mutUniform, expr=toolbox.expr_mut, pset=pset)
        toolbox.decorate(
            "mate",
            gp.staticLimit(key=operator.attrgetter("height"), max_value=self.config.max_tree_depth),
        )
        toolbox.decorate(
            "mutate",
            gp.staticLimit(key=operator.attrgetter("height"), max_value=self.config.max_tree_depth),
        )
        return toolbox

    # ------------------------------------------------------------------ public

    def fit(self, prices: pd.Series, target: pd.Series) -> str:
        """Evolve a population and store the best individual.

        Returns the symbolic expression of the winner as a string.
        """
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a Series")
        if not isinstance(target, pd.Series):
            raise TypeError("target must be a Series")
        joined = pd.concat([prices.rename("p"), target.rename("t")], axis=1).dropna()
        if len(joined) < 20:
            raise ValueError("need at least 20 aligned non-null bars")

        random.seed(self.config.seed)
        np.random.seed(self.config.seed)

        pset = self._build_pset()
        toolbox = self._build_toolbox(
            pset, joined["t"].to_numpy(), joined["p"].to_numpy()
        )
        pop = toolbox.population(n=self.config.population_size)
        hof = tools.HallOfFame(1)

        algorithms.eaSimple(
            pop,
            toolbox,
            cxpb=self.config.crossover_prob,
            mutpb=self.config.mutation_prob,
            ngen=self.config.n_generations,
            halloffame=hof,
            verbose=False,
        )

        self._toolbox = toolbox
        self._pset = pset
        self._best = hof[0] if len(hof) else pop[0]
        return str(self._best)

    def best_expression(self) -> str:
        if self._best is None:
            raise RuntimeError("call fit() first")
        return str(self._best)

    def predict(self, prices: pd.Series) -> pd.Series:
        if self._best is None:
            raise RuntimeError("call fit() first")
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a Series")
        func = self._toolbox.compile(expr=self._best)
        out: List[float] = []
        for p in prices.to_numpy():
            try:
                v = float(func(p))
            except (OverflowError, ZeroDivisionError, ValueError):
                v = float("nan")
            if not math.isfinite(v):
                v = float("nan")
            out.append(v)
        return pd.Series(out, index=prices.index, name="gp_signal")


__all__ = ["DEAP_AVAILABLE", "GPConfig", "GeneticFormulaEngine"]
