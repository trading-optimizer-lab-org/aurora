"""Equity-curve similarity scoring (R83).

For every pair of approved strategies in the review queue, compute a
similarity score between their equity curves so the operator does not
accidentally combine two near-duplicates into a "diversified"
portfolio.

Two scores are exposed:

- ``pearson_similarity`` -- correlation of equity curves rebased to 1.0.
  Range: [-1, 1]. 1 = identical, -1 = mirror, 0 = uncorrelated.
- ``return_correlation`` -- correlation of period returns. Less
  sensitive to compounding effects; typically the cleaner signal.

Both are pure functions; callers feed in two pd.Series indexed by date.

The roadmap entry mentions DTW (dynamic time warping). DTW is heavier
and only useful when the curves can shift in time. For the review-queue
use case (same backtest period, same data), simple correlation is the
right first cut. DTW is a follow-up.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SimilarityScore:
    """Pair-wise similarity between two equity curves."""

    strategy_id_a: str
    strategy_id_b: str
    pearson_similarity: float
    return_correlation: float
    n_overlap_bars: int

    @property
    def is_duplicate(self) -> bool:
        """Heuristic: both scores above 0.95 -> near-duplicate."""
        return (
            self.pearson_similarity >= 0.95
            and self.return_correlation >= 0.95
        )


def equity_to_returns(equity: pd.Series) -> pd.Series:
    """Convert an equity curve to period returns."""
    return equity.pct_change().dropna()


def pairwise_similarity(
    equity_a: pd.Series,
    equity_b: pd.Series,
    *,
    strategy_id_a: str = "A",
    strategy_id_b: str = "B",
) -> SimilarityScore:
    """Compute the similarity score for one pair of equity curves.

    The two curves are aligned on their common DatetimeIndex; the
    comparison uses overlap only. Curves that do not overlap return a
    score of NaN with ``n_overlap_bars=0``.
    """
    aligned_a, aligned_b = equity_a.align(equity_b, join="inner")
    n = len(aligned_a)
    if n < 2:
        return SimilarityScore(
            strategy_id_a=strategy_id_a,
            strategy_id_b=strategy_id_b,
            pearson_similarity=float("nan"),
            return_correlation=float("nan"),
            n_overlap_bars=n,
        )

    eq_a = aligned_a / aligned_a.iloc[0]
    eq_b = aligned_b / aligned_b.iloc[0]
    pearson_eq = float(np.corrcoef(eq_a.values, eq_b.values)[0, 1])

    rets_a = equity_to_returns(aligned_a)
    rets_b = equity_to_returns(aligned_b)
    rets_a, rets_b = rets_a.align(rets_b, join="inner")
    if len(rets_a) < 2:
        return_corr = float("nan")
    else:
        return_corr = float(np.corrcoef(rets_a.values, rets_b.values)[0, 1])

    return SimilarityScore(
        strategy_id_a=strategy_id_a,
        strategy_id_b=strategy_id_b,
        pearson_similarity=pearson_eq,
        return_correlation=return_corr,
        n_overlap_bars=n,
    )


def pairwise_matrix(
    equity_curves: dict[str, pd.Series],
    *,
    duplicate_threshold: float = 0.95,
) -> tuple[list[SimilarityScore], list[tuple[str, str]]]:
    """Compute the full pair-wise similarity matrix and the duplicate set.

    Args:
        equity_curves: ``{strategy_id: equity_series}`` mapping.
        duplicate_threshold: pairs with both scores above this value
            are reported as duplicates.

    Returns:
        ``(scores, duplicates)`` where ``scores`` is the full set of
        non-self pair-wise scores and ``duplicates`` is the subset of
        ``(id_a, id_b)`` pairs flagged as near-duplicates.
    """
    ids = list(equity_curves)
    scores: list[SimilarityScore] = []
    duplicates: list[tuple[str, str]] = []
    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1:]:
            score = pairwise_similarity(
                equity_curves[id_a],
                equity_curves[id_b],
                strategy_id_a=id_a,
                strategy_id_b=id_b,
            )
            scores.append(score)
            if (
                np.isfinite(score.pearson_similarity)
                and score.pearson_similarity >= duplicate_threshold
                and np.isfinite(score.return_correlation)
                and score.return_correlation >= duplicate_threshold
            ):
                duplicates.append((id_a, id_b))
    return scores, duplicates


__all__ = [
    "SimilarityScore",
    "equity_to_returns",
    "pairwise_similarity",
    "pairwise_matrix",
]
