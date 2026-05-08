"""Black-Litterman blended-views model.

The Black-Litterman model (Black & Litterman 1992) blends a prior expected
return vector pi with a set of subjective views Q expressed through a picking
matrix P, producing a posterior expected return vector and covariance matrix
suitable for mean-variance optimization.

Math (canonical form):
    Posterior return:
        mu_post = pi + tau*Sigma*P^T * (P*tau*Sigma*P^T + Omega)^-1 * (Q - P*pi)
    Posterior covariance:
        Sigma_post = Sigma + tau*Sigma - tau*Sigma*P^T *
                     (P*tau*Sigma*P^T + Omega)^-1 * P*tau*Sigma
    Tangency weights from posterior:
        w = (1/lambda) * Sigma_post^-1 * mu_post

References:
    Black, F. and Litterman, R. (1992) "Global Portfolio Optimization",
    Financial Analysts Journal, 48(5), 28-43.
    He, G. and Litterman, R. (1999) "The Intuition Behind Black-Litterman
    Model Portfolios", Goldman Sachs Investment Management Research.
"""
from __future__ import annotations
import warnings
from dataclasses import dataclass
from typing import Optional, Union
import numpy as np
import pandas as pd
from numpy import linalg


# Highest user confidence we accept; anything strictly above is clipped (with
# a warning) to keep Omega entries strictly positive and the BL system
# numerically well-conditioned.
_MAX_CONFIDENCE = 0.999
# Lowest user confidence we accept. Below this, Omega entries blow up so the
# BL solver assigns essentially zero weight to the view; it is the user's
# choice but we emit a warning so it is auditable.
_MIN_CONFIDENCE = 1e-3
# Minimum acceptable eigenvalue of the posterior covariance before we project
# it back to PSD via spectral clipping.
_PSD_EIG_TOL = -1e-10
# Floor we set negative eigenvalues to during PSD projection.
_PSD_EIG_FLOOR = 1e-12


@dataclass
class BLResult:
    """Output of a Black-Litterman blend."""
    posterior_returns: pd.Series        # blended expected returns
    posterior_cov: pd.DataFrame         # blended covariance
    prior_returns: pd.Series
    prior_cov: pd.DataFrame
    views_p: pd.DataFrame               # picking matrix (N_views x N_assets)
    views_q: pd.Series                  # view returns (N_views,)
    omega: pd.DataFrame                 # view uncertainty (N_views x N_views)
    optimal_weights: pd.Series          # max-Sharpe portfolio weights


def _project_psd(matrix: np.ndarray) -> np.ndarray:
    """Project a symmetric matrix to the PSD cone via spectral clipping.

    Symmetrizes the input, computes the eigendecomposition, and if the
    minimum eigenvalue is below ``_PSD_EIG_TOL`` clips negatives up to
    a relative floor. The floor scales with the largest eigenvalue so
    matrices with very different magnitudes (e.g. daily-vs-monthly cov,
    or USD-billions notional-scaled inputs) all retain numerical
    conditioning rather than collapsing to a fixed absolute floor.
    If the matrix is already PSD within tolerance, returns the
    symmetrized input unchanged.
    """
    M = 0.5 * (matrix + matrix.T)
    eigvals = linalg.eigvalsh(M)
    if float(eigvals.min()) >= _PSD_EIG_TOL:
        return M
    eigvals_full, eigvecs = linalg.eigh(M)
    floor = max(_PSD_EIG_FLOOR, 1e-8 * float(eigvals_full.max()))
    eigvals_full = np.where(eigvals_full < floor, floor, eigvals_full)
    fixed = (eigvecs * eigvals_full) @ eigvecs.T
    return 0.5 * (fixed + fixed.T)


class BlackLittermanModel:
    """Black-Litterman blended-views model.

    Args:
        prior_returns: pd.Series of prior expected returns (e.g. CAPM-implied).
        prior_cov: pd.DataFrame covariance matrix of asset returns.
        views_p: pd.DataFrame N_views x N_assets, rows = absolute or relative
                 views.
                 - Absolute view: row = e.g. [1, 0, 0, 0] = "asset 0 will
                   return Q_i".
                 - Relative view: e.g. [1, -1, 0, 0] = "asset 0 outperforms
                   asset 1 by Q_i".
                 May be None or empty to skip the view step (posterior == prior).
        views_q: pd.Series N_views, expected return for each view. Must align
                 with views_p rows.
        view_confidence: float in (0, 1] OR pd.Series per view (default 0.5).
                         Higher confidence -> tighter Omega.
        tau: scalar uncertainty in prior (default 0.05). Standard BL choice
             for monthly returns; some authors use 1/T.
    """

    def __init__(self,
                 prior_returns: pd.Series,
                 prior_cov: pd.DataFrame,
                 views_p: Optional[pd.DataFrame] = None,
                 views_q: Optional[pd.Series] = None,
                 view_confidence: Union[float, pd.Series] = 0.5,
                 tau: float = 0.05):
        if not isinstance(prior_returns, pd.Series):
            raise TypeError("prior_returns must be a pd.Series")
        if not isinstance(prior_cov, pd.DataFrame):
            raise TypeError("prior_cov must be a pd.DataFrame")
        if tau <= 0:
            raise ValueError(f"tau must be > 0, got {tau}")

        # Align prior_cov to prior_returns index.
        assets = list(prior_returns.index)
        if list(prior_cov.index) != assets or list(prior_cov.columns) != assets:
            prior_cov = prior_cov.loc[assets, assets]

        self.assets = assets
        self.prior_returns = prior_returns.astype(float)
        self.prior_cov = prior_cov.astype(float)
        self.tau = float(tau)

        # Validate / canonicalize views.
        has_views = (views_p is not None
                     and views_q is not None
                     and len(views_p) > 0
                     and len(views_q) > 0)
        if has_views:
            if not isinstance(views_p, pd.DataFrame):
                raise TypeError("views_p must be a pd.DataFrame")
            if not isinstance(views_q, pd.Series):
                raise TypeError("views_q must be a pd.Series")
            if len(views_p) != len(views_q):
                raise ValueError(
                    f"views_p has {len(views_p)} rows but views_q has "
                    f"{len(views_q)} entries"
                )
            # Ensure column order matches assets.
            if list(views_p.columns) != assets:
                views_p = views_p.reindex(columns=assets, fill_value=0.0)
            self.views_p = views_p.astype(float)
            self.views_q = views_q.astype(float)
        else:
            # Empty placeholders.
            self.views_p = pd.DataFrame(columns=assets, dtype=float)
            self.views_q = pd.Series(dtype=float)

        self.view_confidence = view_confidence
        self.omega = self._build_omega()

        # Precompute posteriors.
        self._mu_post = self._compute_posterior_returns()
        self._sigma_post = self._compute_posterior_cov()

    # --------------------------------------------------------------------- #
    def _build_omega(self) -> pd.DataFrame:
        """Construct Omega: diagonal view-uncertainty matrix.

        Omega[i, i] = (1 - c_i) / c_i * (P_i * tau * Sigma * P_i^T)
        where c_i in (0, 1) is the per-view confidence (Idzorek-style).
        Higher confidence -> smaller Omega entry -> view dominates.

        Confidence must be strictly less than 1: c==1 forces Omega[i,i]=0,
        which makes the BL solver matrix M = P*tau*Sigma*P^T + Omega
        singular along that view direction. We clip values >= 1 to
        ``_MAX_CONFIDENCE`` (0.999) and emit a warning.
        """
        n_views = len(self.views_p)
        if n_views == 0:
            return pd.DataFrame(dtype=float)

        P = self.views_p.values  # (n_views, n_assets)
        Sigma = self.prior_cov.values

        # Per-view confidence vector.
        if isinstance(self.view_confidence, pd.Series):
            if len(self.view_confidence) != n_views:
                raise ValueError(
                    f"view_confidence Series has {len(self.view_confidence)} "
                    f"entries but there are {n_views} views"
                )
            c = self.view_confidence.values.astype(float)
        else:
            c_scalar = float(self.view_confidence)
            c = np.full(n_views, c_scalar, dtype=float)

        if np.any(c <= 0) or np.any(c > 1):
            raise ValueError(
                f"view_confidence must be in (0, 1], got {c}"
            )
        # Clip exact-1 confidence to keep Omega strictly positive on the
        # diagonal (deterministic-view case is ill-posed for the matrix
        # solver). User can set strict<1 to silence the warning.
        if np.any(c >= 1.0):
            warnings.warn(
                f"view_confidence == 1.0 detected; clipping to "
                f"{_MAX_CONFIDENCE} to keep BL solver well-conditioned. "
                f"Use confidence < 1 to silence this warning.",
                stacklevel=3,
            )
            c = np.minimum(c, _MAX_CONFIDENCE)
        # Clip near-zero confidence so Omega entries do not explode and so
        # the operator notices when a view is effectively being ignored.
        if np.any(c < _MIN_CONFIDENCE):
            warnings.warn(
                f"view_confidence below {_MIN_CONFIDENCE} detected; clipping "
                f"to {_MIN_CONFIDENCE}. The view will receive a very small "
                f"weight in the posterior; raise confidence to silence this.",
                stacklevel=3,
            )
            c = np.maximum(c, _MIN_CONFIDENCE)

        # Diagonal of P * tau * Sigma * P^T (view-implied variance under prior).
        ptp = P @ (self.tau * Sigma) @ P.T
        diag_var = np.diag(ptp).astype(float)
        # Floor to a small positive number so 100% confidence stays invertible.
        diag_var = np.maximum(diag_var, 1e-12)

        # Idzorek-style Omega diag: (1 - c) / c * diag_var.
        omega_diag = ((1.0 - c) / c) * diag_var
        # Floor again for c == 1 case.
        omega_diag = np.maximum(omega_diag, 1e-12)

        omega = np.diag(omega_diag)
        return pd.DataFrame(
            omega,
            index=self.views_p.index,
            columns=self.views_p.index,
        )

    # --------------------------------------------------------------------- #
    def _compute_posterior_returns(self) -> pd.Series:
        """BL posterior returns formula."""
        pi = self.prior_returns.values
        if len(self.views_p) == 0:
            return pd.Series(pi, index=self.assets)

        Sigma = self.prior_cov.values
        P = self.views_p.values
        Q = self.views_q.values
        Omega = self.omega.values

        tauSigma = self.tau * Sigma
        # M = P * tau*Sigma * P^T + Omega   (n_views x n_views)
        M = P @ tauSigma @ P.T + Omega
        # adjustment = tau*Sigma * P^T * M^-1 * (Q - P*pi)
        residual = Q - P @ pi
        # solve M x = residual, then mu_post = pi + tau*Sigma * P^T * x
        try:
            x = linalg.solve(M, residual)
        except linalg.LinAlgError:
            warnings.warn(
                "BL posterior returns: solver matrix M is singular; "
                "falling back to pseudo-inverse. Consider lowering view "
                "confidence or removing redundant views.",
                stacklevel=2,
            )
            x = linalg.pinv(M) @ residual
        mu_post = pi + tauSigma @ P.T @ x
        return pd.Series(mu_post, index=self.assets)

    # --------------------------------------------------------------------- #
    def _compute_posterior_cov(self) -> pd.DataFrame:
        """BL posterior covariance.

        Formula (returns covariance, not parameter covariance):
            Sigma_post = Sigma + M_param
        where
            M_param = tau*Sigma - tau*Sigma * P^T * (P*tau*Sigma*P^T+Omega)^-1
                                 * P*tau*Sigma
        is the posterior parameter covariance.

        Numerical safety: after solving the BL system the result is
        analytically PSD, but floating-point error and ill-conditioned
        Omega/Sigma can produce a min eigenvalue slightly below zero. We
        symmetrize and, if the minimum eigenvalue falls below
        ``_PSD_EIG_TOL``, project to PSD via spectral clipping (negatives
        floored to ``_PSD_EIG_FLOOR``).
        """
        Sigma = self.prior_cov.values
        if len(self.views_p) == 0:
            # No views: posterior parameter cov = tau*Sigma.
            sigma_post = Sigma + self.tau * Sigma
            sigma_post = _project_psd(sigma_post)
            return pd.DataFrame(sigma_post, index=self.assets, columns=self.assets)

        P = self.views_p.values
        Omega = self.omega.values
        tauSigma = self.tau * Sigma
        M = P @ tauSigma @ P.T + Omega
        # M_param = tauSigma - tauSigma * P^T * M^-1 * P * tauSigma
        # Solve linear system for stability:  M Y = P tauSigma  -> Y = M^-1 P tauSigma
        try:
            Y = linalg.solve(M, P @ tauSigma)
        except linalg.LinAlgError:
            warnings.warn(
                "BL posterior cov: solver matrix M = P*tau*Sigma*P^T + Omega "
                "is singular; falling back to pseudo-inverse. Posterior "
                "may be ill-conditioned; consider lowering view confidence.",
                stacklevel=2,
            )
            Y = linalg.pinv(M) @ (P @ tauSigma)
        M_param = tauSigma - tauSigma @ P.T @ Y
        sigma_post = Sigma + M_param
        # Symmetrize for numerical stability.
        sigma_post = 0.5 * (sigma_post + sigma_post.T)
        # Project to PSD if any eigenvalue dips meaningfully below zero.
        sigma_post = _project_psd(sigma_post)
        return pd.DataFrame(sigma_post, index=self.assets, columns=self.assets)

    # --------------------------------------------------------------------- #
    def posterior_returns(self) -> pd.Series:
        """Return blended (posterior) expected returns."""
        return self._mu_post.copy()

    def posterior_cov(self) -> pd.DataFrame:
        """Return blended (posterior) covariance matrix."""
        return self._sigma_post.copy()

    def optimal_weights(self, risk_aversion: float = 1.0) -> pd.Series:
        """Max-Sharpe / unconstrained mean-variance weights from posterior.

        w_unnorm = (1/lambda) * Sigma_post^-1 * mu_post
        Then normalize to sum to 1 (if total != 0).
        """
        if risk_aversion <= 0:
            raise ValueError(f"risk_aversion must be > 0, got {risk_aversion}")
        Sigma = self._sigma_post.values
        mu = self._mu_post.values
        try:
            w = linalg.solve(Sigma, mu) / float(risk_aversion)
        except linalg.LinAlgError:
            warnings.warn(
                "BL optimal_weights: posterior covariance is singular; "
                "falling back to pseudo-inverse. The returned weights may "
                "be unstable.",
                stacklevel=2,
            )
            w = linalg.pinv(Sigma) @ mu / float(risk_aversion)
        s = w.sum()
        if abs(s) > 1e-12:
            w = w / s
        return pd.Series(w, index=self.assets)

    def result(self, risk_aversion: float = 1.0) -> BLResult:
        """Return full BLResult bundle."""
        return BLResult(
            posterior_returns=self.posterior_returns(),
            posterior_cov=self.posterior_cov(),
            prior_returns=self.prior_returns.copy(),
            prior_cov=self.prior_cov.copy(),
            views_p=self.views_p.copy(),
            views_q=self.views_q.copy(),
            omega=self.omega.copy(),
            optimal_weights=self.optimal_weights(risk_aversion=risk_aversion),
        )


# --------------------------------------------------------------------------- #
# CAPM-implied prior returns                                                  #
# --------------------------------------------------------------------------- #
def market_implied_returns(market_caps: pd.Series,
                           prior_cov: pd.DataFrame,
                           risk_aversion: float = 2.5) -> pd.Series:
    """CAPM-implied prior: pi = lambda * Sigma * w_market.

    Args:
        market_caps: pd.Series of market caps (any positive units; will be
                     normalized to weights summing to 1).
        prior_cov: covariance matrix aligned to market_caps index.
        risk_aversion: lambda (default 2.5, He & Litterman 1999).

    Returns:
        pd.Series of CAPM-implied equilibrium expected returns.
    """
    if not isinstance(market_caps, pd.Series):
        raise TypeError("market_caps must be a pd.Series")
    if not isinstance(prior_cov, pd.DataFrame):
        raise TypeError("prior_cov must be a pd.DataFrame")
    if (market_caps <= 0).any():
        raise ValueError("market_caps must all be > 0")
    if risk_aversion <= 0:
        raise ValueError(f"risk_aversion must be > 0, got {risk_aversion}")

    assets = list(market_caps.index)
    if list(prior_cov.index) != assets or list(prior_cov.columns) != assets:
        prior_cov = prior_cov.loc[assets, assets]

    w_market = market_caps / market_caps.sum()
    pi = float(risk_aversion) * prior_cov.values @ w_market.values
    return pd.Series(pi, index=assets)
