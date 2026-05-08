"""Strategy lifecycle SLA primitive (R140).

Every promoted strategy declares an expected lifetime. At end-of-SLA
the strategy is auto-suspended pending operator-led re-validation.
This module provides the data model and the SLA evaluator; the
auto-loop / scheduler integration is a follow-up consumer.

Design contract
---------------

* SLA is declared per strategy, not per spec. Two specs that produce
  the same approved strategy share one SLA.
* SLA fields are immutable post-promotion. Extending an SLA requires
  an explicit operator ceremony (audit-logged).
* Suspension is "soft": the live wrapper refuses to send new orders
  but never cancels open positions. Operator decision: extend or
  liquidate.
* The SLA evaluator is a pure function over (now, sla, last_validated)
  so it is trivially testable.

Default cadence
---------------

* Initial lifetime: 12 months from promotion.
* Mandatory re-validation: every 90 days.
* Hard ceiling: 24 months without re-validation -> suspended
  regardless of SLA value.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------


DEFAULT_INITIAL_LIFETIME = timedelta(days=365)
DEFAULT_REVALIDATION_INTERVAL = timedelta(days=90)
HARD_CEILING_WITHOUT_REVALIDATION = timedelta(days=730)


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


class LifecycleStatus(str, Enum):
    """Where a strategy sits in its lifecycle."""

    ACTIVE = "active"
    NEEDS_REVALIDATION = "needs_revalidation"
    SLA_EXPIRED = "sla_expired"
    HARD_CEILING_EXCEEDED = "hard_ceiling_exceeded"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategySLA:
    """Frozen SLA for a promoted strategy.

    Attributes:
        strategy_id: short identifier (matches the factory
            `CandidateRun.candidate_id` post-promotion).
        promoted_at: timestamp of OOS_LOCKED ceremony.
        last_validated_at: most recent successful re-validation. Equal
            to ``promoted_at`` until the first re-validation closes.
        initial_lifetime_days: declared lifetime at promotion. Default
            365.
        revalidation_interval_days: cadence for periodic re-validation.
            Default 90.
        hard_ceiling_days: absolute ceiling beyond which the strategy
            is auto-suspended regardless of declared lifetime. Default
            730.
        status: current lifecycle status. Set to ``ACTIVE`` on creation;
            `evaluate` returns the live status given the current time.
    """

    strategy_id: str
    promoted_at: datetime
    last_validated_at: datetime
    initial_lifetime_days: int = DEFAULT_INITIAL_LIFETIME.days
    revalidation_interval_days: int = DEFAULT_REVALIDATION_INTERVAL.days
    hard_ceiling_days: int = HARD_CEILING_WITHOUT_REVALIDATION.days
    status: LifecycleStatus = LifecycleStatus.ACTIVE

    @classmethod
    def at_promotion(
        cls,
        strategy_id: str,
        promoted_at: Optional[datetime] = None,
        **overrides,
    ) -> "StrategySLA":
        ts = promoted_at or datetime.utcnow()
        return cls(
            strategy_id=strategy_id,
            promoted_at=ts,
            last_validated_at=ts,
            **overrides,
        )


# --------------------------------------------------------------------------
# Evaluator
# --------------------------------------------------------------------------


def evaluate(
    sla: StrategySLA,
    now: Optional[datetime] = None,
) -> LifecycleStatus:
    """Return the live lifecycle status for ``sla`` evaluated at ``now``.

    Pure function. Does not mutate ``sla``.
    """
    now = now or datetime.utcnow()
    if sla.status in (LifecycleStatus.SUSPENDED, LifecycleStatus.ARCHIVED):
        return sla.status
    age = now - sla.promoted_at
    since_revalidation = now - sla.last_validated_at

    if age >= timedelta(days=sla.hard_ceiling_days):
        return LifecycleStatus.HARD_CEILING_EXCEEDED
    if age >= timedelta(days=sla.initial_lifetime_days):
        return LifecycleStatus.SLA_EXPIRED
    if since_revalidation >= timedelta(days=sla.revalidation_interval_days):
        return LifecycleStatus.NEEDS_REVALIDATION
    return LifecycleStatus.ACTIVE


def is_blocking(status: LifecycleStatus) -> bool:
    """True iff ``status`` should refuse new live orders.

    NEEDS_REVALIDATION is not blocking on its own -- the operator gets
    a notification and decides. SLA_EXPIRED, HARD_CEILING_EXCEEDED, and
    SUSPENDED are blocking.
    """
    return status in {
        LifecycleStatus.SLA_EXPIRED,
        LifecycleStatus.HARD_CEILING_EXCEEDED,
        LifecycleStatus.SUSPENDED,
    }


# --------------------------------------------------------------------------
# Operator transitions
# --------------------------------------------------------------------------


def extend_sla(
    sla: StrategySLA,
    additional_days: int,
    operator_signature: str,
) -> StrategySLA:
    """Extend the initial lifetime by ``additional_days``.

    Caller must supply a non-empty ``operator_signature``; the audit
    chain records who extended the SLA. Pure function: returns a new
    SLA, does not mutate the input.
    """
    if additional_days <= 0:
        raise ValueError("additional_days must be positive")
    if not operator_signature:
        raise ValueError("operator_signature is required to extend an SLA")
    from dataclasses import replace
    return replace(
        sla,
        initial_lifetime_days=sla.initial_lifetime_days + additional_days,
    )


def record_revalidation(
    sla: StrategySLA,
    when: Optional[datetime] = None,
) -> StrategySLA:
    """Stamp a successful re-validation, resetting the cadence clock."""
    from dataclasses import replace
    return replace(sla, last_validated_at=when or datetime.utcnow())


def suspend(sla: StrategySLA) -> StrategySLA:
    from dataclasses import replace
    return replace(sla, status=LifecycleStatus.SUSPENDED)


def archive(sla: StrategySLA) -> StrategySLA:
    from dataclasses import replace
    return replace(sla, status=LifecycleStatus.ARCHIVED)


__all__ = [
    "DEFAULT_INITIAL_LIFETIME",
    "DEFAULT_REVALIDATION_INTERVAL",
    "HARD_CEILING_WITHOUT_REVALIDATION",
    "LifecycleStatus",
    "StrategySLA",
    "evaluate",
    "is_blocking",
    "extend_sla",
    "record_revalidation",
    "suspend",
    "archive",
]
