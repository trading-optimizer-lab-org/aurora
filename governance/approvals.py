"""Maker-checker approval flow + promotion gate.

The flow enforces this order, one role per call:

    1. ``researcher`` proposes.
    2. ``reviewer`` validates evidence.
    3. ``risk_owner`` approves limits.
    4. ``operator`` approves deployment.

Each step appends an :class:`ApprovalEvent` to the audit chain
(``agent_gateway.audit.AgentAudit`` when available; best-effort JSONL
otherwise) and produces an updated :class:`StrategyRiskRecord` whose
``approval_status`` advances along the maker-checker scale.

Hash provenance:
    The promotion gate refuses promotion when the supplied current
    hashes (``policy_hash``, ``snapshot_hash``, ``strategy_hash``,
    ``validation_evidence_hash``, ``data_contract_hash``) disagree with
    the values pinned at approval time. This is the v4.0 protocol-spine
    contract: nothing live without matching hashes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from quantforge.governance.lifecycle import LifecycleState
from quantforge.governance.risk_register import (
    ApprovalStatus,
    RiskRegister,
    StrategyRiskRecord,
)


# Lifecycle states that count as "live" for gating purposes.
_LIVE_STATES = frozenset(
    {LifecycleState.CANARY, LifecycleState.LIVE, LifecycleState.PAPER}
)


class ApprovalError(ValueError):
    """Raised when the maker-checker order is violated."""


@dataclass(frozen=True)
class ApprovalEvent:
    """One step in the maker-checker workflow.

    ``audit_hash`` is sha256 over the canonical JSON of all other
    fields. It chains to whatever audit log the caller writes the event
    into.
    """

    strategy_id: str
    version: str
    role: str
    actor: str
    timestamp_iso: str
    action: str
    audit_hash: str = ""

    def with_hash(self) -> "ApprovalEvent":
        """Return a copy whose ``audit_hash`` is the canonical sha256."""
        payload = {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "role": self.role,
            "actor": self.actor,
            "timestamp_iso": self.timestamp_iso,
            "action": self.action,
        }
        blob = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()
        return ApprovalEvent(**{**asdict(self), "audit_hash": digest})


# Maker-checker order. Each role advances ``approval_status`` to the
# matching value if and only if the *previous* role has signed off.
_ROLE_ORDER = ("researcher", "reviewer", "risk_owner", "operator")
_ROLE_TARGET_STATUS = {
    "researcher": ApprovalStatus.PROPOSED,
    "reviewer": ApprovalStatus.REVIEWED,
    "risk_owner": ApprovalStatus.RISK_APPROVED,
    "operator": ApprovalStatus.OPERATOR_APPROVED,
}
_ROLE_PRECONDITION = {
    "researcher": (ApprovalStatus.DRAFT,),
    "reviewer": (ApprovalStatus.PROPOSED,),
    "risk_owner": (ApprovalStatus.REVIEWED,),
    "operator": (ApprovalStatus.RISK_APPROVED,),
}


@dataclass
class MakerCheckerFlow:
    """Drives the maker-checker workflow for one risk register.

    The flow is stateless beyond its bound :class:`RiskRegister` and
    audit log; all state lives on the records themselves.

    Attributes:
        register: the JSONL-backed register that holds risk records.
        audit_log_path: optional fallback JSONL path for approval events
            when :class:`agent_gateway.audit.AgentAudit` is unavailable.
            Defaults to ``register.path.parent / 'governance_audit.jsonl'``.
    """

    register: RiskRegister
    audit_log_path: Optional[Path] = None
    events: List[ApprovalEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.audit_log_path is None:
            self.audit_log_path = self.register.path.parent / "governance_audit.jsonl"

    # ------------------------------------------------------------------
    # Public step API
    # ------------------------------------------------------------------
    def propose(self, record: StrategyRiskRecord, actor: str) -> StrategyRiskRecord:
        """Researcher proposes a fresh record (DRAFT -> PROPOSED)."""
        return self._advance(record, role="researcher", actor=actor, action="propose")

    def review(self, record: StrategyRiskRecord, actor: str) -> StrategyRiskRecord:
        """Independent reviewer signs off (PROPOSED -> REVIEWED)."""
        return self._advance(record, role="reviewer", actor=actor, action="review")

    def approve_risk(self, record: StrategyRiskRecord, actor: str) -> StrategyRiskRecord:
        """Risk owner approves limits (REVIEWED -> RISK_APPROVED)."""
        return self._advance(record, role="risk_owner", actor=actor, action="approve_risk")

    def approve_operator(
        self, record: StrategyRiskRecord, actor: str,
    ) -> StrategyRiskRecord:
        """Operator approves deployment (RISK_APPROVED -> OPERATOR_APPROVED)."""
        return self._advance(record, role="operator", actor=actor, action="approve_operator")

    # ------------------------------------------------------------------
    # Override (reject + reason)
    # ------------------------------------------------------------------
    def override(
        self, record: StrategyRiskRecord, actor: str, reason: str,
    ) -> StrategyRiskRecord:
        """Reject the record. Requires a non-empty reason; emits an event.

        Used by the operator to refuse a strategy mid-flow. Persists a
        new ``REJECTED`` record so the register's tail reflects the
        decision.
        """
        if not actor:
            raise ApprovalError("override requires a non-empty actor")
        if not reason or not reason.strip():
            raise ApprovalError("override requires a non-empty reason")
        now = _now_iso()
        new_record = StrategyRiskRecord(
            **{
                **asdict(record),
                "approval_status": ApprovalStatus.REJECTED,
                "limitations": tuple(record.limitations) + (f"override: {reason}",),
                "last_updated_iso": now,
            }
        )
        self.register.register(new_record)
        event = ApprovalEvent(
            strategy_id=record.strategy_id,
            version=record.version,
            role="operator",
            actor=actor,
            timestamp_iso=now,
            action=f"override: {reason}",
        ).with_hash()
        self.events.append(event)
        self._emit_audit(event)
        return new_record

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _advance(
        self,
        record: StrategyRiskRecord,
        *,
        role: str,
        actor: str,
        action: str,
    ) -> StrategyRiskRecord:
        if role not in _ROLE_ORDER:
            raise ApprovalError(f"unknown role: {role}")
        if not actor:
            raise ApprovalError(f"role={role} requires a non-empty actor")
        allowed = _ROLE_PRECONDITION[role]
        if record.approval_status not in allowed:
            raise ApprovalError(
                f"role={role} cannot act on a record in status "
                f"{record.approval_status.value}; expected one of "
                f"{[s.value for s in allowed]}"
            )
        target_status = _ROLE_TARGET_STATUS[role]
        now = _now_iso()
        updated = StrategyRiskRecord(
            **{
                **asdict(record),
                "approval_status": target_status,
                "reviewer": actor if role == "reviewer" else record.reviewer,
                "risk_owner": actor if role == "risk_owner" else record.risk_owner,
                "operator": actor if role == "operator" else record.operator,
                "last_updated_iso": now,
            }
        )
        self.register.register(updated)
        event = ApprovalEvent(
            strategy_id=record.strategy_id,
            version=record.version,
            role=role,
            actor=actor,
            timestamp_iso=now,
            action=action,
        ).with_hash()
        self.events.append(event)
        self._emit_audit(event)
        return updated

    def _emit_audit(self, event: ApprovalEvent) -> None:
        """Write the event to the agent gateway audit chain when available."""
        try:
            from quantforge.agent_gateway.audit import AgentAudit, AgentAuditConfig
            cfg = AgentAuditConfig(log_path=str(self.audit_log_path), mirror_soc2=False)
            AgentAudit(cfg).append(
                actor=event.actor,
                token_id=f"governance:{event.role}",
                action=f"governance.{event.action}",
                scope=event.role,
                request_hash=event.audit_hash,
                outcome="ok",
                details={
                    "strategy_id": event.strategy_id,
                    "version": event.version,
                    "timestamp_iso": event.timestamp_iso,
                },
            )
        except Exception:
            self._fallback_audit(event)

    def _fallback_audit(self, event: ApprovalEvent) -> None:
        """Append a JSONL line if the gateway audit chain is unavailable."""
        if self.audit_log_path is None:
            return
        path = Path(self.audit_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(event), sort_keys=True, default=str) + "\n")


def _now_iso() -> str:
    """Tz-aware UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Promotion gate
# ---------------------------------------------------------------------------
def gate_promotion(
    strategy_id: str,
    version: str,
    target_state: LifecycleState,
    register: RiskRegister,
    today: str,
    *,
    current_policy_hash: Optional[str] = None,
    current_snapshot_hash: Optional[str] = None,
    current_strategy_hash: Optional[str] = None,
    current_validation_evidence_hash: Optional[str] = None,
    current_data_contract_hash: Optional[str] = None,
    open_warnings: int = 0,
    warning_threshold: int = 0,
) -> List[str]:
    """Return refusal reasons. Empty list = OK to promote.

    Refuses when:

    * No risk record exists for ``(strategy_id, version)``.
    * The record is past its expiry (``today`` lexicographically greater
      than ``expiry_iso``).
    * The target state is a "live" state (``PAPER``, ``CANARY``,
      ``LIVE``) but the record is not ``OPERATOR_APPROVED``.
    * Any supplied current hash disagrees with the record's pinned
      hash. Hashes that are not supplied (``None``) are not checked.
    * The number of open warnings exceeds ``warning_threshold``.
    """
    reasons: List[str] = []
    record = register.get(strategy_id, version)
    if record is None:
        reasons.append("missing risk record")
        return reasons
    if record.expiry_iso and today > record.expiry_iso:
        reasons.append("risk record expired")
    if target_state in _LIVE_STATES:
        if record.approval_status != ApprovalStatus.OPERATOR_APPROVED:
            reasons.append(
                f"approval_status={record.approval_status.value}, "
                f"requires operator_approved for live targets"
            )
    reasons.extend(_hash_mismatches(
        record,
        current_policy_hash=current_policy_hash,
        current_snapshot_hash=current_snapshot_hash,
        current_strategy_hash=current_strategy_hash,
        current_validation_evidence_hash=current_validation_evidence_hash,
        current_data_contract_hash=current_data_contract_hash,
    ))
    if open_warnings > warning_threshold:
        reasons.append(
            f"open_warnings={open_warnings} exceeds threshold {warning_threshold}"
        )
    return reasons


def _hash_mismatches(
    record: StrategyRiskRecord,
    *,
    current_policy_hash: Optional[str],
    current_snapshot_hash: Optional[str],
    current_strategy_hash: Optional[str],
    current_validation_evidence_hash: Optional[str],
    current_data_contract_hash: Optional[str],
) -> List[str]:
    """Return one reason per mismatched hash."""
    out: List[str] = []
    pairs: Dict[str, Any] = {
        "policy_hash": (current_policy_hash, record.policy_hash),
        "snapshot_hash": (current_snapshot_hash, record.snapshot_hash),
        "strategy_hash": (current_strategy_hash, record.strategy_hash),
        "validation_evidence_hash": (
            current_validation_evidence_hash, record.validation_evidence_hash,
        ),
        "data_contract_hash": (current_data_contract_hash, record.data_contract_hash),
    }
    for label, (current, pinned) in pairs.items():
        if current is None:
            continue
        if current != pinned:
            out.append(f"{label} mismatch: current={current!r} pinned={pinned!r}")
    return out


__all__ = [
    "ApprovalError",
    "ApprovalEvent",
    "MakerCheckerFlow",
    "gate_promotion",
]
