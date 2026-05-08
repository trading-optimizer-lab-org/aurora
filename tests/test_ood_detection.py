"""Tests for OODDetector."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.validation.ood_detection import OODDetector


def test_basic_inlier(seed=42):
    rng = np.random.default_rng(seed)
    X_train = rng.normal(0, 1, (200, 3))
    X_test = rng.normal(0, 1, (50, 3))
    od = OODDetector(contamination=0.05).run(X_train, X_test)
    assert od.test_ood_flags.shape == (50,)
    # Most test points come from same dist; OOD fraction should be modest
    assert od.ood_fraction() < 0.4


def test_outliers_flagged():
    rng = np.random.default_rng(0)
    X_train = rng.normal(0, 1, (200, 3))
    X_test = np.full((20, 3), 10.0)  # far OOD
    od = OODDetector(contamination=0.05).run(X_train, X_test)
    # All clearly OOD points should be flagged
    assert od.ood_fraction() > 0.5


def test_dim_mismatch_raises():
    rng = np.random.default_rng(0)
    X_train = rng.normal(0, 1, (50, 3))
    X_test = rng.normal(0, 1, (50, 4))
    with pytest.raises(ValueError):
        OODDetector().run(X_train, X_test)


def test_too_few_train_raises():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        OODDetector().run(rng.normal(0, 1, (3, 2)), rng.normal(0, 1, (5, 2)))
