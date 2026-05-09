"""Strategy risk register.

A :class:`StrategyRiskRecord` answers the model-risk question for any
strategy that may be promoted toward paper or live capital:

* What is this strategy *for*? (intended use)
* When should it *not* be used? (limitations + assumptions)
* Who owns it, who reviewed it, who approved limits, who approves
  deployment?
* Which validation evidence and data contract did it ride in on?
* Which protocol policy / snapshot / strategy hash is it bound to?
* What are the live risk limits, when does it expire, and when must it
  be revalidated?

Records are immutable (frozen dataclass). Updates produce a *new*
record; persistence appends to a JSONL log under
``runtime_paths.base_data_dir() / "risk_register.jsonl"`` (override via
``$QF_RISK_REGISTER``). The *latest* record for a given strategy + version
is the one with the highest ``last_updated_iso``.

Hash provenance:
    A record carries the fingerprints required by the v4.0 protocol
    spine: ``policy_hash``, ``snapshot_hash``, ``strategy_hash``,
    ``validation_evidence_hash`` and ``data_contract_hash``. The
    promotion gate refuses promotion when any supplied current hash
    fails to match the value pinned at approval time.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from quantforge.core import runtime_paths


class ApprovalStatus(str, Enum):
    """Maker-checker workflow status of a risk record.

    The string values are stable on-disk so JSONL records remain
    portable across versions.
    """

    DRAFT = "draft"
    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    RISK_APPROVED = "risk_approved"
    OPERATOR_APPROVED = "operator_approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


def risk_register_path() -> Path:
    """Return the JSONL path for the risk register.

    Override with ``$QF_RISK_REGISTER``. Defaults to
    ``runtime_paths.base_data_dir() / 'risk_register.jsonl'`` so it
    obeys the project's runtime-paths discipline.
    """
    raw = os.environ.get("QF_RISK_REGISTER")
    return Path(raw) if raw else runtime_paths.base_data_dir() / "risk_register.jsonl"


@dataclass(frozen=True)
class StrategyRiskRecord:
    """Immutable model-risk record for one ``(strategy_id, version)``.

    All fields are required so that downstream gates can compare hashes
    without optional-handling. Use sentinel strings (e.g. ``"UNKNOWN"``)
    rather than ``None`` for missing-but-required values, except for the
    explicitly-optional reviewer / risk_owner / operator slots that the
    maker-checker flow fills in over time.
    """

    strategy_id: str
    version: str
    intended_use: str
    limitations: Tuple[str, ...]
    assumptions: Tuple[str, ...]
    owner: str
    reviewer: Optional[str]
    risk_owner: Optional[str]
    operator: Optional[str]
    approval_status: ApprovalStatus
    policy_hash: str
    snapshot_hash: str
    strategy_hash: str
    validation_evidence_hash: str
    data_contract_hash: str
    risk_limits: Dict[str, float] = field(default_factory=dict)
    expiry_iso: str = ""
    revalidation_iso: str = ""
    created_at_iso: str = ""
    last_updated_iso: str = ""

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, object]:
        """Return a JSON-serializable dict.

        Tuples become lists; the enum becomes its string value.
        """
        d = asdict(self)
        d["limitations"] = list(self.limitations)
        d["assumptions"] = list(self.assumptions)
        d["risk_limits"] = dict(self.risk_limits)
        d["approval_status"] = self.approval_status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "StrategyRiskRecord":
        """Inverse of :meth:`to_dict`. Tolerates raw enum-string values."""
        status_raw = data.get("approval_status", ApprovalStatus.DRAFT.value)
        if isinstance(status_raw, ApprovalStatus):
            status = status_raw
        else:
            status = ApprovalStatus(str(status_raw))
        limits_raw = data.get("risk_limits", {}) or {}
        if not isinstance(limits_raw, dict):
            limits_raw = {}
        return cls(
            strategy_id=str(data["strategy_id"]),
            version=str(data["version"]),
            intended_use=str(data.get("intended_use", "")),
            limitations=tuple(data.get("limitations", []) or []),  # type: ignore[arg-type]
            assumptions=tuple(data.get("assumptions", []) or []),  # type: ignore[arg-type]
            owner=str(data.get("owner", "")),
            reviewer=_opt_str(data.get("reviewer")),
            risk_owner=_opt_str(data.get("risk_owner")),
            operator=_opt_str(data.get("operator")),
            approval_status=status,
            policy_hash=str(data.get("policy_hash", "")),
            snapshot_hash=str(data.get("snapshot_hash", "")),
            strategy_hash=str(data.get("strategy_hash", "")),
            validation_evidence_hash=str(data.get("validation_evidence_hash", "")),
            data_contract_hash=str(data.get("data_contract_hash", "")),
            risk_limits={str(k): float(v) for k, v in limits_raw.items()},
            expiry_iso=str(data.get("expiry_iso", "")),
            revalidation_iso=str(data.get("revalidation_iso", "")),
            created_at_iso=str(data.get("created_at_iso", "")),
            last_updated_iso=str(data.get("last_updated_iso", "")),
        )


def _opt_str(value: object) -> Optional[str]:
    """Coerce an incoming JSON value into ``Optional[str]``."""
    if value is None:
        return None
    s = str(value)
    return s if s else None


class RiskRegister:
    """JSONL-backed strategy risk register.

    Append-only log. The "current" record for any
    ``(strategy_id, version)`` pair is the *last* one written, which is
    also the one with the highest ``last_updated_iso`` produced by the
    maker-checker flow.

    Design rationale: the audit chain in
    :mod:`quantforge.agent_gateway.audit` already covers tamper-evident
    logging; this register only needs durable append-only persistence.
    Reads scan the file end-to-start so latest-wins lookup is O(N) but
    cheap in practice (one record per strategy lifecycle event).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else risk_register_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def register(self, record: StrategyRiskRecord) -> StrategyRiskRecord:
        """Append a new record. Returns the record (echo for chaining)."""
        line = json.dumps(record.to_dict(), sort_keys=True, default=str)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def all_records(self) -> List[StrategyRiskRecord]:
        """Return every record in append order. Skips malformed lines."""
        if not self._path.exists():
            return []
        out: List[StrategyRiskRecord] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    out.append(StrategyRiskRecord.from_dict(payload))
                except (KeyError, ValueError):
                    continue
        return out

    def get(self, strategy_id: str, version: str) -> Optional[StrategyRiskRecord]:
        """Return the latest record for a given (strategy_id, version)."""
        match: Optional[StrategyRiskRecord] = None
        for rec in self.all_records():
            if rec.strategy_id == strategy_id and rec.version == version:
                match = rec
        return match

    def latest(self, strategy_id: str) -> Optional[StrategyRiskRecord]:
        """Return the most recent record for a strategy across all versions."""
        match: Optional[StrategyRiskRecord] = None
        for rec in self.all_records():
            if rec.strategy_id != strategy_id:
                continue
            if match is None or rec.last_updated_iso >= match.last_updated_iso:
                match = rec
        return match

    def is_approved(self, strategy_id: str, version: str) -> bool:
        """True iff the record exists and is OPERATOR_APPROVED."""
        rec = self.get(strategy_id, version)
        return rec is not None and rec.approval_status == ApprovalStatus.OPERATOR_APPROVED

    def is_expired(self, strategy_id: str, version: str, today: str) -> bool:
        """True iff a record exists and ``today`` is past ``expiry_iso``.

        ``today`` is compared as ISO date strings (lexicographic order
        matches chronological order for ``YYYY-MM-DD`` form).
        """
        rec = self.get(strategy_id, version)
        if rec is None:
            return False
        if not rec.expiry_iso:
            return False
        return today > rec.expiry_iso


__all__ = [
    "ApprovalStatus",
    "RiskRegister",
    "StrategyRiskRecord",
    "risk_register_path",
]
