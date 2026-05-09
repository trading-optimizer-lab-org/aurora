"""Contrastive embedding for trading strategies.

Trains a small MLP encoder with a triplet loss so that "similar" strategies
end up close in embedding space. Each *strategy* is represented by a fixed
feature vector (e.g. annualised return, vol, max drawdown, turnover, hit-rate,
pair-wise return correlations). Triplets ``(anchor, positive, negative)`` are
provided by the caller; ``positive`` should be a strategy in the same regime
or family as ``anchor``, while ``negative`` should differ.

Lazy torch dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import torch  # type: ignore
    from torch import nn  # type: ignore
    from torch.utils.data import DataLoader, TensorDataset  # type: ignore
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    DataLoader = None  # type: ignore[assignment]
    TensorDataset = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "aurora.ml.contrastive_strategy requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ContrastiveConfig:
    """Hyperparameters for :class:`ContrastiveStrategyEmbedder`."""
    in_features: int = 8
    embedding_dim: int = 16
    hidden_dim: int = 32
    learning_rate: float = 1e-3
    batch_size: int = 32
    epochs: int = 30
    triplet_margin: float = 1.0
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


def _build_encoder(cfg: ContrastiveConfig):
    _require_torch()

    class _Encoder(nn.Module):
        def __init__(self, c: ContrastiveConfig):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(c.in_features, c.hidden_dim),
                nn.ReLU(),
                nn.Linear(c.hidden_dim, c.embedding_dim),
            )

        def forward(self, x):
            z = self.net(x)
            # L2-normalise so similarities are cosine-like
            return z / (z.norm(dim=-1, keepdim=True) + 1e-8)

    return _Encoder(cfg)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class ContrastiveStrategyEmbedder:
    """Triplet-loss encoder for strategies.

    Workflow::

        emb = ContrastiveStrategyEmbedder(ContrastiveConfig(in_features=6))
        emb.fit(triplets=(A, P, N))   # each (B, in_features)
        z = emb.embed(X)              # (N, embedding_dim)
        s = emb.similarity(X1, X2)    # cosine similarity
    """

    def __init__(self, config: Optional[ContrastiveConfig] = None):
        _require_torch()
        self.config = config if config is not None else ContrastiveConfig()
        if self.config.in_features < 1:
            raise ValueError("in_features must be >= 1")
        if self.config.embedding_dim < 2:
            raise ValueError("embedding_dim must be >= 2")
        if self.config.triplet_margin <= 0.0:
            raise ValueError("triplet_margin must be > 0")
        if self.config.seed is not None:
            torch.manual_seed(self.config.seed)
        self._encoder = _build_encoder(self.config)
        self._fitted = False

    # ------------------------------------------------------------------ helpers

    def _check_X(self, X: np.ndarray) -> None:
        if not isinstance(X, np.ndarray):
            raise TypeError("X must be a numpy ndarray")
        if X.ndim != 2 or X.shape[1] != self.config.in_features:
            raise ValueError(
                f"X must be 2-D with {self.config.in_features} features"
            )

    # ------------------------------------------------------------------ fit

    def fit(
        self,
        triplets: Tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> Dict[str, List[float]]:
        if not isinstance(triplets, tuple) or len(triplets) != 3:
            raise TypeError("triplets must be a tuple (anchor, positive, negative)")
        anchor, positive, negative = triplets
        for arr, name in [(anchor, "anchor"), (positive, "positive"), (negative, "negative")]:
            if not isinstance(arr, np.ndarray):
                raise TypeError(f"{name} must be a numpy ndarray")
        self._check_X(anchor)
        self._check_X(positive)
        self._check_X(negative)
        if not (anchor.shape[0] == positive.shape[0] == negative.shape[0]):
            raise ValueError("anchor/positive/negative must share first dim")

        a_t = torch.tensor(anchor, dtype=torch.float32)
        p_t = torch.tensor(positive, dtype=torch.float32)
        n_t = torch.tensor(negative, dtype=torch.float32)
        ds = TensorDataset(a_t, p_t, n_t)
        loader = DataLoader(ds, batch_size=self.config.batch_size, shuffle=True)
        opt = torch.optim.Adam(self._encoder.parameters(), lr=self.config.learning_rate)
        loss_fn = nn.TripletMarginLoss(margin=float(self.config.triplet_margin))
        history: Dict[str, List[float]] = {"loss": []}
        self._encoder.train()
        for _ in range(self.config.epochs):
            ep = 0.0
            nb = 0
            for ab, pb, nb_ in loader:
                opt.zero_grad()
                za = self._encoder(ab)
                zp = self._encoder(pb)
                zn = self._encoder(nb_)
                loss = loss_fn(za, zp, zn)
                loss.backward()
                opt.step()
                ep += float(loss.item())
                nb += 1
            history["loss"].append(ep / max(nb, 1))
        self._fitted = True
        return history

    # ------------------------------------------------------------------ embed

    def embed(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("call fit() before embed()")
        self._check_X(X)
        self._encoder.eval()
        with torch.no_grad():
            z = self._encoder(torch.tensor(X, dtype=torch.float32)).cpu().numpy()
        return z

    def similarity(self, X1: np.ndarray, X2: np.ndarray) -> np.ndarray:
        z1 = self.embed(X1)
        z2 = self.embed(X2)
        if z1.shape[0] != z2.shape[0]:
            raise ValueError("X1 and X2 must have the same number of rows")
        return (z1 * z2).sum(axis=-1)
