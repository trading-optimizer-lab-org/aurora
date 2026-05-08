"""Active learning by uncertainty querying.

Wraps any model that provides a probability estimate (``predict_proba`` or
``decision_function``) and selects the *unlabeled* samples on which the model
is most uncertain. For pure regressors, an MC-dropout-style or ensemble-based
uncertainty function may be passed instead.

No heavy dependency: the wrapper is pure NumPy. The user-supplied model just
has to expose enough interface to score a row.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ActiveLearnerConfig:
    """Hyperparameters for :class:`ActiveLearner`."""
    query_size: int = 10
    strategy: str = "least_confident"  # least_confident | margin | entropy
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Uncertainty scoring
# ---------------------------------------------------------------------------


def _ensure_proba(p: np.ndarray) -> np.ndarray:
    """Coerce 1-D binary probability into 2-D shape ``(N, 2)``."""
    if p.ndim == 1:
        p = np.column_stack([1.0 - p, p])
    return p


def _least_confident(p: np.ndarray) -> np.ndarray:
    p = _ensure_proba(p)
    return 1.0 - p.max(axis=1)


def _margin(p: np.ndarray) -> np.ndarray:
    p = _ensure_proba(p)
    if p.shape[1] < 2:
        return np.zeros(p.shape[0])
    sorted_p = np.sort(p, axis=1)[:, ::-1]
    return -(sorted_p[:, 0] - sorted_p[:, 1])  # smaller margin -> higher uncertainty


def _entropy(p: np.ndarray) -> np.ndarray:
    p = _ensure_proba(p)
    eps = 1e-12
    return -(p * np.log(p + eps)).sum(axis=1)


_STRATEGIES: Dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "least_confident": _least_confident,
    "margin": _margin,
    "entropy": _entropy,
}


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class ActiveLearner:
    """Query-by-uncertainty selector.

    ``model`` must expose ``predict_proba(X) -> (N, n_classes)`` for the default
    scoring strategies. Alternatively, an explicit ``score_fn`` can be passed
    in :meth:`query` to customise uncertainty per problem.
    """

    def __init__(
        self,
        model: Any,
        config: Optional[ActiveLearnerConfig] = None,
    ):
        if model is None:
            raise ValueError("model must not be None")
        self.model = model
        self.config = config if config is not None else ActiveLearnerConfig()
        if self.config.query_size < 1:
            raise ValueError("query_size must be >= 1")
        if self.config.strategy not in _STRATEGIES:
            raise ValueError(
                f"unknown strategy '{self.config.strategy}'; "
                f"choose from {sorted(_STRATEGIES)}"
            )

    # ------------------------------------------------------------------ scoring

    def uncertainty_scores(
        self,
        X_pool: np.ndarray,
        score_fn: Optional[Callable[[np.ndarray], np.ndarray]] = None,
    ) -> np.ndarray:
        if not isinstance(X_pool, np.ndarray):
            raise TypeError("X_pool must be a numpy ndarray")
        if X_pool.ndim != 2:
            raise ValueError("X_pool must be 2-D")
        if score_fn is not None:
            scores = score_fn(X_pool)
            if not isinstance(scores, np.ndarray):
                raise TypeError("score_fn must return a numpy ndarray")
            if scores.shape[0] != X_pool.shape[0]:
                raise ValueError("score_fn returned wrong length")
            return scores.astype(np.float64)
        if not hasattr(self.model, "predict_proba"):
            raise AttributeError(
                "model lacks predict_proba; pass an explicit score_fn instead"
            )
        proba = np.asarray(self.model.predict_proba(X_pool))
        return _STRATEGIES[self.config.strategy](proba)

    # ------------------------------------------------------------------ query

    def query(
        self,
        X_pool: np.ndarray,
        score_fn: Optional[Callable[[np.ndarray], np.ndarray]] = None,
        query_size: Optional[int] = None,
    ) -> np.ndarray:
        """Return indices of the ``query_size`` most uncertain rows."""
        scores = self.uncertainty_scores(X_pool, score_fn=score_fn)
        k = query_size if query_size is not None else self.config.query_size
        if k < 1:
            raise ValueError("query_size must be >= 1")
        k = min(k, X_pool.shape[0])
        # Highest score == most uncertain
        idx = np.argsort(-scores)[:k]
        return idx.astype(np.int64)
