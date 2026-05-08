"""Hierarchical Risk Parity (HRP) allocator.

Reference: Lopez de Prado (2016), "Building Diversified Portfolios that
Outperform Out-of-Sample". Source style adapted from PyPortfolioOpt
(pypfopt/hierarchical_portfolio.py, Robert Martin, MIT).

Algorithm (de Prado 2016):
1. Tree clustering   : convert correlation -> distance d_ij = sqrt(0.5*(1-rho_ij)),
                       build hierarchical clustering via scipy.linkage.
2. Quasi-diagonalize : reorder rows/cols of the covariance so similar assets
                       are adjacent (dendrogram leaf order).
3. Recursive bisect  : split sorted index into halves, allocate inversely to
                       cluster variance (1 / sigma^2_cluster), recurse.

HRP is long-only by construction. Weights sum to 1.0.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
from scipy.spatial.distance import squareform


# de Prado HRP uses ``single`` linkage on a correlation-derived distance
# matrix. ``ward`` requires Euclidean inputs (it minimizes squared-Euclidean
# variance) and is therefore invalid on the d_ij = sqrt(0.5 * (1 - rho_ij))
# distance space; we keep it out of the allow-list to prevent silent misuse.
_VALID_LINKAGE = ("single", "complete", "average")
_VALID_COV_ESTIMATOR = ("sample", "ledoit_wolf")


# --------------------------------------------------------------------------- #
# Result                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class HRPResult:
    """Output of hrp_allocate()."""
    weights: pd.Series          # one weight per asset, sums to 1.0
    cluster_tree: np.ndarray    # linkage matrix from scipy (shape (N-1, 4))
    sorted_order: list          # asset names in quasi-diagonalization order
    correlation: pd.DataFrame   # NxN correlation matrix used
    distance: pd.DataFrame      # NxN distance matrix d_ij = sqrt(0.5*(1-rho_ij))


# --------------------------------------------------------------------------- #
# Primitive helpers                                                           #
# --------------------------------------------------------------------------- #
def correlation_distance(corr: pd.DataFrame) -> pd.DataFrame:
    """Convert correlation matrix to distance matrix.

    d_ij = sqrt(0.5 * (1 - corr_ij)). Result is in [0, 1]:
        rho =  1 -> d = 0   (identical)
        rho =  0 -> d ~ 0.707
        rho = -1 -> d = 1   (anti-correlated)
    """
    if not isinstance(corr, pd.DataFrame):
        raise TypeError("corr must be a pd.DataFrame")
    if corr.shape[0] != corr.shape[1]:
        raise ValueError(f"corr must be square, got {corr.shape}")
    c = corr.values.astype(float)
    # Numerical safety: clip to [-1, 1]
    c = np.clip(c, -1.0, 1.0)
    d = np.sqrt(0.5 * (1.0 - c))
    # Force exact zero on diagonal (sqrt rounding can leave ~1e-9)
    np.fill_diagonal(d, 0.0)
    return pd.DataFrame(d, index=corr.index, columns=corr.columns)


def quasi_diagonalize(linkage_mat: np.ndarray) -> list:
    """Reorder leaves based on dendrogram for quasi-diagonal correlation.

    Uses scipy.cluster.hierarchy.leaves_list, which returns the leaves of the
    dendrogram in left-to-right order, matching de Prado's "quasi-diagonal"
    sort: similar assets become adjacent.
    """
    leaves = sch.leaves_list(linkage_mat)
    return [int(x) for x in leaves]


def _cluster_variance(cov: np.ndarray, idx: np.ndarray) -> float:
    """Inverse-variance allocation -> cluster variance.

    For sub-cov C, w = (diag(C))^-1 / sum, then var = w' C w.
    """
    sub = cov[np.ix_(idx, idx)]
    diag = np.diag(sub).astype(float)
    diag = np.where(diag <= 1e-16, 1e-16, diag)  # guard against zero-vol
    inv_diag = 1.0 / diag
    w = inv_diag / inv_diag.sum()
    return float(w @ sub @ w)


def hrp_recursive_bisection(cov: pd.DataFrame, sorted_idx: list) -> pd.Series:
    """Recursive bisection step. Allocates 1/sigma weights down the tree.

    Quasi-Diag HRP semantics
    ------------------------
    This implementation follows the **Quasi-Diagonal HRP** formulation
    described in Lopez de Prado (2016): the dendrogram is collapsed into a
    quasi-diagonal ordering and the recursive bisection then splits the
    sorted index in halves at each step (``mid = len(c) // 2``). This is
    NOT the fully tree-aware variant that recurses along the actual
    dendrogram cluster boundaries; for sufficiently structured correlation
    matrices the two approaches converge, but in pathological cases they
    can disagree. The function is therefore aliased as
    :func:`quasi_diag_hrp_recursive_bisection` to make the contract
    explicit at call sites.

    Args:
        cov: NxN covariance DataFrame (rows/cols = asset names).
        sorted_idx: list of asset NAMES in quasi-diagonalization order.

    Returns:
        pd.Series indexed by asset name, weights sum to 1.0.
    """
    if not isinstance(cov, pd.DataFrame):
        raise TypeError("cov must be a pd.DataFrame")
    if cov.shape[0] != cov.shape[1]:
        raise ValueError(f"cov must be square, got {cov.shape}")
    if len(sorted_idx) != cov.shape[0]:
        raise ValueError(
            f"sorted_idx length {len(sorted_idx)} != cov size {cov.shape[0]}"
        )

    names = list(sorted_idx)
    cov_mat = cov.loc[names, names].values.astype(float)
    n = len(names)

    # Iterative bisection (de Prado, 2016): work on integer positions in sorted order.
    w = np.ones(n, dtype=float)
    clusters = [np.arange(n, dtype=int)]
    while clusters:
        new_clusters = []
        for c in clusters:
            if len(c) <= 1:
                continue
            mid = len(c) // 2
            left = c[:mid]
            right = c[mid:]
            v_left = _cluster_variance(cov_mat, left)
            v_right = _cluster_variance(cov_mat, right)
            total = v_left + v_right
            if total <= 0:
                # Degenerate: equal split between subclusters
                alpha = 0.5
            else:
                alpha = 1.0 - v_left / total  # weight for LEFT
            w[left] *= alpha
            w[right] *= (1.0 - alpha)
            new_clusters.append(left)
            new_clusters.append(right)
        clusters = new_clusters

    # Numerical guard: renormalize (should already sum to 1.0).
    s = w.sum()
    if s > 0:
        w = w / s
    return pd.Series(w, index=names)


# --------------------------------------------------------------------------- #
# Covariance estimators                                                       #
# --------------------------------------------------------------------------- #
def _estimate_cov(returns: pd.DataFrame, estimator: str) -> pd.DataFrame:
    """Sample or Ledoit-Wolf shrinkage covariance."""
    if estimator == "sample":
        return returns.cov()
    if estimator == "ledoit_wolf":
        try:
            from sklearn.covariance import LedoitWolf
        except ImportError as e:
            raise ImportError(
                "ledoit_wolf estimator requires scikit-learn (H.4 prerequisite)"
            ) from e
        lw = LedoitWolf().fit(returns.values)
        return pd.DataFrame(lw.covariance_, index=returns.columns, columns=returns.columns)
    raise ValueError(f"unknown cov_estimator: {estimator}, valid: {_VALID_COV_ESTIMATOR}")


# --------------------------------------------------------------------------- #
# Main API                                                                    #
# --------------------------------------------------------------------------- #
def hrp_allocate(
    returns: pd.DataFrame,
    linkage_method: str = "single",
    cov_estimator: str = "sample",
) -> HRPResult:
    """Quasi-Diagonal Hierarchical Risk Parity (Lopez de Prado, 2016).

    Implementation note
    -------------------
    This is the **Quasi-Diag HRP** variant: clustering produces a
    quasi-diagonal asset ordering, and recursive bisection then splits the
    SORTED INDEX in halves rather than recursing along true dendrogram
    cluster boundaries. The two formulations agree on well-structured
    matrices and the published de Prado reference uses this algorithm.
    See :func:`hrp_recursive_bisection` for details.

    Steps:
    1. Compute correlation -> distance d_ij = sqrt(0.5 * (1 - corr_ij))
    2. Hierarchical clustering (scipy.linkage on condensed distance)
    3. Quasi-diagonalize correlation matrix via dendrogram order
    4. Recursive bisection on the sorted halves; allocate inversely to risk

    Args:
        returns: DataFrame of asset returns, columns = asset names.
        linkage_method: 'single' | 'complete' | 'average'. ``'ward'`` is
            explicitly rejected (raises ``ValueError``) because it requires
            Euclidean inputs while HRP works on a correlation-derived
            distance space; de Prado (2016) uses ``'single'``.
        cov_estimator: 'sample' | 'ledoit_wolf' (requires sklearn).

    Returns:
        HRPResult with weights summing to 1.0, all weights >= 0.
    """
    # Input validation
    if not isinstance(returns, pd.DataFrame):
        raise TypeError("returns must be a pd.DataFrame")
    if returns.shape[1] < 2:
        raise ValueError(
            f"HRP requires >= 2 assets, got {returns.shape[1]}"
        )
    if returns.shape[0] < 2:
        raise ValueError(
            f"HRP requires >= 2 observations, got {returns.shape[0]}"
        )
    if linkage_method == "ward":
        raise ValueError(
            "linkage_method='ward' is not supported by HRP: ward requires "
            "Euclidean inputs but HRP operates on the correlation-derived "
            "distance d_ij = sqrt(0.5 * (1 - rho_ij)). De Prado (2016) uses "
            "'single' linkage."
        )
    if linkage_method not in _VALID_LINKAGE:
        raise ValueError(
            f"unknown linkage_method: {linkage_method}, valid: {_VALID_LINKAGE}"
        )
    if cov_estimator not in _VALID_COV_ESTIMATOR:
        raise ValueError(
            f"unknown cov_estimator: {cov_estimator}, valid: {_VALID_COV_ESTIMATOR}"
        )

    asset_names = list(returns.columns)

    # Step 1: correlation + distance
    corr = returns.corr()
    if corr.isnull().values.any():
        raise ValueError(
            "correlation contains NaN — input returns may be constant or have NaNs"
        )
    dist = correlation_distance(corr)

    # Step 2: hierarchical clustering on condensed distance
    # squareform expects checks=True by default; force-symmetrize to suppress
    # tiny float-symmetry violations from corr().
    dist_arr = dist.values.astype(float)
    dist_arr = 0.5 * (dist_arr + dist_arr.T)
    np.fill_diagonal(dist_arr, 0.0)
    condensed = squareform(dist_arr, checks=False)
    cluster_tree = sch.linkage(condensed, method=linkage_method)

    # Step 3: quasi-diagonalize (leaves of dendrogram, in left-to-right order)
    int_order = quasi_diagonalize(cluster_tree)
    sorted_names = [asset_names[i] for i in int_order]

    # Step 4: recursive bisection
    cov = _estimate_cov(returns, cov_estimator)
    weights = hrp_recursive_bisection(cov, sorted_names)

    # Reorder weights to match input column order for downstream consumers.
    weights = weights.reindex(asset_names)

    return HRPResult(
        weights=weights,
        cluster_tree=cluster_tree,
        sorted_order=sorted_names,
        correlation=corr,
        distance=dist,
    )


# Explicit alias making the Quasi-Diag HRP contract obvious at call sites.
quasi_diag_hrp = hrp_allocate
quasi_diag_hrp_recursive_bisection = hrp_recursive_bisection
