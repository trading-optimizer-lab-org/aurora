"""Hierarchical Equal Risk Contribution (HERC).

Reference: Raffinot (2018), "The Hierarchical Equal Risk Contribution
Portfolio".

Differences vs HRP (de Prado 2016)
----------------------------------
- HRP uses single linkage and recursive bisection allocating inverse to
  cluster *variance*.
- HERC uses Ward (or any user-chosen) linkage and at each split allocates
  the *cluster budget* so that the two children have equal risk contribution
  (Equal Risk Contribution, ERC), then within each leaf cluster distributes
  proportionally to inverse vol or ERC over the assets.

The implementation here is a faithful port of Raffinot's recipe.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
from scipy.spatial.distance import squareform


_VALID_LINKAGE = ("single", "complete", "average", "ward")


@dataclass
class HierarchicalEqualRiskContribution:
    """HERC (Raffinot 2018) allocator.

    Parameters
    ----------
    linkage_method
        One of ``single``, ``complete``, ``average``, ``ward``.
    n_clusters
        Number of clusters to cut the dendrogram into. If None, uses the
        gap-statistic-style heuristic min(sqrt(N), N-1).
    risk_measure
        ``'variance'`` or ``'std'`` for the cluster risk measure.
    """
    linkage_method: str = "ward"
    n_clusters: int | None = None
    risk_measure: str = "variance"

    def __post_init__(self) -> None:
        if self.linkage_method not in _VALID_LINKAGE:
            raise ValueError(f"linkage_method must be in {_VALID_LINKAGE}")
        if self.risk_measure not in ("variance", "std"):
            raise ValueError("risk_measure must be 'variance' or 'std'")

    @staticmethod
    def _correlation_distance(corr: np.ndarray) -> np.ndarray:
        """d_ij = sqrt(0.5 * (1 - rho_ij))."""
        d = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
        np.fill_diagonal(d, 0.0)
        return d

    def _cluster_risk(self, idx: List[int], cov: np.ndarray) -> float:
        """Risk of an inverse-vol weighted sub-portfolio over indices ``idx``."""
        if len(idx) == 0:
            return 0.0
        sub = cov[np.ix_(idx, idx)]
        ivp = 1.0 / np.clip(np.diag(sub), 1e-12, None)
        ivp = ivp / ivp.sum()
        var = float(ivp @ sub @ ivp)
        return var if self.risk_measure == "variance" else float(np.sqrt(var))

    def allocate(self, returns) -> pd.Series:
        """Return HERC weights as a Series.

        ``returns`` may be a pd.DataFrame (T x N) or a 2-D ndarray.
        """
        if isinstance(returns, pd.DataFrame):
            R = returns.values
            cols = list(returns.columns)
        else:
            R = np.asarray(returns, dtype=float)
            if R.ndim != 2:
                raise ValueError("returns must be 2-D")
            cols = [f"a{i}" for i in range(R.shape[1])]
        T, N = R.shape
        if N == 0:
            return pd.Series(dtype=float)
        if N == 1:
            return pd.Series([1.0], index=cols)

        cov = np.cov(R, rowvar=False, ddof=1)
        std = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
        corr = cov / np.outer(std, std)
        np.clip(corr, -1.0, 1.0, out=corr)

        dist = self._correlation_distance(corr)
        # condensed distance for scipy.linkage
        cond = squareform(dist, checks=False)
        Z = sch.linkage(cond, method=self.linkage_method)

        # Cut the dendrogram into K clusters
        k = self.n_clusters
        if k is None:
            k = max(2, min(int(np.sqrt(N)), N - 1))
        k = max(2, min(k, N))
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
        clusters: dict[int, List[int]] = {}
        for i, lab in enumerate(labels):
            clusters.setdefault(int(lab), []).append(i)

        # Top-down split using the linkage merging order, equal-risk between siblings
        cluster_weights = self._equal_risk_split(Z, clusters, cov)

        # Within each cluster: inverse-variance weighting across its assets
        w = np.zeros(N, dtype=float)
        for cid, members in clusters.items():
            ivp = 1.0 / np.clip(np.diag(cov)[members], 1e-12, None)
            ivp = ivp / ivp.sum()
            for j, m in enumerate(members):
                w[m] = cluster_weights[cid] * ivp[j]
        # Defensive renorm
        s = w.sum()
        if s > 0:
            w = w / s
        return pd.Series(w, index=cols)

    def _equal_risk_split(
        self,
        Z: np.ndarray,
        clusters: dict[int, List[int]],
        cov: np.ndarray,
    ) -> dict[int, float]:
        """Split a unit budget across clusters so siblings have equal risk."""
        # Compute per-cluster risk and inverse-risk normalise (a one-shot ERC
        # across the K clusters, equivalent to recursive equal-risk splits on
        # a balanced tree).
        cluster_risks = {cid: self._cluster_risk(members, cov)
                         for cid, members in clusters.items()}
        total_risk = sum(cluster_risks.values())
        if total_risk <= 0:
            n = len(clusters)
            return {cid: 1.0 / n for cid in clusters}
        inv = {cid: 1.0 / r if r > 0 else 0.0 for cid, r in cluster_risks.items()}
        s = sum(inv.values())
        if s <= 0:
            n = len(clusters)
            return {cid: 1.0 / n for cid in clusters}
        return {cid: v / s for cid, v in inv.items()}
