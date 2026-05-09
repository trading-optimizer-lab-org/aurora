"""Tests for quantforge.ml.curriculum_learning."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.ml.curriculum_learning import (
    CurriculumConfig,
    CurriculumScheduler,
)


def _diff_score(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.abs(X[:, 0])  # easy = small magnitude


def test_constructor_validates():
    with pytest.raises(ValueError):
        CurriculumScheduler(CurriculumConfig(n_epochs=0))
    with pytest.raises(ValueError):
        CurriculumScheduler(CurriculumConfig(start_fraction=0.0))
    with pytest.raises(ValueError):
        CurriculumScheduler(CurriculumConfig(end_fraction=2.0))
    with pytest.raises(ValueError):
        CurriculumScheduler(
            CurriculumConfig(start_fraction=0.9, end_fraction=0.5)
        )


def test_fit_and_visible_indices_grow():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((50, 3))
    y = rng.standard_normal(50)
    cs = CurriculumScheduler(
        CurriculumConfig(n_epochs=5, start_fraction=0.2, end_fraction=1.0)
    )
    cs.fit(X, y, _diff_score)
    sizes = [cs.visible_indices(e).shape[0] for e in range(5)]
    assert sizes[0] < sizes[-1]
    assert sizes[-1] == 50


def test_iter_epochs_yields_arrays():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((20, 4))
    y = rng.standard_normal(20)
    cs = CurriculumScheduler(CurriculumConfig(n_epochs=3))
    cs.fit(X, y, _diff_score)
    epochs = list(cs.iter_epochs())
    assert len(epochs) == 3
    for X_e, y_e in epochs:
        assert X_e.ndim == 2
        assert y_e.ndim == 1
        assert X_e.shape[0] == y_e.shape[0]


def test_pacing_modes():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((30, 2))
    y = rng.standard_normal(30)
    for mode in ("linear", "quadratic", "exponential"):
        cs = CurriculumScheduler(CurriculumConfig(n_epochs=4, pacing=mode))
        cs.fit(X, y, _diff_score)
        f0 = cs.fraction_at(0)
        f3 = cs.fraction_at(3)
        assert f0 <= f3
    with pytest.raises(ValueError):
        cs = CurriculumScheduler(CurriculumConfig(n_epochs=4, pacing="bogus"))
        cs.fit(X, y, _diff_score)
        cs.fraction_at(0)


def test_input_validation():
    cs = CurriculumScheduler(CurriculumConfig(n_epochs=2))
    with pytest.raises(TypeError):
        cs.fit([[1, 2]], np.zeros(1), _diff_score)
    with pytest.raises(ValueError):
        cs.fit(np.zeros((4, 2)), np.zeros(3), _diff_score)
    with pytest.raises(TypeError):
        cs.fit(np.zeros((4, 2)), np.zeros(4), "not-callable")
    with pytest.raises(TypeError):
        cs.fit(np.zeros((4, 2)), np.zeros(4), lambda X, y: [1, 2, 3, 4])
    with pytest.raises(ValueError):
        cs.fit(np.zeros((4, 2)), np.zeros(4), lambda X, y: np.zeros(7))


def test_visible_before_fit_raises():
    cs = CurriculumScheduler(CurriculumConfig(n_epochs=2))
    with pytest.raises(RuntimeError):
        cs.visible_indices(0)
    with pytest.raises(RuntimeError):
        next(cs.iter_epochs())
