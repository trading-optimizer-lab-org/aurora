"""Tests for quantforge.ml.mamba_ssm."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.mamba_ssm import (
    MambaConfig,
    MambaForecaster,
    TORCH_AVAILABLE,
    MAMBA_AVAILABLE,
)


def _make_data(n: int = 64, t: int = 12, f: int = 4, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, t, f)).astype(np.float32)
    y = (X[:, -1, 0] * 2.0 + 0.1 * rng.standard_normal(n)).astype(np.float32)
    return X, y


def test_constructor_validates():
    with pytest.raises(ValueError):
        MambaForecaster(MambaConfig(input_dim=0))
    with pytest.raises(ValueError):
        MambaForecaster(MambaConfig(seq_len=0))
    with pytest.raises(ValueError):
        MambaForecaster(MambaConfig(n_layers=0))


def test_fit_returns_history():
    X, y = _make_data(n=40, t=8, f=3)
    cfg = MambaConfig(input_dim=3, seq_len=8, d_model=16, n_layers=1, epochs=3, batch_size=16)
    f = MambaForecaster(cfg)
    h = f.fit(X, y)
    assert "loss" in h
    assert len(h["loss"]) == 3
    assert all(np.isfinite(h["loss"]))


def test_predict_shape():
    X, y = _make_data(n=32, t=6, f=2)
    cfg = MambaConfig(input_dim=2, seq_len=6, d_model=8, n_layers=1, epochs=2, batch_size=16)
    f = MambaForecaster(cfg)
    f.fit(X, y)
    yhat = f.predict(X)
    assert yhat.shape == (32,)
    assert np.isfinite(yhat).all()


def test_predict_before_fit_raises():
    cfg = MambaConfig(input_dim=2, seq_len=4, d_model=8, n_layers=1, epochs=1)
    f = MambaForecaster(cfg)
    X = np.zeros((4, 4, 2), dtype=np.float32)
    with pytest.raises(RuntimeError):
        f.predict(X)


def test_input_validation():
    cfg = MambaConfig(input_dim=2, seq_len=4, d_model=8, n_layers=1, epochs=1, batch_size=4)
    f = MambaForecaster(cfg)
    with pytest.raises(TypeError):
        f.fit([1, 2, 3], np.zeros(3, dtype=np.float32))
    bad_t = np.zeros((4, 5, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        f.fit(bad_t, np.zeros(4, dtype=np.float32))
    bad_f = np.zeros((4, 4, 7), dtype=np.float32)
    with pytest.raises(ValueError):
        f.fit(bad_f, np.zeros(4, dtype=np.float32))


def test_backend_string():
    cfg = MambaConfig(input_dim=2, seq_len=4, d_model=8, n_layers=1, epochs=1)
    f = MambaForecaster(cfg)
    assert f.backend in ("mamba", "gru")
    if not MAMBA_AVAILABLE:
        assert f.backend == "gru"
