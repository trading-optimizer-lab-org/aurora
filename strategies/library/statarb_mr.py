"""Multi-asset statistical arbitrage via PCA factor removal + z-score basket.

Workflow:
  1. Fit PCA on rolling-window returns of N assets.
  2. Reconstruct returns from top K factors -> compute residual returns.
  3. Cumulate residuals into a per-asset residual price.
  4. Compute z-score of each residual price vs its rolling mean/std.
  5. Signal: short top z (rich), long bottom z (cheap). Threshold-gated.

Returns DataFrame of weights (rows=dates, cols=assets) in {-1, 0, +1}.
The MultiAssetEngine can normalize gross exposure downstream.

Anti-lookahead: at bar i, only returns[:i+1] used.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from aurora.strategies.base import StrategySpec


@dataclass
class StatArbMRConfig:
    """Configuration."""
    lookback: int = 60
    n_factors: int = 1
    entry_z: float = 2.0
    exit_z: float = 0.5
    min_periods: int = 60


class StatArbMeanRev:
    """PCA-residual stat-arb mean reversion across an asset basket.

    Returns per-asset weights in {-1, 0, +1}. NOT a Strategy subclass
    (multi-asset by design). Consumed by MultiAssetEngine or used standalone.
    """

    def __init__(
        self,
        lookback: int = 60,
        n_factors: int = 1,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        min_periods: Optional[int] = None,
    ):
        if lookback < 10:
            raise ValueError(f"lookback must be >= 10, got {lookback}")
        if n_factors < 1:
            raise ValueError(f"n_factors must be >= 1, got {n_factors}")
        if entry_z <= 0:
            raise ValueError(f"entry_z must be > 0, got {entry_z}")
        if exit_z < 0:
            raise ValueError(f"exit_z must be >= 0, got {exit_z}")
        ez = float(entry_z)
        xz = float(exit_z)
        if xz >= ez:
            xz = ez * 0.99
        self.lookback = int(lookback)
        self.n_factors = int(n_factors)
        self.entry_z = ez
        self.exit_z = xz
        self.min_periods = int(min_periods) if min_periods is not None else self.lookback

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="StatArbMeanRev",
            params={
                "lookback": 60,
                "n_factors": 1,
                "entry_z": 2.0,
                "exit_z": 0.5,
            },
            param_ranges={
                "lookback": (20, 252),
                "n_factors": (1, 5),
                "entry_z": (1.0, 3.5),
                "exit_z": (0.0, 1.5),
            },
        )

    @staticmethod
    def _pca_residuals(rets: np.ndarray, k: int) -> np.ndarray:
        """Subtract top-k PCA reconstruction from rets. Returns residuals.

        rets shape: (T, N). Output shape: (T, N).
        Uses centered SVD on the window. k clamped to [1, min(T, N) - 1].
        """
        T, N = rets.shape
        if T < 2 or N < 2:
            return rets - rets.mean(axis=0, keepdims=True)
        kk = max(1, min(int(k), min(T, N) - 1))
        mu = rets.mean(axis=0, keepdims=True)
        X = rets - mu
        try:
            U, S, Vt = np.linalg.svd(X, full_matrices=False)
        except np.linalg.LinAlgError:
            return X
        # Reconstruction with top-k components
        recon = (U[:, :kk] * S[:kk]) @ Vt[:kk, :]
        return X - recon

    def signals(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Compute signals as a DataFrame of weights in {-1, 0, +1}.

        Args:
            prices: pd.DataFrame, columns=symbols, index=DatetimeIndex.

        Returns:
            pd.DataFrame of same shape, values in {-1, 0, 1}.
        """
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be pd.DataFrame")
        if prices.shape[1] < 2:
            raise ValueError("need >= 2 assets")
        if prices.shape[0] < self.lookback + 2:
            raise ValueError(
                f"insufficient bars: {prices.shape[0]} < lookback+2 ({self.lookback + 2})"
            )

        prices_clean = prices.ffill().bfill()
        rets = prices_clean.pct_change().fillna(0.0)
        T, N = rets.shape
        cols = list(prices.columns)
        idx = prices.index

        weights = np.zeros((T, N), dtype=float)
        # State: per-asset position
        cur = np.zeros(N, dtype=float)

        L = self.lookback
        K = self.n_factors

        # Roll forward: at bar i (>= L), use window rets[i-L+1 : i+1]
        for i in range(T):
            if i < L - 1:
                weights[i] = 0.0
                cur[:] = 0.0
                continue
            window = rets.iloc[i - L + 1 : i + 1].values.astype(float)
            try:
                resid = self._pca_residuals(window, K)
            except Exception:
                weights[i] = cur
                continue
            # Cumulate into a residual "price" within the window
            cum = resid.cumsum(axis=0)
            last = cum[-1]
            mu = cum.mean(axis=0)
            sigma = cum.std(axis=0, ddof=0)
            with np.errstate(divide="ignore", invalid="ignore"):
                z = np.where(sigma > 1e-12, (last - mu) / sigma, 0.0)
            # State machine: rich (z > entry) -> short; cheap (z < -entry) -> long
            for j in range(N):
                zj = z[j]
                if cur[j] == 0.0:
                    if zj > self.entry_z:
                        cur[j] = -1.0
                    elif zj < -self.entry_z:
                        cur[j] = 1.0
                else:
                    if abs(zj) < self.exit_z:
                        cur[j] = 0.0
            weights[i] = cur.copy()

        return pd.DataFrame(weights, index=idx, columns=cols)

    def predict(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Alias of signals() for compatibility with predictive APIs."""
        return self.signals(prices)
