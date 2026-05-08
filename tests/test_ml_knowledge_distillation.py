"""Tests for quantforge.ml.knowledge_distillation."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from quantforge.ml.knowledge_distillation import (
    DistillationConfig,
    KnowledgeDistiller,
)


def _make_data(n: int = 64, f: int = 4, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, f)).astype(np.float32)
    y = (X[:, 0] - 0.5 * X[:, 1] + 0.05 * rng.standard_normal(n)).astype(np.float32)
    return X, y


def _teacher(X: np.ndarray) -> np.ndarray:
    return (X[:, 0] - 0.5 * X[:, 1]).astype(np.float32).reshape(-1, 1)


def test_constructor_validates():
    with pytest.raises(ValueError):
        KnowledgeDistiller(DistillationConfig(in_features=0))
    with pytest.raises(ValueError):
        KnowledgeDistiller(DistillationConfig(alpha=2.0))
    with pytest.raises(ValueError):
        KnowledgeDistiller(DistillationConfig(temperature=0.0))


def test_fit_runs():
    X, y = _make_data(n=64, f=4)
    cfg = DistillationConfig(in_features=4, student_hidden=8, epochs=5, batch_size=16)
    kd = KnowledgeDistiller(cfg)
    h = kd.fit(X, y, teacher=_teacher)
    assert "loss" in h and "hard_loss" in h and "soft_loss" in h
    assert len(h["loss"]) == 5


def test_predict_shape():
    X, y = _make_data(n=32, f=4)
    cfg = DistillationConfig(in_features=4, student_hidden=8, epochs=3, batch_size=16)
    kd = KnowledgeDistiller(cfg)
    kd.fit(X, y, teacher=_teacher)
    yhat = kd.predict(X)
    assert yhat.shape == (32,)
    assert np.isfinite(yhat).all()


def test_predict_before_fit_raises():
    cfg = DistillationConfig(in_features=4, student_hidden=8, epochs=1)
    kd = KnowledgeDistiller(cfg)
    with pytest.raises(RuntimeError):
        kd.predict(np.zeros((3, 4), dtype=np.float32))


def test_input_validation():
    cfg = DistillationConfig(in_features=4, student_hidden=8, epochs=1, batch_size=4)
    kd = KnowledgeDistiller(cfg)
    X = np.zeros((4, 4), dtype=np.float32)
    y = np.zeros(4, dtype=np.float32)
    with pytest.raises(TypeError):
        kd.fit(X, y, teacher="not-callable")
    with pytest.raises(TypeError):
        kd.fit("bad", y, teacher=_teacher)
    with pytest.raises(ValueError):
        kd.fit(np.zeros((4, 7), dtype=np.float32), y, teacher=_teacher)


def test_teacher_must_return_array():
    cfg = DistillationConfig(in_features=4, student_hidden=8, epochs=1, batch_size=4)
    kd = KnowledgeDistiller(cfg)
    X = np.zeros((4, 4), dtype=np.float32)
    y = np.zeros(4, dtype=np.float32)
    with pytest.raises(TypeError):
        kd.fit(X, y, teacher=lambda x: list(range(x.shape[0])))
