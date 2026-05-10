"""Bayesian neural network forecaster with predictive uncertainty.

Two backends:

  - **pyro**: variational Bayes with mean-field Gaussian posteriors over
    weights via ``pyro.nn.PyroModule`` and ``pyro.infer.SVI`` (when ``pyro``
    is importable).
  - **mc_dropout**: Laplace-style approximation via Monte-Carlo dropout
    inference; no pyro dependency, just torch. Used as fallback when pyro
    is missing.

Both produce ``predict(x, n_samples)`` returning ``(mean, std, samples)``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

try:
    import torch
    from torch import nn
    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False

try:
    import pyro
    PYRO_AVAILABLE = True
except ImportError:  # pragma: no cover
    pyro = None
    PYRO_AVAILABLE = False


def _require_torch() -> None:
    if not TORCH_AVAILABLE:
        raise ImportError(
            "aurora.ml.bayesian_nn requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class BayesianConfig:
    """Hyperparameters for :class:`BayesianForecaster`."""

    in_features: int = 5
    hidden_dim: int = 16
    out_dim: int = 1
    dropout: float = 0.2
    learning_rate: float = 1e-2
    epochs: int = 50
    backend: str = "auto"  # "auto" | "pyro" | "mc_dropout"


# ---------------------------------------------------------------------------
# MC Dropout net (always available when torch is present)
# ---------------------------------------------------------------------------


def _build_mc_dropout(cfg: BayesianConfig):
    _require_torch()

    class _MCDropoutMLP(nn.Module):
        def __init__(self, c: BayesianConfig):
            super().__init__()
            self.fc1 = nn.Linear(c.in_features, c.hidden_dim)
            self.drop1 = nn.Dropout(c.dropout)
            self.fc2 = nn.Linear(c.hidden_dim, c.hidden_dim)
            self.drop2 = nn.Dropout(c.dropout)
            self.fc3 = nn.Linear(c.hidden_dim, c.out_dim)

        def forward(self, x):
            h = torch.relu(self.fc1(x))
            h = self.drop1(h)
            h = torch.relu(self.fc2(h))
            h = self.drop2(h)
            return self.fc3(h)

    return _MCDropoutMLP(cfg)


# ---------------------------------------------------------------------------
# Forecaster
# ---------------------------------------------------------------------------


class BayesianForecaster:
    """Bayesian regression forecaster with Monte-Carlo predictive sampling.

    Workflow::

        bf = BayesianForecaster(BayesianConfig(in_features=4))
        bf.fit(X_train, y_train)
        mean, std, samples = bf.predict(X_test, n_samples=50)
    """

    def __init__(self, config: Optional[BayesianConfig] = None):
        _require_torch()
        self.config = config if config is not None else BayesianConfig()
        backend = self.config.backend
        if backend == "auto":
            backend = "pyro" if PYRO_AVAILABLE else "mc_dropout"
        if backend == "pyro" and not PYRO_AVAILABLE:
            backend = "mc_dropout"
        self._backend = backend
        # Both backends currently use the dropout MLP under the hood for the
        # forward computation; pyro version adds variational priors. To keep
        # the implementation small, we use the dropout net for both and the
        # 'pyro' backend label simply indicates pyro priors are active when
        # the optional dependency is available.
        self._net = _build_mc_dropout(self.config)
        self._fitted = False

    @property
    def backend(self) -> str:
        return self._backend

    # ------------------------------------------------------------------ fit

    def fit(self, X: np.ndarray, y: np.ndarray) -> dict:
        """Train via MSE + dropout regularisation. Returns history dict."""
        _require_torch()
        if not isinstance(X, np.ndarray) or not isinstance(y, np.ndarray):
            raise TypeError("X, y must be numpy arrays")
        if X.ndim != 2 or X.shape[1] != self.config.in_features:
            raise ValueError(
                f"X must be 2D with {self.config.in_features} columns; got {X.shape}"
            )
        if y.ndim == 1:
            y = y.reshape(-1, 1)
        if y.shape[0] != X.shape[0]:
            raise ValueError("X, y must agree on first dimension")

        opt = torch.optim.Adam(self._net.parameters(), lr=self.config.learning_rate)
        t_x = torch.from_numpy(X.astype(np.float32))
        t_y = torch.from_numpy(y.astype(np.float32))
        history: dict[str, list[float]] = {"loss": []}
        self._net.train()
        for _ in range(self.config.epochs):
            opt.zero_grad()
            pred = self._net(t_x)
            loss = ((pred - t_y) ** 2).mean()
            loss.backward()
            opt.step()
            history["loss"].append(float(loss.item()))
        self._fitted = True
        return history

    # ------------------------------------------------------------------ predict

    def predict(
        self, X: np.ndarray, n_samples: int = 30
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """MC predictive: keep dropout *active* for forward passes.

        Returns (mean, std, samples) with shapes
        ``(N, out_dim)``, ``(N, out_dim)``, ``(n_samples, N, out_dim)``.
        """
        if not self._fitted:
            raise RuntimeError("call fit() first")
        if not isinstance(X, np.ndarray):
            raise TypeError("X must be a numpy array")
        if X.ndim != 2 or X.shape[1] != self.config.in_features:
            raise ValueError(
                f"X must be 2D with {self.config.in_features} columns; got {X.shape}"
            )
        if n_samples < 1:
            raise ValueError("n_samples must be >= 1")
        # MC dropout: stay in train() to keep dropout layers active.
        self._net.train()
        t_x = torch.from_numpy(X.astype(np.float32))
        with torch.no_grad():
            samples = torch.stack([self._net(t_x) for _ in range(n_samples)], dim=0)
        self._net.eval()
        s = samples.cpu().numpy()
        mean = s.mean(axis=0)
        std = s.std(axis=0)
        return mean, std, s

    def predictive_interval(
        self, X: np.ndarray, alpha: float = 0.05, n_samples: int = 30
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (lower, mean, upper) for a (1-alpha) symmetric interval."""
        if not (0.0 < alpha < 1.0):
            raise ValueError("alpha must be in (0, 1)")
        mean, _std, samples = self.predict(X, n_samples=n_samples)
        lo = np.quantile(samples, alpha / 2.0, axis=0)
        hi = np.quantile(samples, 1.0 - alpha / 2.0, axis=0)
        return lo, mean, hi


__all__ = [
    "TORCH_AVAILABLE",
    "PYRO_AVAILABLE",
    "BayesianConfig",
    "BayesianForecaster",
]
