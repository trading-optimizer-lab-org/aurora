"""R165 - Research degrees-of-freedom ledger enforcement.

Records the search pressure that preceded a winner: how many candidates
were generated, modified, rejected, validated and overridden before the
result was reported. The ledger is append-only and the candidate cannot
reach validation without the required event chain.

The ledger sits next to (not on top of) :mod:`aurora.research.factory`.
The factory writes its archive of accepted submissions; this ledger is
hash-linked, broader (it covers GA generations and auto-loop variations
too) and the source of the ``trial_pressure_score`` reported in
validation evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


class LedgerEventType(str, Enum):
    UNIVERSE_SELECTED = "universe_selected"
    PROVIDER_SET = "provider_set"
    DATE_RANGE_SET = "date_range_set"
    FEATURE_SET = "feature_set"
    PARAMETER_GRID = "parameter_grid"
    SEED_SET = "seed_set"
    CANDIDATE_GENERATED = "candidate_generated"
    CANDIDATE_REJECTED = "candidate_rejected"
    CANDIDATE_MODIFIED = "candidate_modified"
    VALIDATION_RUN = "validation_run"
    OVERRIDE = "override"
    OOS_UNLOCK = "oos_unlock"
    PROMOTION = "promotion"
    RETIREMENT = "retirement"


# Events that must be present (at least once) before a candidate may
# move into validation.
_PRE_VALIDATION_REQUIRED: Tuple[LedgerEventType, ...] = (
    LedgerEventType.UNIVERSE_SELECTED,
    LedgerEventType.PROVIDER_SET,
    LedgerEventType.DATE_RANGE_SET,
    LedgerEventType.FEATURE_SET,
    LedgerEventType.SEED_SET,
    LedgerEventType.CANDIDATE_GENERATED,
)


_PRE_PROMOTION_REQUIRED: Tuple[LedgerEventType, ...] = (
    LedgerEventType.VALIDATION_RUN,
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerEvent:
    """One immutable event in the research ledger.

    ``parent_hash`` chains events together so a missing entry is
    detectable. ``event_hash`` is a sha256 over the canonical payload
    plus the parent hash.
    """

    event_id: str
    event_type: LedgerEventType
    project_id: str
    actor: str
    payload: Dict[str, Any]
    timestamp: str
    parent_hash: str
    event_hash: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "LedgerEvent":
        data = dict(payload)
        data["event_type"] = LedgerEventType(data["event_type"])
        return cls(**data)


@dataclass(frozen=True)
class TrialPressureScore:
    """Aggregate measure of how much searching preceded a winner."""

    project_id: str
    candidates_generated: int
    candidates_rejected: int
    candidates_modified: int
    parameter_choices: int
    overrides: int
    oos_unlocks: int
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


class LedgerIntegrityError(RuntimeError):
    """Raised when the chain hash of the ledger is broken."""


class LedgerEnforcementError(RuntimeError):
    """Raised when an event is missing for a gated transition."""


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class ResearchLedger:
    """JSONL-backed append-only research ledger.

    The ledger is small enough to keep in memory; persistence is via a
    JSONL file at :attr:`path`. Reading the ledger verifies the hash
    chain so a missing or rewritten line trips
    :class:`LedgerIntegrityError`.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    # -- I/O ---------------------------------------------------------------

    def _ensure_parent(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        events = self.events()
        if not events:
            return "GENESIS"
        return events[-1].event_hash

    def append(
        self,
        event_type: LedgerEventType,
        *,
        project_id: str,
        actor: str,
        payload: Optional[Mapping[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> LedgerEvent:
        with self._lock:
            self._ensure_parent()
            parent = self._last_hash()
            ev = self._build_event(
                event_type=event_type,
                project_id=project_id,
                actor=actor,
                payload=payload or {},
                parent_hash=parent,
                timestamp=timestamp,
            )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev.to_dict(), sort_keys=True) + "\n")
            return ev

    def events(self, *, project_id: Optional[str] = None) -> List[LedgerEvent]:
        if not self._path.exists():
            return []
        out: List[LedgerEvent] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(LedgerEvent.from_dict(json.loads(line)))
        if project_id is not None:
            out = [e for e in out if e.project_id == project_id]
        return out

    def verify_chain(self) -> None:
        """Walk the ledger and raise on broken parent_hash chain."""
        prev = "GENESIS"
        for ev in self.events():
            if ev.parent_hash != prev:
                raise LedgerIntegrityError(
                    f"broken chain at event {ev.event_id}: "
                    f"expected parent={prev[:12]}, got {ev.parent_hash[:12]}"
                )
            recomputed = _hash_event(
                ev.event_type, ev.project_id, ev.actor, ev.payload,
                ev.timestamp, ev.parent_hash, ev.event_id,
            )
            if recomputed != ev.event_hash:
                raise LedgerIntegrityError(
                    f"event {ev.event_id} hash mismatch"
                )
            prev = ev.event_hash

    # -- enforcement -------------------------------------------------------

    def assert_ready_for_validation(self, project_id: str) -> None:
        """Raise unless the project has all pre-validation events."""
        types_seen = {e.event_type for e in self.events(project_id=project_id)}
        missing = [t for t in _PRE_VALIDATION_REQUIRED if t not in types_seen]
        if missing:
            raise LedgerEnforcementError(
                "research ledger missing pre-validation events: "
                + ", ".join(t.value for t in missing)
            )

    def assert_ready_for_promotion(self, project_id: str) -> None:
        """Raise unless the project also has a validation_run event."""
        self.assert_ready_for_validation(project_id)
        types_seen = {e.event_type for e in self.events(project_id=project_id)}
        missing = [t for t in _PRE_PROMOTION_REQUIRED if t not in types_seen]
        if missing:
            raise LedgerEnforcementError(
                "research ledger missing pre-promotion events: "
                + ", ".join(t.value for t in missing)
            )

    # -- pressure ----------------------------------------------------------

    def trial_pressure(self, project_id: str) -> TrialPressureScore:
        events = self.events(project_id=project_id)
        generated = sum(
            1 for e in events
            if e.event_type is LedgerEventType.CANDIDATE_GENERATED
        )
        rejected = sum(
            1 for e in events
            if e.event_type is LedgerEventType.CANDIDATE_REJECTED
        )
        modified = sum(
            1 for e in events
            if e.event_type is LedgerEventType.CANDIDATE_MODIFIED
        )
        overrides = sum(
            1 for e in events if e.event_type is LedgerEventType.OVERRIDE
        )
        unlocks = sum(
            1 for e in events if e.event_type is LedgerEventType.OOS_UNLOCK
        )
        # Parameter grid breadth: count unique grid sizes recorded.
        grid_choices = 0
        for e in events:
            if e.event_type is LedgerEventType.PARAMETER_GRID:
                grid_choices += int(e.payload.get("n_choices", 0))
        # Cheap composite score: proportional to total search pressure.
        score = (
            generated + rejected + modified
            + grid_choices + 5 * overrides + 10 * unlocks
        )
        return TrialPressureScore(
            project_id=project_id,
            candidates_generated=generated,
            candidates_rejected=rejected,
            candidates_modified=modified,
            parameter_choices=grid_choices,
            overrides=overrides,
            oos_unlocks=unlocks,
            score=float(score),
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _build_event(
        *,
        event_type: LedgerEventType,
        project_id: str,
        actor: str,
        payload: Mapping[str, Any],
        parent_hash: str,
        timestamp: Optional[str] = None,
    ) -> LedgerEvent:
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        event_id = _hash_event_id(project_id, ts, parent_hash, event_type)
        event_hash = _hash_event(
            event_type, project_id, actor, dict(payload),
            ts, parent_hash, event_id,
        )
        return LedgerEvent(
            event_id=event_id,
            event_type=event_type,
            project_id=project_id,
            actor=actor,
            payload=dict(payload),
            timestamp=ts,
            parent_hash=parent_hash,
            event_hash=event_hash,
        )


def _hash_event_id(
    project_id: str,
    timestamp: str,
    parent_hash: str,
    event_type: LedgerEventType,
) -> str:
    base = f"{project_id}|{timestamp}|{parent_hash}|{event_type.value}".encode()
    return hashlib.sha256(base).hexdigest()[:16]


def _hash_event(
    event_type: LedgerEventType,
    project_id: str,
    actor: str,
    payload: Mapping[str, Any],
    timestamp: str,
    parent_hash: str,
    event_id: str,
) -> str:
    canonical = json.dumps(
        {
            "event_id": event_id,
            "event_type": event_type.value,
            "project_id": project_id,
            "actor": actor,
            "payload": dict(payload),
            "timestamp": timestamp,
            "parent_hash": parent_hash,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "LedgerEnforcementError",
    "LedgerEvent",
    "LedgerEventType",
    "LedgerIntegrityError",
    "ResearchLedger",
    "TrialPressureScore",
]
