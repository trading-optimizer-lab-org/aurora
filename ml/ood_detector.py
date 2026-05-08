"""Out-of-distribution feature detector (R145).

For ML strategies, detect when live feature distributions diverge
from training feature distributions. Two simple metrics:

- KL divergence on histogrammed features (per-dimension).
- Mahalanobis distance of the latest live sample vs the training
  mean / covariance.

The detector is intentionally light: heavyweight options like
isolation forest or autoencoder reconstruction error live as future
follow-ups. Today's job is to flag obvious drift loud and early.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np


@dataclass(frozen=True)
class DriftReport:
    """Summary of OOD comparison for one feature batch."""

    n_features: int
    kl_per_feature: List[float]
    max_kl: float
    mahalanobis_distance: float
    is_drift: bool


@dataclass
class OODDetector:
    """Train on a reference feature matrix, score new batches against it.

    Attributes:
        reference: training-time feature matrix (rows=samples, cols=features).
        kl_threshold: per-feature KL divergence above which the feature
            is flagged. Default 0.5 nats.
        mahalanobis_threshold: above which the global Mahalanobis trip
            fires. Default 5.0.
        bins: histogram bin count per feature.
    """

    reference: np.ndarray
    kl_threshold: float = 0.5
    mahalanobis_threshold: float = 5.0
    bins: int = 20
    _ref_mean: np.ndarray = field(init=False, default=None)  # type: ignore[assignment]
    _ref_cov_inv: np.ndarray = field(init=False, default=None)  # type: ignore[assignment]
    _ref_hists: List[np.ndarray] = field(init=False, default_factory=list)
    _ref_edges: List[np.ndarray] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        ref = np.asarray(self.reference, dtype=float)
        if ref.ndim != 2:
            raise ValueError("reference must be 2-D (samples x features)")
        self._ref_mean = ref.mean(axis=0)
        cov = np.cov(ref, rowvar=False)
        if cov.ndim == 0:
            cov = np.array([[float(cov)]])
        # Pseudo-inverse for robustness on singular covariances.
        self._ref_cov_inv = np.linalg.pinv(cov)
        for j in range(ref.shape[1]):
            hist, edges = np.histogram(ref[:, j], bins=self.bins, density=True)
            self._ref_hists.append(hist + 1e-12)
            self._ref_edges.append(edges)

    def score(self, batch: np.ndarray) -> DriftReport:
        """Score ``batch`` against the reference."""
        b = np.asarray(batch, dtype=float)
        if b.ndim == 1:
            b = b.reshape(1, -1)
        kls: List[float] = []
        for j in range(b.shape[1]):
            new_hist, _ = np.histogram(
                b[:, j], bins=self._ref_edges[j], density=True,
            )
            new_hist = new_hist + 1e-12
            kl = float(np.sum(self._ref_hists[j] * np.log(self._ref_hists[j] / new_hist)))
            kls.append(kl)
        max_kl = max(kls) if kls else 0.0
        # Mahalanobis on the batch mean.
        delta = b.mean(axis=0) - self._ref_mean
        mahal = float(np.sqrt(max(0.0, delta @ self._ref_cov_inv @ delta)))
        is_drift = max_kl > self.kl_threshold or mahal > self.mahalanobis_threshold
        return DriftReport(
            n_features=b.shape[1],
            kl_per_feature=kls,
            max_kl=max_kl,
            mahalanobis_distance=mahal,
            is_drift=is_drift,
        )


__all__ = [
    "DriftReport",
    "OODDetector",
]
