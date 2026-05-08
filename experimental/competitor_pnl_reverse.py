"""Competitor PnL reverse engineer.

Given a competitor's reported holdings (13F-style) over time and a
reported total PnL, infer approximate underlying signal weights via a
simple linear regression of returns onto holdings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass
class CompetitorPnLReverseEngineer:
    """Infer signal weights from public 13F + reported PnL.

    Parameters
    ----------
    ridge : float
        Ridge regularization on the regression to stabilize ill-conditioned
        holding matrices. Non-negative.
    """

    ridge: float = 1e-3

    def __post_init__(self) -> None:
        if self.ridge < 0:
            raise ValueError("ridge must be non-negative")

    def infer(
        self,
        holdings: np.ndarray,
        returns: np.ndarray,
        pnl: np.ndarray,
    ) -> dict:
        """Estimate signal weights.

        Parameters
        ----------
        holdings : ndarray
            Shape ``(T, N)`` weights of N assets at T snapshots.
        returns : ndarray
            Shape ``(T, N)`` realized returns per asset.
        pnl : ndarray
            Shape ``(T,)`` reported portfolio PnL.
        """
        H = np.asarray(holdings, dtype=float)
        R = np.asarray(returns, dtype=float)
        P = np.asarray(pnl, dtype=float).ravel()
        if H.shape != R.shape:
            raise ValueError("holdings and returns must have same shape")
        if H.shape[0] != P.size:
            raise ValueError("holdings rows must match pnl length")

        # Per-asset contribution = holding * return at time t.
        X = H * R
        # Solve (X^T X + ridge*I) w = X^T P.
        XtX = X.T @ X + self.ridge * np.eye(X.shape[1])
        XtY = X.T @ P
        weights = np.linalg.solve(XtX, XtY)

        pred = X @ weights
        ss_res = float(np.sum((P - pred) ** 2))
        ss_tot = float(np.sum((P - P.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        return {
            "weights": weights,
            "r2": r2,
            "n_assets": H.shape[1],
            "n_periods": H.shape[0],
        }
