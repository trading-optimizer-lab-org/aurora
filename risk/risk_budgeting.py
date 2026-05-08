"""Bucketed Risk Budgeting allocator.

Reference: Bruder & Roncalli (2012), "Managing Risk Exposures using the Risk
Budgeting Approach". Roncalli (2013), "Introduction to Risk Parity and
Budgeting".

Group assets by an arbitrary bucket label (sector, region, style) and
allocate so that each *bucket* contributes a target fraction of total
portfolio risk. Within each bucket, weights are inverse-vol.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Mapping

import numpy as np


@dataclass
class RiskBudgetingAllocator:
    """Risk budgeting by bucket.

    Parameters
    ----------
    targets
        Mapping bucket_label -> target fraction of total portfolio risk.
        Must be non-negative and sum to 1.0 (renormalised if not).
    long_only
        If True, weights are non-negative.
    max_iter, tol
        Iterative solver controls.
    """
    targets: Mapping[str, float] = field(default_factory=dict)
    long_only: bool = True
    max_iter: int = 500
    tol: float = 1e-9

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("targets cannot be empty")
        for k, v in self.targets.items():
            if v < 0:
                raise ValueError(f"target for '{k}' must be >= 0")
        s = sum(self.targets.values())
        if s <= 0:
            raise ValueError("sum of targets must be > 0")
        # Renormalise if the user supplied unnormalised weights (e.g. percentages)
        if abs(s - 1.0) > 1e-9:
            self.targets = {k: v / s for k, v in self.targets.items()}

    def allocate(self, returns_matrix, buckets: list[str]) -> np.ndarray:
        """Compute risk-budgeting weights.

        ``buckets[j]`` is the bucket label of column j in ``returns_matrix``.
        Output weights match the column order of ``returns_matrix``.
        """
        R = np.asarray(returns_matrix, dtype=float)
        if R.ndim != 2:
            raise ValueError("returns_matrix must be 2-D")
        T, N = R.shape
        if len(buckets) != N:
            raise ValueError("len(buckets) must equal number of columns")
        if N == 0:
            return np.array([])
        if T < 2:
            return np.full(N, 1.0 / N)

        Sigma = np.cov(R, rowvar=False, ddof=1)
        std = np.sqrt(np.clip(np.diag(Sigma), 1e-16, None))

        # Map bucket -> column indices
        bmap: dict[str, list[int]] = {}
        for i, b in enumerate(buckets):
            bmap.setdefault(b, []).append(i)

        # Identify any buckets present in data but not in self.targets, and vice
        # versa. Missing bucket targets get 0; weights inside such buckets remain 0.
        active_buckets = [b for b in bmap if self.targets.get(b, 0.0) > 0]

        # Iteratively rescale per-bucket sub-allocations so cluster risk
        # contributions match self.targets.
        w = np.zeros(N, dtype=float)
        # Initial inverse-vol within bucket, equal across active buckets
        if active_buckets:
            init_share = 1.0 / len(active_buckets)
            for b in active_buckets:
                idx = bmap[b]
                inv = 1.0 / std[idx]
                inv = inv / inv.sum()
                for j, m in enumerate(idx):
                    w[m] = init_share * inv[j]
        else:
            return np.full(N, 1.0 / N)

        for _ in range(self.max_iter):
            pv2 = float(w @ Sigma @ w)
            if pv2 <= 1e-16:
                break
            # Risk contribution per asset: RC_i = w_i * (Sigma w)_i / pv
            sw = Sigma @ w
            rc_asset = w * sw / np.sqrt(pv2)
            # Aggregate to bucket level
            new_w = w.copy()
            for b in active_buckets:
                idx = bmap[b]
                rc_b = float(rc_asset[idx].sum())
                if rc_b <= 1e-16:
                    continue
                target_share = self.targets[b]
                cur_share = rc_b / np.sqrt(pv2) if False else rc_b / np.sum(rc_asset)
                if cur_share <= 1e-16:
                    continue
                scale = np.sqrt(target_share / cur_share)
                new_w[idx] = new_w[idx] * scale
            # Renormalise to sum 1
            if self.long_only:
                new_w = np.clip(new_w, 0.0, None)
            s = new_w.sum()
            if s <= 1e-16:
                break
            new_w = new_w / s
            if np.linalg.norm(new_w - w) < self.tol:
                w = new_w
                break
            w = new_w
        return w

    def bucket_contributions(
        self, weights, returns_matrix, buckets: list[str]
    ) -> dict[str, float]:
        """Realised risk contribution per bucket as a fraction of total."""
        w = np.asarray(weights, dtype=float)
        R = np.asarray(returns_matrix, dtype=float)
        Sigma = np.cov(R, rowvar=False, ddof=1)
        sw = Sigma @ w
        rc = w * sw
        total = rc.sum()
        out: dict[str, float] = {}
        if total <= 1e-16:
            for b in self.targets:
                out[b] = 0.0
            return out
        for b in self.targets:
            idx = [i for i, lab in enumerate(buckets) if lab == b]
            out[b] = float(rc[idx].sum() / total) if idx else 0.0
        return out
