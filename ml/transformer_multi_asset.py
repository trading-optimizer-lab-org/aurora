"""Multi-asset transformer with cross-asset attention.

Encodes a panel ``(T, N, F)`` of N assets and F features over T timesteps
through:

    1. linear projection F -> d_model
    2. learned asset embedding (N, d_model)
    3. positional encoding over T
    4. self-attention over the flattened (T*N) sequence with a causal mask
       (only positions at the same time t or earlier may attend)
    5. linear head -> (T, N) signal

Lazy torch dependency. The module imports without torch installed; classes
raise ``ImportError`` at instantiation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:  # optional dep
    import torch
    from torch import nn
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover - environment-dependent
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "aurora.ml.transformer_multi_asset requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class MultiAssetTransformerConfig:
    """Hyperparameters for :class:`MultiAssetTransformer`."""

    n_assets: int = 5
    n_features: int = 4
    d_model: int = 32
    n_heads: int = 4
    num_layers: int = 2
    dim_feedforward: int = 64
    dropout: float = 0.1
    max_len: int = 512


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def _build_transformer(cfg: MultiAssetTransformerConfig):
    """Helper that constructs the nn.Module. Kept as a function so the file
    parses without torch installed.
    """
    _require_torch()

    class _MultiAssetTransformerImpl(nn.Module):
        def __init__(self, c: MultiAssetTransformerConfig):
            super().__init__()
            self.cfg = c
            self.input_proj = nn.Linear(c.n_features, c.d_model)
            self.asset_embed = nn.Embedding(c.n_assets, c.d_model)
            # Sinusoidal positional encoding over time.
            pe = torch.zeros(c.max_len, c.d_model)
            position = torch.arange(0, c.max_len).unsqueeze(1).float()
            div = torch.exp(
                torch.arange(0, c.d_model, 2).float()
                * -(math.log(10000.0) / c.d_model)
            )
            pe[:, 0::2] = torch.sin(position * div)
            pe[:, 1::2] = torch.cos(position * div)
            self.register_buffer("pos_enc", pe)

            encoder_layer = nn.TransformerEncoderLayer(
                d_model=c.d_model,
                nhead=c.n_heads,
                dim_feedforward=c.dim_feedforward,
                dropout=c.dropout,
                batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=c.num_layers)
            self.head = nn.Linear(c.d_model, 1)

        def _causal_mask(self, T: int, N: int, device) -> "torch.Tensor":
            """Block all attention to positions whose timestep > current.

            Within the same timestep, all assets may attend to each other.
            Returns a (T*N, T*N) bool mask where True == "do not attend".
            """
            t_idx = torch.arange(T, device=device).repeat_interleave(N)
            mask = t_idx.unsqueeze(0) > t_idx.unsqueeze(1)
            return mask

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            """x: (T, N, F) -> signal (T, N)."""
            T, N, F = x.shape
            if N != self.cfg.n_assets:
                raise ValueError(
                    f"Expected n_assets={self.cfg.n_assets}, got {N}"
                )
            if F != self.cfg.n_features:
                raise ValueError(
                    f"Expected n_features={self.cfg.n_features}, got {F}"
                )
            if T > self.cfg.max_len:
                raise ValueError(
                    f"Sequence length {T} exceeds max_len {self.cfg.max_len}"
                )
            asset_ids = torch.arange(N, device=x.device)
            asset_emb = self.asset_embed(asset_ids)        # (N, d_model)
            pos_enc: "torch.Tensor" = self.pos_enc  # type: ignore[assignment]
            pos = pos_enc[:T]                               # (T, d_model)

            h = self.input_proj(x)                          # (T, N, d_model)
            h = h + asset_emb.unsqueeze(0)                  # broadcast over T
            h = h + pos.unsqueeze(1)                        # broadcast over N
            h = h.reshape(1, T * N, self.cfg.d_model)       # batch=1
            mask = self._causal_mask(T, N, x.device)
            out = self.encoder(h, mask=mask)                # (1, T*N, d_model)
            sig = self.head(out).squeeze(-1)                # (1, T*N)
            return sig.view(T, N)

    return _MultiAssetTransformerImpl(cfg)


class MultiAssetTransformer:
    """Friendly wrapper around the underlying nn.Module.

    Usage::

        model = MultiAssetTransformer(MultiAssetTransformerConfig(n_assets=4, n_features=3))
        x = np.random.randn(50, 4, 3).astype(np.float32)
        signal = model.predict(x)   # (50, 4) numpy array
    """

    def __init__(self, config: Optional[MultiAssetTransformerConfig] = None):
        _require_torch()
        self.config = config if config is not None else MultiAssetTransformerConfig()
        self._net = _build_transformer(self.config)
        self._net.eval()

    @property
    def n_parameters(self) -> int:
        return sum(p.numel() for p in self._net.parameters())

    def predict(self, x: np.ndarray) -> np.ndarray:
        if not isinstance(x, np.ndarray):
            raise TypeError("x must be a numpy array of shape (T, N, F)")
        if x.ndim != 3:
            raise ValueError(f"x must be 3D (T, N, F); got shape {x.shape}")
        with torch.no_grad():
            t = torch.from_numpy(x.astype(np.float32))
            out = self._net(t).cpu().numpy()
        return out

    def train_step(self, x: np.ndarray, y: np.ndarray, lr: float = 1e-3) -> float:
        """Single SGD step on MSE loss. Returns scalar loss."""
        if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
            raise TypeError("x, y must be numpy arrays")
        if x.shape[:2] != y.shape[:2]:
            raise ValueError("x and y must agree on (T, N)")
        self._net.train()
        opt = torch.optim.Adam(self._net.parameters(), lr=lr)
        opt.zero_grad()
        t_x = torch.from_numpy(x.astype(np.float32))
        t_y = torch.from_numpy(y.astype(np.float32))
        pred = self._net(t_x)
        loss = ((pred - t_y) ** 2).mean()
        loss.backward()
        opt.step()
        self._net.eval()
        return float(loss.item())


__all__ = [
    "TORCH_AVAILABLE",
    "MultiAssetTransformerConfig",
    "MultiAssetTransformer",
]
