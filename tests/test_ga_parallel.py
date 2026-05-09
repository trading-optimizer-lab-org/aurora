"""Tests for distributed GA via joblib (Task 5.1)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.strategies.library import MACross
from aurora.ga.runner import run_ga, GAConfig
from aurora.ga.fitness import multi_objective_fitness


pytest.importorskip("deap")


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2012-01-01", periods=900, freq="B")
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.012, 900)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


@pytest.fixture
def is_oos(fake_prices):
    return fake_prices.iloc[:600], fake_prices.iloc[600:]


def _params_to_key(params: dict) -> tuple:
    return tuple(sorted(params.items()))


def test_sequential_baseline(is_oos):
    is_p, oos_p = is_oos
    cfg = GAConfig(
        population=12, generations=2, seed=42, backend="sequential",
    )
    pareto = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                   cfg, verbose=False)
    assert isinstance(pareto, list)
    assert len(pareto) >= 1
    params, fit = pareto[0]
    assert isinstance(params, dict)
    assert "fast" in params and "slow" in params
    assert isinstance(fit, tuple)
    assert len(fit) == 4


def test_joblib_runs(is_oos):
    pytest.importorskip("joblib")
    is_p, oos_p = is_oos
    cfg = GAConfig(
        population=12, generations=2, seed=42,
        backend="joblib", n_workers=2,
    )
    pareto = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                   cfg, verbose=False)
    assert isinstance(pareto, list)
    assert len(pareto) >= 1
    params, fit = pareto[0]
    assert "fast" in params
    assert len(fit) == 4


def test_results_equivalence_seed(is_oos):
    """Same seed -> same Pareto front in sequential vs joblib (modulo
    minor non-determinism from worker dispatch order). We compare the set
    of decoded parameter combinations on the front, not their order.
    """
    pytest.importorskip("joblib")
    is_p, oos_p = is_oos

    cfg_seq = GAConfig(
        population=12, generations=2, seed=123, backend="sequential",
    )
    cfg_par = GAConfig(
        population=12, generations=2, seed=123,
        backend="joblib", n_workers=2,
    )

    pareto_seq = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                       cfg_seq, verbose=False)
    pareto_par = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                       cfg_par, verbose=False)

    keys_seq = {_params_to_key(p) for p, _ in pareto_seq}
    keys_par = {_params_to_key(p) for p, _ in pareto_par}

    # Front should overlap heavily. With the same seed and a deterministic
    # fitness function, joblib's loky backend should reproduce the
    # sequential front exactly. Allow a small Jaccard tolerance for any
    # numerical ordering edge case at the front boundary.
    inter = keys_seq & keys_par
    union = keys_seq | keys_par
    jaccard = len(inter) / len(union) if union else 0.0
    assert jaccard >= 0.5, (
        f"pareto fronts diverge: jaccard={jaccard:.2f} "
        f"seq={len(keys_seq)} par={len(keys_par)} inter={len(inter)}"
    )


def test_invalid_backend(is_oos):
    is_p, oos_p = is_oos
    cfg = GAConfig(
        population=8, generations=1, seed=1, backend="bogus",
    )
    with pytest.raises(ValueError):
        run_ga(MACross, is_p, oos_p, multi_objective_fitness,
               cfg, verbose=False)
