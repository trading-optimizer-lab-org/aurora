"""Strategy graveyard view (R39).

Surfaces every archived candidate with its rejection reason and
timestamp so an operator can see "what we tried and why it failed".
Pairs with R9 (RAG) so the graveyard is searchable, with R140
(lifecycle SLA + auto-archive) so SLA-expired versions land here, and
with R152 (ancestry tree) so the lineage of archived variants is
visible.

The primitive reads the existing research-archive JSONL produced by
the factory and the lifecycle SLA module and projects rejected /
archived rows into a uniform :class:`GraveyardEntry`. The CLI surface
(`forge research graveyard`) consumes these entries; this module
deliberately keeps the data plumbing separate from the CLI so the
read path is testable without touching the 3000+ line CLI dispatcher.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class GraveyardEntry:
    """One archived / rejected strategy version."""

    strategy_id: str
    version: str
    rejection_reason: str
    rejected_at: str
    family: Optional[str] = None
    parent_version: Optional[str] = None
    final_metric: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


_REJECTION_EVENTS = {
    "rejected",
    "archived",
    "sla_expired",
    "superseded",
}


def read_graveyard(archive_path: Path) -> List[GraveyardEntry]:
    """Read the research archive JSONL and project rejected rows."""
    if not archive_path.exists():
        return []
    out: List[GraveyardEntry] = []
    with archive_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            event = str(row.get("event", row.get("status", "")))
            if event not in _REJECTION_EVENTS:
                continue
            out.append(GraveyardEntry(
                strategy_id=str(row.get("strategy_id", "")),
                version=str(row.get("version", "")),
                rejection_reason=str(row.get("reason", row.get("rejection_reason", ""))),
                rejected_at=str(row.get("timestamp", row.get("rejected_at", ""))),
                family=row.get("family"),
                parent_version=row.get("parent_version"),
                final_metric=(
                    float(row["final_metric"])
                    if "final_metric" in row and row["final_metric"] is not None
                    else None
                ),
                extra={
                    k: v for k, v in row.items()
                    if k not in {
                        "event", "status", "strategy_id", "version",
                        "reason", "rejection_reason", "timestamp",
                        "rejected_at", "family", "parent_version",
                        "final_metric",
                    }
                },
            ))
    return out


def filter_graveyard(
    entries: Iterable[GraveyardEntry],
    *,
    family: Optional[str] = None,
    reason_substring: Optional[str] = None,
    since: Optional[str] = None,
) -> List[GraveyardEntry]:
    """Apply common filters used by the CLI."""
    out = list(entries)
    if family is not None:
        out = [e for e in out if e.family == family]
    if reason_substring is not None:
        s = reason_substring.lower()
        out = [e for e in out if s in e.rejection_reason.lower()]
    if since is not None:
        out = [e for e in out if e.rejected_at >= since]
    return out


def format_table(entries: Iterable[GraveyardEntry]) -> str:
    """Plain-text table renderer suitable for CLI output."""
    rows = [
        ("strategy_id", "version", "family", "rejection_reason", "rejected_at"),
    ]
    for e in entries:
        rows.append((
            e.strategy_id,
            e.version,
            e.family or "",
            e.rejection_reason,
            e.rejected_at,
        ))
    widths = [
        max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))
    ]
    out_lines = []
    for r in rows:
        line = "  ".join(str(r[i]).ljust(widths[i]) for i in range(len(r)))
        out_lines.append(line)
    return "\n".join(out_lines)


__all__ = [
    "GraveyardEntry",
    "read_graveyard",
    "filter_graveyard",
    "format_table",
]
