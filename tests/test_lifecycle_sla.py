"""Tests for research.lifecycle (R140)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from aurora.research.lifecycle import (
    LifecycleStatus,
    StrategySLA,
    archive,
    evaluate,
    extend_sla,
    is_blocking,
    record_revalidation,
    suspend,
)


def _sla_at(start: datetime) -> StrategySLA:
    return StrategySLA.at_promotion("test-strategy", promoted_at=start)


def test_active_within_lifetime_and_revalidation_interval():
    sla = _sla_at(datetime(2026, 1, 1))
    assert evaluate(sla, now=datetime(2026, 1, 30)) == LifecycleStatus.ACTIVE
    assert is_blocking(LifecycleStatus.ACTIVE) is False


def test_needs_revalidation_after_interval():
    sla = _sla_at(datetime(2026, 1, 1))
    # 91 days later -> past 90-day cadence but inside 365-day lifetime.
    assert evaluate(sla, now=datetime(2026, 4, 2)) == LifecycleStatus.NEEDS_REVALIDATION
    assert is_blocking(LifecycleStatus.NEEDS_REVALIDATION) is False


def test_sla_expired_after_initial_lifetime():
    sla = _sla_at(datetime(2026, 1, 1))
    assert evaluate(sla, now=datetime(2027, 1, 2)) == LifecycleStatus.SLA_EXPIRED
    assert is_blocking(LifecycleStatus.SLA_EXPIRED) is True


def test_hard_ceiling_exceeded_overrides_sla_extension():
    sla = _sla_at(datetime(2024, 1, 1))
    sla = extend_sla(sla, additional_days=2_000, operator_signature="ops")
    # 3 years past promotion: hard ceiling (730 days) trips even though
    # the extended lifetime would still allow it.
    assert (
        evaluate(sla, now=datetime(2027, 1, 2))
        == LifecycleStatus.HARD_CEILING_EXCEEDED
    )
    assert is_blocking(LifecycleStatus.HARD_CEILING_EXCEEDED) is True


def test_record_revalidation_resets_cadence_clock():
    sla = _sla_at(datetime(2026, 1, 1))
    sla = record_revalidation(sla, when=datetime(2026, 4, 1))
    # 30 days after re-validation -> back to ACTIVE despite original
    # promotion being more than 90 days ago.
    assert evaluate(sla, now=datetime(2026, 5, 1)) == LifecycleStatus.ACTIVE


def test_suspended_status_persists():
    sla = _sla_at(datetime(2026, 1, 1))
    sla = suspend(sla)
    # No matter when we evaluate, suspended stays suspended.
    assert evaluate(sla, now=datetime(2030, 1, 1)) == LifecycleStatus.SUSPENDED
    assert is_blocking(LifecycleStatus.SUSPENDED) is True


def test_archived_status_persists():
    sla = _sla_at(datetime(2026, 1, 1))
    sla = archive(sla)
    assert evaluate(sla, now=datetime(2030, 1, 1)) == LifecycleStatus.ARCHIVED


def test_extend_sla_requires_positive_days_and_signature():
    sla = _sla_at(datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        extend_sla(sla, additional_days=0, operator_signature="ops")
    with pytest.raises(ValueError):
        extend_sla(sla, additional_days=30, operator_signature="")
