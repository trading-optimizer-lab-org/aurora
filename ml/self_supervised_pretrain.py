"""Self-supervised pretraining on return sequences.

Two pretext tasks are supported:

* ``masked``: a fraction of timesteps in the input window is replaced by zeros
  (mask token); the model must reconstruct the original values.
* ``next_step``: the model receives ``[r_0..r_{T-2}]`` and must predict
  ``[r_1..r_{T-1}]``.

After pretraining, ``encode(X)`` returns the encoder representation of the
last timestep, suitable for downstream classifiers / forecasters.

Lazy torch dependency.
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
    torch = None
    nn = None
    DataLoader = None
    TensorDataset = None
    TORCH_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "quantforge.ml.self_supervised_pretrain requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class SelfSupervisedConfig:
    seq_len: int = 32
    n_features: int = 1
    hidden_dim: int = 32
    task: str = "masked"  # masked | next_step
    mask_ratio: float = 0.15
    learning_rate: float = 1e-3
    batch_size: int = 32
    epochs: int = 20
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Encoder + heads
# ---------------------------------------------------------------------------


def _build_modules(cfg: SelfSupervisedConfig):
    _require_torch()

    class _Encoder(nn.Module):
        def __init__(self, c: SelfSupervisedConfig):
            super().__init__()
            self.gru = nn.GRU(
                input_size=c.n_features,
                hidden_size=c.hidden_dim,
                num_layers=1,
                batch_first=True,
            )

        def forward(self, x):
            out, _ = self.gru(x)
            return out  # (B, T, H)

    class _Head(nn.Module):
        def __init__(self, c: SelfSupervisedConfig):
            super().__init__()
            self.proj = nn.Linear(c.hidden_dim, c.n_features)

        def forward(self, h):
            return self.proj(h)

    return _Encoder(cfg), _Head(cfg)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class SelfSupervisedPretrainer:
    """Pretrain a sequence encoder via masked / next-step reconstruction.

    Workflow::

        ssp = SelfSupervisedPretrainer(SelfSupervisedConfig(seq_len=20, n_features=1))
        ssp.fit(X)              # X: (N, T, F)
        Z = ssp.encode(X_new)   # (N, hidden_dim)
    """

    def __init__(self, config: Optional[SelfSupervisedConfig] = None):
        _require_torch()
        self.config = config if config is not None else SelfSupervisedConfig()
        if self.config.task not in ("masked", "next_step"):
            raise ValueError("task must be 'masked' or 'next_step'")
        if self.config.seq_len < 2:
            raise ValueError("seq_len must be >= 2")
        if self.config.n_features < 1:
            raise ValueError("n_features must be >= 1")
        if not (0.0 < self.config.mask_ratio < 1.0):
            raise ValueError("mask_ratio must be in (0, 1)")
        if self.config.seed is not None:
            torch.manual_seed(self.config.seed)
        self._encoder, self._head = _build_modules(self.config)
        self._fitted = False

    # ------------------------------------------------------------------ helpers

    def _check_X(self, X: np.ndarray) -> None:
        if not isinstance(X, np.ndarray):
            raise TypeError("X must be a numpy ndarray")
        if X.ndim != 3:
            raise ValueError("X must be 3-D (N, seq_len, n_features)")
        if X.shape[1] != self.config.seq_len:
            raise ValueError(
                f"X seq_len {X.shape[1]} != config.seq_len {self.config.seq_len}"
            )
        if X.shape[2] != self.config.n_features:
            raise ValueError(
                f"X n_features {X.shape[2]} != config.n_features {self.config.n_features}"
            )

    # ------------------------------------------------------------------ fit

    def fit(self, X: np.ndarray) -> Dict[str, List[float]]:
        self._check_X(X)
        Xt = torch.tensor(X, dtype=torch.float32)
        ds = TensorDataset(Xt)
        loader = DataLoader(ds, batch_size=self.config.batch_size, shuffle=True)
        opt = torch.optim.Adam(
            list(self._encoder.parameters()) + list(self._head.parameters()),
            lr=self.config.learning_rate,
        )
        loss_fn = nn.MSELoss()
        history: Dict[str, List[float]] = {"loss": []}
        self._encoder.train()
        self._head.train()
        for _ in range(self.config.epochs):
            ep = 0.0
            nb = 0
            for (xb,) in loader:
                if self.config.task == "masked":
                    mask = (torch.rand(xb.shape[:2]) < self.config.mask_ratio).float()
                    mask3 = mask.unsqueeze(-1)
                    x_in = xb * (1.0 - mask3)
                    target = xb
                    enc = self._encoder(x_in)
                    pred = self._head(enc)
                    if mask3.sum() > 0:
                        loss = loss_fn(pred * mask3, target * mask3)
                    else:
                        loss = loss_fn(pred, target) * 0.0
                else:  # next_step
                    x_in = xb[:, :-1, :]
                    target = xb[:, 1:, :]
                    enc = self._encoder(x_in)
                    pred = self._head(enc)
                    loss = loss_fn(pred, target)
                opt.zero_grad()
                loss.backward()
                opt.step()
                ep += float(loss.item())
                nb += 1
            history["loss"].append(ep / max(nb, 1))
        self._fitted = True
        return history

    # ------------------------------------------------------------------ encode

    def encode(self, X: np.ndarray) -> np.ndarray:
        """Return last-step encoder hidden state, shape ``(N, hidden_dim)``."""
        if not self._fitted:
            raise RuntimeError("call fit() before encode()")
        self._check_X(X)
        self._encoder.eval()
        with torch.no_grad():
            h = self._encoder(torch.tensor(X, dtype=torch.float32))
            last = h[:, -1, :].cpu().numpy()
        return last

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Reconstruct the input (masked task) or next-step (next_step task)."""
        if not self._fitted:
            raise RuntimeError("call fit() before predict()")
        self._check_X(X)
        self._encoder.eval()
        self._head.eval()
        with torch.no_grad():
            if self.config.task == "next_step":
                x_in = torch.tensor(X[:, :-1, :], dtype=torch.float32)
            else:
                x_in = torch.tensor(X, dtype=torch.float32)
            out = self._head(self._encoder(x_in)).cpu().numpy()
        return out
