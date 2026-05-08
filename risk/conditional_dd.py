"""Conditional Drawdown at Risk (CDaR).

Reference: Chekhlov, Uryasev & Zabarankin (2005), "Drawdown measure in
portfolio optimization". CDaR_alpha is the average of the worst (1-alpha)
fraction of drawdowns in the running drawdown series.

Pipeline
--------
1. Cumulative wealth W_t = product_{i<=t} (1 + r_i).
2. Running peak P_t = max_{s<=t} W_s.
3. Drawdown D_t = (P_t - W_t) / P_t  (non-negative).
4. DaR_alpha = alpha-quantile of D_t.
5. CDaR_alpha = mean(D_t | D_t >= DaR_alpha).
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np


@dataclass
class ConditionalDrawdownAtRisk:
    """CDaR (Chekhlov-Uryasev) at confidence level alpha.

    Parameters
    ----------
    alpha
        Confidence level in (0, 1). Default 0.95 -> average of the worst 5%
        of drawdowns.
    """
    alpha: float = 0.95

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha < 1.0):
            raise ValueError("alpha must be in (0,1)")

    @staticmethod
    def _drawdown_series(returns: np.ndarray) -> np.ndarray:
        if returns.size == 0:
            return np.zeros(0)
        wealth = np.cumprod(1.0 + returns)
        peak = np.maximum.accumulate(wealth)
        # Guard against wealth wipe-out (peak should always be positive after r > -1)
        peak = np.where(peak <= 0, 1e-12, peak)
        return (peak - wealth) / peak

    def compute(self, returns) -> float:
        """CDaR for a 1-D returns vector. Returned as positive fraction (e.g. 0.18 = 18%)."""
        r = np.asarray(returns, dtype=float).ravel()
        r = r[~np.isnan(r)]
        if r.size == 0:
            return 0.0
        dd = self._drawdown_series(r)
        dar = float(np.quantile(dd, self.alpha))
        tail = dd[dd >= dar]
        if tail.size == 0:
            return float(dar)
        return float(tail.mean())

    def allocate(self, returns_matrix) -> np.ndarray:
        """Inverse-CDaR weights across columns of (T, N)."""
        R = np.asarray(returns_matrix, dtype=float)
        if R.ndim != 2:
            raise ValueError("returns_matrix must be 2-D (T, N)")
        n = R.shape[1]
        if n == 0:
            return np.array([])
        cdars = np.array([self.compute(R[:, j]) for j in range(n)])
        if not np.all(cdars > 0):
            return np.full(n, 1.0 / n)
        inv = 1.0 / cdars
        return inv / inv.sum()
