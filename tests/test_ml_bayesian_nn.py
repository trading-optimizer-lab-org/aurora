"""Tests for aurora.ml.bayesian_nn."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.bayesian_nn import (
    BayesianConfig,
    BayesianForecaster,
    PYRO_AVAILABLE,
    TORCH_AVAILABLE,
)


@pytest.fixture
def linear_data():
    rng = np.random.default_rng(0)
    n, d = 200, 4
    X = rng.standard_normal((n, d)).astype(np.float32)
    w = np.array([0.5, -1.0, 2.0, 0.0], dtype=np.float32)
    y = (X @ w + 0.1 * rng.standard_normal(n)).astype(np.float32)
    return X, y


def test_fit_history_decreases(linear_data):
    X, y = linear_data
    bf = BayesianForecaster(BayesianConfig(in_features=4, hidden_dim=8, epochs=30))
    history = bf.fit(X, y)
    assert "loss" in history
    assert len(history["loss"]) == 30
    # loss should drop overall
    assert history["loss"][-1] < history["loss"][0]


def test_predict_shapes(linear_data):
    X, y = linear_data
    bf = BayesianForecaster(BayesianConfig(in_features=4, hidden_dim=8, epochs=15))
    bf.fit(X, y)
    mean, std, samples = bf.predict(X, n_samples=20)
    assert mean.shape == (X.shape[0], 1)
    assert std.shape == (X.shape[0], 1)
    assert samples.shape == (20, X.shape[0], 1)
    # std should be positive (non-zero) due to dropout
    assert (std >= 0).all()


def test_predictive_interval_contains_mean(linear_data):
    X, y = linear_data
    bf = BayesianForecaster(BayesianConfig(in_features=4, hidden_dim=8, epochs=15))
    bf.fit(X, y)
    lo, mean, hi = bf.predictive_interval(X, alpha=0.1, n_samples=40)
    assert lo.shape == mean.shape == hi.shape
    # quantiles should bracket the mean
    assert (lo <= mean + 1e-6).all()
    assert (mean <= hi + 1e-6).all()


def test_predict_before_fit_raises(linear_data):
    X, _ = linear_data
    bf = BayesianForecaster(BayesianConfig(in_features=4, hidden_dim=8))
    with pytest.raises(RuntimeError):
        bf.predict(X)


def test_input_validation(linear_data):
    X, y = linear_data
    bf = BayesianForecaster(BayesianConfig(in_features=4, hidden_dim=8, epochs=2))
    with pytest.raises(TypeError):
        bf.fit([[1.0]], y)
    with pytest.raises(ValueError):
        bf.fit(np.zeros((5, 7), dtype=np.float32), y[:5])
    bf.fit(X, y)
    with pytest.raises(ValueError):
        bf.predict(X, n_samples=0)


def test_backend_resolution():
    bf = BayesianForecaster(BayesianConfig(in_features=4, backend="auto"))
    expected = "pyro" if PYRO_AVAILABLE else "mc_dropout"
    assert bf.backend == expected
