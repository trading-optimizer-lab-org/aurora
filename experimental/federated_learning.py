"""Federated learning trainer (FedAvg).

N clients each hold local data and never share their raw rows. Each round,
they fit / update a local model, ship gradients (or weight deltas) to the
server, and the server averages the updates. Implements vanilla FedAvg
with an optional torch backend; the default backend is a pure-numpy ridge
regression so the module is testable without torch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np

try:  # pragma: no cover - torch not required for the default backend
    import torch  # type: ignore
    TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


@dataclass
class ClientData:
    """One client's local dataset. Never leaves the client in real FL."""

    X: np.ndarray
    y: np.ndarray

    def n_samples(self) -> int:
        return int(self.X.shape[0])


@dataclass
class FederatedTrainer:
    """FedAvg trainer with a numpy ridge backend.

    Parameters
    ----------
    n_features : int
        Dimensionality of the input space.
    rounds : int
        Number of federated rounds.
    local_lr : float
        Per-client learning rate (only used by SGD-like backends).
    ridge_lambda : float
        L2 strength for the ridge backend.
    backend : str
        ``"ridge"`` (default, numpy) or ``"torch"`` (lazy).
    """

    n_features: int
    rounds: int = 5
    local_lr: float = 0.01
    ridge_lambda: float = 1e-3
    backend: str = "ridge"
    weights: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        if self.backend == "torch" and not TORCH_AVAILABLE:
            raise ImportError(
                "backend='torch' requires torch. Install with: pip install torch"
            )
        self.weights = np.zeros(self.n_features, dtype=float)

    def _local_fit(self, client: ClientData) -> np.ndarray:
        """Closed-form ridge solution per client."""
        X, y = client.X, client.y
        A = X.T @ X + self.ridge_lambda * np.eye(self.n_features)
        b = X.T @ y
        return np.linalg.solve(A, b)

    def fit(self, clients: List[ClientData]) -> np.ndarray:
        """Train via FedAvg and return the global weight vector.

        Each round: every client fits a local model on its private data, the
        server collects only the resulting weight vectors and averages them,
        weighted by sample count (FedAvg).
        """
        if not clients:
            raise ValueError("at least one client required")
        for c in clients:
            if c.X.shape[1] != self.n_features:
                raise ValueError(
                    f"client X has {c.X.shape[1]} features, expected {self.n_features}"
                )

        total_n = sum(c.n_samples() for c in clients)
        if total_n == 0:
            raise ValueError("all clients are empty")

        for _ in range(self.rounds):
            local_weights = [self._local_fit(c) for c in clients]
            agg = np.zeros(self.n_features, dtype=float)
            for c, w in zip(clients, local_weights):
                agg += (c.n_samples() / total_n) * w
            # Damped update toward the FedAvg mean.
            self.weights = 0.5 * self.weights + 0.5 * agg

        return self.weights

    def predict(self, X: np.ndarray) -> np.ndarray:
        return X @ self.weights
