"""Quantum portfolio optimizer placeholder.

Stub for the post-NISQ era. Wraps qiskit lazily and exposes a QAOA-style
interface for portfolio allocation, but falls back to a classical CVaR
linear program (or mean-variance closed form) when qiskit is absent. The
intent is to give downstream code a stable API today while leaving the
quantum backend pluggable tomorrow.

Theoretical advantage
---------------------
Portfolio selection over N discrete asset bundles is a QUBO (quadratic
unconstrained binary optimization). On a fault-tolerant quantum computer,
QAOA / quantum annealing in principle provides a quadratic speedup over
brute force search and may find higher-quality minima for non-convex,
cardinality-constrained allocations than the classical convex relaxation.
In practice, today's NISQ hardware is dominated by noise; the classical
fallback is what actually runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:  # pragma: no cover - exercised only when qiskit is installed
    import qiskit  # type: ignore
    QISKIT_AVAILABLE = True
except ImportError:
    qiskit = None  # type: ignore[assignment]
    QISKIT_AVAILABLE = False


@dataclass
class QuantumPortfolioOptimizer:
    """QAOA-like portfolio optimizer with classical fallback.

    Parameters
    ----------
    risk_aversion : float
        Mean-variance lambda. Higher = more risk averse.
    qaoa_layers : int
        Number of QAOA layers (p). Ignored in classical fallback.
    seed : int
        RNG seed for reproducibility of the fallback path.
    """

    risk_aversion: float = 1.0
    qaoa_layers: int = 1
    seed: int = 42
    backend: str = field(init=False)

    def __post_init__(self) -> None:
        self.backend = "qiskit" if QISKIT_AVAILABLE else "classical"

    def optimize(self, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
        """Return long-only weights summing to 1.

        Uses the classical mean-variance closed form when qiskit is unavailable
        (which is always the case in CI).
        """
        mu = np.asarray(mu, dtype=float)
        sigma = np.asarray(sigma, dtype=float)
        n = mu.shape[0]
        if sigma.shape != (n, n):
            raise ValueError(f"sigma must be {n}x{n}, got {sigma.shape}")

        if self.backend == "qiskit":  # pragma: no cover - quantum path not on CI
            return self._optimize_qaoa(mu, sigma)
        return self._optimize_classical(mu, sigma)

    def _optimize_classical(self, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
        # Tikhonov-regularized mean-variance, projected to the simplex.
        n = mu.shape[0]
        reg = sigma + 1e-6 * np.eye(n)
        try:
            inv = np.linalg.inv(reg)
        except np.linalg.LinAlgError:
            inv = np.linalg.pinv(reg)
        raw = inv @ mu / max(self.risk_aversion, 1e-9)
        # project to long-only simplex
        w = np.clip(raw, 0.0, None)
        s = w.sum()
        if s <= 0:
            return np.full(n, 1.0 / n)
        return w / s

    def _optimize_qaoa(self, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:  # pragma: no cover
        # Placeholder for a real QAOA construction (operator + ansatz +
        # variational eigensolver). Not exercised in the test suite because
        # qiskit isn't installed in CI.
        return self._optimize_classical(mu, sigma)
