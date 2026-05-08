"""Few-shot strategy classification with Prototypical Networks.

Each "class" is a regime (or any strategy family). For each regime, the
caller supplies ``K`` example feature vectors (the "support set"). At
inference time, a new query vector is classified by nearest-prototype
distance, where the prototype is the mean of the support embeddings.

The encoder is a small MLP. With ``embedding_dim == in_features`` and the
identity initialisation, the wrapper degenerates to a NumPy nearest-mean
classifier, which is useful as a baseline.

Lazy torch dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import torch  # type: ignore
    from torch import nn  # type: ignore
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "quantforge.ml.few_shot_strategy requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class FewShotConfig:
    in_features: int = 8
    embedding_dim: int = 16
    hidden_dim: int = 32
    learning_rate: float = 1e-3
    epochs: int = 30
    n_episodes: int = 50  # episodes per epoch during meta-training
    n_way: int = 3
    k_shot: int = 5
    q_query: int = 5
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


def _build_encoder(cfg: FewShotConfig):
    _require_torch()

    class _Encoder(nn.Module):
        def __init__(self, c: FewShotConfig):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(c.in_features, c.hidden_dim),
                nn.ReLU(),
                nn.Linear(c.hidden_dim, c.embedding_dim),
            )

        def forward(self, x):
            return self.net(x)

    return _Encoder(cfg)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class FewShotStrategyAdapter:
    """ProtoNet-style few-shot regime classifier.

    Workflow::

        fs = FewShotStrategyAdapter(FewShotConfig(in_features=4))
        fs.fit({"bull": X_bull, "bear": X_bear, "flat": X_flat})
        labels = fs.predict(X_new)   # ("bull", "bear", ...)
    """

    def __init__(self, config: Optional[FewShotConfig] = None):
        _require_torch()
        self.config = config if config is not None else FewShotConfig()
        if self.config.in_features < 1:
            raise ValueError("in_features must be >= 1")
        if self.config.embedding_dim < 2:
            raise ValueError("embedding_dim must be >= 2")
        if self.config.k_shot < 1:
            raise ValueError("k_shot must be >= 1")
        if self.config.n_way < 2:
            raise ValueError("n_way must be >= 2")
        if self.config.seed is not None:
            torch.manual_seed(self.config.seed)
            self._rng = np.random.default_rng(self.config.seed)
        else:
            self._rng = np.random.default_rng()
        self._encoder = _build_encoder(self.config)
        self._labels: List[str] = []
        self._prototypes: Optional[np.ndarray] = None  # (n_classes, embedding_dim)
        self._fitted = False

    # ------------------------------------------------------------------ helpers

    def _check_X(self, X: np.ndarray, name: str = "X") -> None:
        if not isinstance(X, np.ndarray):
            raise TypeError(f"{name} must be a numpy ndarray")
        if X.ndim != 2 or X.shape[1] != self.config.in_features:
            raise ValueError(
                f"{name} must be 2-D with {self.config.in_features} features"
            )

    # ------------------------------------------------------------------ fit

    def fit(
        self,
        support_by_label: Dict[str, np.ndarray],
    ) -> Dict[str, List[float]]:
        """Meta-train + register prototypes from a dict of regime -> samples."""
        if not isinstance(support_by_label, dict) or len(support_by_label) < 2:
            raise ValueError("support_by_label must contain >= 2 classes")
        for lbl, arr in support_by_label.items():
            if not isinstance(lbl, str):
                raise TypeError("labels must be strings")
            self._check_X(arr, name=f"support[{lbl}]")
            if arr.shape[0] < self.config.k_shot:
                raise ValueError(
                    f"class '{lbl}' has {arr.shape[0]} samples, need >= k_shot={self.config.k_shot}"
                )
        labels = list(support_by_label.keys())
        n_classes = len(labels)
        n_way = min(self.config.n_way, n_classes)
        opt = torch.optim.Adam(self._encoder.parameters(), lr=self.config.learning_rate)
        history: Dict[str, List[float]] = {"loss": []}
        loss_fn = nn.CrossEntropyLoss()
        self._encoder.train()
        for _ in range(self.config.epochs):
            ep = 0.0
            for _ep_i in range(self.config.n_episodes):
                # Sample a n_way subset for this episode
                way_labels = list(self._rng.choice(labels, size=n_way, replace=False))
                supports = []
                queries = []
                query_labels: List[int] = []
                for ci, lbl in enumerate(way_labels):
                    pool = support_by_label[lbl]
                    n_pool = pool.shape[0]
                    take = min(n_pool, self.config.k_shot + self.config.q_query)
                    perm = self._rng.permutation(n_pool)[:take]
                    sup_idx = perm[: self.config.k_shot]
                    q_idx = perm[self.config.k_shot:]
                    supports.append(pool[sup_idx])
                    if len(q_idx) > 0:
                        queries.append(pool[q_idx])
                        query_labels.extend([ci] * len(q_idx))
                if not queries:
                    continue
                support_t = torch.tensor(np.stack(supports), dtype=torch.float32)
                query_t = torch.tensor(np.concatenate(queries, axis=0), dtype=torch.float32)
                ql = torch.tensor(query_labels, dtype=torch.long)
                # Encode support and queries
                sup_z = self._encoder(support_t.view(-1, self.config.in_features)).view(
                    n_way, -1, self.config.embedding_dim
                )
                proto = sup_z.mean(dim=1)  # (n_way, embedding_dim)
                qz = self._encoder(query_t)  # (n_q, embedding_dim)
                # Negative squared euclidean distance as logits
                d2 = ((qz.unsqueeze(1) - proto.unsqueeze(0)) ** 2).sum(dim=-1)
                logits = -d2
                loss = loss_fn(logits, ql)
                opt.zero_grad()
                loss.backward()
                opt.step()
                ep += float(loss.item())
            history["loss"].append(ep / max(self.config.n_episodes, 1))
        # Compute final prototypes from full support set
        self._labels = labels
        self._encoder.eval()
        protos = []
        with torch.no_grad():
            for lbl in labels:
                arr = support_by_label[lbl]
                z = self._encoder(torch.tensor(arr, dtype=torch.float32)).cpu().numpy()
                protos.append(z.mean(axis=0))
        self._prototypes = np.stack(protos, axis=0)
        self._fitted = True
        return history

    # ------------------------------------------------------------------ predict

    def _embed(self, X: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            return self._encoder(torch.tensor(X, dtype=torch.float32)).cpu().numpy()

    def predict(self, X: np.ndarray) -> List[str]:
        if not self._fitted or self._prototypes is None:
            raise RuntimeError("call fit() before predict()")
        self._check_X(X)
        z = self._embed(X)
        # Squared euclidean distance to each prototype
        d2 = ((z[:, None, :] - self._prototypes[None, :, :]) ** 2).sum(axis=-1)
        idx = np.argmin(d2, axis=1)
        return [self._labels[i] for i in idx.tolist()]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted or self._prototypes is None:
            raise RuntimeError("call fit() before predict_proba()")
        self._check_X(X)
        z = self._embed(X)
        d2 = ((z[:, None, :] - self._prototypes[None, :, :]) ** 2).sum(axis=-1)
        logits = -d2
        # Softmax row-wise (numpy)
        m = logits.max(axis=1, keepdims=True)
        e = np.exp(logits - m)
        return e / e.sum(axis=1, keepdims=True)
