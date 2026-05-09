"""Expected Shortfall (Conditional VaR) — coherent risk measure.

Reference: Rockafellar & Uryasev (2000, 2002), "Optimization of Conditional
Value-at-Risk". Acerbi & Tasche (2002) on coherence properties.

ES_alpha(L) = E[L | L >= VaR_alpha(L)] for losses L (i.e. -returns).
We compute the historical (empirical) ES on a returns vector at multiple
confidence levels in a single pass.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass
class ExpectedShortfall:
    """Coherent ES at multiple confidence levels.

    Parameters
    ----------
    alphas
        Confidence levels in (0, 1). E.g. (0.95, 0.975, 0.99).
    interpolation
        ``'linear'`` (default) uses np.quantile interpolation; ``'lower'`` takes
        the largest sample loss <= the alpha-quantile (more conservative on
        small samples).
    """
    alphas: Sequence[float] = field(default_factory=lambda: (0.95, 0.975, 0.99))
    interpolation: str = "linear"

    def __post_init__(self) -> None:
        for a in self.alphas:
            if not (0.0 < a < 1.0):
                raise ValueError(f"alpha must be in (0,1), got {a}")
        if self.interpolation not in ("linear", "lower"):
            raise ValueError("interpolation must be 'linear' or 'lower'")

    def compute(self, returns) -> dict:
        """Return dict {alpha: ES} where ES is reported as a positive loss.

        Empty input returns dict of zeros. NaNs are dropped.
        """
        r = np.asarray(returns, dtype=float).ravel()
        r = r[~np.isnan(r)]
        out: dict = {}
        if r.size == 0:
            return {float(a): 0.0 for a in self.alphas}
        losses = -r
        for a in self.alphas:
            # VaR is the alpha-quantile of losses
            if self.interpolation == "linear":
                var = float(np.quantile(losses, a))
            else:
                var = float(np.quantile(losses, a, method="lower"))
            tail = losses[losses >= var]
            if tail.size == 0:
                out[float(a)] = float(var)
            else:
                out[float(a)] = float(tail.mean())
        return out

    def allocate(self, returns_matrix) -> np.ndarray:
        """Inverse-ES weighting across columns of a (T, N) returns matrix.

        Uses the highest alpha in ``self.alphas``. Returns weights in [0, 1]
        summing to 1.0. Columns with zero or non-positive ES fall back to
        equal-weight.
        """
        R = np.asarray(returns_matrix, dtype=float)
        if R.ndim != 2:
            raise ValueError("returns_matrix must be 2-D (T, N)")
        n = R.shape[1]
        if n == 0:
            return np.array([])
        alpha = float(max(self.alphas))
        es_vec = np.empty(n, dtype=float)
        for j in range(n):
            r_j = R[:, j]
            r_j = r_j[~np.isnan(r_j)]
            if r_j.size == 0:
                es_vec[j] = 0.0
                continue
            losses = -r_j
            var = np.quantile(losses, alpha)
            tail = losses[losses >= var]
            es_vec[j] = float(tail.mean()) if tail.size else float(var)
        # Inverse-ES weighting; non-positive ES -> equal weight fallback
        if not np.all(es_vec > 0):
            return np.full(n, 1.0 / n)
        inv = 1.0 / es_vec
        return inv / inv.sum()
