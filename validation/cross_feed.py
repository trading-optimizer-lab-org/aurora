"""Multi-feed cross-validation (R112).

Run the same strategy against N data providers (Yahoo, OpenBB, broker-
cached, vendor B) and assert the fitness numbers agree within
tolerance. Catches data-source-specific anomalies (split handling,
dividend adjustments, timezone bugs).

The primitive ships with the comparison logic only -- the data feeds
themselves stay pluggable so operators bring their own providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

import numpy as np

from aurora.core.metrics import compute_metrics


@dataclass(frozen=True)
class FeedResult:
    """One per-feed metric."""

    feed_name: str
    sharpe: float
    calmar: float
    cagr: float
    mdd: float


@dataclass(frozen=True)
class CrossFeedReport:
    """Aggregate view across feeds."""

    per_feed: List[FeedResult]
    sharpe_max_spread: float
    calmar_max_spread: float
    suspicious_feeds: List[str]


def cross_feed_validate(
    *,
    strategy_fn: Callable[[np.ndarray], np.ndarray],
    feed_returns: Dict[str, np.ndarray],
    sharpe_tolerance: float = 0.5,
    calmar_tolerance: float = 0.5,
    ppy: int = 252,
) -> CrossFeedReport:
    """Compare per-feed metrics and flag feeds that diverge from the median.

    Args:
        strategy_fn: callable that maps a per-feed asset-return series
            to a per-bar strategy-return series.
        feed_returns: dict of feed_name -> per-bar asset returns.
        sharpe_tolerance: feeds whose Sharpe deviates from the median
            by more than this are flagged.
        calmar_tolerance: same, for Calmar.
        ppy: periods per year.

    Returns:
        :class:`CrossFeedReport`.
    """
    if len(feed_returns) < 2:
        raise ValueError("need at least 2 feeds to cross-validate")
    rows: List[FeedResult] = []
    for feed, rets in feed_returns.items():
        strat = strategy_fn(np.asarray(rets, dtype=float))
        m = compute_metrics(strat, ppy=ppy)
        rows.append(FeedResult(
            feed_name=feed,
            sharpe=float(m.sharpe),
            calmar=float(m.calmar),
            cagr=float(m.cagr),
            mdd=float(m.mdd),
        ))
    sharpes = np.asarray([r.sharpe for r in rows])
    calmars = np.asarray([r.calmar for r in rows])
    median_sharpe = float(np.median(sharpes))
    median_calmar = float(np.median(calmars))
    suspicious = [
        r.feed_name
        for r in rows
        if abs(r.sharpe - median_sharpe) > sharpe_tolerance
        or abs(r.calmar - median_calmar) > calmar_tolerance
    ]
    return CrossFeedReport(
        per_feed=rows,
        sharpe_max_spread=float(sharpes.max() - sharpes.min()),
        calmar_max_spread=float(calmars.max() - calmars.min()),
        suspicious_feeds=suspicious,
    )


__all__ = [
    "FeedResult",
    "CrossFeedReport",
    "cross_feed_validate",
]
