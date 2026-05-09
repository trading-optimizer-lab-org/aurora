"""Tests for quantforge.ml.genetic_programming."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

deap = pytest.importorskip("deap")

from aurora.ml.genetic_programming import (
    DEAP_AVAILABLE,
    GPConfig,
    GeneticFormulaEngine,
)


@pytest.fixture
def prices():
    rng = np.random.default_rng(0)
    n = 200
    rets = rng.normal(0.0005, 0.01, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"), name="p")


@pytest.fixture
def target(prices):
    # Make the target weakly tied to price level so GP has signal.
    return (np.log(prices) - np.log(prices).mean()).rename("t")


def test_engine_fit_returns_expression(prices, target):
    eng = GeneticFormulaEngine(GPConfig(population_size=20, n_generations=3))
    expr = eng.fit(prices, target)
    assert isinstance(expr, str)
    assert len(expr) > 0
    assert "x" in expr or any(op in expr for op in ("add", "sub", "mul"))


def test_predict_shape_matches_input(prices, target):
    eng = GeneticFormulaEngine(GPConfig(population_size=15, n_generations=2))
    eng.fit(prices, target)
    sig = eng.predict(prices)
    assert isinstance(sig, pd.Series)
    assert len(sig) == len(prices)
    assert sig.index.equals(prices.index)


def test_predict_before_fit_raises(prices):
    eng = GeneticFormulaEngine(GPConfig(population_size=10, n_generations=1))
    with pytest.raises(RuntimeError):
        eng.predict(prices)
    with pytest.raises(RuntimeError):
        eng.best_expression()


def test_fit_validates_input():
    eng = GeneticFormulaEngine(GPConfig(population_size=10, n_generations=1))
    with pytest.raises(TypeError):
        eng.fit([1, 2, 3], pd.Series([1, 2, 3]))
    with pytest.raises(TypeError):
        eng.fit(pd.Series([1, 2, 3]), [1, 2, 3])
    short = pd.Series(range(5), dtype=float)
    with pytest.raises(ValueError):
        eng.fit(short, short)


def test_two_engines_in_one_process_do_not_collide(prices, target):
    """DEAP creator state is global; ensure repeated fits succeed."""
    a = GeneticFormulaEngine(GPConfig(population_size=10, n_generations=1))
    b = GeneticFormulaEngine(GPConfig(population_size=10, n_generations=1))
    expr_a = a.fit(prices, target)
    expr_b = b.fit(prices, target)
    assert isinstance(expr_a, str)
    assert isinstance(expr_b, str)
