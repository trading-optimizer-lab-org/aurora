"""Spectral Risk Measures.

Reference: Acerbi (2002), "Spectral measures of risk: A coherent representation
of subjective risk aversion".

A spectral risk measure is M_phi(L) = integral_0^1 phi(p) * L_(p) dp where:
    - L_(p) is the p-quantile of losses (empirical inverse CDF),
    - phi(p) is a non-negative, non-decreasing, integrable risk-aversion
      weighting function with integral_0^1 phi(p) dp = 1.

Setting phi(p) = 1/(1-alpha) * 1{p >= alpha} recovers ES_alpha. Exponential
weighting phi(p) ~ exp(k*p) with k>0 emphasises the right tail more smoothly.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional

import math
import numpy as np


def exponential_phi(k: float = 10.0) -> Callable[[np.ndarray], np.ndarray]:
    """Exponential risk-aversion weighting.

    phi(p) = k * exp(k*(p-1)) / (1 - exp(-k))

    Normalised so that integral_0^1 phi(p) dp == 1. k > 0 places more weight
    on high quantiles (large losses).
    """
    if k <= 0:
        raise ValueError("k must be > 0 for exponential phi")
    norm = 1.0 - math.exp(-k)

    def phi(p: np.ndarray) -> np.ndarray:
        return k * np.exp(k * (p - 1.0)) / norm
    return phi


def power_phi(gamma: float = 2.0) -> Callable[[np.ndarray], np.ndarray]:
    """Power-law risk aversion phi(p) = (gamma + 1) * p**gamma. gamma > 0."""
    if gamma <= 0:
        raise ValueError("gamma must be > 0 for power phi")
    g1 = gamma + 1.0

    def phi(p: np.ndarray) -> np.ndarray:
        return g1 * np.power(p, gamma)
    return phi


@dataclass
class SpectralRiskMeasure:
    """Spectral risk measure with user-defined phi(p).

    Parameters
    ----------
    phi
        Callable phi(p) -> array, where p in [0,1]. If None, defaults to
        ``exponential_phi(k=10)``.
    n_grid
        Number of integration knots used for the trapezoidal sum in
        ``compute()``. Higher = smoother, slower.
    """
    phi: Optional[Callable[[np.ndarray], np.ndarray]] = None
    n_grid: int = 1000

    def __post_init__(self) -> None:
        if self.phi is None:
            self.phi = exponential_phi(k=10.0)
        if self.n_grid < 16:
            raise ValueError("n_grid must be >= 16")

    def compute(self, returns) -> float:
        """Empirical spectral risk on a 1-D returns vector. Reported as positive loss."""
        r = np.asarray(returns, dtype=float).ravel()
        r = r[~np.isnan(r)]
        if r.size == 0:
            return 0.0
        losses = np.sort(-r)  # ascending order: small loss -> large loss
        # Map quantile grid p in (0,1) onto sorted losses by index
        p = np.linspace(1.0 / self.n_grid, 1.0 - 1.0 / self.n_grid, self.n_grid)
        idx = np.clip((p * losses.size).astype(int), 0, losses.size - 1)
        L_p = losses[idx]
        w = self.phi(p)  # type: ignore[misc]
        # Re-normalise w on the discrete grid to integrate to 1 (defensive)
        w = w / np.trapezoid(w, p)
        return float(np.trapezoid(w * L_p, p))

    def allocate(self, returns_matrix) -> np.ndarray:
        """Inverse-spectral-risk weights across columns of (T, N)."""
        R = np.asarray(returns_matrix, dtype=float)
        if R.ndim != 2:
            raise ValueError("returns_matrix must be 2-D (T, N)")
        n = R.shape[1]
        if n == 0:
            return np.array([])
        risks = np.array([self.compute(R[:, j]) for j in range(n)])
        if not np.all(risks > 0):
            return np.full(n, 1.0 / n)
        inv = 1.0 / risks
        return inv / inv.sum()
