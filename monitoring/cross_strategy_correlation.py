"""Cross-strategy regime correlation alert (R154).

When N approved strategies all underperform simultaneously, run a
common-cause analysis: are they all long the same regime? Same
factor exposure? Same data dependency? Output a single-page
"common cause" summary.

Pure-data implementation. The integration with the live monitoring
loop ships separately as a consumer of this module.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class StrategySnapshot:
    """Recent state of one strategy: returns + tags."""

    strategy_id: str
    recent_returns: np.ndarray
    factor_tags: List[str] = field(default_factory=list)
    regime_tag: Optional[str] = None
    data_provider: Optional[str] = None


@dataclass(frozen=True)
class CommonCauseReport:
    """Aggregate report when multiple strategies degrade together."""

    timestamp_iso: str
    n_underperforming: int
    threshold_used: float
    underperformers: List[str]
    pairwise_max_correlation: float
    common_factor_tags: List[str]
    common_regime: Optional[str]
    common_data_provider: Optional[str]
    notes: List[str]


def find_common_cause(
    snapshots: Sequence[StrategySnapshot],
    *,
    underperform_threshold: float = -0.02,
    min_count: int = 2,
    tag_majority_fraction: float = 0.6,
    when: Optional[datetime] = None,
) -> Optional[CommonCauseReport]:
    """Detect common-cause underperformance.

    Args:
        snapshots: per-strategy recent state.
        underperform_threshold: a strategy is "underperforming" when
            its recent-returns sum is below this. Default -2%.
        min_count: alert only when at least this many strategies are
            underperforming together.
        tag_majority_fraction: a tag is reported as common when this
            fraction of underperformers share it. Default 0.6.
        when: timestamp for the report (default now UTC).

    Returns:
        :class:`CommonCauseReport` or ``None`` when fewer than
        ``min_count`` strategies underperform.
    """
    underperformers = [
        s for s in snapshots
        if s.recent_returns.sum() <= underperform_threshold
    ]
    if len(underperformers) < min_count:
        return None

    notes: List[str] = []

    # Pairwise return correlation (max across pairs).
    pair_max = 0.0
    if len(underperformers) >= 2:
        # Align on the shortest series.
        min_len = min(len(s.recent_returns) for s in underperformers)
        if min_len >= 2:
            stack = np.vstack([
                s.recent_returns[-min_len:] for s in underperformers
            ])
            corr = np.corrcoef(stack)
            mask = ~np.eye(len(underperformers), dtype=bool)
            pair_max = float(np.nanmax(corr[mask]))

    # Common factor tags by majority vote.
    flat_tags = [
        tag
        for s in underperformers
        for tag in s.factor_tags
    ]
    counter = Counter(flat_tags)
    threshold = max(1, int(round(tag_majority_fraction * len(underperformers))))
    common_tags = sorted([
        tag for tag, n in counter.items() if n >= threshold
    ])

    # Common regime / data provider.
    regimes = Counter([s.regime_tag for s in underperformers if s.regime_tag])
    providers = Counter([s.data_provider for s in underperformers if s.data_provider])
    common_regime = regimes.most_common(1)[0][0] if regimes else None
    if regimes and regimes.most_common(1)[0][1] < threshold:
        common_regime = None
    common_provider = providers.most_common(1)[0][0] if providers else None
    if providers and providers.most_common(1)[0][1] < threshold:
        common_provider = None

    if pair_max >= 0.85:
        notes.append("equity-curve correlation high; check for direct overlap")
    if common_tags:
        notes.append(f"shared factors: {', '.join(common_tags)}")
    if common_regime:
        notes.append(f"shared regime tag: {common_regime}")
    if common_provider:
        notes.append(f"shared data provider: {common_provider}")
    if not notes:
        notes.append("no obvious common-cause; consider per-strategy review")

    ts = (when or datetime.utcnow()).isoformat()
    return CommonCauseReport(
        timestamp_iso=ts,
        n_underperforming=len(underperformers),
        threshold_used=underperform_threshold,
        underperformers=[s.strategy_id for s in underperformers],
        pairwise_max_correlation=pair_max,
        common_factor_tags=common_tags,
        common_regime=common_regime,
        common_data_provider=common_provider,
        notes=notes,
    )


__all__ = [
    "StrategySnapshot",
    "CommonCauseReport",
    "find_common_cause",
]
