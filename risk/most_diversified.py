"""Most Diversified Portfolio (alternate parameterization).

Reference: Choueifaty & Coignard (2008); Choueifaty, Froidure & Reynier (2013).

Whereas :mod:`risk.max_diversification` implements the standard MDP via
projected gradient on the diversification ratio directly, this module casts
the problem as the equivalent QP in the *correlation* space:

    min_y   y^T C y
    s.t.    y >= 0,  sum(y) = 1

with the recovery w_i = (y_i / sigma_i) / sum_j (y_j / sigma_j). This form
admits a stable cyclical-coordinate-descent solver and tends to be robust
on near-singular covariance matrices.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np


@dataclass
class MostDiversifiedAlloc:
    """Diversification-ratio maximizer (correlation-space QP).

    Parameters
    ----------
    long_only
        If True, enforce y >= 0 (which is the canonical Choueifaty MDP).
    max_iter, tol
        Solver controls for the cyclic coordinate descent.
    """
    long_only: bool = True
    max_iter: int = 5000
    tol: float = 1e-10

    def __post_init__(self) -> None:
        if self.max_iter < 100:
            raise ValueError("max_iter must be >= 100")
        if self.tol <= 0:
            raise ValueError("tol must be > 0")

    def _solve_qp_corr(self, C: np.ndarray) -> np.ndarray:
        """Cyclic coordinate descent on min y^T C y s.t. simplex."""
        N = C.shape[0]
        y = np.full(N, 1.0 / N)
        for _ in range(self.max_iter):
            y_old = y.copy()
            for i in range(N):
                # Hold y_j (j!=i) fixed; analytic minimiser of quadratic in y_i
                grad_i = float(C[i] @ y)
                # Optimal step: y_i_new = y_i - grad_i / C[i,i]; project to >= 0
                step = grad_i / max(float(C[i, i]), 1e-12)
                y_i_new = y[i] - 0.5 * step
                if self.long_only:
                    y_i_new = max(y_i_new, 0.0)
                y[i] = y_i_new
            # Renormalise to the simplex after each sweep
            s = y.sum()
            if s <= 1e-12:
                y = np.full(N, 1.0 / N)
            else:
                y = y / s
            if np.linalg.norm(y - y_old) < self.tol:
                break
        return y

    def diversification_ratio(self, weights, cov) -> float:
        w = np.asarray(weights, dtype=float)
        Sigma = np.asarray(cov, dtype=float)
        sigma = np.sqrt(np.clip(np.diag(Sigma), 1e-16, None))
        pv = float(np.sqrt(max(w @ Sigma @ w, 1e-16)))
        return float((w @ sigma) / pv)

    def allocate(self, returns_matrix=None, cov=None) -> np.ndarray:
        if cov is None:
            if returns_matrix is None:
                raise ValueError("Provide returns_matrix or cov")
            R = np.asarray(returns_matrix, dtype=float)
            if R.ndim != 2:
                raise ValueError("returns_matrix must be 2-D")
            Sigma = np.atleast_2d(np.cov(R, rowvar=False, ddof=1))
        else:
            Sigma = np.atleast_2d(np.asarray(cov, dtype=float))
        N = Sigma.shape[0]
        if N == 0:
            return np.array([])
        if N == 1:
            return np.array([1.0])

        sigma = np.sqrt(np.clip(np.diag(Sigma), 1e-16, None))
        D_inv = 1.0 / sigma
        C = Sigma * np.outer(D_inv, D_inv)
        np.clip(C, -1.0, 1.0, out=C)
        # Symmetrize defensively
        C = 0.5 * (C + C.T)

        y = self._solve_qp_corr(C)
        # Recover w from y: w_i = (y_i / sigma_i) / sum_j (y_j / sigma_j)
        z = y / sigma
        s = z.sum()
        if s <= 1e-12:
            return np.full(N, 1.0 / N)
        return z / s
