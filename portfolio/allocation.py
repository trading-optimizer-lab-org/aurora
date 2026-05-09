# ruff: noqa: N806
"""Portfolio allocator base class plus simple baselines.

The ``PortfolioOptimizer`` ABC defines the minimal sklearn-style interface:

- ``fit(returns)`` learns weights from a (T, N) return matrix
- ``predict()`` returns the weight vector
- ``summary()`` returns a small dict of summary stats

Concrete baselines:
- ``EqualWeightAllocator``
- ``InverseVolAllocator`` (weights ~ 1/vol)
- ``CashAllocator`` (single cash bucket)
- ``BenchmarkTrackerAllocator`` (matches given benchmark weights)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

import numpy as np


class PortfolioOptimizer(ABC):
    """Abstract base for portfolio allocators."""

    def __init__(self) -> None:
        self._weights: np.ndarray | None = None
        self._fitted: bool = False
        self._n_assets: int = 0

    @abstractmethod
    def fit(self, returns: np.ndarray) -> PortfolioOptimizer:
        """Fit the allocator on a (T, N) return matrix.

        Subclasses set ``self._weights`` and ``self._fitted = True`` and
        return ``self`` for chaining.
        """

    def predict(self) -> np.ndarray:
        """Return the fitted weight vector."""
        if not self._fitted or self._weights is None:
            raise RuntimeError("call fit() before predict()")
        return self._weights.copy()

    def summary(self) -> dict[str, float]:
        """Return a small dict of weight stats for reports."""
        if not self._fitted or self._weights is None:
            return {"n_assets": 0.0}
        w = self._weights
        return {
            "n_assets": float(w.size),
            "sum": float(w.sum()),
            "min": float(w.min()),
            "max": float(w.max()),
            "gross_exposure": float(np.sum(np.abs(w))),
            "concentration": float(np.sum(w * w)),
        }


class EqualWeightAllocator(PortfolioOptimizer):
    """1/N over the columns of ``returns``."""

    def fit(self, returns: np.ndarray) -> EqualWeightAllocator:
        R = _check_returns_matrix(returns)
        n = R.shape[1]
        if n == 0:
            self._weights = np.array([], dtype=float)
        else:
            self._weights = np.full(n, 1.0 / n, dtype=float)
        self._n_assets = n
        self._fitted = True
        return self


class InverseVolAllocator(PortfolioOptimizer):
    """Weights proportional to 1 / std(returns).

    Fallback to equal weight when all volatilities are zero or NaN.
    """

    def __init__(self, eps: float = 1e-12) -> None:
        super().__init__()
        if eps <= 0:
            raise ValueError("eps must be > 0")
        self.eps = float(eps)

    def fit(self, returns: np.ndarray) -> InverseVolAllocator:
        R = _check_returns_matrix(returns)
        n = R.shape[1]
        self._n_assets = n
        if n == 0:
            self._weights = np.array([], dtype=float)
            self._fitted = True
            return self

        if R.shape[0] < 2:
            self._weights = np.full(n, 1.0 / n, dtype=float)
            self._fitted = True
            return self

        std = np.std(R, axis=0, ddof=1)
        std = np.where(np.isfinite(std), std, 0.0)
        # Avoid div-by-zero -- floor with eps before inverting.
        inv = 1.0 / np.maximum(std, self.eps)
        s = inv.sum()
        if s <= 0:
            self._weights = np.full(n, 1.0 / n, dtype=float)
        else:
            self._weights = inv / s
        self._fitted = True
        return self


class CashAllocator(PortfolioOptimizer):
    """Allocate everything to cash (a single zero-return bucket).

    The cash bucket is appended as the last column conceptually, but the
    weight vector returned matches the asset count of the input matrix --
    a zero vector that signals 'fully in cash'. Sum of returned weights
    is 0; the implicit cash share is 1 - sum(weights).
    """

    def fit(self, returns: np.ndarray) -> CashAllocator:
        R = _check_returns_matrix(returns)
        n = R.shape[1]
        self._n_assets = n
        self._weights = np.zeros(n, dtype=float)
        self._fitted = True
        return self


class BenchmarkTrackerAllocator(PortfolioOptimizer):
    """Match a given benchmark weight vector exactly.

    Useful as a control allocator: optimisers should beat this on
    risk-adjusted metrics, otherwise they are just adding cost.
    """

    def __init__(self, benchmark_weights: Sequence[float]) -> None:
        super().__init__()
        bench = np.asarray(benchmark_weights, dtype=float).ravel()
        if bench.size == 0:
            raise ValueError("benchmark_weights must be non-empty")
        if not np.all(np.isfinite(bench)):
            raise ValueError("benchmark_weights must be finite")
        self._benchmark = bench

    def fit(self, returns: np.ndarray) -> BenchmarkTrackerAllocator:
        R = _check_returns_matrix(returns)
        n = R.shape[1]
        if n != self._benchmark.size:
            raise ValueError(
                f"returns has {n} assets, benchmark has "
                f"{self._benchmark.size}"
            )
        self._weights = self._benchmark.copy()
        self._n_assets = n
        self._fitted = True
        return self


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _check_returns_matrix(returns) -> np.ndarray:
    """Validate the (T, N) return matrix and return as float ndarray."""
    R = np.asarray(returns, dtype=float)
    if R.ndim == 1:
        # Treat a 1-D vector as a single asset (T,) -> (T, 1)
        R = R.reshape(-1, 1)
    if R.ndim != 2:
        raise ValueError(f"returns must be 1-D or 2-D, got {R.ndim}-D")
    if not np.all(np.isfinite(R)) and R.size > 0:
        # Down-stream allocators tolerate this (they ravel + drop NaN);
        # leave it alone here so InverseVolAllocator can still fall back.
        pass
    return R
