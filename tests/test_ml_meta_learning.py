"""Tests for aurora.ml.meta_learning."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.meta_learning import (
    MetaConfig,
    MetaLearner,
    Task,
    TORCH_AVAILABLE,
)


def _make_regime_task(name: str, slope: float, n: int = 80, seed: int = 0) -> Task:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((n, 4)).astype(np.float32)
    y = (slope * x[:, 0] + 0.05 * rng.standard_normal(n)).astype(np.float32)
    half = n // 2
    return Task(
        name=name,
        support_x=x[:half],
        support_y=y[:half],
        query_x=x[half:],
        query_y=y[half:],
    )


@pytest.fixture
def regimes():
    return [
        _make_regime_task("bull", slope=1.0, seed=0),
        _make_regime_task("bear", slope=-1.0, seed=1),
        _make_regime_task("flat", slope=0.0, seed=2),
    ]


def test_meta_fit_decreases_loss(regimes):
    ml = MetaLearner(MetaConfig(in_features=4, hidden_dim=8, meta_steps=20, inner_steps=2))
    history = ml.meta_fit(regimes)
    assert "meta_loss" in history
    assert len(history["meta_loss"]) == 20
    # First half avg vs last half avg should decrease
    h = history["meta_loss"]
    assert np.mean(h[-5:]) < np.mean(h[:5])


def test_adapt_returns_params(regimes):
    ml = MetaLearner(MetaConfig(in_features=4, hidden_dim=8, meta_steps=5))
    ml.meta_fit(regimes)
    adapted = ml.adapt(regimes[0].support_x, regimes[0].support_y)
    assert isinstance(adapted, list)
    assert len(adapted) == 4  # W1, b1, W2, b2
    for p in adapted:
        assert isinstance(p, torch.Tensor)


def test_predict_shape(regimes):
    ml = MetaLearner(MetaConfig(in_features=4, hidden_dim=8, meta_steps=2))
    ml.meta_fit(regimes)
    out = ml.predict(regimes[0].query_x)
    assert out.shape == (regimes[0].query_x.shape[0], 1)


def test_meta_fit_validates_input():
    ml = MetaLearner(MetaConfig(in_features=4, hidden_dim=8))
    with pytest.raises(ValueError):
        ml.meta_fit([])
    with pytest.raises(TypeError):
        ml.meta_fit([{"name": "x"}])  # not a Task


def test_predict_validates_shape(regimes):
    ml = MetaLearner(MetaConfig(in_features=4, hidden_dim=8, meta_steps=1))
    ml.meta_fit(regimes)
    with pytest.raises(ValueError):
        ml.predict(np.zeros((5, 7), dtype=np.float32))
    with pytest.raises(TypeError):
        ml.predict([[0.0] * 4])


def test_adapt_validates_input(regimes):
    ml = MetaLearner(MetaConfig(in_features=4, hidden_dim=8, meta_steps=1))
    ml.meta_fit(regimes)
    with pytest.raises(TypeError):
        ml.adapt([1, 2], [3, 4])
