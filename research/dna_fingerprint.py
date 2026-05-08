"""Strategy DNA / fingerprint similarity (R92).

Beyond R83 (equity-curve similarity): a fingerprint that mixes
signal-vector similarity, parameter-space similarity, and a composite
score so a new candidate too close to a production strategy is
auto-archived rather than competing for review-queue slots.

Three sub-scores feed one composite:

- ``signal_similarity``: cosine similarity of signal vectors.
- ``parameter_similarity``: 1 - normalised distance in parameter space.
- ``equity_similarity``: Pearson correlation of equity curves
  (delegated to R83 if the caller passes them in).

Composite = weighted average. Default weights treat the three sources
as equally informative; operators can override.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

import numpy as np


@dataclass(frozen=True)
class FingerprintScores:
    """One similarity comparison of two strategies."""

    signal_similarity: float
    parameter_similarity: float
    equity_similarity: float
    composite: float


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float).ravel()
    b = np.asarray(b, dtype=float).ravel()
    if len(a) == 0 or len(b) == 0:
        return 0.0
    if len(a) != len(b):
        # Pad / truncate to the shorter length so the metric is defined.
        m = min(len(a), len(b))
        a, b = a[:m], b[:m]
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _parameter_distance(
    params_a: Mapping[str, float],
    params_b: Mapping[str, float],
) -> float:
    """Normalised Euclidean distance in the shared parameter subspace.

    Each shared key is z-scored using the pair-wise mean and range to
    avoid one large-scale parameter dominating.
    """
    common = sorted(set(params_a) & set(params_b))
    if not common:
        return 0.0
    diffs = []
    for key in common:
        a = float(params_a[key])
        b = float(params_b[key])
        scale = max(abs(a), abs(b), 1.0)
        diffs.append((a - b) / scale)
    return float(np.linalg.norm(diffs) / np.sqrt(len(common)))


def fingerprint(
    *,
    signal_vector_a: np.ndarray,
    signal_vector_b: np.ndarray,
    params_a: Mapping[str, float],
    params_b: Mapping[str, float],
    equity_a: Optional[np.ndarray] = None,
    equity_b: Optional[np.ndarray] = None,
    weights: Optional[Mapping[str, float]] = None,
) -> FingerprintScores:
    """Compare two strategies and return their similarity scores."""
    sig_sim = _cosine_similarity(signal_vector_a, signal_vector_b)
    param_dist = _parameter_distance(params_a, params_b)
    param_sim = max(0.0, 1.0 - param_dist)
    if equity_a is not None and equity_b is not None:
        m = min(len(equity_a), len(equity_b))
        if m >= 5:
            corr = float(np.corrcoef(np.asarray(equity_a)[:m],
                                     np.asarray(equity_b)[:m])[0, 1])
            equity_sim = (corr + 1.0) / 2.0
        else:
            equity_sim = 0.0
    else:
        equity_sim = 0.0

    w = dict(weights or {"signal": 1.0, "parameter": 1.0, "equity": 1.0})
    total = w["signal"] + w["parameter"] + w["equity"]
    composite = (
        w["signal"] * sig_sim
        + w["parameter"] * param_sim
        + w["equity"] * equity_sim
    ) / total if total > 0 else 0.0
    return FingerprintScores(
        signal_similarity=sig_sim,
        parameter_similarity=param_sim,
        equity_similarity=equity_sim,
        composite=composite,
    )


def is_too_similar(scores: FingerprintScores, *, threshold: float = 0.85) -> bool:
    """True iff the composite score breaches the auto-archive threshold."""
    return scores.composite >= threshold


__all__ = [
    "FingerprintScores",
    "fingerprint",
    "is_too_similar",
]
