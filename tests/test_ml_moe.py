"""Tests for aurora.ml.moe."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.moe import MoEConfig, MixtureOfExperts


def _make_data(n: int = 80, f: int = 6, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, f)).astype(np.float32)
    y = (X[:, 0] - 0.5 * X[:, 1] + 0.1 * rng.standard_normal(n)).astype(np.float32)
    return X, y


def test_constructor_validates():
    with pytest.raises(ValueError):
        MixtureOfExperts(MoEConfig(in_features=0))
    with pytest.raises(ValueError):
        MixtureOfExperts(MoEConfig(n_experts=1))
    with pytest.raises(ValueError):
        MixtureOfExperts(MoEConfig(out_dim=0))


def test_fit_runs():
    X, y = _make_data(n=64, f=4)
    cfg = MoEConfig(in_features=4, hidden_dim=8, n_experts=3, epochs=4, batch_size=16)
    m = MixtureOfExperts(cfg)
    h = m.fit(X, y)
    assert "loss" in h
    assert len(h["loss"]) == 4
    assert all(np.isfinite(h["loss"]))


def test_predict_shape():
    X, y = _make_data(n=40, f=4)
    cfg = MoEConfig(in_features=4, hidden_dim=8, n_experts=3, epochs=3, batch_size=16)
    m = MixtureOfExperts(cfg)
    m.fit(X, y)
    out = m.predict(X)
    assert out.shape == (40,)
    assert np.isfinite(out).all()


def test_gate_weights_sum_to_one():
    X, y = _make_data(n=40, f=4)
    cfg = MoEConfig(in_features=4, hidden_dim=8, n_experts=4, epochs=2, batch_size=16)
    m = MixtureOfExperts(cfg)
    m.fit(X, y)
    gw = m.gate_weights(X)
    assert gw.shape == (40, 4)
    assert np.allclose(gw.sum(axis=1), 1.0, atol=1e-5)


def test_predict_before_fit_raises():
    cfg = MoEConfig(in_features=4, hidden_dim=8, n_experts=2, epochs=1)
    m = MixtureOfExperts(cfg)
    with pytest.raises(RuntimeError):
        m.predict(np.zeros((3, 4), dtype=np.float32))
    with pytest.raises(RuntimeError):
        m.gate_weights(np.zeros((3, 4), dtype=np.float32))


def test_input_validation():
    cfg = MoEConfig(in_features=4, hidden_dim=8, n_experts=2, epochs=1, batch_size=4)
    m = MixtureOfExperts(cfg)
    with pytest.raises(TypeError):
        m.fit([1, 2], np.zeros(2, dtype=np.float32))
    with pytest.raises(ValueError):
        m.fit(np.zeros((3, 7), dtype=np.float32), np.zeros(3, dtype=np.float32))
    with pytest.raises(ValueError):
        m.fit(np.zeros((3, 4), dtype=np.float32), np.zeros(2, dtype=np.float32))
