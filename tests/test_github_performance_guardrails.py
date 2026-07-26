from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import RunSpec
from aurora.infra.github_performance.guardrails import (
    BudgetLedger,
    PlanGuardrailViolation,
    RuntimeLimits,
    SafeStopController,
    SafeStopReason,
    evaluate_budget,
    evaluate_deadline,
    enforce_plan_guardrails,
    write_budget_audit,
    write_deadline_audit,
)
from aurora.infra.github_performance.telemetry import ResourceObservation
from github_performance_helpers import minimal_valid_spec


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def _observation(
    *,
    rss_mb: float = 500.0,
    free_disk_mb: float = 20_000.0,
) -> ResourceObservation:
    return ResourceObservation(
        observed_at=NOW,
        root_pid=100,
        process_count=3,
        child_aware=True,
        rss_mb=rss_mb,
        peak_memory_mb=rss_mb,
        total_memory_mb=1_000.0,
        free_disk_mb=free_disk_mb,
        cpu_seconds=20.0,
        io_read_bytes=1_000,
        io_write_bytes=2_000,
        io_wait_seconds=0.5,
        load_1m=1.0,
    )


def test_budget_projection_blocks_minutes_and_cost_before_launch() -> None:
    ledger = BudgetLedger.project(
        max_billable_minutes=100.0,
        max_cost=30.0,
        consumed_billable_minutes=40.0,
        committed_billable_minutes=10.0,
        projected_additional_billable_minutes=51.0,
        cost_per_billable_minute=0.40,
    )
    decision = evaluate_budget(ledger)

    assert ledger.projected_total_billable_minutes == 101.0
    assert ledger.projected_total_cost == 40.4
    assert decision.route_allowed is False
    assert decision.checkpoint_requested is True
    assert decision.reason_codes == (
        "BILLABLE_MINUTES_BUDGET_EXCEEDED",
        "COST_BUDGET_EXCEEDED",
    )


def test_cost_budget_fails_closed_without_rate_evidence() -> None:
    ledger = BudgetLedger.project(
        max_billable_minutes=0.0,
        max_cost=10.0,
        consumed_billable_minutes=1.0,
        committed_billable_minutes=0.0,
        projected_additional_billable_minutes=1.0,
        cost_per_billable_minute=None,
    )
    decision = evaluate_budget(ledger)

    assert decision.route_allowed is False
    assert decision.evidence_complete is False
    assert decision.reason_codes == ("COST_RATE_EVIDENCE_MISSING",)


def test_deadline_projection_includes_checkpoint_margin() -> None:
    safe = evaluate_deadline(
        now=NOW,
        deadline=NOW + timedelta(minutes=10),
        projected_remaining_seconds=7 * 60,
        checkpoint_margin_seconds=60,
    )
    unsafe = evaluate_deadline(
        now=NOW,
        deadline=NOW + timedelta(minutes=10),
        projected_remaining_seconds=9 * 60,
        checkpoint_margin_seconds=120,
    )

    assert safe.route_allowed is True
    assert safe.checkpoint_requested is False
    assert unsafe.route_allowed is False
    assert unsafe.checkpoint_requested is True
    assert unsafe.reason_codes == ("DEADLINE_WOULD_BE_EXCEEDED",)


def test_planner_refuses_route_beyond_hard_deadline_or_budget() -> None:
    payload = minimal_valid_spec()
    payload["identity"]["deadline_utc"] = (
        NOW + timedelta(minutes=5)
    ).isoformat()
    payload["resources"]["max_billable_minutes"] = 2.0
    spec = RunSpec.model_validate(payload)

    with pytest.raises(
        PlanGuardrailViolation,
        match="DEADLINE_WOULD_BE_EXCEEDED",
    ):
        enforce_plan_guardrails(
            spec,
            now=NOW,
            projected_wall_seconds=6 * 60,
            projected_billable_minutes=1.0,
            cost_per_billable_minute=None,
            checkpoint_margin_seconds=30.0,
        )

    payload["identity"]["deadline_utc"] = (
        NOW + timedelta(hours=1)
    ).isoformat()
    spec = RunSpec.model_validate(payload)
    with pytest.raises(
        PlanGuardrailViolation,
        match="BILLABLE_MINUTES_BUDGET_EXCEEDED",
    ):
        enforce_plan_guardrails(
            spec,
            now=NOW,
            projected_wall_seconds=60.0,
            projected_billable_minutes=3.0,
            cost_per_billable_minute=None,
            checkpoint_margin_seconds=30.0,
        )


def test_runtime_requests_memory_stop_only_at_durable_boundary() -> None:
    controller = SafeStopController(
        limits=RuntimeLimits(
            max_memory_pct=80.0,
            min_free_disk_mb=5_000.0,
            sustained_memory_breach_samples=2,
        )
    )
    controller.observe(_observation(rss_mb=850.0))
    controller.observe(_observation(rss_mb=860.0))

    mid_unit = controller.poll(at_durable_unit_boundary=False)
    boundary = controller.poll(at_durable_unit_boundary=True)

    assert mid_unit.checkpoint_requested is False
    assert mid_unit.pending_stop is True
    assert boundary.checkpoint_requested is True
    assert boundary.stop_reason is SafeStopReason.MEMORY_PRESSURE
    assert boundary.stop_only_at_durable_unit_boundary is True


def test_runtime_requests_immediate_next_boundary_for_low_disk() -> None:
    controller = SafeStopController(
        limits=RuntimeLimits(
            max_memory_pct=90.0,
            min_free_disk_mb=5_000.0,
            sustained_memory_breach_samples=2,
        )
    )
    controller.observe(_observation(free_disk_mb=4_999.0))

    decision = controller.poll(at_durable_unit_boundary=True)

    assert decision.checkpoint_requested is True
    assert decision.stop_reason is SafeStopReason.DISK_PRESSURE


def test_runtime_fails_closed_when_resource_evidence_is_missing() -> None:
    controller = SafeStopController(
        limits=RuntimeLimits(
            max_memory_pct=80.0,
            min_free_disk_mb=5_000.0,
            sustained_memory_breach_samples=2,
        )
    )
    controller.observe(None)

    decision = controller.poll(at_durable_unit_boundary=True)

    assert decision.checkpoint_requested is True
    assert decision.stop_reason is SafeStopReason.MISSING_EVIDENCE


def test_runtime_accepts_deadline_and_budget_checkpoint_requests() -> None:
    controller = SafeStopController(
        limits=RuntimeLimits(
            max_memory_pct=80.0,
            min_free_disk_mb=5_000.0,
            sustained_memory_breach_samples=2,
        )
    )
    deadline = evaluate_deadline(
        now=NOW,
        deadline=NOW + timedelta(seconds=100),
        projected_remaining_seconds=90,
        checkpoint_margin_seconds=20,
    )
    budget = evaluate_budget(
        BudgetLedger.project(
            max_billable_minutes=10,
            max_cost=0,
            consumed_billable_minutes=9,
            committed_billable_minutes=0,
            projected_additional_billable_minutes=2,
            cost_per_billable_minute=None,
        )
    )
    controller.observe(
        _observation(),
        deadline_decision=deadline,
        budget_decision=budget,
    )

    decision = controller.poll(at_durable_unit_boundary=True)

    assert decision.checkpoint_requested is True
    assert decision.stop_reason is SafeStopReason.DEADLINE_RISK
    assert SafeStopReason.BUDGET_RISK in decision.pending_reasons


def test_budget_and_deadline_audits_are_written(tmp_path: Path) -> None:
    ledger = BudgetLedger.project(
        max_billable_minutes=100,
        max_cost=0,
        consumed_billable_minutes=10,
        committed_billable_minutes=5,
        projected_additional_billable_minutes=20,
        cost_per_billable_minute=None,
    )
    budget = evaluate_budget(ledger)
    deadline = evaluate_deadline(
        now=NOW,
        deadline=NOW + timedelta(hours=1),
        projected_remaining_seconds=600,
        checkpoint_margin_seconds=60,
    )

    budget_path = write_budget_audit(
        ledger,
        budget,
        tmp_path / "budget_audit.json",
    )
    deadline_path = write_deadline_audit(
        deadline,
        tmp_path / "deadline_audit.json",
    )

    budget_payload = json.loads(budget_path.read_text(encoding="utf-8"))
    deadline_payload = json.loads(
        deadline_path.read_text(encoding="utf-8")
    )
    assert budget_payload["decision"]["route_allowed"] is True
    assert (
        budget_payload["ledger"]["projected_total_billable_minutes"]
        == 35
    )
    assert deadline_payload["route_allowed"] is True
