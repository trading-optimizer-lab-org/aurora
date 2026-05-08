"""Cross-validation matrix visualisation (R97).

Render the CSCV / PBO output as a matrix of train / test fold
performance plus a delta heatmap. Pure-data: returns numpy matrices
that the tearsheet (R51 split future) renders.

Surfaces "the strategy looks fine on average but has a fold where it
loses 30%" which a single point estimate hides.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

import numpy as np


@dataclass(frozen=True)
class CVMatrix:
    """A train / test metric matrix across folds."""

    fold_labels: List[str]
    train_metrics: np.ndarray
    test_metrics: np.ndarray

    @property
    def delta(self) -> np.ndarray:
        """train - test per fold; positive means overfit."""
        return self.train_metrics - self.test_metrics

    @property
    def median_delta(self) -> float:
        return float(np.median(self.delta))

    @property
    def worst_fold_index(self) -> int:
        """Index of the fold with the largest train-minus-test gap."""
        return int(np.argmax(self.delta))

    def summary(self) -> str:
        lines = [
            f"folds={len(self.fold_labels)}",
            f"train mean={self.train_metrics.mean():.4f}",
            f"test mean={self.test_metrics.mean():.4f}",
            f"median delta={self.median_delta:+.4f}",
            f"worst fold={self.fold_labels[self.worst_fold_index]} "
            f"(delta={self.delta[self.worst_fold_index]:+.4f})",
        ]
        return "\n".join(lines)


def build_matrix(
    fold_labels: Sequence[str],
    train_metrics: Sequence[float],
    test_metrics: Sequence[float],
) -> CVMatrix:
    if not (len(fold_labels) == len(train_metrics) == len(test_metrics)):
        raise ValueError("fold_labels / train_metrics / test_metrics length mismatch")
    return CVMatrix(
        fold_labels=list(fold_labels),
        train_metrics=np.asarray(train_metrics, dtype=float),
        test_metrics=np.asarray(test_metrics, dtype=float),
    )


__all__ = [
    "CVMatrix",
    "build_matrix",
]
