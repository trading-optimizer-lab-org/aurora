"""Tests for SHAPExplainer (lazy shap)."""
from __future__ import annotations
import numpy as np
import pytest

from quantforge.validation.shap_explain import SHAPExplainer


class _DummyModel:
    """Linear model: y = X @ w."""
    def __init__(self, w):
        self.w = np.asarray(w, dtype=float)

    def predict(self, X):
        return X @ self.w


@pytest.fixture
def fake_data():
    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (60, 4))
    return X


def test_basic_run(fake_data):
    model = _DummyModel(w=[1.0, 2.0, 0.0, -3.0])
    se = SHAPExplainer().run(model, fake_data)
    assert se.shap_values.shape == (60, 4)
    assert se.feature_importances.shape == (4,)
    assert len(se.feature_names) == 4


def test_feature_importance_orders(fake_data):
    """Feature with zero coefficient should get lowest importance."""
    model = _DummyModel(w=[5.0, 5.0, 0.0, 5.0])
    se = SHAPExplainer().run(model, fake_data)
    fi = se.feature_importances
    assert fi[2] < fi[0]
    assert fi[2] < fi[1]
    assert fi[2] < fi[3]


def test_invalid_inputs(fake_data):
    model = _DummyModel(w=[1.0, 1.0, 1.0, 1.0])
    with pytest.raises(ValueError):
        SHAPExplainer().run(model, np.zeros(5))
    with pytest.raises(TypeError):
        SHAPExplainer().run(object(), fake_data)
    with pytest.raises(ValueError):
        SHAPExplainer().run(model, fake_data, feature_names=["a", "b"])


def test_custom_feature_names(fake_data):
    model = _DummyModel(w=[1.0, 1.0, 1.0, 1.0])
    se = SHAPExplainer().run(model, fake_data,
                              feature_names=["alpha", "beta", "gamma", "delta"])
    assert se.feature_names == ["alpha", "beta", "gamma", "delta"]
