"""R175 - Solo-operator risk record + approval gates.

A strategy cannot be promoted toward shadow / paper / canary / live
without a current :class:`StrategyRiskRecord` whose hashes match the
underlying validation evidence. Overrides are explicit and audited.

The state machine is:

    drafted -> reviewed_by_operator -> approved_for_shadow ->
    approved_for_paper -> approved_for_canary -> approved_for_live ->
    retired

Backward jumps (paper -> shadow) are allowed for de-escalation. Forward
jumps must be one stage at a time. Expired records cannot promote.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import date as _date_type, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class LifecycleStage(str, Enum):
    """Where the strategy lives in the promotion pipeline."""

    DRAFTED = "drafted"
    REVIEWED = "reviewed_by_operator"
    SHADOW = "approved_for_shadow"
    PAPER = "approved_for_paper"
    CANARY = "approved_for_canary"
    LIVE = "approved_for_live"
    RETIRED = "retired"


_FORWARD_ORDER: Tuple[LifecycleStage, ...] = (
    LifecycleStage.DRAFTED,
    LifecycleStage.REVIEWED,
    LifecycleStage.SHADOW,
    LifecycleStage.PAPER,
    LifecycleStage.CANARY,
    LifecycleStage.LIVE,
)


class PromotionBlocked(RuntimeError):
    """Raised when a promotion attempt fails a governance gate."""


@dataclass(frozen=True)
class StrategyOverride:
    """Audit-grade record of a manual override."""

    strategy_id: str
    actor: str
    reason: str
    affected_field: str
    previous_value: Any
    new_value: Any
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StrategyRiskRecord:
    """Per-strategy risk record bound to validation evidence by hash."""

    strategy_id: str
    intended_use: str
    limitations: str
    assumptions: str
    operator: str
    risk_limits: Dict[str, float]
    validation_id: str
    policy_hash: str
    snapshot_hash: str
    strategy_hash: str
    benchmark_pack_hash: str = ""
    evidence_pack_id: str = ""
    expires_at: Optional[_date_type] = None
    revalidate_at: Optional[_date_type] = None
    stage: LifecycleStage = LifecycleStage.DRAFTED
    overrides: Tuple[StrategyOverride, ...] = field(default_factory=tuple)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")
        if not self.operator:
            raise ValueError("operator must be non-empty")
        if not isinstance(self.stage, LifecycleStage):
            object.__setattr__(self, "stage", LifecycleStage(self.stage))
        if self.expires_at is not None and not isinstance(self.expires_at, _date_type):
            raise TypeError("expires_at must be a date or None")
        if self.revalidate_at is not None and not isinstance(self.revalidate_at, _date_type):
            raise TypeError("revalidate_at must be a date or None")

    def is_expired(self, *, today: Optional[_date_type] = None) -> bool:
        if self.expires_at is None:
            return False
        from datetime import date as _d

        ref = today if today is not None else _d.today()
        return self.expires_at < ref

    def hashes_match(
        self,
        *,
        policy_hash: str,
        snapshot_hash: str,
        strategy_hash: str,
    ) -> bool:
        return (
            self.policy_hash == policy_hash
            and self.snapshot_hash == snapshot_hash
            and self.strategy_hash == strategy_hash
        )

    def content_hash(self) -> str:
        """Stable sha256 over content fields (excludes overrides + timestamps)."""
        payload = {
            "strategy_id": self.strategy_id,
            "intended_use": self.intended_use,
            "limitations": self.limitations,
            "assumptions": self.assumptions,
            "operator": self.operator,
            "risk_limits": self.risk_limits,
            "validation_id": self.validation_id,
            "policy_hash": self.policy_hash,
            "snapshot_hash": self.snapshot_hash,
            "strategy_hash": self.strategy_hash,
            "benchmark_pack_hash": self.benchmark_pack_hash,
            "evidence_pack_id": self.evidence_pack_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revalidate_at": (
                self.revalidate_at.isoformat() if self.revalidate_at else None
            ),
            "stage": self.stage.value,
        }
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def to_dict(self) -> dict:
        d = {
            "strategy_id": self.strategy_id,
            "intended_use": self.intended_use,
            "limitations": self.limitations,
            "assumptions": self.assumptions,
            "operator": self.operator,
            "risk_limits": dict(self.risk_limits),
            "validation_id": self.validation_id,
            "policy_hash": self.policy_hash,
            "snapshot_hash": self.snapshot_hash,
            "strategy_hash": self.strategy_hash,
            "benchmark_pack_hash": self.benchmark_pack_hash,
            "evidence_pack_id": self.evidence_pack_id,
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at else None
            ),
            "revalidate_at": (
                self.revalidate_at.isoformat() if self.revalidate_at else None
            ),
            "stage": self.stage.value,
            "overrides": [o.to_dict() for o in self.overrides],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "content_hash": self.content_hash(),
        }
        return d


# ---------------------------------------------------------------------------
# Promotion logic
# ---------------------------------------------------------------------------


def can_promote(
    record: StrategyRiskRecord,
    target: LifecycleStage,
    *,
    today: Optional[_date_type] = None,
    allow_backwards: bool = True,
) -> Tuple[bool, str]:
    """Return ``(allowed, reason)`` for advancing ``record`` to ``target``."""
    if target is LifecycleStage.RETIRED:
        return True, "retire is always allowed"
    if record.stage is LifecycleStage.RETIRED:
        return False, "retired strategy cannot be promoted; create a new record"
    if record.is_expired(today=today):
        return False, f"record expired on {record.expires_at!s}"
    try:
        cur_idx = _FORWARD_ORDER.index(record.stage)
        tgt_idx = _FORWARD_ORDER.index(target)
    except ValueError:
        return False, f"unknown stage {record.stage!r} or {target!r}"
    if tgt_idx == cur_idx:
        return False, "already at requested stage"
    if tgt_idx < cur_idx:
        if allow_backwards:
            return True, "de-escalation allowed"
        return False, "backward promotion not allowed"
    if tgt_idx - cur_idx > 1:
        return False, (
            f"cannot skip stages: {record.stage.value} -> {target.value}"
        )
    return True, "ok"


def promote(
    record: StrategyRiskRecord,
    target: LifecycleStage,
    *,
    today: Optional[_date_type] = None,
    allow_backwards: bool = True,
) -> StrategyRiskRecord:
    """Return a new record at ``target`` if the promotion is allowed."""
    allowed, reason = can_promote(
        record, target, today=today, allow_backwards=allow_backwards,
    )
    if not allowed:
        raise PromotionBlocked(reason)
    now = datetime.now(timezone.utc).isoformat()
    return _replace_record(record, stage=target, updated_at=now)


def assert_can_run(
    record: StrategyRiskRecord,
    *,
    expected_policy_hash: str,
    expected_snapshot_hash: str,
    expected_strategy_hash: str,
    minimum_stage: LifecycleStage,
    today: Optional[_date_type] = None,
) -> None:
    """Raise :class:`PromotionBlocked` unless the record permits ``minimum_stage``.

    This is the gate paper / canary / live runners call before submitting
    orders for a strategy.
    """
    if record.is_expired(today=today):
        raise PromotionBlocked(
            f"record expired on {record.expires_at!s}; revalidate first"
        )
    if not record.hashes_match(
        policy_hash=expected_policy_hash,
        snapshot_hash=expected_snapshot_hash,
        strategy_hash=expected_strategy_hash,
    ):
        raise PromotionBlocked(
            "validation evidence hash mismatch; risk record is stale"
        )
    try:
        rec_idx = _FORWARD_ORDER.index(record.stage)
        min_idx = _FORWARD_ORDER.index(minimum_stage)
    except ValueError as exc:
        raise PromotionBlocked(f"unknown stage: {exc}") from exc
    if rec_idx < min_idx:
        raise PromotionBlocked(
            f"current stage {record.stage.value} below required "
            f"{minimum_stage.value}"
        )


def add_override(
    record: StrategyRiskRecord,
    *,
    actor: str,
    reason: str,
    affected_field: str,
    previous_value: Any,
    new_value: Any,
) -> StrategyRiskRecord:
    """Append an audited override to ``record`` and return the new record."""
    if not actor or not reason:
        raise ValueError("override requires actor and reason")
    override = StrategyOverride(
        strategy_id=record.strategy_id,
        actor=actor,
        reason=reason,
        affected_field=affected_field,
        previous_value=previous_value,
        new_value=new_value,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return _replace_record(
        record,
        overrides=record.overrides + (override,),
        updated_at=override.created_at,
    )


def _replace_record(record: StrategyRiskRecord, **overrides) -> StrategyRiskRecord:
    payload = {
        "strategy_id": record.strategy_id,
        "intended_use": record.intended_use,
        "limitations": record.limitations,
        "assumptions": record.assumptions,
        "operator": record.operator,
        "risk_limits": dict(record.risk_limits),
        "validation_id": record.validation_id,
        "policy_hash": record.policy_hash,
        "snapshot_hash": record.snapshot_hash,
        "strategy_hash": record.strategy_hash,
        "benchmark_pack_hash": record.benchmark_pack_hash,
        "evidence_pack_id": record.evidence_pack_id,
        "expires_at": record.expires_at,
        "revalidate_at": record.revalidate_at,
        "stage": record.stage,
        "overrides": record.overrides,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    payload.update(overrides)
    return StrategyRiskRecord(**payload)


# ---------------------------------------------------------------------------
# Persistent registry
# ---------------------------------------------------------------------------


@dataclass
class StrategyRiskRegistry:
    """JSONL-backed registry of :class:`StrategyRiskRecord` objects.

    The latest record per ``strategy_id`` wins; the file is append-only
    so the operator (or auditor) can replay history.
    """

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def append(self, record: StrategyRiskRecord) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def latest(self, strategy_id: str) -> Optional[StrategyRiskRecord]:
        latest: Optional[StrategyRiskRecord] = None
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if payload.get("strategy_id") != strategy_id:
                    continue
                latest = _record_from_payload(payload)
        return latest

    def all_strategies(self) -> List[str]:
        if not self.path.exists():
            return []
        seen: set[str] = set()
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                seen.add(payload["strategy_id"])
        return sorted(seen)


def _record_from_payload(payload: Dict[str, Any]) -> StrategyRiskRecord:
    overrides_raw = payload.get("overrides") or []
    overrides = tuple(
        StrategyOverride(**{k: v for k, v in o.items()})
        for o in overrides_raw
    )
    expires_at = payload.get("expires_at")
    revalidate_at = payload.get("revalidate_at")
    from datetime import date as _d

    return StrategyRiskRecord(
        strategy_id=payload["strategy_id"],
        intended_use=payload["intended_use"],
        limitations=payload["limitations"],
        assumptions=payload["assumptions"],
        operator=payload["operator"],
        risk_limits=dict(payload.get("risk_limits", {})),
        validation_id=payload["validation_id"],
        policy_hash=payload["policy_hash"],
        snapshot_hash=payload["snapshot_hash"],
        strategy_hash=payload["strategy_hash"],
        benchmark_pack_hash=payload.get("benchmark_pack_hash", ""),
        evidence_pack_id=payload.get("evidence_pack_id", ""),
        expires_at=_d.fromisoformat(expires_at) if expires_at else None,
        revalidate_at=_d.fromisoformat(revalidate_at) if revalidate_at else None,
        stage=LifecycleStage(payload.get("stage", LifecycleStage.DRAFTED.value)),
        overrides=overrides,
        created_at=payload.get("created_at", ""),
        updated_at=payload.get("updated_at", ""),
    )


__all__ = [
    "LifecycleStage",
    "PromotionBlocked",
    "StrategyOverride",
    "StrategyRiskRecord",
    "StrategyRiskRegistry",
    "add_override",
    "assert_can_run",
    "can_promote",
    "promote",
]
