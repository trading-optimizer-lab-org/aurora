"""Tests for aurora.ml.few_shot_strategy."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.few_shot_strategy import (
    FewShotConfig,
    FewShotStrategyAdapter,
)


def _make_regimes(seed: int = 0):
    rng = np.random.default_rng(seed)
    bull = rng.normal(loc=2.0, scale=0.5, size=(20, 4)).astype(np.float32)
    bear = rng.normal(loc=-2.0, scale=0.5, size=(20, 4)).astype(np.float32)
    flat = rng.normal(loc=0.0, scale=0.3, size=(20, 4)).astype(np.float32)
    return {"bull": bull, "bear": bear, "flat": flat}


def test_constructor_validates():
    with pytest.raises(ValueError):
        FewShotStrategyAdapter(FewShotConfig(in_features=0))
    with pytest.raises(ValueError):
        FewShotStrategyAdapter(FewShotConfig(embedding_dim=1))
    with pytest.raises(ValueError):
        FewShotStrategyAdapter(FewShotConfig(k_shot=0))
    with pytest.raises(ValueError):
        FewShotStrategyAdapter(FewShotConfig(n_way=1))


def test_fit_runs():
    sup = _make_regimes()
    cfg = FewShotConfig(
        in_features=4,
        embedding_dim=8,
        hidden_dim=16,
        epochs=3,
        n_episodes=10,
        n_way=3,
        k_shot=5,
        q_query=3,
    )
    fs = FewShotStrategyAdapter(cfg)
    h = fs.fit(sup)
    assert "loss" in h
    assert len(h["loss"]) == 3


def test_predict_returns_known_labels():
    sup = _make_regimes()
    cfg = FewShotConfig(
        in_features=4,
        embedding_dim=8,
        hidden_dim=16,
        epochs=5,
        n_episodes=20,
        n_way=3,
        k_shot=5,
        q_query=3,
    )
    fs = FewShotStrategyAdapter(cfg)
    fs.fit(sup)
    rng = np.random.default_rng(42)
    Xq = rng.normal(loc=2.0, scale=0.5, size=(10, 4)).astype(np.float32)
    labels = fs.predict(Xq)
    assert len(labels) == 10
    valid = {"bull", "bear", "flat"}
    for l in labels:
        assert l in valid


def test_predict_proba_shape_and_normalisation():
    sup = _make_regimes()
    cfg = FewShotConfig(
        in_features=4,
        embedding_dim=8,
        hidden_dim=16,
        epochs=2,
        n_episodes=8,
        n_way=3,
        k_shot=5,
        q_query=3,
    )
    fs = FewShotStrategyAdapter(cfg)
    fs.fit(sup)
    rng = np.random.default_rng(0)
    X = rng.standard_normal((6, 4)).astype(np.float32)
    p = fs.predict_proba(X)
    assert p.shape == (6, 3)
    assert np.allclose(p.sum(axis=1), 1.0, atol=1e-5)


def test_predict_before_fit_raises():
    cfg = FewShotConfig(in_features=4, embedding_dim=4, hidden_dim=8, epochs=1)
    fs = FewShotStrategyAdapter(cfg)
    with pytest.raises(RuntimeError):
        fs.predict(np.zeros((3, 4), dtype=np.float32))
    with pytest.raises(RuntimeError):
        fs.predict_proba(np.zeros((3, 4), dtype=np.float32))


def test_fit_validates():
    cfg = FewShotConfig(in_features=4, embedding_dim=4, hidden_dim=8, epochs=1, n_episodes=2, k_shot=3)
    fs = FewShotStrategyAdapter(cfg)
    with pytest.raises(ValueError):
        fs.fit({"only-one": np.zeros((5, 4), dtype=np.float32)})
    with pytest.raises(TypeError):
        fs.fit({1: np.zeros((5, 4), dtype=np.float32), 2: np.zeros((5, 4), dtype=np.float32)})
    # Too few samples per class
    with pytest.raises(ValueError):
        fs.fit(
            {
                "a": np.zeros((2, 4), dtype=np.float32),
                "b": np.zeros((2, 4), dtype=np.float32),
            }
        )
