"""Curriculum learning: easy-to-hard sample ordering.

Ranks training examples by a user-supplied ``difficulty_score`` (smaller =
easier) and exposes an iterator that grows the training pool over time. This
is the "static curriculum" variant: difficulty is computed once up-front, and
the schedule controls how much of the pool is visible at each epoch.

Pure NumPy. No heavy deps.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class CurriculumConfig:
    """Hyperparameters for :class:`CurriculumScheduler`."""
    n_epochs: int = 10
    start_fraction: float = 0.2  # initial visible fraction of the pool
    end_fraction: float = 1.0    # final visible fraction
    pacing: str = "linear"        # linear | quadratic | exponential
    seed: Optional[int] = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pacing_fraction(epoch: int, total: int, start: float, end: float, mode: str) -> float:
    if total <= 1:
        t = 1.0
    else:
        t = epoch / float(total - 1)
    t = max(0.0, min(1.0, t))
    if mode == "linear":
        f = start + (end - start) * t
    elif mode == "quadratic":
        f = start + (end - start) * (t ** 2)
    elif mode == "exponential":
        # Smooth exponential ramp
        f = start + (end - start) * (1.0 - np.exp(-3.0 * t)) / (1.0 - np.exp(-3.0))
    else:
        raise ValueError(f"unknown pacing '{mode}'")
    return float(max(0.0, min(1.0, f)))


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class CurriculumScheduler:
    """Difficulty-ordered sampler.

    Workflow::

        cs = CurriculumScheduler(CurriculumConfig(n_epochs=20))
        cs.fit(X, y, difficulty_score=fn)            # ranks samples once
        for X_e, y_e in cs.iter_epochs():
            train_one_epoch(model, X_e, y_e)
    """

    def __init__(self, config: Optional[CurriculumConfig] = None):
        self.config = config if config is not None else CurriculumConfig()
        if self.config.n_epochs < 1:
            raise ValueError("n_epochs must be >= 1")
        if not (0.0 < self.config.start_fraction <= 1.0):
            raise ValueError("start_fraction must be in (0, 1]")
        if not (0.0 < self.config.end_fraction <= 1.0):
            raise ValueError("end_fraction must be in (0, 1]")
        if self.config.start_fraction > self.config.end_fraction:
            raise ValueError("start_fraction must be <= end_fraction")
        self._rng = np.random.default_rng(self.config.seed)
        self._sorted_idx: Optional[np.ndarray] = None
        self._X: Optional[np.ndarray] = None
        self._y: Optional[np.ndarray] = None

    # ------------------------------------------------------------------ fit

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        difficulty_score: Callable[[np.ndarray, np.ndarray], np.ndarray],
    ) -> "CurriculumScheduler":
        if not isinstance(X, np.ndarray) or not isinstance(y, np.ndarray):
            raise TypeError("X and y must be numpy ndarrays")
        if X.shape[0] != y.shape[0]:
            raise ValueError("X and y must have matching first dim")
        if not callable(difficulty_score):
            raise TypeError("difficulty_score must be callable")
        scores = difficulty_score(X, y)
        if not isinstance(scores, np.ndarray):
            raise TypeError("difficulty_score must return a numpy ndarray")
        if scores.shape[0] != X.shape[0]:
            raise ValueError("difficulty_score returned wrong length")
        self._sorted_idx = np.argsort(scores, kind="stable").astype(np.int64)
        self._X = X
        self._y = y
        return self

    # ------------------------------------------------------------------ iterate

    def fraction_at(self, epoch: int) -> float:
        if epoch < 0 or epoch >= self.config.n_epochs:
            raise ValueError("epoch out of range")
        return _pacing_fraction(
            epoch,
            self.config.n_epochs,
            self.config.start_fraction,
            self.config.end_fraction,
            self.config.pacing,
        )

    def visible_indices(self, epoch: int) -> np.ndarray:
        if self._sorted_idx is None:
            raise RuntimeError("call fit() before visible_indices()")
        n = self._sorted_idx.shape[0]
        f = self.fraction_at(epoch)
        k = max(1, int(round(f * n)))
        return self._sorted_idx[:k].copy()

    def iter_epochs(self) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        if self._X is None or self._y is None or self._sorted_idx is None:
            raise RuntimeError("call fit() before iter_epochs()")
        for ep in range(self.config.n_epochs):
            idx = self.visible_indices(ep)
            self._rng.shuffle(idx)
            yield self._X[idx], self._y[idx]
