"""Tests for quantforge.ml.active_learning."""
from __future__ import annotations

import numpy as np
import pytest

from quantforge.ml.active_learning import (
    ActiveLearner,
    ActiveLearnerConfig,
)


class _StubProbaModel:
    """Returns predict_proba that depends on x[:, 0]."""

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        # Map first column through sigmoid; rows near 0 are most uncertain
        z = 1.0 / (1.0 + np.exp(-X[:, 0]))
        return np.column_stack([1.0 - z, z])


def test_constructor_validates():
    with pytest.raises(ValueError):
        ActiveLearner(model=None)
    with pytest.raises(ValueError):
        ActiveLearner(model=_StubProbaModel(), config=ActiveLearnerConfig(query_size=0))
    with pytest.raises(ValueError):
        ActiveLearner(
            model=_StubProbaModel(),
            config=ActiveLearnerConfig(strategy="bogus"),
        )


def test_query_picks_uncertain_samples():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((20, 3))
    # Insert most-uncertain points (col0 == 0)
    X[3, 0] = 0.0
    X[7, 0] = 0.01
    al = ActiveLearner(_StubProbaModel(), ActiveLearnerConfig(query_size=2))
    idx = al.query(X)
    assert len(idx) == 2
    # The most uncertain rows are 3 and 7
    assert set(idx.tolist()) <= {3, 7, 0, 1, 2, 4, 5, 6, 8}  # at least includes one
    assert 3 in idx.tolist() or 7 in idx.tolist()


def test_uncertainty_strategies():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((10, 2))
    for strat in ("least_confident", "margin", "entropy"):
        al = ActiveLearner(
            _StubProbaModel(), ActiveLearnerConfig(query_size=3, strategy=strat)
        )
        scores = al.uncertainty_scores(X)
        assert scores.shape == (10,)
        idx = al.query(X)
        assert len(idx) == 3


def test_query_with_score_fn():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((10, 2))

    def my_scorer(arr):
        return np.abs(arr[:, 0])  # uncertainty proportional to magnitude

    class _Empty:
        pass

    al = ActiveLearner(_Empty(), ActiveLearnerConfig(query_size=2))
    idx = al.query(X, score_fn=my_scorer)
    assert len(idx) == 2


def test_score_fn_validation():
    al = ActiveLearner(_StubProbaModel(), ActiveLearnerConfig(query_size=2))
    X = np.zeros((4, 2))
    with pytest.raises(TypeError):
        al.query(X, score_fn=lambda arr: [0.1, 0.2, 0.3, 0.4])
    with pytest.raises(ValueError):
        al.query(X, score_fn=lambda arr: np.zeros(arr.shape[0] + 1))


def test_input_validation():
    al = ActiveLearner(_StubProbaModel(), ActiveLearnerConfig(query_size=2))
    with pytest.raises(TypeError):
        al.query([[1, 2], [3, 4]])
    with pytest.raises(ValueError):
        al.query(np.zeros(5))


def test_no_proba_raises():
    class _NoProba:
        pass

    al = ActiveLearner(_NoProba(), ActiveLearnerConfig(query_size=1))
    with pytest.raises(AttributeError):
        al.query(np.zeros((3, 2)))
