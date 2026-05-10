"""R180 - Local incident notes and lightweight postmortems.

Plain-data incident records persisted as JSONL. The operator opens an
incident, appends timeline entries while triaging, then closes it with a
short postmortem. Closed incidents are immutable except for explicitly
audited append-only notes.

Incident types match the R180 list: stale data, bad tick, provider
outage, broker disconnect, missing fill, duplicate fill, rejected order
spike, margin warning, drawdown breach, kill switch fired,
reconciliation mismatch, OOS leak attempt, evidence hash mismatch.
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


class IncidentSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


class IncidentKind(str, Enum):
    STALE_DATA = "stale_data"
    BAD_TICK = "bad_tick"
    PROVIDER_OUTAGE = "provider_outage"
    BROKER_DISCONNECTED = "broker_disconnected"
    MISSING_FILL = "missing_fill"
    DUPLICATE_FILL = "duplicate_fill"
    REJECTED_ORDER_SPIKE = "rejected_order_spike"
    MARGIN_WARNING = "margin_warning"
    DRAWDOWN_BREACH = "drawdown_breach"
    KILL_SWITCH_FIRED = "kill_switch_fired"
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    OOS_LEAK_ATTEMPT = "oos_leak_attempt"
    EVIDENCE_HASH_MISMATCH = "evidence_hash_mismatch"
    OTHER = "other"


class IncidentStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class IncidentNote:
    """One line on an incident timeline."""

    note_id: str
    text: str
    actor: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IncidentRecord:
    """Persisted incident."""

    incident_id: str
    severity: IncidentSeverity
    kind: IncidentKind
    title: str
    opened_at: str
    closed_at: Optional[str] = None
    affected_strategies: Tuple[str, ...] = field(default_factory=tuple)
    affected_symbols: Tuple[str, ...] = field(default_factory=tuple)
    evidence_hashes: Tuple[str, ...] = field(default_factory=tuple)
    timeline: Tuple[IncidentNote, ...] = field(default_factory=tuple)
    impact: str = ""
    root_cause: str = ""
    action_items: Tuple[str, ...] = field(default_factory=tuple)
    status: IncidentStatus = IncidentStatus.OPEN

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["kind"] = self.kind.value
        d["status"] = self.status.value
        d["timeline"] = [n.to_dict() for n in self.timeline]
        return d

    def to_postmortem(self) -> str:
        """Render a short Markdown postmortem."""
        lines = [
            f"# Incident {self.incident_id}: {self.title}",
            "",
            f"- **kind**: {self.kind.value}",
            f"- **severity**: {self.severity.value}",
            f"- **status**: {self.status.value}",
            f"- **opened_at**: {self.opened_at}",
        ]
        if self.closed_at:
            lines.append(f"- **closed_at**: {self.closed_at}")
        if self.affected_strategies:
            lines.append(
                f"- **strategies**: {', '.join(self.affected_strategies)}"
            )
        if self.affected_symbols:
            lines.append(
                f"- **symbols**: {', '.join(self.affected_symbols)}"
            )
        if self.evidence_hashes:
            lines.append(
                f"- **evidence**: {', '.join(self.evidence_hashes)}"
            )
        lines.append("")
        if self.timeline:
            lines.append("## Timeline")
            for note in self.timeline:
                lines.append(
                    f"- `{note.created_at}` ({note.actor}): {note.text}"
                )
            lines.append("")
        if self.impact:
            lines.append("## Impact")
            lines.append(self.impact)
            lines.append("")
        if self.root_cause:
            lines.append("## Root cause")
            lines.append(self.root_cause)
            lines.append("")
        if self.action_items:
            lines.append("## Action items")
            for item in self.action_items:
                lines.append(f"- {item}")
            lines.append("")
        return "\n".join(lines)


class IncidentImmutable(RuntimeError):
    """Raised when a closed incident is being modified."""


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@dataclass
class IncidentLedger:
    """JSONL-backed append-only incident ledger.

    The ledger uses an append-only model where each entry is a snapshot
    of the incident after the latest mutation. ``latest`` returns the
    most recent snapshot per ``incident_id``.
    """

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    # -- mutation ----------------------------------------------------------

    def open_incident(
        self,
        *,
        kind: IncidentKind,
        severity: IncidentSeverity,
        title: str,
        actor: str,
        affected_strategies: Iterable[str] = (),
        affected_symbols: Iterable[str] = (),
        evidence_hashes: Iterable[str] = (),
        initial_note: str = "",
        incident_id: Optional[str] = None,
    ) -> IncidentRecord:
        if not title:
            raise ValueError("title must be non-empty")
        with self._lock:
            now = _now_iso()
            inc_id = incident_id or _make_id(kind)
            timeline: Tuple[IncidentNote, ...] = ()
            if initial_note:
                timeline = (IncidentNote(
                    note_id=_make_note_id(),
                    text=initial_note,
                    actor=actor,
                    created_at=now,
                ),)
            record = IncidentRecord(
                incident_id=inc_id,
                severity=severity,
                kind=kind,
                title=title,
                opened_at=now,
                affected_strategies=tuple(sorted(set(affected_strategies))),
                affected_symbols=tuple(sorted(set(affected_symbols))),
                evidence_hashes=tuple(evidence_hashes),
                timeline=timeline,
                status=IncidentStatus.OPEN,
            )
            self._write(record)
            return record

    def append_note(
        self,
        incident_id: str,
        *,
        text: str,
        actor: str,
    ) -> IncidentRecord:
        with self._lock:
            current = self._latest(incident_id)
            note = IncidentNote(
                note_id=_make_note_id(),
                text=text,
                actor=actor,
                created_at=_now_iso(),
            )
            record = _replace(current, timeline=current.timeline + (note,))
            self._write(record)
            return record

    def close(
        self,
        incident_id: str,
        *,
        actor: str,
        impact: str,
        root_cause: str,
        action_items: Iterable[str] = (),
    ) -> IncidentRecord:
        with self._lock:
            current = self._latest(incident_id)
            if current.status is IncidentStatus.CLOSED:
                raise IncidentImmutable(
                    f"incident {incident_id} already closed"
                )
            now = _now_iso()
            note = IncidentNote(
                note_id=_make_note_id(),
                text=f"closed by {actor}",
                actor=actor,
                created_at=now,
            )
            record = _replace(
                current,
                timeline=current.timeline + (note,),
                impact=impact,
                root_cause=root_cause,
                action_items=tuple(action_items),
                status=IncidentStatus.CLOSED,
                closed_at=now,
            )
            self._write(record)
            return record

    # -- read --------------------------------------------------------------

    def latest(self, incident_id: str) -> Optional[IncidentRecord]:
        try:
            return self._latest(incident_id)
        except KeyError:
            return None

    def all_incidents(self) -> List[IncidentRecord]:
        latest: Dict[str, IncidentRecord] = {}
        for record in self._read_all():
            latest[record.incident_id] = record
        return [latest[k] for k in sorted(latest.keys())]

    def open_incidents(self) -> List[IncidentRecord]:
        return [r for r in self.all_incidents() if r.status is IncidentStatus.OPEN]

    # -- helpers -----------------------------------------------------------

    def _latest(self, incident_id: str) -> IncidentRecord:
        latest: Optional[IncidentRecord] = None
        for record in self._read_all():
            if record.incident_id == incident_id:
                latest = record
        if latest is None:
            raise KeyError(f"incident {incident_id} not found")
        return latest

    def _write(self, record: IncidentRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def _read_all(self) -> List[IncidentRecord]:
        if not self.path.exists():
            return []
        out: List[IncidentRecord] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                out.append(_record_from_payload(payload))
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id(kind: IncidentKind) -> str:
    return f"INC-{kind.value}-{uuid.uuid4().hex[:8]}"


def _make_note_id() -> str:
    return uuid.uuid4().hex[:12]


def _record_from_payload(payload: Mapping[str, Any]) -> IncidentRecord:
    timeline_raw = payload.get("timeline", [])
    timeline = tuple(IncidentNote(**n) for n in timeline_raw)
    return IncidentRecord(
        incident_id=payload["incident_id"],
        severity=IncidentSeverity(payload["severity"]),
        kind=IncidentKind(payload["kind"]),
        title=payload["title"],
        opened_at=payload["opened_at"],
        closed_at=payload.get("closed_at"),
        affected_strategies=tuple(payload.get("affected_strategies", [])),
        affected_symbols=tuple(payload.get("affected_symbols", [])),
        evidence_hashes=tuple(payload.get("evidence_hashes", [])),
        timeline=timeline,
        impact=payload.get("impact", ""),
        root_cause=payload.get("root_cause", ""),
        action_items=tuple(payload.get("action_items", [])),
        status=IncidentStatus(payload.get("status", IncidentStatus.OPEN.value)),
    )


def _replace(record: IncidentRecord, **overrides) -> IncidentRecord:
    payload = {
        "incident_id": record.incident_id,
        "severity": record.severity,
        "kind": record.kind,
        "title": record.title,
        "opened_at": record.opened_at,
        "closed_at": record.closed_at,
        "affected_strategies": record.affected_strategies,
        "affected_symbols": record.affected_symbols,
        "evidence_hashes": record.evidence_hashes,
        "timeline": record.timeline,
        "impact": record.impact,
        "root_cause": record.root_cause,
        "action_items": record.action_items,
        "status": record.status,
    }
    payload.update(overrides)
    return IncidentRecord(**payload)


__all__ = [
    "IncidentImmutable",
    "IncidentKind",
    "IncidentLedger",
    "IncidentNote",
    "IncidentRecord",
    "IncidentSeverity",
    "IncidentStatus",
]
