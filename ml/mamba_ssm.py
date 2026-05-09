"""Mamba state-space model forecaster.

Lightweight forecaster that prefers ``mamba-ssm`` if installed, otherwise
falls back to a small GRU. The public API (``MambaConfig`` + ``MambaForecaster``)
is identical regardless of backend, so callers do not need to special-case
the dependency.

Both heavy deps (``mamba_ssm`` and ``torch``) are lazy-imported. The module is
import-safe without either; consumers should branch on ``MAMBA_AVAILABLE`` /
``TORCH_AVAILABLE`` for optional features.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None
    TORCH_AVAILABLE = False

try:  # pragma: no cover - exercised only when mamba-ssm is installed
    from mamba_ssm import Mamba
    MAMBA_AVAILABLE = True
except Exception:  # pragma: no cover
    Mamba = None
    MAMBA_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "quantforge.ml.mamba_ssm requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class MambaConfig:
    """Hyperparameters for :class:`MambaForecaster`."""
    input_dim: int = 4
    d_model: int = 32
    n_layers: int = 2
    seq_len: int = 30
    dropout: float = 0.1
    learning_rate: float = 1e-3
    batch_size: int = 32
    epochs: int = 10
    device: str = "cpu"
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _build_backbone(cfg: MambaConfig):
    """Return an nn.Module mapping (B, T, input_dim) -> (B, d_model)."""
    _require_torch()

    if MAMBA_AVAILABLE:  # pragma: no cover - integration only
        class _MambaNet(nn.Module):
            def __init__(self, c: MambaConfig):
                super().__init__()
                self.proj = nn.Linear(c.input_dim, c.d_model)
                self.blocks = nn.ModuleList(
                    [Mamba(d_model=c.d_model) for _ in range(c.n_layers)]
                )
                self.drop = nn.Dropout(c.dropout)

            def forward(self, x):
                h = self.proj(x)
                for blk in self.blocks:
                    h = blk(h) + h
                return self.drop(h[:, -1, :])

        return _MambaNet(cfg)

    class _GRUNet(nn.Module):
        def __init__(self, c: MambaConfig):
            super().__init__()
            self.gru = nn.GRU(
                input_size=c.input_dim,
                hidden_size=c.d_model,
                num_layers=c.n_layers,
                dropout=c.dropout if c.n_layers > 1 else 0.0,
                batch_first=True,
            )

        def forward(self, x):
            out, _ = self.gru(x)
            return out[:, -1, :]

    return _GRUNet(cfg)


# ---------------------------------------------------------------------------
# Forecaster
# ---------------------------------------------------------------------------


class MambaForecaster:
    """State-space-style forecaster with a GRU fallback.

    Workflow::

        f = MambaForecaster(MambaConfig(input_dim=4, seq_len=20))
        f.fit(X, y)             # X: (N, T, F)   y: (N,)
        yhat = f.predict(X_new)
    """

    def __init__(self, config: Optional[MambaConfig] = None):
        _require_torch()
        self.config = config if config is not None else MambaConfig()
        if self.config.input_dim < 1:
            raise ValueError("input_dim must be >= 1")
        if self.config.seq_len < 1:
            raise ValueError("seq_len must be >= 1")
        if self.config.n_layers < 1:
            raise ValueError("n_layers must be >= 1")
        if self.config.seed is not None:
            torch.manual_seed(self.config.seed)
        self._backbone = _build_backbone(self.config)
        self._head = nn.Linear(self.config.d_model, 1)
        self._device = torch.device(self.config.device)
        self._backbone.to(self._device)
        self._head.to(self._device)
        self._fitted = False

    # ------------------------------------------------------------------ helpers

    def _check_inputs(self, X: np.ndarray, y: Optional[np.ndarray]) -> None:
        if not isinstance(X, np.ndarray):
            raise TypeError("X must be a numpy ndarray")
        if X.ndim != 3:
            raise ValueError("X must have shape (N, seq_len, input_dim)")
        if X.shape[1] != self.config.seq_len:
            raise ValueError(
                f"X seq dimension {X.shape[1]} != config.seq_len={self.config.seq_len}"
            )
        if X.shape[2] != self.config.input_dim:
            raise ValueError(
                f"X feature dimension {X.shape[2]} != config.input_dim={self.config.input_dim}"
            )
        if y is not None:
            if not isinstance(y, np.ndarray):
                raise TypeError("y must be a numpy ndarray")
            if y.shape[0] != X.shape[0]:
                raise ValueError("X and y must have the same first dimension")

    # ------------------------------------------------------------------ fit

    def fit(self, X: np.ndarray, y: np.ndarray) -> Dict[str, List[float]]:
        self._check_inputs(X, y)
        X_t = torch.tensor(X, dtype=torch.float32, device=self._device)
        y_t = torch.tensor(y.reshape(-1, 1), dtype=torch.float32, device=self._device)
        ds = TensorDataset(X_t, y_t)
        loader = DataLoader(ds, batch_size=self.config.batch_size, shuffle=True)
        opt = torch.optim.Adam(
            list(self._backbone.parameters()) + list(self._head.parameters()),
            lr=self.config.learning_rate,
        )
        loss_fn = nn.MSELoss()
        history: Dict[str, List[float]] = {"loss": []}
        self._backbone.train()
        self._head.train()
        for _ in range(self.config.epochs):
            epoch_loss = 0.0
            n_batches = 0
            for xb, yb in loader:
                opt.zero_grad()
                feat = self._backbone(xb)
                pred = self._head(feat)
                loss = loss_fn(pred, yb)
                loss.backward()
                opt.step()
                epoch_loss += float(loss.item())
                n_batches += 1
            history["loss"].append(epoch_loss / max(n_batches, 1))
        self._fitted = True
        return history

    # ------------------------------------------------------------------ predict

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("call fit() before predict()")
        self._check_inputs(X, None)
        self._backbone.eval()
        self._head.eval()
        X_t = torch.tensor(X, dtype=torch.float32, device=self._device)
        with torch.no_grad():
            out = self._head(self._backbone(X_t)).cpu().numpy().reshape(-1)
        return out

    @property
    def backend(self) -> str:
        return "mamba" if MAMBA_AVAILABLE else "gru"
