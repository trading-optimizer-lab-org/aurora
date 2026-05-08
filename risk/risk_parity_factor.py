"""Factor Risk Parity — equalize risk contributions across PCA factors.

Reference: Meucci (2009), "Managing Diversification". Roncalli & Weisang (2016),
"Risk Parity Portfolios with Risk Factors".

Idea
----
Asset-level risk parity equalises sigma_i * w_i. Factor risk parity equalises
the risk contribution of each *factor* in a factor model. Here we use the
PCA factors of the asset return covariance: factors are the eigenvectors of
Sigma, factor variances are the eigenvalues lambda_k.

Workflow
--------
1. Sigma = empirical covariance of asset returns (T, N).
2. Eigendecompose Sigma = V * diag(lambda) * V^T  (V columns = factors).
3. Portfolio variance in factor space: sum_k lambda_k * (V_k^T w)^2.
4. Optimise w on the simplex so each factor contributes ~ equally.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np


@dataclass
class FactorRiskParity:
    """Risk parity by PCA factor exposure.

    Parameters
    ----------
    n_factors
        Number of leading PCA factors to equalise. If None, uses all factors.
    max_iter, tol
        Iterative solver controls.
    long_only
        If True, project intermediate weights onto the simplex each iteration.
    """
    n_factors: int | None = None
    max_iter: int = 500
    tol: float = 1e-9
    long_only: bool = True

    def __post_init__(self) -> None:
        if self.max_iter < 10:
            raise ValueError("max_iter must be >= 10")
        if self.tol <= 0:
            raise ValueError("tol must be > 0")

    @staticmethod
    def _project_simplex(w: np.ndarray) -> np.ndarray:
        # Euclidean projection onto the probability simplex (Wang & Carreira-Perpinan 2013)
        n = w.size
        u = np.sort(w)[::-1]
        css = np.cumsum(u) - 1.0
        rho_idx = np.where(u - css / (np.arange(n) + 1) > 0)[0]
        if rho_idx.size == 0:
            return np.full(n, 1.0 / n)
        rho = rho_idx[-1]
        theta = css[rho] / (rho + 1)
        return np.maximum(w - theta, 0.0)

    def allocate(self, returns_matrix) -> np.ndarray:
        """Compute factor-risk-parity weights from a (T, N) returns matrix."""
        R = np.asarray(returns_matrix, dtype=float)
        if R.ndim != 2:
            raise ValueError("returns_matrix must be 2-D (T, N)")
        T, N = R.shape
        if T < 2 or N == 0:
            return np.full(N, 1.0 / N) if N else np.array([])

        Sigma = np.atleast_2d(np.cov(R, rowvar=False, ddof=1))
        if N == 1:
            return np.array([1.0])
        # Symmetric eigendecomposition (Sigma is PSD up to numerical noise)
        eigvals, eigvecs = np.linalg.eigh(Sigma)
        # eigh returns ascending; flip to descending so the largest factors come first
        order = np.argsort(eigvals)[::-1]
        eigvals = np.clip(eigvals[order], 1e-12, None)
        eigvecs = eigvecs[:, order]
        k = self.n_factors if self.n_factors is not None else N
        k = min(k, N)
        V = eigvecs[:, :k]   # (N, k)
        lam = eigvals[:k]    # (k,)

        # Iteratively rebalance so factor contributions approach equality.
        w = np.full(N, 1.0 / N)
        target = 1.0 / k
        for _ in range(self.max_iter):
            f = V.T @ w                         # factor exposure (k,)
            contrib = lam * (f ** 2)            # raw factor variance share
            total = contrib.sum()
            if total <= 1e-16:
                break
            shares = contrib / total            # current factor shares
            # Multiplicative update: shrink over-weighted factors, grow under-weighted
            scale = np.sqrt(target / np.clip(shares, 1e-12, None))
            new_f = f * scale
            # Map adjusted factor exposures back to asset space (least squares)
            try:
                w_new = np.linalg.lstsq(V.T, new_f, rcond=None)[0]
            except np.linalg.LinAlgError:
                w_new = w.copy()
            if self.long_only:
                w_new = self._project_simplex(w_new)
            else:
                s = w_new.sum()
                if abs(s) > 1e-12:
                    w_new = w_new / s
            if np.linalg.norm(w_new - w) < self.tol:
                w = w_new
                break
            w = w_new
        return w

    def factor_contributions(self, weights, returns_matrix) -> np.ndarray:
        """Return factor variance contributions for diagnostic purposes."""
        w = np.asarray(weights, dtype=float)
        R = np.asarray(returns_matrix, dtype=float)
        Sigma = np.cov(R, rowvar=False, ddof=1)
        eigvals, eigvecs = np.linalg.eigh(Sigma)
        order = np.argsort(eigvals)[::-1]
        eigvals = np.clip(eigvals[order], 1e-12, None)
        eigvecs = eigvecs[:, order]
        k = self.n_factors if self.n_factors is not None else eigvals.size
        k = min(k, eigvals.size)
        V = eigvecs[:, :k]
        lam = eigvals[:k]
        f = V.T @ w
        return lam * (f ** 2)
