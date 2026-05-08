"""MAML-style meta-learning across regimes.

Each "task" is one regime (e.g. low-vol vs high-vol, bull vs bear). The
meta-learner maintains a single set of initial weights that, after a small
number of gradient steps on a regime's support set, performs well on that
regime's query set.

Algorithm (first-order MAML):

  for each meta_step:
      sample a batch of tasks (regimes)
      for each task:
          theta'  = theta - inner_lr * grad_support(theta)
          loss_q  = loss_query(theta')
          accumulate grad of loss_q w.r.t. theta
      theta <- theta - meta_lr * mean(accumulated grads)

Lazy torch dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

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
            "quantforge.ml.meta_learning requires torch. "
            "Install with: pip install torch"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class MetaConfig:
    in_features: int = 4
    hidden_dim: int = 16
    out_dim: int = 1
    inner_lr: float = 1e-2
    meta_lr: float = 1e-3
    inner_steps: int = 1
    meta_steps: int = 30


# ---------------------------------------------------------------------------
# Task definition
# ---------------------------------------------------------------------------


@dataclass
class Task:
    """One regime / task.

    Attributes
    ----------
    name: human-readable label.
    support_x, support_y: data used for the inner-loop adaptation step.
    query_x, query_y: data used for the meta-objective.
    """

    name: str
    support_x: np.ndarray
    support_y: np.ndarray
    query_x: np.ndarray
    query_y: np.ndarray


# ---------------------------------------------------------------------------
# Helpers (functional forward so we can do MAML by hand)
# ---------------------------------------------------------------------------


def _functional_forward(x, params: List["torch.Tensor"]):
    """Two-layer MLP forward pass given parameter list ``[W1, b1, W2, b2]``.

    Lets us compute gradients with respect to a *temporary* param tensor for
    the inner loop without rebuilding an nn.Module.
    """
    W1, b1, W2, b2 = params
    h = torch.relu(x @ W1 + b1)
    return h @ W2 + b2


def _init_params(cfg: MetaConfig, generator: "torch.Generator") -> List["torch.Tensor"]:
    """Xavier-init the four parameter tensors as leaves with grad enabled."""
    W1 = torch.empty(cfg.in_features, cfg.hidden_dim)
    nn.init.xavier_uniform_(W1, generator=generator)
    b1 = torch.zeros(cfg.hidden_dim)
    W2 = torch.empty(cfg.hidden_dim, cfg.out_dim)
    nn.init.xavier_uniform_(W2, generator=generator)
    b2 = torch.zeros(cfg.out_dim)
    out = []
    for t in (W1, b1, W2, b2):
        t = t.clone().detach().requires_grad_(True)
        out.append(t)
    return out


def _mse(pred, target):
    return ((pred - target) ** 2).mean()


# ---------------------------------------------------------------------------
# Meta-learner
# ---------------------------------------------------------------------------


class MetaLearner:
    """First-order MAML over user-supplied tasks (regimes)."""

    def __init__(self, config: Optional[MetaConfig] = None, seed: int = 42):
        _require_torch()
        self.config = config if config is not None else MetaConfig()
        self.seed = seed
        gen = torch.Generator()
        gen.manual_seed(seed)
        self._params = _init_params(self.config, gen)

    # ------------------------------------------------------------------ inner

    def _inner_adapt(
        self, support_x: "torch.Tensor", support_y: "torch.Tensor"
    ) -> List["torch.Tensor"]:
        """Run inner_steps gradient steps. Returns adapted parameter tensors.

        First-order MAML: we treat the inner-loop gradient as constant when
        computing the meta gradient.
        """
        adapted = [p.detach().clone().requires_grad_(True) for p in self._params]
        for _ in range(self.config.inner_steps):
            pred = _functional_forward(support_x, adapted)
            loss = _mse(pred, support_y)
            grads = torch.autograd.grad(loss, adapted)
            adapted = [
                (p - self.config.inner_lr * g).detach().requires_grad_(True)
                for p, g in zip(adapted, grads)
            ]
        return adapted

    # ------------------------------------------------------------------ fit

    def meta_fit(self, tasks: Sequence[Task]) -> Dict[str, List[float]]:
        """Run ``meta_steps`` outer iterations across the supplied tasks."""
        if not tasks:
            raise ValueError("must supply at least one Task")
        for t in tasks:
            if not isinstance(t, Task):
                raise TypeError("tasks must be Task instances")

        history = {"meta_loss": []}
        meta_opt = torch.optim.Adam(self._params, lr=self.config.meta_lr)
        for _ in range(self.config.meta_steps):
            meta_opt.zero_grad()
            total_loss = torch.tensor(0.0)
            for t in tasks:
                sx = torch.from_numpy(t.support_x.astype(np.float32))
                sy = torch.from_numpy(t.support_y.astype(np.float32))
                qx = torch.from_numpy(t.query_x.astype(np.float32))
                qy = torch.from_numpy(t.query_y.astype(np.float32))
                if sy.ndim == 1:
                    sy = sy.unsqueeze(-1)
                if qy.ndim == 1:
                    qy = qy.unsqueeze(-1)

                # First-order MAML: do inner adaptation, then evaluate query
                # loss as a function of the *base* params via fresh forward
                # using gradient-of-gradient approximation (we just evaluate
                # query loss using adapted params and treat its gradient as
                # an unbiased proxy for the meta gradient).
                with torch.enable_grad():
                    adapted = self._inner_adapt(sx, sy)
                    q_pred = _functional_forward(qx, adapted)
                    q_loss = _mse(q_pred, qy)
                    # Push the gradient back into base params via FOMAML:
                    # use adapted-params gradient as a stand-in for base.
                    base_grads = torch.autograd.grad(q_loss, adapted)
                for p, g in zip(self._params, base_grads):
                    if p.grad is None:
                        p.grad = g.detach().clone()
                    else:
                        p.grad = p.grad + g.detach()
                total_loss = total_loss + q_loss.detach()

            # average grads across tasks
            for p in self._params:
                if p.grad is not None:
                    p.grad /= len(tasks)
            meta_opt.step()
            history["meta_loss"].append(float(total_loss.item() / len(tasks)))
        return history

    # ------------------------------------------------------------------ adapt

    def adapt(self, support_x: np.ndarray, support_y: np.ndarray) -> List["torch.Tensor"]:
        """Return params adapted to a fresh regime (does not mutate base)."""
        if not isinstance(support_x, np.ndarray) or not isinstance(support_y, np.ndarray):
            raise TypeError("support_x and support_y must be numpy arrays")
        sx = torch.from_numpy(support_x.astype(np.float32))
        sy = torch.from_numpy(support_y.astype(np.float32))
        if sy.ndim == 1:
            sy = sy.unsqueeze(-1)
        return self._inner_adapt(sx, sy)

    # ------------------------------------------------------------------ predict

    def predict(self, x: np.ndarray, params: Optional[List["torch.Tensor"]] = None) -> np.ndarray:
        """Forward-pass prediction with either the meta params or adapted ones."""
        if not isinstance(x, np.ndarray):
            raise TypeError("x must be a numpy array")
        if x.ndim != 2 or x.shape[1] != self.config.in_features:
            raise ValueError(
                f"x must be 2D with {self.config.in_features} columns; got {x.shape}"
            )
        with torch.no_grad():
            t_x = torch.from_numpy(x.astype(np.float32))
            ps = params if params is not None else self._params
            return _functional_forward(t_x, ps).cpu().numpy()


__all__ = [
    "TORCH_AVAILABLE",
    "MetaConfig",
    "Task",
    "MetaLearner",
]
