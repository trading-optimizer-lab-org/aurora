"""Universe rebalance gate (R134).

When the underlying universe (e.g. S&P 500 constituents) shifts,
audit which approved strategies depend on the affected names.
Strategies referencing a removed name auto-pause until a manual
ceremony.

Pure-data primitive: the consumer (live wrapper / daily ops) is
responsible for actually pausing the strategy. This module just
detects the diff.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List


@dataclass(frozen=True)
class UniverseDiff:
    """Symbols added vs removed between two universe snapshots."""

    added: FrozenSet[str]
    removed: FrozenSet[str]
    timestamp_iso: str


def diff_universe(
    previous: set[str] | list[str],
    current: set[str] | list[str],
    timestamp_iso: str = "",
) -> UniverseDiff:
    """Return added / removed sets between two universe snapshots."""
    prev = frozenset(previous)
    cur = frozenset(current)
    return UniverseDiff(
        added=frozenset(cur - prev),
        removed=frozenset(prev - cur),
        timestamp_iso=timestamp_iso,
    )


def affected_strategies(
    diff: UniverseDiff,
    strategy_universes: Dict[str, set[str] | list[str]],
) -> List[str]:
    """Return strategy ids that reference any removed symbol.

    Removed symbols are the dangerous side: a strategy that holds a
    delisted name has nowhere to trade. Added symbols are
    informational only.
    """
    if not diff.removed:
        return []
    out: List[str] = []
    for sid, universe in strategy_universes.items():
        if any(sym in diff.removed for sym in universe):
            out.append(sid)
    return out


__all__ = [
    "UniverseDiff",
    "diff_universe",
    "affected_strategies",
]
