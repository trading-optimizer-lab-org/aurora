"""Mixture-of-Experts (MoE) for multi-regime forecasting.

A small gating network produces per-sample weights over ``n_experts`` MLPs.
The output is the weighted sum of expert predictions. Useful when the
underlying signal switches behaviour across regimes (bull/bear, high-vol/
low-vol, risk-on/risk-off), letting each expert specialise.

Lazy torch dependency. Module imports without torch; consumers branch on
``TORCH_AVAILABLE``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    DataLoader = None  # type: ignore[assignment,misc]
    TensorDataset = None  # type: ignore[assignment,misc]
    TORCH_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "aurora.ml.moe requires torch. Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class MoEConfig:
    in_features: int = 8
    hidden_dim: int = 32
    out_dim: int = 1
    n_experts: int = 4
    learning_rate: float = 1e-3
    batch_size: int = 32
    epochs: int = 20
    dropout: float = 0.1
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def _build_moe(cfg: MoEConfig):
    _require_torch()

    class _Expert(nn.Module):
        def __init__(self, c: MoEConfig):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(c.in_features, c.hidden_dim),
                nn.ReLU(),
                nn.Dropout(c.dropout),
                nn.Linear(c.hidden_dim, c.out_dim),
            )

        def forward(self, x):
            return self.net(x)

    class _Gate(nn.Module):
        def __init__(self, c: MoEConfig):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(c.in_features, c.hidden_dim),
                nn.ReLU(),
                nn.Linear(c.hidden_dim, c.n_experts),
            )

        def forward(self, x):
            return torch.softmax(self.net(x), dim=-1)

    class _MoE(nn.Module):
        def __init__(self, c: MoEConfig):
            super().__init__()
            self.experts = nn.ModuleList([_Expert(c) for _ in range(c.n_experts)])
            self.gate = _Gate(c)
            self.out_dim = c.out_dim
            self.n_experts = c.n_experts

        def forward(self, x):
            # gate_weights: (B, n_experts)
            gate_weights = self.gate(x)
            # expert_out: (B, n_experts, out_dim)
            expert_out = torch.stack([e(x) for e in self.experts], dim=1)
            # Weighted sum across experts
            return (gate_weights.unsqueeze(-1) * expert_out).sum(dim=1), gate_weights

    return _MoE(cfg)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class MixtureOfExperts:
    """MoE regressor with a softmax gating network."""

    def __init__(self, config: Optional[MoEConfig] = None):
        _require_torch()
        self.config = config if config is not None else MoEConfig()
        if self.config.in_features < 1:
            raise ValueError("in_features must be >= 1")
        if self.config.n_experts < 2:
            raise ValueError("n_experts must be >= 2")
        if self.config.out_dim < 1:
            raise ValueError("out_dim must be >= 1")
        if self.config.seed is not None:
            torch.manual_seed(self.config.seed)
        self._model = _build_moe(self.config)
        self._fitted = False

    # ------------------------------------------------------------------ helpers

    def _check_X(self, X: np.ndarray) -> None:
        if not isinstance(X, np.ndarray):
            raise TypeError("X must be a numpy ndarray")
        if X.ndim != 2:
            raise ValueError("X must be 2-D (N, in_features)")
        if X.shape[1] != self.config.in_features:
            raise ValueError(
                f"X has {X.shape[1]} features, expected {self.config.in_features}"
            )

    # ------------------------------------------------------------------ fit

    def fit(self, X: np.ndarray, y: np.ndarray) -> Dict[str, List[float]]:
        self._check_X(X)
        if not isinstance(y, np.ndarray):
            raise TypeError("y must be a numpy ndarray")
        if y.shape[0] != X.shape[0]:
            raise ValueError("X and y must have matching first dim")
        y2 = y.reshape(-1, self.config.out_dim).astype(np.float32)
        Xt = torch.tensor(X, dtype=torch.float32)
        yt = torch.tensor(y2, dtype=torch.float32)
        ds = TensorDataset(Xt, yt)
        loader = DataLoader(ds, batch_size=self.config.batch_size, shuffle=True)
        opt = torch.optim.Adam(self._model.parameters(), lr=self.config.learning_rate)
        loss_fn = nn.MSELoss()
        history: Dict[str, List[float]] = {"loss": []}
        self._model.train()
        for _ in range(self.config.epochs):
            ep_loss = 0.0
            nb = 0
            for xb, yb in loader:
                opt.zero_grad()
                pred, _ = self._model(xb)
                loss = loss_fn(pred, yb)
                loss.backward()
                opt.step()
                ep_loss += float(loss.item())
                nb += 1
            history["loss"].append(ep_loss / max(nb, 1))
        self._fitted = True
        return history

    # ------------------------------------------------------------------ predict

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("call fit() before predict()")
        self._check_X(X)
        self._model.eval()
        with torch.no_grad():
            pred, _ = self._model(torch.tensor(X, dtype=torch.float32))
        out = pred.cpu().numpy()
        if self.config.out_dim == 1:
            return out.reshape(-1)
        return out

    def gate_weights(self, X: np.ndarray) -> np.ndarray:
        """Return per-sample expert weights (N, n_experts)."""
        if not self._fitted:
            raise RuntimeError("call fit() before gate_weights()")
        self._check_X(X)
        self._model.eval()
        with torch.no_grad():
            _, gw = self._model(torch.tensor(X, dtype=torch.float32))
        return gw.cpu().numpy()
