"""Synthetic alpha generator.

Generates a novel synthetic factor time series that is approximately
orthogonal to a set of "common" factors via Gram-Schmidt residualization.
Numpy only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class SyntheticAlphaGenerator:
    """Generate synthetic factors orthogonal to common ones.

    Parameters
    ----------
    seed : int
        Random seed for reproducibility.
    n_periods : int
        Length of the generated series.
    """

    seed: int = 42
    n_periods: int = 252

    def __post_init__(self) -> None:
        if self.n_periods <= 0:
            raise ValueError("n_periods must be positive")
        self._rng = np.random.default_rng(self.seed)

    def _residualize(self, candidate: np.ndarray, common: np.ndarray) -> np.ndarray:
        if common.size == 0:
            return candidate
        X = np.atleast_2d(common)
        if X.shape[0] != candidate.shape[0]:
            X = X.T
        # Augment with an intercept so residual is uncorrelated (not just
        # orthogonal in raw dot product) to each common column.
        X_aug = np.hstack([X, np.ones((X.shape[0], 1))])
        beta, *_ = np.linalg.lstsq(X_aug, candidate, rcond=None)
        return candidate - X_aug @ beta

    def generate(self, common_factors: Optional[np.ndarray] = None) -> dict:
        """Return a synthetic factor series and its diagnostics.

        Parameters
        ----------
        common_factors : ndarray, optional
            Shape ``(n_periods, k)`` matrix of factors to be orthogonal to.
        """
        candidate = self._rng.standard_normal(self.n_periods)
        if common_factors is None or common_factors.size == 0:
            residual = candidate
            corr_max = 0.0
        else:
            common = np.asarray(common_factors, dtype=float)
            if common.ndim == 1:
                common = common.reshape(-1, 1)
            if common.shape[0] != self.n_periods:
                raise ValueError("common_factors first axis must match n_periods")
            residual = self._residualize(candidate, common)
            corr_max = max(
                abs(float(np.corrcoef(residual, common[:, i])[0, 1]))
                for i in range(common.shape[1])
            )

        # Standardize.
        std = float(residual.std(ddof=1)) if residual.size > 1 else 1.0
        if std > 0:
            residual = (residual - residual.mean()) / std

        return {
            "factor": residual,
            "n_periods": self.n_periods,
            "max_corr_with_common": corr_max,
        }
