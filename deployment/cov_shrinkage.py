"""Covariance shrinkage estimators (Task H.4).

Provides several covariance estimators for portfolio optimization:
- Sample covariance (annualized)
- Ledoit-Wolf optimal shrinkage (multiple targets)
- Oracle Approximating Shrinkage (OAS, Chen et al.)
- Exponentially weighted covariance
- PSD repair utilities (spectral / diagonal loading)

sklearn.covariance is required for Ledoit-Wolf and OAS. Manual fallbacks
are provided for shrinkage targets sklearn does not expose directly
(single_factor, constant_correlation).
"""
from __future__ import annotations
import warnings

import numpy as np
import pandas as pd

try:
    from sklearn.covariance import LedoitWolf as _SKLedoitWolf
    from sklearn.covariance import OAS as _SKOAS
    _HAS_SKLEARN = True
except ImportError:  # pragma: no cover
    _SKLedoitWolf = None
    _SKOAS = None
    _HAS_SKLEARN = False


# ---------------------------------------------------------------------------
# Cadence inference / validation
# ---------------------------------------------------------------------------
# Tolerance for matching inferred cadence -> annualization frequency.
# We map common cadences to a small range of valid `frequency` values so a
# user passing 252 against weekly data triggers a warning.
_CADENCE_FREQ_RANGES: dict[str, tuple[int, int]] = {
    "intraday_minute": (50000, 1_000_000),  # any high frequency
    "intraday_hourly": (1500, 5000),
    "daily":           (200, 366),          # 252 trading-day or 365 calendar
    "weekly":          (40, 60),            # 52
    "monthly":         (10, 14),             # 12
    "quarterly":       (3, 5),               # 4
    "yearly":          (1, 2),
}


def _infer_cadence(idx: pd.DatetimeIndex) -> str:
    """Return a coarse cadence label from a DatetimeIndex.

    Uses the median gap between consecutive timestamps to pick the closest
    label in :data:`_CADENCE_FREQ_RANGES`. Returns ``"unknown"`` if there is
    not enough data.
    """
    if len(idx) < 2:
        return "unknown"
    deltas = np.diff(idx.values).astype("timedelta64[s]").astype(float)
    deltas = deltas[deltas > 0]
    if deltas.size == 0:
        return "unknown"
    median_s = float(np.median(deltas))
    minute = 60.0
    hour = 3600.0
    day = 86400.0
    if median_s < 5 * minute:
        return "intraday_minute"
    if median_s < 0.9 * day:
        return "intraday_hourly"
    if median_s < 5 * day:
        return "daily"
    if median_s < 20 * day:
        return "weekly"
    if median_s < 70 * day:
        return "monthly"
    if median_s < 200 * day:
        return "quarterly"
    return "yearly"


def _warn_if_cadence_mismatch(returns, frequency: int, source: str) -> None:
    """Emit a UserWarning if `returns` has a DatetimeIndex whose cadence does
    not match `frequency`. No-op for arrays / non-Datetime indices."""
    idx = getattr(returns, "index", None)
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) < 3:
        return
    cadence = _infer_cadence(idx)
    if cadence == "unknown":
        return
    lo, hi = _CADENCE_FREQ_RANGES[cadence]
    if not (lo <= frequency <= hi):
        warnings.warn(
            f"{source}: inferred cadence '{cadence}' (median bar gap) does "
            f"not match frequency={frequency}. Expected frequency in "
            f"[{lo}, {hi}] for this cadence (e.g. 252 daily, 52 weekly, "
            f"12 monthly). Annualized covariance may be off by a constant "
            f"factor.",
            UserWarning,
            stacklevel=3,
        )


# ---------------------------------------------------------------------------
# Sample covariance
# ---------------------------------------------------------------------------
def sample_covariance(returns: pd.DataFrame, frequency: int = 252) -> pd.DataFrame:
    """Sample covariance matrix annualized.

    Args:
        returns: DataFrame of asset returns (rows = obs, cols = assets)
        frequency: bars per year (252 daily, 52 weekly, 12 monthly)

    Returns:
        DataFrame (n_assets x n_assets) annualized covariance.

    Warns:
        UserWarning if `returns` has a DatetimeIndex whose inferred cadence
        does not match `frequency` (e.g. weekly data with frequency=252).
    """
    if not isinstance(returns, pd.DataFrame):
        returns = pd.DataFrame(returns)
    _warn_if_cadence_mismatch(returns, frequency, source="sample_covariance")
    cov = returns.cov() * frequency
    return cov


# ---------------------------------------------------------------------------
# Ledoit-Wolf shrinkage
# ---------------------------------------------------------------------------
def _shrinkage_target_matrix(sample_cov: np.ndarray, target: str) -> np.ndarray:
    """Build the shrinkage target F matrix."""
    n = sample_cov.shape[0]
    if target == "constant_variance":
        # F = mu * I where mu = trace(S)/n
        mu = np.trace(sample_cov) / n
        return mu * np.eye(n)
    if target == "identity":
        return np.eye(n)
    if target == "single_factor":
        # F has the same diagonal as S; off-diagonal = single-factor implied
        # (Ledoit-Wolf 2003 single-index target). Approximate via average
        # cov as factor proxy.
        var = np.diag(sample_cov)
        avg_cov = (sample_cov.sum() - np.trace(sample_cov)) / (n * (n - 1))
        F = np.full_like(sample_cov, avg_cov)
        np.fill_diagonal(F, var)
        return F
    if target == "constant_correlation":
        # Same diag as S; off-diag = avg_corr * sqrt(var_i * var_j)
        var = np.diag(sample_cov)
        std = np.sqrt(var)
        denom = np.outer(std, std)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.where(denom > 0, sample_cov / denom, 0.0)
        # avg off-diag corr
        mask: np.ndarray = ~np.eye(n, dtype=bool)
        if mask.sum() > 0:
            avg_corr = corr[mask].mean()
        else:
            avg_corr = 0.0
        F = avg_corr * denom
        np.fill_diagonal(F, var)
        return F
    raise ValueError(f"Unknown shrinkage_target: {target}")


def ledoit_wolf_shrinkage(returns: pd.DataFrame,
                          shrinkage_target: str = "constant_variance",
                          frequency: int = 252) -> tuple[pd.DataFrame, float]:
    """Ledoit-Wolf optimal shrinkage estimator.

    Args:
        returns: DataFrame of asset returns
        shrinkage_target: 'constant_variance' | 'identity' |
                          'single_factor' | 'constant_correlation'
        frequency: bars per year

    Returns:
        (shrunk_cov DataFrame, optimal_shrinkage_factor float in [0,1])
    """
    if not _HAS_SKLEARN:
        raise ImportError(
            "scikit-learn is required for Ledoit-Wolf shrinkage. "
            "Install with: pip install scikit-learn"
        )
    if not isinstance(returns, pd.DataFrame):
        returns = pd.DataFrame(returns)
    _warn_if_cadence_mismatch(returns, frequency, source="ledoit_wolf_shrinkage")
    cols = list(returns.columns)
    X = returns.to_numpy(dtype=float)
    X = X - X.mean(axis=0, keepdims=True)
    n_obs = X.shape[0]
    if n_obs < 2:
        raise ValueError("Need at least 2 observations")

    # Sample cov (using N divisor like sklearn's LedoitWolf)
    S = (X.T @ X) / n_obs

    if shrinkage_target == "constant_variance":
        # Use sklearn directly (it uses constant_variance target)
        lw = _SKLedoitWolf().fit(X)
        shrunk = lw.covariance_
        delta = float(lw.shrinkage_)
    else:
        # Manual shrinkage with custom target.
        # Use sklearn's shrinkage estimate as the optimal delta against
        # constant_variance, then apply to chosen target. For non-trivial
        # targets, recompute delta via Ledoit-Wolf optimal formula.
        F = _shrinkage_target_matrix(S, shrinkage_target)
        delta = _optimal_shrinkage_factor(X, S, F)
        shrunk = delta * F + (1.0 - delta) * S

    # Annualize
    shrunk_ann = shrunk * frequency
    df = pd.DataFrame(shrunk_ann, index=cols, columns=cols)
    return df, float(delta)


def _optimal_shrinkage_factor(X: np.ndarray, S: np.ndarray,
                              F: np.ndarray) -> float:
    """Compute Ledoit-Wolf optimal shrinkage factor for arbitrary target F.

    Implements the standard formula:
        delta* = pi_hat / gamma_hat / T   (clipped to [0, 1])
    where pi_hat is the sum of asymptotic variances of sample cov entries
    and gamma_hat = ||F - S||_F^2.

    Reference: Ledoit & Wolf (2004) "Honey, I Shrunk the Sample Covariance
    Matrix", section 3.

    Vectorized: replaces an O(T*N^2) Python loop with two O(T*N^2) BLAS
    matmuls. For X centered (mean 0) and S = (1/T) X.T @ X:
        pi_ij = (1/T) sum_t (X_ti X_tj - S_ij)^2
              = (1/T) sum_t (X_ti X_tj)^2 - S_ij^2
              = (1/T) (X^2).T @ (X^2)  -  S * S
    """
    T, n = X.shape
    Xc = X  # already centered upstream
    Xsq = Xc * Xc
    pi_mat = (Xsq.T @ Xsq) / T - S * S
    pi_hat = float(pi_mat.sum())

    # gamma: squared Frobenius distance F vs S
    diff = F - S
    gamma = float((diff * diff).sum())
    if gamma <= 0:
        return 0.0

    kappa = pi_hat / gamma
    delta = kappa / T
    return float(np.clip(delta, 0.0, 1.0))


# ---------------------------------------------------------------------------
# OAS shrinkage
# ---------------------------------------------------------------------------
def oas_shrinkage(returns: pd.DataFrame,
                  frequency: int = 252) -> tuple[pd.DataFrame, float]:
    """Oracle Approximating Shrinkage (Chen, Wiesel, Eldar, Hero 2010).

    Returns:
        (shrunk_cov DataFrame, optimal_shrinkage_factor float in [0,1])
    """
    if not _HAS_SKLEARN:
        raise ImportError(
            "scikit-learn is required for OAS shrinkage. "
            "Install with: pip install scikit-learn"
        )
    if not isinstance(returns, pd.DataFrame):
        returns = pd.DataFrame(returns)
    cols = list(returns.columns)
    X = returns.to_numpy(dtype=float)
    if X.shape[0] < 2:
        raise ValueError("Need at least 2 observations")

    oas = _SKOAS().fit(X)
    cov_ann = oas.covariance_ * frequency
    df = pd.DataFrame(cov_ann, index=cols, columns=cols)
    return df, float(oas.shrinkage_)


# ---------------------------------------------------------------------------
# Exponentially weighted covariance
# ---------------------------------------------------------------------------
def exponential_cov(returns: pd.DataFrame, span: int = 60,
                    frequency: int = 252,
                    effective_n_threshold: float = 3.0) -> pd.DataFrame:
    """Exponentially weighted covariance (annualized).

    More recent observations are weighted more heavily via the EWMA scheme.

    Args:
        returns: DataFrame of asset returns
        span: EWMA span (lambda = (span-1)/(span+1))
        frequency: bars per year
        effective_n_threshold: minimum effective sample size required to
            apply the (1 - sum w^2) reliability bias correction. Below
            this floor the correction blows up the covariance (divides by
            an arbitrarily small number) so we fall back to the biased
            estimate and emit a warning instead.

    Returns:
        Annualized covariance DataFrame.
    """
    if not isinstance(returns, pd.DataFrame):
        returns = pd.DataFrame(returns)
    if span < 1:
        raise ValueError("span must be >= 1")
    cols = list(returns.columns)
    X = returns.to_numpy(dtype=float)
    T, n = X.shape
    if T < 2:
        raise ValueError("Need at least 2 observations")

    # Decay weights: w_t = (1-alpha)^(T-1-t), alpha = 2/(span+1)
    alpha = 2.0 / (span + 1.0)
    ages = np.arange(T - 1, -1, -1)  # most recent has age 0
    weights = (1.0 - alpha) ** ages
    weights /= weights.sum()

    mean = (weights[:, None] * X).sum(axis=0)
    Xc = X - mean
    # Weighted cov
    cov = (Xc * weights[:, None]).T @ Xc
    # Bias correction (reliability weights). With weights summing to 1, the
    # divisor that yields an unbiased estimator is 1 - sum(w_t^2). The
    # effective sample size is 1 / sum(w^2); when it falls below the
    # configurable threshold (default ~3 obs), the correction explodes the
    # variance, so we fall back to the biased estimator with a warning.
    sum_sq = float((weights ** 2).sum())
    bias_corr = 1.0 - sum_sq
    eff_n = 1.0 / sum_sq if sum_sq > 0 else float("inf")
    threshold = float(effective_n_threshold)
    cutoff = 1.0 - 1.0 / threshold if threshold > 0 else 0.0
    if bias_corr > 1e-12 and bias_corr >= cutoff:
        cov = cov / bias_corr
    elif bias_corr > 1e-12:
        # Degenerate: not enough effective observations. Keep biased
        # estimate so the variance does not blow up; warn the operator.
        warnings.warn(
            f"exponential_cov: effective sample size {eff_n:.2f} is below "
            f"threshold {threshold:.2f} (bias_corr={bias_corr:.4f}); "
            f"returning biased estimate to avoid variance blow-up.",
            UserWarning,
            stacklevel=2,
        )
    cov_ann = cov * frequency
    df = pd.DataFrame(cov_ann, index=cols, columns=cols)
    return df


# ---------------------------------------------------------------------------
# PSD repair
# ---------------------------------------------------------------------------
def fix_nonpositive_semidefinite(matrix: pd.DataFrame,
                                 fix_method: str = "spectral") -> pd.DataFrame:
    """Fix matrix to be positive semi-definite.

    Args:
        matrix: input covariance / correlation DataFrame
        fix_method: 'spectral' | 'diagonal_loading'

    Returns:
        PSD DataFrame with same index/columns.
    """
    if not isinstance(matrix, pd.DataFrame):
        matrix = pd.DataFrame(matrix)
    cols = list(matrix.columns)
    idx = list(matrix.index)
    M = matrix.to_numpy(dtype=float)
    # Symmetrize (numerical asymmetry can flip eigenvalue sign)
    M = 0.5 * (M + M.T)

    if fix_method == "spectral":
        eigvals, eigvecs = np.linalg.eigh(M)
        # Floor at a small POSITIVE value (not 0) to keep the matrix
        # invertible after the projection. Clipping at exactly 0 produces
        # a PSD-but-singular matrix, which downstream optimizers (e.g.
        # quadratic programs requiring Sigma^-1) cannot handle. Using a
        # constant 1e-10 floor breaks down when the matrix is poorly
        # scaled (huge eigvals): the smallest eig becomes negligible
        # relative to the largest and the condition number explodes. Tie
        # the floor to ``eigvals.max()`` so the resulting condition
        # number stays bounded near 1e8.
        max_eig = float(eigvals.max()) if eigvals.size else 0.0
        floor = max(1e-10, 1e-8 * max_eig)
        eigvals_clipped = np.clip(eigvals, floor, None)
        fixed = (eigvecs * eigvals_clipped) @ eigvecs.T
        fixed = 0.5 * (fixed + fixed.T)
        return pd.DataFrame(fixed, index=idx, columns=cols)

    if fix_method == "diagonal_loading":
        # Add increasing constant to diagonal until min eigenvalue >= 0
        eigvals = np.linalg.eigvalsh(M)
        min_eig = float(eigvals.min())
        if min_eig >= 0:
            return pd.DataFrame(M, index=idx, columns=cols)
        # Initial loading: bring min eig to 0 + small epsilon
        epsilon = 1e-10
        loading = -min_eig + epsilon
        fixed = M + loading * np.eye(M.shape[0])
        # Iterate in case of numerical issues
        for _ in range(20):
            min_eig = float(np.linalg.eigvalsh(fixed).min())
            if min_eig >= 0:
                break
            fixed = fixed + abs(min_eig) * np.eye(fixed.shape[0])
        return pd.DataFrame(fixed, index=idx, columns=cols)

    raise ValueError(f"Unknown fix_method: {fix_method}")
