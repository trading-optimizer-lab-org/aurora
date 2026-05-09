"""Correlation-graph neural network on a panel of assets.

Builds a graph G = (V, E) where each node is an asset and each edge connects
assets whose pairwise return correlation exceeds a configurable threshold.
A simple message-passing layer is implemented in two ways:

  1. ``torch_geometric``-based GCN (used when available),
  2. Pure PyTorch fallback that does ``(D^-0.5 A D^-0.5) X W`` directly.

Both pathways are lazy: the module imports without torch / torch_geometric
installed, and the relevant class raises ``ImportError`` at instantiation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

try:  # core torch
    import torch
    from torch import nn
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None
    nn = None
    TORCH_AVAILABLE = False

try:  # optional pyg
    import torch_geometric
    from torch_geometric.nn import GCNConv
    PYG_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch_geometric = None
    GCNConv = None
    PYG_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "quantforge.ml.graph_neural_net requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Graph construction (no torch needed)
# ---------------------------------------------------------------------------


def build_correlation_graph(
    returns: pd.DataFrame, threshold: float = 0.3
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (adjacency_dense, edge_index) for a correlation graph.

    adjacency_dense: (N, N) float, off-diagonal == |corr| above threshold (else 0),
                     diagonal == 1 (self-loop).
    edge_index:      (2, E) int, each column an undirected edge (both directions).
    """
    if not isinstance(returns, pd.DataFrame):
        raise TypeError("returns must be a DataFrame")
    if returns.shape[1] < 2:
        raise ValueError("need at least 2 assets to build a graph")
    if not (-1.0 <= threshold <= 1.0):
        raise ValueError("threshold must be between -1 and 1")

    corr = returns.corr().to_numpy()
    n = corr.shape[0]
    adj = np.zeros_like(corr)
    for i in range(n):
        for j in range(n):
            if i == j:
                adj[i, j] = 1.0
            elif abs(corr[i, j]) >= threshold:
                adj[i, j] = abs(corr[i, j])

    # edge list (both directions for undirected)
    src, dst = [], []
    for i in range(n):
        for j in range(n):
            if i != j and adj[i, j] > 0:
                src.append(i)
                dst.append(j)
    if not src:
        src.append(0)
        dst.append(0)
    edge_index = np.vstack([np.array(src, dtype=np.int64), np.array(dst, dtype=np.int64)])
    return adj, edge_index


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class CorrelationGNNConfig:
    n_assets: int = 5
    in_features: int = 4
    hidden_dim: int = 16
    out_dim: int = 1
    threshold: float = 0.3
    use_pyg: bool = True  # falls back to dense GCN if torch_geometric absent


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def _make_pyg_net(cfg: CorrelationGNNConfig):
    _require_torch()
    if not PYG_AVAILABLE:
        raise ImportError("torch_geometric is not installed")

    class _PyGNet(nn.Module):
        def __init__(self, c: CorrelationGNNConfig):
            super().__init__()
            self.conv1 = GCNConv(c.in_features, c.hidden_dim)
            self.conv2 = GCNConv(c.hidden_dim, c.out_dim)

        def forward(self, x, edge_index):
            h = self.conv1(x, edge_index)
            h = torch.relu(h)
            return self.conv2(h, edge_index)

    return _PyGNet(cfg)


def _make_dense_net(cfg: CorrelationGNNConfig):
    _require_torch()

    class _DenseGCN(nn.Module):
        def __init__(self, c: CorrelationGNNConfig):
            super().__init__()
            self.w1 = nn.Linear(c.in_features, c.hidden_dim)
            self.w2 = nn.Linear(c.hidden_dim, c.out_dim)

        @staticmethod
        def _normalize(adj: "torch.Tensor") -> "torch.Tensor":
            # D^-0.5 A D^-0.5
            d = adj.sum(dim=1).clamp(min=1e-12)
            d_inv_sqrt = d.pow(-0.5)
            return adj * d_inv_sqrt.unsqueeze(0) * d_inv_sqrt.unsqueeze(1)

        def forward(self, x: "torch.Tensor", adj: "torch.Tensor") -> "torch.Tensor":
            ahat = self._normalize(adj)
            h = torch.relu(self.w1(ahat @ x))
            return self.w2(ahat @ h)

    return _DenseGCN(cfg)


class CorrelationGraphNN:
    """High-level convenience class.

    ``forward(features, returns)``: features is (N, F), returns is (T, N) used
    only for graph construction. Returns (N, out_dim) tensor as numpy.
    """

    def __init__(self, config: Optional[CorrelationGNNConfig] = None):
        _require_torch()
        self.config = config if config is not None else CorrelationGNNConfig()
        if self.config.use_pyg and PYG_AVAILABLE:
            self._mode = "pyg"
            self._net = _make_pyg_net(self.config)
        else:
            self._mode = "dense"
            self._net = _make_dense_net(self.config)
        self._net.eval()

    @property
    def backend(self) -> str:
        return self._mode

    def predict(self, features: np.ndarray, returns: pd.DataFrame) -> np.ndarray:
        if not isinstance(features, np.ndarray):
            raise TypeError("features must be a numpy array")
        if features.shape != (self.config.n_assets, self.config.in_features):
            raise ValueError(
                f"features shape {features.shape} != ({self.config.n_assets}, {self.config.in_features})"
            )
        adj_dense, edge_index = build_correlation_graph(
            returns, threshold=self.config.threshold
        )
        with torch.no_grad():
            x = torch.from_numpy(features.astype(np.float32))
            if self._mode == "pyg":
                ei = torch.from_numpy(edge_index.astype(np.int64))
                out = self._net(x, ei)
            else:
                a = torch.from_numpy(adj_dense.astype(np.float32))
                out = self._net(x, a)
            return out.cpu().numpy()


__all__ = [
    "TORCH_AVAILABLE",
    "PYG_AVAILABLE",
    "CorrelationGNNConfig",
    "CorrelationGraphNN",
    "build_correlation_graph",
]
