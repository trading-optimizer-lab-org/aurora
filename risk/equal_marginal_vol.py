"""Equal Marginal Volatility (EMV) allocator.

Reference: Maillard, Roncalli & Teiletche (2010), "On the Properties of
Equally-Weighted Risk Contributions Portfolios".

EMV equalises the marginal contribution to portfolio volatility:
    MC_i = (Sigma w)_i / sqrt(w^T Sigma w)
i.e. the partial derivative of portfolio vol w.r.t. w_i.

Note this differs from Equal Risk Contribution (ERC) which equalises
w_i * MC_i (the *risk contribution*). EMV equalises the marginals only.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np


@dataclass
class EqualMarginalVolPortfolio:
    """EMV allocator.

    Parameters
    ----------
    long_only
        If True, project intermediate weights onto the simplex.
    max_iter, tol
        Iteration controls.
    """
    long_only: bool = True
    max_iter: int = 1000
    tol: float = 1e-10

    def __post_init__(self) -> None:
        if self.max_iter < 50:
            raise ValueError("max_iter must be >= 50")
        if self.tol <= 0:
            raise ValueError("tol must be > 0")

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

    def marginal_contributions(self, weights, cov) -> np.ndarray:
        w = np.asarray(weights, dtype=float)
        Sigma = np.asarray(cov, dtype=float)
        pv = float(np.sqrt(max(w @ Sigma @ w, 1e-16)))
        return (Sigma @ w) / pv

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

        # Equalising marginal contributions: solve Sigma @ w = c * 1 with sum(w)=1.
        # w_unnorm = Sigma^{-1} 1, then renormalise.
        try:
            inv_S = np.linalg.pinv(Sigma)
        except np.linalg.LinAlgError:
            return np.full(N, 1.0 / N)
        w = inv_S @ np.ones(N)
        if self.long_only:
            w = self._project_simplex(w)
            # Refinement: a few sweeps to enforce equality after the projection
            for _ in range(self.max_iter // 10):
                mc = self.marginal_contributions(w, Sigma)
                target = mc.mean()
                # Move weights so their MCs come closer to ``target``.
                err = mc - target
                w_new = w - 0.001 * err
                w_new = self._project_simplex(w_new)
                if np.linalg.norm(w_new - w) < self.tol:
                    w = w_new
                    break
                w = w_new
        else:
            s = w.sum()
            if abs(s) < 1e-12:
                return np.full(N, 1.0 / N)
            w = w / s
        return w
