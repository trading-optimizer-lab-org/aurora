"""Knowledge distillation: train a small student from a teacher's predictions.

Standard regression / soft-target distillation. The teacher can be any
callable that maps ``X (np.ndarray)`` -> ``np.ndarray`` of predictions; this
keeps the wrapper agnostic to whether the teacher is a torch model, a
scikit-learn estimator, or a closed-form function.

Lazy torch dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

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
            "aurora.ml.knowledge_distillation requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class DistillationConfig:
    """Hyperparameters for :class:`KnowledgeDistiller`."""
    in_features: int = 8
    student_hidden: int = 16
    out_dim: int = 1
    learning_rate: float = 1e-3
    batch_size: int = 32
    epochs: int = 20
    alpha: float = 0.5  # weight on hard target loss; (1-alpha) on soft (teacher)
    temperature: float = 1.0  # T > 1 softens regression targets / classification logits
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Student model
# ---------------------------------------------------------------------------


def _build_student(cfg: DistillationConfig):
    _require_torch()

    class _Student(nn.Module):
        def __init__(self, c: DistillationConfig):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(c.in_features, c.student_hidden),
                nn.ReLU(),
                nn.Linear(c.student_hidden, c.out_dim),
            )

        def forward(self, x):
            return self.net(x)

    return _Student(cfg)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class KnowledgeDistiller:
    """Distil a teacher into a smaller student MLP.

    Workflow::

        kd = KnowledgeDistiller(DistillationConfig(in_features=4))
        kd.fit(X_train, y_train, teacher=lambda X: rf.predict(X).reshape(-1, 1))
        y_hat = kd.predict(X_test)
    """

    def __init__(self, config: Optional[DistillationConfig] = None):
        _require_torch()
        self.config = config if config is not None else DistillationConfig()
        if self.config.in_features < 1:
            raise ValueError("in_features must be >= 1")
        if self.config.out_dim < 1:
            raise ValueError("out_dim must be >= 1")
        if not (0.0 <= self.config.alpha <= 1.0):
            raise ValueError("alpha must be in [0, 1]")
        if self.config.temperature <= 0.0:
            raise ValueError("temperature must be > 0")
        if self.config.seed is not None:
            torch.manual_seed(self.config.seed)
        self._student = _build_student(self.config)
        self._fitted = False

    # ------------------------------------------------------------------ helpers

    def _check_X(self, X: np.ndarray) -> None:
        if not isinstance(X, np.ndarray):
            raise TypeError("X must be a numpy ndarray")
        if X.ndim != 2:
            raise ValueError("X must be 2-D")
        if X.shape[1] != self.config.in_features:
            raise ValueError(
                f"X has {X.shape[1]} features, expected {self.config.in_features}"
            )

    # ------------------------------------------------------------------ fit

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        teacher: Callable[[np.ndarray], np.ndarray],
    ) -> Dict[str, List[float]]:
        self._check_X(X)
        if not callable(teacher):
            raise TypeError("teacher must be callable: f(X) -> np.ndarray")
        if not isinstance(y, np.ndarray):
            raise TypeError("y must be a numpy ndarray")
        if y.shape[0] != X.shape[0]:
            raise ValueError("X and y must have matching first dim")

        # Capture teacher predictions once (offline distillation)
        t_pred = teacher(X)
        if not isinstance(t_pred, np.ndarray):
            raise TypeError("teacher must return a numpy ndarray")
        t_pred = t_pred.reshape(-1, self.config.out_dim).astype(np.float32)
        y2 = y.reshape(-1, self.config.out_dim).astype(np.float32)
        # Apply temperature (soften targets)
        t_soft = t_pred / float(self.config.temperature)

        Xt = torch.tensor(X, dtype=torch.float32)
        yt = torch.tensor(y2, dtype=torch.float32)
        st = torch.tensor(t_soft, dtype=torch.float32)
        ds = TensorDataset(Xt, yt, st)
        loader = DataLoader(ds, batch_size=self.config.batch_size, shuffle=True)
        opt = torch.optim.Adam(self._student.parameters(), lr=self.config.learning_rate)
        loss_fn = nn.MSELoss()
        history: Dict[str, List[float]] = {"loss": [], "hard_loss": [], "soft_loss": []}
        self._student.train()
        for _ in range(self.config.epochs):
            ep_loss = ep_hard = ep_soft = 0.0
            nb = 0
            for xb, yb, sb in loader:
                opt.zero_grad()
                pred = self._student(xb)
                hard = loss_fn(pred, yb)
                soft = loss_fn(pred / float(self.config.temperature), sb)
                loss = self.config.alpha * hard + (1.0 - self.config.alpha) * soft
                loss.backward()
                opt.step()
                ep_loss += float(loss.item())
                ep_hard += float(hard.item())
                ep_soft += float(soft.item())
                nb += 1
            history["loss"].append(ep_loss / max(nb, 1))
            history["hard_loss"].append(ep_hard / max(nb, 1))
            history["soft_loss"].append(ep_soft / max(nb, 1))
        self._fitted = True
        return history

    # ------------------------------------------------------------------ predict

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("call fit() before predict()")
        self._check_X(X)
        self._student.eval()
        with torch.no_grad():
            out = self._student(torch.tensor(X, dtype=torch.float32)).cpu().numpy()
        if self.config.out_dim == 1:
            return out.reshape(-1)
        return out
