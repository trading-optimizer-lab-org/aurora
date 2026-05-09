"""Tests for quantforge.ml.graph_neural_net."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from aurora.ml.graph_neural_net import (
    CorrelationGNNConfig,
    CorrelationGraphNN,
    PYG_AVAILABLE,
    TORCH_AVAILABLE,
    build_correlation_graph,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def correlated_returns():
    rng = np.random.default_rng(0)
    n_bars = 200
    base = rng.normal(0, 0.01, n_bars)
    cols = {
        "A": base + rng.normal(0, 0.001, n_bars),
        "B": base + rng.normal(0, 0.001, n_bars),  # highly correlated with A
        "C": rng.normal(0, 0.01, n_bars),          # independent
        "D": rng.normal(0, 0.01, n_bars),          # independent
    }
    return pd.DataFrame(cols)


# ---------------------------------------------------------------------------
# graph construction
# ---------------------------------------------------------------------------


def test_build_correlation_graph_shapes(correlated_returns):
    adj, edge_index = build_correlation_graph(correlated_returns, threshold=0.5)
    n = correlated_returns.shape[1]
    assert adj.shape == (n, n)
    assert edge_index.ndim == 2
    assert edge_index.shape[0] == 2
    # diagonal is self-loop
    assert np.allclose(np.diag(adj), 1.0)


def test_build_graph_high_threshold_yields_sparse_graph(correlated_returns):
    adj_low, _ = build_correlation_graph(correlated_returns, threshold=0.1)
    adj_high, _ = build_correlation_graph(correlated_returns, threshold=0.9)
    # high threshold -> at most A-B edges remain off-diagonal
    off_low = (adj_low > 0).sum() - adj_low.shape[0]
    off_high = (adj_high > 0).sum() - adj_high.shape[0]
    assert off_high <= off_low


def test_build_graph_validates_input(correlated_returns):
    with pytest.raises(TypeError):
        build_correlation_graph([[1, 2], [3, 4]])
    with pytest.raises(ValueError):
        build_correlation_graph(correlated_returns[["A"]])
    with pytest.raises(ValueError):
        build_correlation_graph(correlated_returns, threshold=1.5)


# ---------------------------------------------------------------------------
# CorrelationGraphNN
# ---------------------------------------------------------------------------


def test_dense_gcn_forward_shape(correlated_returns):
    cfg = CorrelationGNNConfig(
        n_assets=correlated_returns.shape[1],
        in_features=3,
        hidden_dim=8,
        out_dim=1,
        threshold=0.4,
        use_pyg=False,
    )
    model = CorrelationGraphNN(cfg)
    assert model.backend == "dense"
    feats = np.random.RandomState(0).randn(cfg.n_assets, cfg.in_features).astype(np.float32)
    out = model.predict(feats, correlated_returns)
    assert out.shape == (cfg.n_assets, cfg.out_dim)


def test_predict_validates_features(correlated_returns):
    cfg = CorrelationGNNConfig(
        n_assets=correlated_returns.shape[1], in_features=3, use_pyg=False
    )
    model = CorrelationGraphNN(cfg)
    with pytest.raises(TypeError):
        model.predict([[1, 2, 3]] * cfg.n_assets, correlated_returns)
    with pytest.raises(ValueError):
        model.predict(np.zeros((cfg.n_assets + 1, cfg.in_features), dtype=np.float32), correlated_returns)


def test_pyg_backend_only_when_available(correlated_returns):
    cfg = CorrelationGNNConfig(
        n_assets=correlated_returns.shape[1], in_features=2, hidden_dim=4, use_pyg=True
    )
    model = CorrelationGraphNN(cfg)
    if PYG_AVAILABLE:
        assert model.backend == "pyg"
    else:
        assert model.backend == "dense"
