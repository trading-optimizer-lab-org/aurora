"""SOC 2 append-only audit trail with tamper-evident hash chain.

Each event is appended with a SHA-256 chain link that includes the prior
event hash, so any retroactive edit invalidates the chain from the edit
point forward. This satisfies SOC 2 CC7.2 logging integrity criteria.

The store is a plain JSONL file by default. Verification re-walks the
chain and reports the index of the first broken link, if any.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


GENESIS_HASH: str = "0" * 64


@dataclass
class SOC2Config:
    """Static config for the SOC2 audit trail.

    Attributes:
        log_path: path to the append-only JSONL file.
        actor_default: default actor when not provided per event.
        clock_drift_tolerance_s: max allowed reverse-time gap before warning.
    """
    log_path: str = field(
        default_factory=lambda: str(
            __import__(
                "aurora.core.runtime_paths", fromlist=["audit_log_path"]
            ).audit_log_path()
        )
    )
    actor_default: str = "system"
    clock_drift_tolerance_s: float = 5.0
    extra_metadata: tuple[str, ...] = field(default_factory=tuple)


class SOC2AuditTrail:
    """Append-only audit log with SHA-256 hash chain."""

    def __init__(self, config: Optional[SOC2Config] = None) -> None:
        self.config = config or SOC2Config()
        self._path = Path(self.config.log_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def append(
        self,
        event_type: str,
        payload: Optional[dict] = None,
        actor: Optional[str] = None,
    ) -> dict:
        """Append a new event and return the stored record."""
        prior_hash = self._tip_hash()
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor or self.config.actor_default,
            "event_type": event_type,
            "payload": payload or {},
            "prior_hash": prior_hash,
        }
        record["this_hash"] = self._hash_record(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def verify(self) -> dict:
        """Re-walk the chain and return integrity report.

        Returns a dict with keys: ok (bool), n_events (int), broken_index
        (Optional[int]). If broken_index is not None, that 0-based index is
        the first event whose stored hash does not match the recomputed hash
        or whose prior_hash does not match the previous event's this_hash.
        """
        if not self._path.exists():
            return {"ok": True, "n_events": 0, "broken_index": None}
        prev = GENESIS_HASH
        idx = 0
        broken: Optional[int] = None
        with self._path.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    broken = idx
                    break
                if rec.get("prior_hash") != prev:
                    broken = idx
                    break
                stored = rec.get("this_hash")
                expected = self._hash_record(
                    {k: rec[k] for k in rec if k != "this_hash"}
                )
                if stored != expected:
                    broken = idx
                    break
                prev = stored
        return {
            "ok": broken is None,
            "n_events": idx + 1 if self._path.stat().st_size > 0 else 0,
            "broken_index": broken,
        }

    def tip(self) -> Optional[dict]:
        """Return the most recent event record, or None if log is empty."""
        if not self._path.exists() or self._path.stat().st_size == 0:
            return None
        last_line = ""
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last_line = line.strip()
        if not last_line:
            return None
        return json.loads(last_line)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _tip_hash(self) -> str:
        last = self.tip()
        if last is None:
            return GENESIS_HASH
        return last.get("this_hash", GENESIS_HASH)

    @staticmethod
    def _hash_record(record: dict) -> str:
        blob = json.dumps(
            {k: v for k, v in record.items() if k != "this_hash"},
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
