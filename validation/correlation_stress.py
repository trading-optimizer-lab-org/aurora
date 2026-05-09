"""Correlation breakdown stress test (Task L.4).

Test how a strategy or portfolio behaves when the cross-asset correlation
structure changes. Three regimes are evaluated:

1. **Base**: original empirical correlations.
2. **Decorrelated**: forced identity correlation (zero off-diagonal).
3. **Correlated**: forced near-perfect correlation (~0.95) -- crisis mode.

Plus an optional **custom** scenario with a user-supplied target matrix.

Method:
    Given a target correlation matrix C, sample iid standard normals,
    multiply by Cholesky(C) to inject the target correlation, then if
    `preserve_marginals=True` re-map each column to match the empirical
    marginal distribution of the original returns via inverse-rank mapping
    (preserves mean, std, skew, fat tails). Otherwise rescale to the
    historical (mean, std).

The diversification ratio (Choueifaty-Coignard) summarises the benefit
of cross-asset hedging: DR = sum(w_i * sigma_i) / portfolio_sigma.

CRITICAL: random draws use child_rng for reproducibility; set_global_seed
must be called by the caller.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
import numpy as np
import pandas as pd

from aurora.core.engine_multi import MultiAssetEngine
from aurora.core.metrics import compute_metrics
from aurora.core.seed import child_rng


# --------------------------------------------------------------------------- #
# Result dataclass                                                            #
# --------------------------------------------------------------------------- #
@dataclass
class CorrelationStressResult:
    """Output of stress_correlation_breakdown.

    Each *_metrics dict contains the keys produced by Metrics.to_dict()
    (cagr, mdd, calmar, sharpe, sortino, ...). custom_metrics is None when
    no custom_target was supplied.
    """
    base_metrics: dict
    decorrelated_metrics: dict
    correlated_metrics: dict
    custom_metrics: Optional[dict]
    base_correlation: pd.DataFrame
    diversification_ratio: float


# --------------------------------------------------------------------------- #
# Cholesky-based correlation forcing                                          #
# --------------------------------------------------------------------------- #
def _whiten_columns(Z: np.ndarray) -> np.ndarray:
    """ZCA-style whitening of an (T, n) sample matrix.

    Returns a transformed matrix W with sample mean 0 and sample covariance
    exactly equal to the identity (within FP precision). Use this when the
    downstream Cholesky/Y = Z @ L.T step requires the target correlation to
    be realized exactly in the finite sample.
    """
    T, n = Z.shape
    if T < 2 or n < 1:
        return Z
    Z_centered = Z - Z.mean(axis=0)
    cov = (Z_centered.T @ Z_centered) / T
    # Symmetrize for numerical safety, then invert via eigen-decomp with
    # a small spectral floor to handle near-singular sample covariance.
    cov = 0.5 * (cov + cov.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.clip(eigvals, 1e-12, None)
    inv_sqrt = (eigvecs * (1.0 / np.sqrt(eigvals))) @ eigvecs.T
    return Z_centered @ inv_sqrt


def _safe_cholesky(C: np.ndarray, jitter: float = 1e-10) -> np.ndarray:
    """Cholesky with progressive diagonal regularization for near-singular C."""
    eps = jitter
    for _ in range(20):
        try:
            return np.linalg.cholesky(C + eps * np.eye(C.shape[0]))
        except np.linalg.LinAlgError:
            eps *= 10.0
    # Final fallback: spectral floor
    eigvals, eigvecs = np.linalg.eigh(C)
    eigvals = np.clip(eigvals, 1e-8, None)
    fixed = (eigvecs * eigvals) @ eigvecs.T
    fixed = 0.5 * (fixed + fixed.T)
    return np.linalg.cholesky(fixed)


def force_correlation(returns_matrix: pd.DataFrame, target_corr: float,
                      preserve_marginals: bool = True,
                      seed_name: str = "force_corr") -> pd.DataFrame:
    """Generate synthetic returns matrix with forced uniform correlation.

    Args:
        returns_matrix: DataFrame [time, assets] of empirical returns.
        target_corr: float in [-1, 1].
            0  -> identity (decorrelated)
            1  -> near-perfect correlation (regularized to 0.99)
            -1 -> anti-correlated (only sensible for N=2)
        preserve_marginals: if True, remap columns to match empirical marginal
            distribution via inverse-rank mapping.
        seed_name: child RNG name for reproducibility.

    Returns:
        DataFrame with same shape, index and columns as input.
    """
    if not isinstance(returns_matrix, pd.DataFrame):
        raise TypeError("returns_matrix must be a pd.DataFrame")
    if not (-1.0 <= target_corr <= 1.0):
        raise ValueError(f"target_corr must be in [-1, 1], got {target_corr}")

    cols = list(returns_matrix.columns)
    idx = returns_matrix.index
    n = len(cols)
    T = len(returns_matrix)
    if T < 2 or n < 1:
        raise ValueError("returns_matrix must have >=2 rows and >=1 column")

    # Build target correlation matrix (uniform off-diagonal).
    # For target_corr = +1 we regularize to 0.99 to preserve PD.
    # For target_corr = -1 with n>2, the rank-1 anti-correlation matrix
    # is not PD; clip to a feasible lower bound -1/(n-1) + epsilon.
    if n == 1:
        C = np.array([[1.0]])
    else:
        rho = float(target_corr)
        if rho >= 1.0:
            rho = 0.99
        # Lower feasibility bound for uniform-off-diagonal corr matrix
        lb = -1.0 / (n - 1) + 1e-3
        if rho < lb:
            rho = lb
        C = np.full((n, n), rho, dtype=float)
        np.fill_diagonal(C, 1.0)

    L = _safe_cholesky(C)
    rng = child_rng(seed_name)
    Z = rng.standard_normal(size=(T, n))
    # ZCA whitening: standardize and decorrelate Z BEFORE the Cholesky
    # multiply so that the target correlation matrix (which assumes
    # iid unit-variance inputs) is applied to truly orthonormal columns.
    # Without this step finite-sample correlation in Z leaks into the
    # off-diagonal correlations of Y, biasing the realized C.
    Z = _whiten_columns(Z)
    Y = Z @ L.T  # rows have correlation matrix C, exact in finite samples

    X = returns_matrix.to_numpy(dtype=float)

    if preserve_marginals:
        # Inverse-rank mapping per column: replace ranks of synthetic Y with
        # the sorted empirical values. Preserves the empirical marginal
        # distribution exactly while keeping (approximately) the rank-correlation
        # structure of Y.
        out = np.zeros_like(Y)
        for j in range(n):
            sorted_emp = np.sort(X[:, j])
            order = np.argsort(np.argsort(Y[:, j]))
            out[:, j] = sorted_emp[order]
    else:
        # Match empirical mean/std per column (linear rescale of Y).
        # Per-column linear transforms (a*Y + b) preserve cross-correlations
        # for a > 0, so rescaling Y here does not distort the target C.
        # ``ddof=1`` matches the convention used by cscv._sharpe_columns
        # (sample std) so cross-module statistics are comparable.
        mu = X.mean(axis=0)
        sd = X.std(axis=0, ddof=1)
        out = Y * sd + mu

    return pd.DataFrame(out, index=idx, columns=cols)


# --------------------------------------------------------------------------- #
# Custom correlation scenario                                                 #
# --------------------------------------------------------------------------- #
def custom_correlation_scenario(returns_matrix: pd.DataFrame,
                                target_corr_matrix: pd.DataFrame,
                                preserve_marginals: bool = True,
                                seed_name: str = "custom_corr") -> pd.DataFrame:
    """Force returns to an arbitrary specified correlation structure.

    Args:
        returns_matrix: empirical DataFrame [time, assets].
        target_corr_matrix: DataFrame [n, n] target correlation. Must be
            symmetric, unit diagonal, and PD (or near-PD; spectral repair
            is applied).
        preserve_marginals: same semantics as force_correlation.
        seed_name: child RNG name.

    Returns:
        DataFrame with same shape as returns_matrix.
    """
    if not isinstance(returns_matrix, pd.DataFrame):
        raise TypeError("returns_matrix must be a pd.DataFrame")
    if not isinstance(target_corr_matrix, pd.DataFrame):
        raise TypeError("target_corr_matrix must be a pd.DataFrame")

    cols = list(returns_matrix.columns)
    if list(target_corr_matrix.columns) != cols or list(target_corr_matrix.index) != cols:
        raise ValueError(
            "target_corr_matrix index/columns must match returns_matrix.columns"
        )

    C = target_corr_matrix.to_numpy(dtype=float)
    C = 0.5 * (C + C.T)  # symmetrize
    if not np.allclose(np.diag(C), 1.0, atol=1e-6):
        raise ValueError("target_corr_matrix must have unit diagonal")

    # Spectral repair if non-PD
    eigvals, eigvecs = np.linalg.eigh(C)
    if eigvals.min() < 1e-10:
        eigvals = np.clip(eigvals, 1e-8, None)
        C = (eigvecs * eigvals) @ eigvecs.T
        C = 0.5 * (C + C.T)
        # Renormalize to unit diagonal
        d = np.sqrt(np.diag(C))
        C = C / np.outer(d, d)

    L = _safe_cholesky(C)
    rng = child_rng(seed_name)
    T = len(returns_matrix)
    n = len(cols)
    Z = rng.standard_normal(size=(T, n))
    # ZCA whiten BEFORE Cholesky so target C is applied to truly iid
    # unit-variance inputs (see force_correlation for rationale).
    Z = _whiten_columns(Z)
    Y = Z @ L.T

    X = returns_matrix.to_numpy(dtype=float)
    if preserve_marginals:
        out = np.zeros_like(Y)
        for j in range(n):
            sorted_emp = np.sort(X[:, j])
            order = np.argsort(np.argsort(Y[:, j]))
            out[:, j] = sorted_emp[order]
    else:
        # ``ddof=1`` matches cscv._sharpe_columns so cross-module statistics
        # use the same sample-variance convention.
        mu = X.mean(axis=0)
        sd = X.std(axis=0, ddof=1)
        out = Y * sd + mu

    return pd.DataFrame(out, index=returns_matrix.index, columns=cols)


# --------------------------------------------------------------------------- #
# Diversification ratio                                                       #
# --------------------------------------------------------------------------- #
def diversification_ratio(returns_matrix: pd.DataFrame,
                          weights: pd.Series) -> float:
    """Choueifaty-Coignard diversification ratio.

    DR = sum_i (|w_i| * sigma_i) / sigma_portfolio

    Where sigma_i is the per-asset std and sigma_portfolio is the std of
    the weighted portfolio returns sum_i w_i * r_i.

    DR = 1   -> no diversification benefit (portfolio behaves like one asset)
    DR > 1   -> diversification effective
    """
    if not isinstance(returns_matrix, pd.DataFrame):
        raise TypeError("returns_matrix must be a pd.DataFrame")
    if not isinstance(weights, pd.Series):
        raise TypeError("weights must be a pd.Series")
    cols = list(returns_matrix.columns)
    if list(weights.index) != cols:
        # Reindex; missing values become 0
        weights = weights.reindex(cols).fillna(0.0)

    w = weights.to_numpy(dtype=float)
    X = returns_matrix.to_numpy(dtype=float)
    sigmas = X.std(axis=0, ddof=0)
    numer = float(np.sum(np.abs(w) * sigmas))
    port_rets = X @ w
    sig_port = float(port_rets.std(ddof=0))
    if sig_port < 1e-15:
        return 0.0
    return numer / sig_port


# --------------------------------------------------------------------------- #
# Stress orchestrator                                                         #
# --------------------------------------------------------------------------- #
def _prices_from_returns(prices_dict: dict, returns_matrix: pd.DataFrame) -> dict:
    """Rebuild a price dict from a synthetic returns matrix using each asset's
    empirical starting price."""
    out = {}
    for sym in returns_matrix.columns:
        p0 = float(prices_dict[sym].iloc[0])
        rets = returns_matrix[sym].to_numpy(dtype=float)
        # Reconstruct prices: first bar = p0, then p0 * cumprod(1+r) on the
        # remaining bars (returns_matrix already has T bars, but the first row
        # represents the return INTO the second timestamp). Convention:
        # prices_dict has T+1 bars in general, but we accept T bars in
        # returns_matrix as len(prices)-1. Caller handles index alignment.
        nav = np.concatenate([[1.0], np.cumprod(1.0 + rets)])
        prices_full = p0 * nav
        # Build a Series of length len(rets)+1 indexed against prices_dict[sym]
        idx_full = prices_dict[sym].index
        if len(prices_full) != len(idx_full):
            # Fallback: align by length
            idx_full = idx_full[: len(prices_full)]
            prices_full = prices_full[: len(idx_full)]
        out[sym] = pd.Series(prices_full, index=idx_full, name=sym)
    return out


def stress_correlation_breakdown(strategy_factory: Callable,
                                 prices_dict: dict[str, pd.Series],
                                 weights_dict: dict[str, np.ndarray] = None,
                                 ppy: int = 252,
                                 custom_target: Optional[pd.DataFrame] = None,
                                 seed_name: str = "corr_stress",
                                 gross_leverage_cap: float = 1.0,
                                 net_leverage_cap: float = 2.0) -> CorrelationStressResult:
    """Stress-test a strategy / portfolio under different correlation regimes.

    Steps:
        1. Build empirical returns matrix from prices_dict (intersection idx).
        2. Run base regime via MultiAssetEngine on supplied weights.
        3. Force corr matrix to identity (decorrelated). Re-run.
        4. Force corr matrix to ~0.99 (crisis). Re-run.
        5. Optional: custom target matrix. Re-run.

    Args:
        strategy_factory: callable. If `weights_dict` is not None this argument
            is allowed to be None (we just consume the precomputed weights).
            Otherwise it must accept (prices_dict_synth) and return a
            weight_dict {symbol: np.array}.
        prices_dict: dict[symbol -> pd.Series] of empirical prices.
        weights_dict: optional dict[symbol -> np.array] of weights aligned to
            the *intersection* index of prices_dict. If supplied, used for
            all regimes. If None, strategy_factory is invoked per regime.
        ppy: periods per year.
        custom_target: optional DataFrame with custom target correlation.
        seed_name: child RNG namespace prefix.

    Returns:
        CorrelationStressResult.
    """
    if not prices_dict:
        raise ValueError("prices_dict is empty")
    if weights_dict is None and strategy_factory is None:
        raise ValueError("supply either strategy_factory or weights_dict")

    # Build aligned returns matrix
    symbols = sorted(prices_dict.keys())
    common_idx = None
    for s in symbols:
        idx = prices_dict[s].index
        common_idx = idx if common_idx is None else common_idx.intersection(idx)
    aligned_prices = {s: prices_dict[s].reindex(common_idx) for s in symbols}
    rets_df = pd.DataFrame(
        {s: aligned_prices[s].pct_change().fillna(0.0).values for s in symbols},
        index=common_idx,
    )
    # Drop the first row (zero by construction) so the matrix represents true returns
    rets_df_nz = rets_df.iloc[1:].copy()

    base_corr = rets_df_nz.corr()

    # Helper to run one regime. A fresh MultiAssetEngine is instantiated per
    # call so any internal state (cached covariance, leverage tracking,
    # rebalance bookkeeping) cannot bleed between regimes — using a single
    # shared engine produced subtle cross-regime contamination on long runs.
    def _run_regime(synth_rets_or_none: Optional[pd.DataFrame]) -> dict:
        engine = MultiAssetEngine(
            gross_leverage_cap=gross_leverage_cap,
            net_leverage_cap=net_leverage_cap,
        )
        if synth_rets_or_none is None:
            # Base regime: use empirical prices directly
            run_prices = aligned_prices
        else:
            run_prices = _prices_from_returns(aligned_prices, synth_rets_or_none)
        # Resolve weights for this regime
        if weights_dict is not None:
            w_use = {s: np.asarray(weights_dict[s], dtype=float) for s in symbols}
        else:
            w_use = strategy_factory(run_prices)
        # Run
        res = engine.run(run_prices, w_use, ppy=ppy)
        return res.metrics.to_dict()

    base_metrics = _run_regime(None)

    decor_synth = force_correlation(
        rets_df_nz, target_corr=0.0, preserve_marginals=True,
        seed_name=f"{seed_name}_decor",
    )
    decor_metrics = _run_regime(decor_synth)

    crisis_synth = force_correlation(
        rets_df_nz, target_corr=0.95, preserve_marginals=True,
        seed_name=f"{seed_name}_crisis",
    )
    crisis_metrics = _run_regime(crisis_synth)

    custom_metrics = None
    if custom_target is not None:
        custom_synth = custom_correlation_scenario(
            rets_df_nz, custom_target, preserve_marginals=True,
            seed_name=f"{seed_name}_custom",
        )
        custom_metrics = _run_regime(custom_synth)

    # Diversification ratio on base regime, using mean weight per asset
    if weights_dict is not None:
        mean_w = pd.Series(
            {s: float(np.mean(np.asarray(weights_dict[s], dtype=float)))
             for s in symbols}
        )
    else:
        # Use unit equal-weight as fallback
        mean_w = pd.Series({s: 1.0 / len(symbols) for s in symbols})
    dr = diversification_ratio(rets_df_nz, mean_w)

    return CorrelationStressResult(
        base_metrics=base_metrics,
        decorrelated_metrics=decor_metrics,
        correlated_metrics=crisis_metrics,
        custom_metrics=custom_metrics,
        base_correlation=base_corr,
        diversification_ratio=dr,
    )
