"""Append-only hash-chained audit log for the AgentGateway.

Each entry stores both ``prev_hash`` (chain back-reference) and
``this_hash`` (entry digest). ``verify_chain`` re-walks the JSONL file
and detects any entry whose recomputed digest does not match the stored
``this_hash`` or whose ``prev_hash`` does not match the previous entry's
``this_hash``.

When ``mirror_soc2`` is enabled, every append also writes to the
existing :class:`aurora.compliance.soc2_audit.SOC2AuditTrail` so the
canonical SOC 2 log holds the same record. Mirror failures are
swallowed (best-effort) so a SOC2 outage cannot wedge gateway
operations.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


GENESIS_HASH = "0" * 64


@dataclass
class AgentAuditConfig:
    """Static config for the agent gateway audit trail.

    Attributes:
        log_path: append-only JSONL path. Created on first write.
        mirror_soc2: when True, mirror entries to ``SOC2AuditTrail`` on
            best-effort basis.
    """

    log_path: str
    mirror_soc2: bool = True
    extra_metadata: tuple = field(default_factory=tuple)


class AgentAudit:
    """Append-only hash-chained JSONL audit log."""

    _write_lock: threading.Lock = threading.Lock()

    def __init__(self, config: AgentAuditConfig) -> None:
        self.config = config
        self._path = Path(config.log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = self._compute_initial_seq()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def append(
        self,
        *,
        actor: str,
        token_id: str,
        action: str,
        scope: str,
        request_hash: str,
        outcome: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Append a new entry. Returns the stored record."""
        with AgentAudit._write_lock:
            prev = self._tip_hash()
            seq = self._seq
            entry: Dict[str, Any] = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "seq": int(seq),
                "actor": str(actor),
                "token_id": str(token_id),
                "action": str(action),
                "scope": str(scope),
                "request_hash": str(request_hash),
                "outcome": str(outcome),
                "details": dict(details or {}),
                "prev_hash": prev,
            }
            entry["this_hash"] = self._hash_entry(entry)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
            self._seq = seq + 1
        if self.config.mirror_soc2:
            self._mirror_soc2(entry)
        return entry

    def verify_chain(self) -> Dict[str, Any]:
        """Walk the chain and return integrity report.

        Result keys:
          ``ok`` -- bool, True iff every entry's stored hash matches the
              recomputed hash AND every ``prev_hash`` matches the prior
              entry's ``this_hash``.
          ``n_entries`` -- total entries inspected.
          ``broken_index`` -- 0-based seq of the first broken entry, or
              ``None`` when ``ok`` is True.
        """
        if not self._path.exists():
            return {"ok": True, "n_entries": 0, "broken_index": None}
        prev = GENESIS_HASH
        idx = -1
        broken: Optional[int] = None
        with self._path.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    broken = idx
                    break
                if entry.get("prev_hash") != prev:
                    broken = idx
                    break
                stored = entry.get("this_hash")
                expected = self._hash_entry(
                    {k: entry[k] for k in entry if k != "this_hash"}
                )
                if stored != expected:
                    broken = idx
                    break
                prev = stored
        return {
            "ok": broken is None,
            "n_entries": idx + 1 if idx >= 0 else 0,
            "broken_index": broken,
        }

    def entries(self) -> List[Dict[str, Any]]:
        """Return all entries as a list (for inspection / tests)."""
        if not self._path.exists():
            return []
        out: List[Dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break
        return out

    def find(self, *, token_id: Optional[str] = None,
             actor: Optional[str] = None,
             outcome: Optional[str] = None) -> List[Dict[str, Any]]:
        """Filtered iteration helper used by daily-cap aggregation."""
        out: List[Dict[str, Any]] = []
        for entry in self.entries():
            if token_id is not None and entry.get("token_id") != token_id:
                continue
            if actor is not None and entry.get("actor") != actor:
                continue
            if outcome is not None and entry.get("outcome") != outcome:
                continue
            out.append(entry)
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _compute_initial_seq(self) -> int:
        """Resume sequence numbering from the existing JSONL file."""
        if not self._path.exists() or self._path.stat().st_size == 0:
            return 0
        last_seq = -1
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    break
                last_seq = int(entry.get("seq", last_seq))
        return last_seq + 1

    def _tip_hash(self) -> str:
        if not self._path.exists() or self._path.stat().st_size == 0:
            return GENESIS_HASH
        last_line = ""
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last_line = line.strip()
        if not last_line:
            return GENESIS_HASH
        try:
            return json.loads(last_line).get("this_hash", GENESIS_HASH)
        except json.JSONDecodeError:
            return GENESIS_HASH

    @staticmethod
    def _hash_entry(entry: Dict[str, Any]) -> str:
        blob = json.dumps(
            {k: v for k, v in entry.items() if k != "this_hash"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _mirror_soc2(self, entry: Dict[str, Any]) -> None:
        """Best-effort mirror of the entry to SOC2AuditTrail. Never raises."""
        try:
            from aurora.compliance.soc2_audit import (
                SOC2AuditTrail, SOC2Config,
            )
            log_path = str(Path(self._path).parent / "soc2_mirror.jsonl")
            cfg = SOC2Config(log_path=log_path,
                             actor_default=entry.get("actor", "agent"))
            SOC2AuditTrail(cfg).append(
                event_type=f"agent_gateway.{entry['action']}",
                payload={
                    "token_id": entry["token_id"],
                    "scope": entry["scope"],
                    "outcome": entry["outcome"],
                    "request_hash": entry["request_hash"],
                    "details": entry.get("details", {}),
                },
                actor=entry.get("actor"),
            )
        except Exception:
            # Never let SOC2 mirror failures wedge the primary gateway log.
            return None


def request_hash(payload: Dict[str, Any]) -> str:
    """Deterministic sha256 of a request payload (used by audit + idempotency)."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


__all__ = [
    "AgentAudit",
    "AgentAuditConfig",
    "GENESIS_HASH",
    "request_hash",
]
