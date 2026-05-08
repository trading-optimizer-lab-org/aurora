"""Regime-conditional risk parity.

Risk parity computed separately on returns conditioned on a regime label
(e.g. produced by an HMM, Markov-switching model, or a trend filter). The
allocator picks the cov estimated only from rows where the regime label
matches the *current* regime, then solves equal-risk-contribution weights.

This avoids smearing out structural cov differences that bull/bear regimes
typically exhibit (vol roughly doubles in bear regimes; correlations cluster).

Plumbing
--------
The regime detector itself lives outside this module; pass a precomputed
regime label series aligned to ``prices.index``. ``HMMRegimeDetector`` is the
recommended choice (see :mod:`quantforge.regime.hmm`) but is not imported
here to keep the dependency graph small.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from quantforge.deployment.risk_parity import risk_parity_weights


@dataclass
class RegimeRPConfig:
    """Configuration for :class:`RegimeRiskParity`."""
    min_obs_per_regime: int = 30   # below this fall back to global cov
    rp_method: str = "sqp"
    rp_max_iter: int = 500
    rp_tol: float = 1e-8


@dataclass
class RegimeRPResult:
    """Output of :meth:`RegimeRiskParity.allocate`."""
    weights: pd.DataFrame              # 1-row DataFrame indexed by current_regime
    cov_used: pd.DataFrame             # cov estimated for the active regime
    n_obs_in_regime: int               # bars matching current_regime
    fallback_to_global: bool           # True if not enough regime obs


class RegimeRiskParity:
    """Risk parity with regime-conditional covariance.

    Args:
        config: :class:`RegimeRPConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[RegimeRPConfig] = None):
        self.config = config or RegimeRPConfig()

    # --------------------------------------------------------------------- #
    def allocate(
        self,
        prices: pd.DataFrame,
        regimes: pd.Series,
        current_regime: object,
    ) -> RegimeRPResult:
        """Compute regime-conditional risk parity weights.

        Args:
            prices: TxN price DataFrame.
            regimes: regime label per timestamp; index must be a subset of
                ``prices.index``. Labels are arbitrary hashables.
            current_regime: regime to condition on (must appear in ``regimes``
                or fallback kicks in).
        """
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pd.DataFrame")
        if not isinstance(regimes, pd.Series):
            raise TypeError("regimes must be a pd.Series")
        if prices.shape[1] < 2:
            raise ValueError(f"need >= 2 assets, got {prices.shape[1]}")

        rets = prices.pct_change().dropna()
        # Align regime labels to returns index.
        regimes_aligned = regimes.reindex(rets.index).ffill().bfill()
        mask = regimes_aligned == current_regime
        n_in = int(mask.sum())

        fallback = n_in < self.config.min_obs_per_regime
        if fallback:
            cov = rets.cov()
        else:
            cov = rets.loc[mask].cov()

        # Numerical safety: jitter near-singular cov.
        cov_arr = cov.to_numpy()
        if not np.all(np.isfinite(cov_arr)):
            cov = rets.cov()
        eigvals = np.linalg.eigvalsh(0.5 * (cov.values + cov.values.T))
        if eigvals.min() <= 1e-12:
            cov = cov + np.eye(cov.shape[0]) * 1e-8

        res = risk_parity_weights(
            cov,
            method=self.config.rp_method,
            max_iter=self.config.rp_max_iter,
            tol=self.config.rp_tol,
        )
        weights_df = pd.DataFrame(
            [res.weights.reindex(prices.columns).values],
            index=[current_regime],
            columns=list(prices.columns),
        )
        return RegimeRPResult(
            weights=weights_df,
            cov_used=cov,
            n_obs_in_regime=n_in,
            fallback_to_global=fallback,
        )
