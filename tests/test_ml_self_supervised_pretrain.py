"""Tests for quantforge.ml.self_supervised_pretrain."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from quantforge.ml.self_supervised_pretrain import (
    SelfSupervisedConfig,
    SelfSupervisedPretrainer,
)


def _make_seqs(n: int = 32, t: int = 16, f: int = 1, seed: int = 0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n, t, f)).astype(np.float32)


def test_constructor_validates():
    with pytest.raises(ValueError):
        SelfSupervisedPretrainer(SelfSupervisedConfig(task="bogus"))
    with pytest.raises(ValueError):
        SelfSupervisedPretrainer(SelfSupervisedConfig(seq_len=1))
    with pytest.raises(ValueError):
        SelfSupervisedPretrainer(SelfSupervisedConfig(n_features=0))
    with pytest.raises(ValueError):
        SelfSupervisedPretrainer(SelfSupervisedConfig(mask_ratio=0.0))


def test_masked_fit_runs():
    X = _make_seqs(n=24, t=10, f=1)
    cfg = SelfSupervisedConfig(seq_len=10, n_features=1, hidden_dim=8, task="masked", epochs=3, batch_size=8)
    ssp = SelfSupervisedPretrainer(cfg)
    h = ssp.fit(X)
    assert "loss" in h
    assert len(h["loss"]) == 3


def test_next_step_fit_runs():
    X = _make_seqs(n=24, t=10, f=2)
    cfg = SelfSupervisedConfig(seq_len=10, n_features=2, hidden_dim=8, task="next_step", epochs=3, batch_size=8)
    ssp = SelfSupervisedPretrainer(cfg)
    h = ssp.fit(X)
    assert "loss" in h
    assert len(h["loss"]) == 3
    assert all(np.isfinite(h["loss"]))


def test_encode_shape():
    X = _make_seqs(n=12, t=8, f=2)
    cfg = SelfSupervisedConfig(seq_len=8, n_features=2, hidden_dim=4, task="masked", epochs=2, batch_size=4)
    ssp = SelfSupervisedPretrainer(cfg)
    ssp.fit(X)
    Z = ssp.encode(X)
    assert Z.shape == (12, 4)


def test_predict_next_step_shape():
    X = _make_seqs(n=8, t=8, f=1)
    cfg = SelfSupervisedConfig(seq_len=8, n_features=1, hidden_dim=4, task="next_step", epochs=2, batch_size=4)
    ssp = SelfSupervisedPretrainer(cfg)
    ssp.fit(X)
    out = ssp.predict(X)
    # next_step uses x[:, :-1, :] internally
    assert out.shape == (8, 7, 1)


def test_predict_masked_shape():
    X = _make_seqs(n=8, t=8, f=1)
    cfg = SelfSupervisedConfig(seq_len=8, n_features=1, hidden_dim=4, task="masked", epochs=2, batch_size=4)
    ssp = SelfSupervisedPretrainer(cfg)
    ssp.fit(X)
    out = ssp.predict(X)
    assert out.shape == (8, 8, 1)


def test_encode_before_fit_raises():
    cfg = SelfSupervisedConfig(seq_len=4, n_features=1, hidden_dim=4, task="masked", epochs=1)
    ssp = SelfSupervisedPretrainer(cfg)
    with pytest.raises(RuntimeError):
        ssp.encode(np.zeros((2, 4, 1), dtype=np.float32))
    with pytest.raises(RuntimeError):
        ssp.predict(np.zeros((2, 4, 1), dtype=np.float32))


def test_input_validation():
    cfg = SelfSupervisedConfig(seq_len=4, n_features=1, hidden_dim=4, task="masked", epochs=1, batch_size=2)
    ssp = SelfSupervisedPretrainer(cfg)
    with pytest.raises(TypeError):
        ssp.fit([1, 2, 3])
    with pytest.raises(ValueError):
        ssp.fit(np.zeros((2, 5, 1), dtype=np.float32))
    with pytest.raises(ValueError):
        ssp.fit(np.zeros((2, 4, 3), dtype=np.float32))
