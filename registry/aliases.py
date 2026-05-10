"""R182 - Strategy / model / feature registry aliases.

Adds a small alias layer on top of :mod:`aurora.registry.versioning` so
operators can ask "which exact version is `live`?" without re-deriving
the answer from individual records. Aliases are mutable but their
movement is audited so an auditor can reconstruct who pointed `live` at
which version and when.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


class AliasName(str, Enum):
    LATEST = "latest"
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    PAPER = "paper"
    CANARY = "canary"
    LIVE = "live"
    RETIRED = "retired"


@dataclass(frozen=True)
class AliasMove:
    """Audit record for an alias pointer change."""

    alias: AliasName
    artefact_kind: str  # "strategy", "model", "feature_set", "data_contract"
    from_version: Optional[str]
    to_version: str
    actor: str
    reason: str
    moved_at: str
    evidence_pack_id: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["alias"] = self.alias.value
        return d


@dataclass(frozen=True)
class AliasState:
    """The current alias -> version map for one artefact kind."""

    artefact_kind: str
    pointers: Dict[AliasName, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "artefact_kind": self.artefact_kind,
            "pointers": {k.value: v for k, v in self.pointers.items()},
        }


class AliasMoveBlocked(RuntimeError):
    """Raised when an alias move violates the registry's invariants."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class AliasRegistry:
    """JSONL-backed alias map with audit trail.

    The latest entry per (artefact_kind, alias) wins. The file is
    append-only so the operator (or auditor) can reconstruct history.
    """

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    # -- mutation ---------------------------------------------------------

    def move(
        self,
        *,
        alias: AliasName,
        artefact_kind: str,
        to_version: str,
        actor: str,
        reason: str,
        evidence_pack_id: str = "",
    ) -> AliasMove:
        """Move ``alias`` to ``to_version`` and audit the change.

        ``LIVE``/``CANARY`` moves require ``evidence_pack_id`` so the
        promotion cannot happen without a reproducible artefact bundle.
        """
        if not to_version:
            raise AliasMoveBlocked("to_version must be non-empty")
        if alias in (AliasName.LIVE, AliasName.CANARY) and not evidence_pack_id:
            raise AliasMoveBlocked(
                f"{alias.value} promotion requires an evidence_pack_id"
            )
        with self._lock:
            current = self._latest_state(artefact_kind)
            from_version = current.pointers.get(alias)
            if from_version == to_version:
                raise AliasMoveBlocked(
                    f"{alias.value} already points to {to_version}"
                )
            move = AliasMove(
                alias=alias,
                artefact_kind=artefact_kind,
                from_version=from_version,
                to_version=to_version,
                actor=actor,
                reason=reason,
                moved_at=datetime.now(timezone.utc).isoformat(),
                evidence_pack_id=evidence_pack_id,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(move.to_dict(), sort_keys=True) + "\n")
            return move

    def retire(
        self,
        *,
        artefact_kind: str,
        version: str,
        actor: str,
        reason: str,
    ) -> AliasMove:
        return self.move(
            alias=AliasName.RETIRED,
            artefact_kind=artefact_kind,
            to_version=version,
            actor=actor,
            reason=reason,
        )

    # -- read --------------------------------------------------------------

    def history(
        self, *, artefact_kind: Optional[str] = None,
    ) -> List[AliasMove]:
        if not self.path.exists():
            return []
        out: List[AliasMove] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                payload["alias"] = AliasName(payload["alias"])
                out.append(AliasMove(**payload))
        if artefact_kind is not None:
            out = [m for m in out if m.artefact_kind == artefact_kind]
        return out

    def state(self, artefact_kind: str) -> AliasState:
        return self._latest_state(artefact_kind)

    def resolve(
        self, *, artefact_kind: str, alias: AliasName,
    ) -> Optional[str]:
        return self._latest_state(artefact_kind).pointers.get(alias)

    def all_artefact_kinds(self) -> List[str]:
        kinds = {m.artefact_kind for m in self.history()}
        return sorted(kinds)

    # -- helpers -----------------------------------------------------------

    def _latest_state(self, artefact_kind: str) -> AliasState:
        pointers: Dict[AliasName, str] = {}
        for move in self.history(artefact_kind=artefact_kind):
            pointers[move.alias] = move.to_version
        return AliasState(artefact_kind=artefact_kind, pointers=pointers)


__all__ = [
    "AliasMove",
    "AliasMoveBlocked",
    "AliasName",
    "AliasRegistry",
    "AliasState",
]
