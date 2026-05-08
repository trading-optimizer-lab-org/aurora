"""Tests for quantforge.ml.contrastive_strategy."""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from quantforge.ml.contrastive_strategy import (
    ContrastiveConfig,
    ContrastiveStrategyEmbedder,
)


def _make_triplets(n: int = 32, f: int = 4, seed: int = 0):
    rng = np.random.default_rng(seed)
    anchor = rng.standard_normal((n, f)).astype(np.float32)
    positive = anchor + 0.05 * rng.standard_normal((n, f)).astype(np.float32)
    negative = -anchor + rng.standard_normal((n, f)).astype(np.float32)
    return anchor, positive, negative


def test_constructor_validates():
    with pytest.raises(ValueError):
        ContrastiveStrategyEmbedder(ContrastiveConfig(in_features=0))
    with pytest.raises(ValueError):
        ContrastiveStrategyEmbedder(ContrastiveConfig(embedding_dim=1))
    with pytest.raises(ValueError):
        ContrastiveStrategyEmbedder(ContrastiveConfig(triplet_margin=0.0))


def test_fit_runs():
    a, p, n = _make_triplets(n=32, f=4)
    cfg = ContrastiveConfig(in_features=4, embedding_dim=8, hidden_dim=16, epochs=4, batch_size=8)
    emb = ContrastiveStrategyEmbedder(cfg)
    h = emb.fit((a, p, n))
    assert "loss" in h
    assert len(h["loss"]) == 4
    assert all(np.isfinite(h["loss"]))


def test_embed_shape_and_norm():
    a, p, n = _make_triplets(n=20, f=4)
    cfg = ContrastiveConfig(in_features=4, embedding_dim=6, hidden_dim=8, epochs=2, batch_size=8)
    emb = ContrastiveStrategyEmbedder(cfg)
    emb.fit((a, p, n))
    Z = emb.embed(a)
    assert Z.shape == (20, 6)
    norms = np.linalg.norm(Z, axis=-1)
    assert np.allclose(norms, 1.0, atol=1e-4)


def test_similarity_anchor_positive_higher():
    a, p, n = _make_triplets(n=32, f=4)
    cfg = ContrastiveConfig(in_features=4, embedding_dim=8, hidden_dim=16, epochs=10, batch_size=8)
    emb = ContrastiveStrategyEmbedder(cfg)
    emb.fit((a, p, n))
    sim_pos = emb.similarity(a, p).mean()
    sim_neg = emb.similarity(a, n).mean()
    assert sim_pos > sim_neg


def test_embed_before_fit_raises():
    cfg = ContrastiveConfig(in_features=4, embedding_dim=4, hidden_dim=8, epochs=1)
    emb = ContrastiveStrategyEmbedder(cfg)
    with pytest.raises(RuntimeError):
        emb.embed(np.zeros((3, 4), dtype=np.float32))


def test_input_validation():
    cfg = ContrastiveConfig(in_features=4, embedding_dim=4, hidden_dim=8, epochs=1)
    emb = ContrastiveStrategyEmbedder(cfg)
    with pytest.raises(TypeError):
        emb.fit("not a tuple")
    with pytest.raises(TypeError):
        emb.fit((np.zeros((3, 4)), [1], np.zeros((3, 4))))
    a = np.zeros((4, 4), dtype=np.float32)
    b = np.zeros((4, 4), dtype=np.float32)
    c = np.zeros((3, 4), dtype=np.float32)
    with pytest.raises(ValueError):
        emb.fit((a, b, c))


def test_similarity_shape_validation():
    a, p, n = _make_triplets(n=8, f=4)
    cfg = ContrastiveConfig(in_features=4, embedding_dim=4, hidden_dim=8, epochs=1, batch_size=4)
    emb = ContrastiveStrategyEmbedder(cfg)
    emb.fit((a, p, n))
    with pytest.raises(ValueError):
        emb.similarity(a, np.zeros((a.shape[0] + 1, 4), dtype=np.float32))
