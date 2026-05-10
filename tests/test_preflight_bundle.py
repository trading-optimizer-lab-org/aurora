"""Tests for R177 research-to-live preflight bundle."""
from __future__ import annotations

import json

import pytest

from aurora.deployment.preflight.bundle import (
    PreflightBundle,
    PreflightCheck,
    build_preflight_bundle,
)
from aurora.governance.approvals import LifecycleStage, StrategyRiskRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ok_record(stage: LifecycleStage = LifecycleStage.PAPER) -> StrategyRiskRecord:
    return StrategyRiskRecord(
        strategy_id="alpha",
        intended_use="x",
        limitations="x",
        assumptions="x",
        operator="op",
        risk_limits={"max_drawdown": 0.1},
        validation_id="v1",
        policy_hash="p1",
        snapshot_hash="s1",
        strategy_hash="x1",
        stage=stage,
    )


def _ok_inputs() -> dict:
    return dict(
        strategy_id="alpha",
        target_stage=LifecycleStage.PAPER,
        risk_record=_ok_record(),
        expected_policy_hash="p1",
        expected_snapshot_hash="s1",
        expected_strategy_hash="x1",
        benchmark_pack={"overall_verdict": "beats"},
        quality_decisions=[
            {"symbol": "SPY", "decision": "approved"},
        ],
        evidence_pack_present=True,
        evidence_pack_hash_ok=True,
        research_ledger_complete=True,
        execution_model="market",
        kill_switch_armed=True,
        broker_healthy=True,
        reconciliation_clean=True,
        capital_limits_set=True,
        rollback_plan_present=True,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_bundle_passes():
    bundle = build_preflight_bundle(**_ok_inputs())
    assert bundle.overall_status == "pass"
    statuses = {c.name: c.status for c in bundle.checks}
    assert statuses["risk_record"] == "pass"
    assert statuses["benchmark_pack"] == "pass"
    assert statuses["evidence_pack"] == "pass"


def test_bundle_to_json_round_trip():
    bundle = build_preflight_bundle(**_ok_inputs())
    payload = json.loads(bundle.to_json())
    assert payload["overall_status"] == "pass"
    assert payload["target_stage"] == "approved_for_paper"


def test_bundle_to_table_includes_overall():
    bundle = build_preflight_bundle(**_ok_inputs())
    text = bundle.to_table()
    assert "overall: pass" in text
    assert "risk_record" in text


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_missing_risk_record_blocks():
    inputs = _ok_inputs()
    inputs["risk_record"] = None
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"
    assert any(c.name == "risk_record" and c.status == "fail" for c in bundle.checks)


def test_hash_mismatch_blocks():
    inputs = _ok_inputs()
    inputs["expected_policy_hash"] = "OTHER"
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"


def test_below_target_stage_blocks():
    inputs = _ok_inputs()
    inputs["risk_record"] = _ok_record(stage=LifecycleStage.SHADOW)
    inputs["target_stage"] = LifecycleStage.LIVE
    bundle = build_preflight_bundle(**inputs)
    assert any(
        c.name == "risk_record" and c.status == "fail"
        and "required" in c.message
        for c in bundle.checks
    )


def test_failing_benchmark_blocks():
    inputs = _ok_inputs()
    inputs["benchmark_pack"] = {"overall_verdict": "fails"}
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"
    assert any(
        c.name == "benchmark_pack" and c.status == "fail" for c in bundle.checks
    )


def test_inconclusive_benchmark_warns():
    inputs = _ok_inputs()
    inputs["benchmark_pack"] = {"overall_verdict": "inconclusive"}
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status in ("warn", "pass")
    assert any(
        c.name == "benchmark_pack" and c.status == "warn" for c in bundle.checks
    )


def test_missing_benchmark_blocks():
    inputs = _ok_inputs()
    inputs["benchmark_pack"] = None
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"


def test_quarantined_quality_decision_blocks():
    inputs = _ok_inputs()
    inputs["quality_decisions"] = [
        {"symbol": "BAD", "decision": "quarantined"},
    ]
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"
    assert any(
        c.name == "data_quality" and c.status == "fail" for c in bundle.checks
    )


def test_missing_evidence_pack_blocks():
    inputs = _ok_inputs()
    inputs["evidence_pack_present"] = False
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"


def test_evidence_pack_hash_failure_blocks():
    inputs = _ok_inputs()
    inputs["evidence_pack_hash_ok"] = False
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"


def test_missing_kill_switch_blocks():
    inputs = _ok_inputs()
    inputs["kill_switch_armed"] = False
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"


def test_missing_capital_limits_blocks():
    inputs = _ok_inputs()
    inputs["capital_limits_set"] = False
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"


def test_missing_rollback_plan_warns():
    inputs = _ok_inputs()
    inputs["rollback_plan_present"] = False
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "warn"


def test_unhealthy_broker_blocks():
    inputs = _ok_inputs()
    inputs["broker_healthy"] = False
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "fail"


def test_unclean_reconciliation_warns():
    inputs = _ok_inputs()
    inputs["reconciliation_clean"] = False
    bundle = build_preflight_bundle(**inputs)
    assert bundle.overall_status == "warn"


def test_overrides_carried_to_dict():
    inputs = _ok_inputs()
    inputs["overrides"] = [{"actor": "op", "reason": "approved by hand"}]
    bundle = build_preflight_bundle(**inputs)
    payload = bundle.to_dict()
    assert payload["overrides"][0]["actor"] == "op"
