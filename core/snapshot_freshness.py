"""Snapshot freshness audit (R143).

Flag snapshots older than a configurable window (default 90 days) as
stale. The auditor refuses to use a stale snapshot for a fresh
backtest unless the operator overrides with a recorded reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


DEFAULT_FRESH_WINDOW = timedelta(days=90)


@dataclass(frozen=True)
class FreshnessVerdict:
    """Per-snapshot freshness result."""

    snapshot_id: str
    age: timedelta
    is_fresh: bool
    cutoff: timedelta


def audit_freshness(
    snapshots: List[dict],
    *,
    cutoff: timedelta = DEFAULT_FRESH_WINDOW,
    now: Optional[datetime] = None,
) -> List[FreshnessVerdict]:
    """Return per-snapshot freshness verdicts.

    Args:
        snapshots: list of dicts with at least ``sha256`` and
            ``created_at`` (ISO string or datetime). Other keys
            ignored.
        cutoff: maximum acceptable age. Default 90 days.
        now: override "now" for tests. Default ``datetime.utcnow()``.

    Returns:
        ``FreshnessVerdict`` per snapshot, in input order.
    """
    n = now or datetime.utcnow()
    out: List[FreshnessVerdict] = []
    for snap in snapshots:
        sha = str(snap.get("sha256") or snap.get("snapshot_id") or "")
        created_raw = snap.get("created_at")
        if isinstance(created_raw, datetime):
            created = created_raw
        elif isinstance(created_raw, str):
            try:
                created = datetime.fromisoformat(created_raw)
            except ValueError:
                # Treat unparseable as infinitely old so it is flagged.
                created = n - cutoff * 10
        else:
            created = n - cutoff * 10
        age = n - created
        out.append(FreshnessVerdict(
            snapshot_id=sha,
            age=age,
            is_fresh=age <= cutoff,
            cutoff=cutoff,
        ))
    return out


def stale_snapshots(verdicts: List[FreshnessVerdict]) -> List[str]:
    return [v.snapshot_id for v in verdicts if not v.is_fresh]


__all__ = [
    "DEFAULT_FRESH_WINDOW",
    "FreshnessVerdict",
    "audit_freshness",
    "stale_snapshots",
]
