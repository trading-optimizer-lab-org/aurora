"""Enforced planning and runtime guardrails for GitHub-only workloads."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    RunSpec,
    Sha256,
    canonical_sha256,
)
from aurora.infra.github_performance.telemetry import ResourceObservation


class SafeStopReason(str, Enum):
    """Operational reasons that may request a durable checkpoint."""

    MISSING_EVIDENCE = "missing_evidence"
    DISK_PRESSURE = "disk_pressure"
    MEMORY_PRESSURE = "memory_pressure"
    DEADLINE_RISK = "deadline_risk"
    BUDGET_RISK = "budget_risk"


class BudgetLedger(FrozenModel):
    """Immutable projection of billable use before another route starts."""

    max_billable_minutes: float = Field(ge=0)
    max_cost: float = Field(ge=0)
    consumed_billable_minutes: float = Field(ge=0)
    committed_billable_minutes: float = Field(ge=0)
    projected_additional_billable_minutes: float = Field(ge=0)
    cost_per_billable_minute: float | None = Field(default=None, ge=0)
    projected_total_billable_minutes: float = Field(ge=0)
    projected_total_cost: float | None = Field(default=None, ge=0)

    @classmethod
    def project(
        cls,
        *,
        max_billable_minutes: float,
        max_cost: float,
        consumed_billable_minutes: float,
        committed_billable_minutes: float,
        projected_additional_billable_minutes: float,
        cost_per_billable_minute: float | None,
    ) -> BudgetLedger:
        total = (
            consumed_billable_minutes
            + committed_billable_minutes
            + projected_additional_billable_minutes
        )
        projected_cost = (
            float(
                Decimal(str(total))
                * Decimal(str(cost_per_billable_minute))
            )
            if cost_per_billable_minute is not None
            else None
        )
        return cls(
            max_billable_minutes=max_billable_minutes,
            max_cost=max_cost,
            consumed_billable_minutes=consumed_billable_minutes,
            committed_billable_minutes=committed_billable_minutes,
            projected_additional_billable_minutes=(
                projected_additional_billable_minutes
            ),
            cost_per_billable_minute=cost_per_billable_minute,
            projected_total_billable_minutes=total,
            projected_total_cost=projected_cost,
        )


class BudgetDecision(FrozenModel):
    route_allowed: bool
    checkpoint_requested: bool
    evidence_complete: bool
    reason_codes: tuple[str, ...]


class ZeroSpendBudgetEvidenceV1(FrozenModel):
    """Exact live proof that Actions cannot spill into paid usage."""

    schema_version: Literal["1"] = "1"
    observed_at: datetime
    actions_budget_verified: bool
    actions_storage_budget_verified: bool
    cache_storage_budget_verified: bool
    prevent_further_usage: bool
    cache_storage_limit_bytes: int = Field(ge=0)
    cache_retention_days: int = Field(ge=1)
    estimated_paid_runner_minutes: int = Field(ge=0)
    estimated_paid_actions_cost: int = Field(ge=0)
    receipt_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_receipt_hash(self) -> "ZeroSpendBudgetEvidenceV1":
        identity = self.model_dump(mode="python", exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256(identity):
            raise ValueError("ZERO_SPEND_BUDGET_RECEIPT_HASH_INVALID")
        return self

    @classmethod
    def create(cls, **values: object) -> "ZeroSpendBudgetEvidenceV1":
        identity = {"schema_version": "1", **values}
        identity.pop("receipt_sha256", None)
        observed_at = identity.get("observed_at")
        if isinstance(observed_at, datetime):
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ValueError("observed_at must be timezone-aware")
            identity["observed_at"] = observed_at.astimezone(timezone.utc)
        candidate = cls.model_construct(**identity, receipt_sha256="0" * 64)
        complete = candidate.model_dump(
            mode="python",
            exclude={"receipt_sha256"},
        )
        return cls(**complete, receipt_sha256=canonical_sha256(complete))


def enforce_zero_spend_budgets(
    evidence: ZeroSpendBudgetEvidenceV1,
    *,
    now: datetime,
) -> str:
    """Fail closed unless all three zero-spend controls are exact and active."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    age = now.astimezone(timezone.utc) - evidence.observed_at
    if age > timedelta(minutes=5) or age < -timedelta(seconds=30):
        raise ValueError("ZERO_SPEND_BUDGET_RECEIPT_STALE")
    if not evidence.actions_budget_verified:
        raise ValueError("ZERO_ACTIONS_SPEND_BUDGET_REQUIRED")
    if not evidence.actions_storage_budget_verified:
        raise ValueError("ZERO_ACTIONS_STORAGE_BUDGET_REQUIRED")
    if not evidence.cache_storage_budget_verified:
        raise ValueError("ZERO_CACHE_STORAGE_BUDGET_REQUIRED")
    if not evidence.prevent_further_usage:
        raise ValueError("ZERO_SPEND_BUDGET_ENFORCEMENT_REQUIRED")
    if evidence.cache_storage_limit_bytes != 10 * 1024**3:
        raise ValueError("FREE_CACHE_STORAGE_LIMIT_REQUIRED")
    if evidence.cache_retention_days != 90:
        raise ValueError("FREE_CACHE_RETENTION_REQUIRED")
    if evidence.estimated_paid_runner_minutes != 0:
        raise ValueError("PAID_RUNNER_FORBIDDEN")
    if evidence.estimated_paid_actions_cost != 0:
        raise ValueError("PAID_ACTIONS_COST_FORBIDDEN")
    return evidence.receipt_sha256


class DeadlineDecision(FrozenModel):
    now: datetime
    deadline: datetime
    projected_remaining_seconds: float = Field(ge=0)
    checkpoint_margin_seconds: float = Field(ge=0)
    projected_completion: datetime
    route_allowed: bool
    checkpoint_requested: bool
    reason_codes: tuple[str, ...]

    @field_validator("now", "deadline", "projected_completion")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline timestamps must be timezone-aware")
        return value


def evaluate_budget(ledger: BudgetLedger) -> BudgetDecision:
    reasons: list[str] = []
    evidence_complete = True
    if (
        ledger.max_billable_minutes > 0
        and ledger.projected_total_billable_minutes
        > ledger.max_billable_minutes
    ):
        reasons.append("BILLABLE_MINUTES_BUDGET_EXCEEDED")
    if ledger.max_cost > 0:
        if ledger.projected_total_cost is None:
            evidence_complete = False
            reasons.append("COST_RATE_EVIDENCE_MISSING")
        elif ledger.projected_total_cost > ledger.max_cost:
            reasons.append("COST_BUDGET_EXCEEDED")
    return BudgetDecision(
        route_allowed=not reasons,
        checkpoint_requested=bool(reasons),
        evidence_complete=evidence_complete,
        reason_codes=tuple(reasons),
    )


def evaluate_deadline(
    *,
    now: datetime,
    deadline: datetime,
    projected_remaining_seconds: float,
    checkpoint_margin_seconds: float,
) -> DeadlineDecision:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if deadline.tzinfo is None or deadline.utcoffset() is None:
        raise ValueError("deadline must be timezone-aware")
    if projected_remaining_seconds < 0 or checkpoint_margin_seconds < 0:
        raise ValueError("deadline projections must be non-negative")
    projected_completion = now + timedelta(
        seconds=projected_remaining_seconds + checkpoint_margin_seconds
    )
    reasons = (
        ("DEADLINE_WOULD_BE_EXCEEDED",)
        if projected_completion > deadline
        else ()
    )
    return DeadlineDecision(
        now=now,
        deadline=deadline,
        projected_remaining_seconds=projected_remaining_seconds,
        checkpoint_margin_seconds=checkpoint_margin_seconds,
        projected_completion=projected_completion,
        route_allowed=not reasons,
        checkpoint_requested=bool(reasons),
        reason_codes=reasons,
    )


class RuntimeLimits(FrozenModel):
    max_memory_pct: float = Field(gt=0, le=100)
    min_free_disk_mb: float = Field(ge=0)
    sustained_memory_breach_samples: int = Field(ge=1)


class RuntimeGuardrailDecision(FrozenModel):
    checkpoint_requested: bool
    pending_stop: bool
    stop_reason: SafeStopReason | None
    pending_reasons: tuple[SafeStopReason, ...]
    stop_only_at_durable_unit_boundary: bool = True


class SafeStopController:
    """Accumulate pressure signals and stop only after a durable unit."""

    _PRIORITY = (
        SafeStopReason.MISSING_EVIDENCE,
        SafeStopReason.DISK_PRESSURE,
        SafeStopReason.MEMORY_PRESSURE,
        SafeStopReason.DEADLINE_RISK,
        SafeStopReason.BUDGET_RISK,
    )

    def __init__(self, *, limits: RuntimeLimits) -> None:
        self.limits = limits
        self._memory_breach_samples = 0
        self._pending: set[SafeStopReason] = set()

    def observe(
        self,
        observation: ResourceObservation | None,
        *,
        deadline_decision: DeadlineDecision | None = None,
        budget_decision: BudgetDecision | None = None,
    ) -> None:
        if (
            observation is None
            or not observation.child_aware
            or observation.total_memory_mb <= 0
        ):
            self._pending.add(SafeStopReason.MISSING_EVIDENCE)
        else:
            memory_pct = (
                observation.rss_mb / observation.total_memory_mb * 100.0
            )
            if memory_pct > self.limits.max_memory_pct:
                self._memory_breach_samples += 1
            else:
                self._memory_breach_samples = 0
            if (
                self._memory_breach_samples
                >= self.limits.sustained_memory_breach_samples
            ):
                self._pending.add(SafeStopReason.MEMORY_PRESSURE)
            if observation.free_disk_mb < self.limits.min_free_disk_mb:
                self._pending.add(SafeStopReason.DISK_PRESSURE)
        if (
            deadline_decision is not None
            and deadline_decision.checkpoint_requested
        ):
            self._pending.add(SafeStopReason.DEADLINE_RISK)
        if (
            budget_decision is not None
            and budget_decision.checkpoint_requested
        ):
            self._pending.add(SafeStopReason.BUDGET_RISK)

    def poll(
        self,
        *,
        at_durable_unit_boundary: bool,
    ) -> RuntimeGuardrailDecision:
        ordered = tuple(
            reason for reason in self._PRIORITY if reason in self._pending
        )
        checkpoint_requested = bool(ordered) and at_durable_unit_boundary
        return RuntimeGuardrailDecision(
            checkpoint_requested=checkpoint_requested,
            pending_stop=bool(ordered),
            stop_reason=ordered[0] if checkpoint_requested else None,
            pending_reasons=ordered,
        )


class PlanGuardrailViolation(RuntimeError):
    """Raised before fan-out when hard resource limits cannot be met."""


def _parse_utc(value: object) -> datetime:
    raw = str(value).strip()
    if not raw:
        raise PlanGuardrailViolation("DEADLINE_EVIDENCE_MISSING")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PlanGuardrailViolation("DEADLINE_EVIDENCE_MISSING")
    return parsed.astimezone(timezone.utc)


def assess_plan_guardrails(
    spec: RunSpec,
    *,
    now: datetime,
    projected_wall_seconds: float,
    projected_billable_minutes: float,
    cost_per_billable_minute: float | None,
    checkpoint_margin_seconds: float,
    consumed_billable_minutes: float = 0.0,
    committed_billable_minutes: float = 0.0,
) -> tuple[DeadlineDecision, BudgetLedger, BudgetDecision]:
    """Project hard deadline and budget bounds without mutating state."""

    deadline = evaluate_deadline(
        now=now,
        deadline=_parse_utc(spec.identity.get("deadline_utc")),
        projected_remaining_seconds=projected_wall_seconds,
        checkpoint_margin_seconds=checkpoint_margin_seconds,
    )
    ledger = BudgetLedger.project(
        max_billable_minutes=float(
            spec.resources.get("max_billable_minutes", 0.0)
        ),
        max_cost=float(spec.resources.get("max_cost", 0.0)),
        consumed_billable_minutes=consumed_billable_minutes,
        committed_billable_minutes=committed_billable_minutes,
        projected_additional_billable_minutes=projected_billable_minutes,
        cost_per_billable_minute=cost_per_billable_minute,
    )
    budget = evaluate_budget(ledger)
    return deadline, ledger, budget


def enforce_plan_guardrails(
    spec: RunSpec,
    *,
    now: datetime,
    projected_wall_seconds: float,
    projected_billable_minutes: float,
    cost_per_billable_minute: float | None,
    checkpoint_margin_seconds: float,
    consumed_billable_minutes: float = 0.0,
    committed_billable_minutes: float = 0.0,
) -> tuple[DeadlineDecision, BudgetLedger, BudgetDecision]:
    """Reject a route before launch when its hard bounds cannot hold."""

    deadline, ledger, budget = assess_plan_guardrails(
        spec,
        now=now,
        projected_wall_seconds=projected_wall_seconds,
        projected_billable_minutes=projected_billable_minutes,
        cost_per_billable_minute=cost_per_billable_minute,
        checkpoint_margin_seconds=checkpoint_margin_seconds,
        consumed_billable_minutes=consumed_billable_minutes,
        committed_billable_minutes=committed_billable_minutes,
    )
    reasons = (*deadline.reason_codes, *budget.reason_codes)
    if reasons:
        raise PlanGuardrailViolation(",".join(reasons))
    return deadline, ledger, budget


def _write_json(path: Path, payload: object) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def write_budget_audit(
    ledger: BudgetLedger,
    decision: BudgetDecision,
    path: Path,
) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "1",
            "ledger": ledger.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
        },
    )


def write_deadline_audit(
    decision: DeadlineDecision,
    path: Path,
) -> Path:
    return _write_json(path, decision)
