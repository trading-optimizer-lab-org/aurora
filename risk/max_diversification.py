"""Maximum Diversification Portfolio (MDP).

Reference: Choueifaty & Coignard (2008), "Toward Maximum Diversification".

The MDP maximises the Diversification Ratio
    DR(w) = (w^T sigma) / sqrt(w^T Sigma w)
subject to long-only and budget constraints. Equivalently, it minimises the
correlation between the portfolio and a synthetic vol-target portfolio,
maximising the use of diversification potential.

Closed-form (long-only): the MDP is the minimum-variance portfolio of the
*correlation* matrix C, rescaled by 1/sigma. We solve numerically with a
projected gradient method for robustness on degenerate covariances.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np


@dataclass
class MaxDiversificationPortfolio:
    """Choueifaty MDP (long-only by default).

    Parameters
    ----------
    long_only
        If True, project onto the simplex each step.
    max_iter, tol, lr
        Solver controls.
    """
    long_only: bool = True
    max_iter: int = 1000
    tol: float = 1e-9
    lr: float = 0.01

    def __post_init__(self) -> None:
        if self.max_iter < 50:
            raise ValueError("max_iter must be >= 50")
        if self.tol <= 0 or self.lr <= 0:
            raise ValueError("tol and lr must be > 0")

    @staticmethod
    def _project_simplex(w: np.ndarray) -> np.ndarray:
        n = w.size
        u = np.sort(w)[::-1]
        css = np.cumsum(u) - 1.0
        rho_idx = np.where(u - css / (np.arange(n) + 1) > 0)[0]
        if rho_idx.size == 0:
            return np.full(n, 1.0 / n)
        rho = rho_idx[-1]
        theta = css[rho] / (rho + 1)
        return np.maximum(w - theta, 0.0)

    def diversification_ratio(self, weights, cov) -> float:
        """DR(w) = sum(w_i * sigma_i) / sqrt(w^T Sigma w)."""
        w = np.asarray(weights, dtype=float)
        Sigma = np.asarray(cov, dtype=float)
        sigma = np.sqrt(np.clip(np.diag(Sigma), 1e-16, None))
        port_vol = float(np.sqrt(max(w @ Sigma @ w, 1e-16)))
        return float((w @ sigma) / port_vol)

    def allocate(self, returns_matrix=None, cov=None) -> np.ndarray:
        """Solve the MDP given a returns matrix or a precomputed covariance."""
        if cov is None:
            if returns_matrix is None:
                raise ValueError("Provide returns_matrix or cov")
            R = np.asarray(returns_matrix, dtype=float)
            if R.ndim != 2:
                raise ValueError("returns_matrix must be 2-D")
            Sigma = np.atleast_2d(np.cov(R, rowvar=False, ddof=1))
        else:
            Sigma = np.atleast_2d(np.asarray(cov, dtype=float))
            if Sigma.ndim != 2 or Sigma.shape[0] != Sigma.shape[1]:
                raise ValueError("cov must be square 2-D")
        N = Sigma.shape[0]
        if N == 0:
            return np.array([])
        if N == 1:
            return np.array([1.0])

        sigma = np.sqrt(np.clip(np.diag(Sigma), 1e-16, None))
        # Closed-form starting point: min-var of correlation matrix, then 1/sigma rescale
        D_inv = 1.0 / sigma
        Corr = Sigma * np.outer(D_inv, D_inv)
        try:
            inv_C = np.linalg.pinv(Corr)
            ones = np.ones(N)
            w0 = inv_C @ ones
            w0 = w0 / sigma
            if self.long_only:
                w0 = self._project_simplex(w0)
            else:
                s = w0.sum()
                w0 = w0 / s if abs(s) > 1e-12 else np.full(N, 1.0 / N)
        except np.linalg.LinAlgError:
            w0 = np.full(N, 1.0 / N)

        w = w0
        prev = -np.inf
        for _ in range(self.max_iter):
            num = float(w @ sigma)
            denom = float(np.sqrt(max(w @ Sigma @ w, 1e-16)))
            dr = num / denom
            # Gradient of DR(w):  d/dw [num/denom] = (sigma*denom - num*Sigma w/denom) / denom^2
            grad = (sigma * denom - num * (Sigma @ w) / denom) / (denom ** 2)
            w_new = w + self.lr * grad
            if self.long_only:
                w_new = self._project_simplex(w_new)
            else:
                s = w_new.sum()
                if abs(s) > 1e-12:
                    w_new = w_new / s
            if abs(dr - prev) < self.tol:
                w = w_new
                break
            prev = dr
            w = w_new
        return w
