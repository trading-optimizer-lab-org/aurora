"""Tests for the multi-agent auditor (P1.B).

Covers ReviewFinding immutability, every reviewer's HARD_FAIL paths,
orchestrator aggregation + gate decision, the LLM augmenter cap, the
validation pipeline wire-in, snapshot integration, and CLI smoke.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import sys
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantforge.agents.auditor import (
    AuditReport,
    AuditorOrchestrator,
    CostReviewer,
    DataLeakReviewer,
    DeploymentReviewer,
    HypothesisReviewer,
    LLM_MAX_SEVERITY,
    RegimeReviewer,
    ReviewContext,
    ReviewFinding,
    ReviewReport,
    ReviewSeverity,
    ReviewerAgent,
    RiskReviewer,
    cap_augmenter_findings,
)
from quantforge.core.protocol_policy import ProtocolPolicy


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def policy() -> ProtocolPolicy:
    return ProtocolPolicy.default()


def _ctx(policy, *, spec=None, bt=None, extras=None) -> ReviewContext:
    return ReviewContext(
        strategy_id="strat_1",
        strategy_spec=spec or {},
        backtest_results=bt or {},
        validation_results=None,
        snapshot_id=None,
        policy=policy,
        extras=extras or {},
    )


def _good_spec() -> dict:
    return {
        "hypothesis": "Cross-sectional momentum is documented in literature.",
        "expected_edge_bps": 30,
        "regime_dependence": "Works in trending, low-vol regimes.",
        "failure_modes": [
            "regime shift to mean-reverting",
            "borrow drying up on shorts",
            "execution costs blow up",
        ],
        "assumptions": ["12-month formation window", "monthly rebalance"],
    }


def _good_backtest(policy: ProtocolPolicy) -> dict:
    cm = policy.cost_model
    expected_bps = cm.commission_bps + cm.spread_bps + cm.slippage_bps
    return {
        "max_drawdown": 0.10,
        "max_leverage": 1.0,
        "cost_breakdown_bps": expected_bps,
        "by_regime": {
            "bull": {"sharpe": 1.2},
            "bear": {"sharpe": 0.4},
            "flat": {"sharpe": 0.7},
        },
        "lookahead_check": {"passed": True},
    }


# ---------------------------------------------------------------------------
# 1. ReviewFinding immutable
# ---------------------------------------------------------------------------


def test_review_finding_is_immutable():
    f = ReviewFinding(
        severity=ReviewSeverity.MEDIUM,
        code="X", title="t", detail="d", evidence={"k": 1},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.code = "Y"  # type: ignore


# ---------------------------------------------------------------------------
# 2. ReviewReport.has_hard_fail
# ---------------------------------------------------------------------------


def test_review_report_has_hard_fail():
    base = ReviewReport(
        reviewer="X",
        target_strategy_id="s1",
        target_run_id=None,
        findings=[ReviewFinding(severity=ReviewSeverity.LOW,
                                code="L", title="t", detail="d")],
        summary="ok",
        score=0.8,
        timestamp=pd.Timestamp.utcnow(),
        policy_hash="abc",
    )
    assert base.has_hard_fail() is False
    rep = dataclasses.replace(
        base,
        findings=[ReviewFinding(severity=ReviewSeverity.HARD_FAIL,
                                code="HF", title="t", detail="d")],
    )
    assert rep.has_hard_fail() is True


# ---------------------------------------------------------------------------
# 3-5. HypothesisReviewer
# ---------------------------------------------------------------------------


def test_hypothesis_reviewer_hard_fail_when_missing(policy):
    rev = HypothesisReviewer()
    ctx = _ctx(policy, spec={"expected_edge_bps": 10})
    rep = rev.review(ctx)
    codes = {f.code for f in rep.findings}
    assert "HYPOTHESIS_MISSING" in codes
    assert rep.has_hard_fail()
    assert rep.score == 0.0


def test_hypothesis_reviewer_hard_fail_edge_too_high(policy):
    rev = HypothesisReviewer()
    spec = _good_spec()
    spec["expected_edge_bps"] = 250
    rep = rev.review(_ctx(policy, spec=spec))
    codes = {f.code for f in rep.findings}
    assert "EXPECTED_EDGE_IMPLAUSIBLE" in codes
    assert rep.has_hard_fail()


def test_hypothesis_reviewer_high_no_failure_modes(policy):
    rev = HypothesisReviewer()
    spec = _good_spec()
    spec.pop("failure_modes")
    rep = rev.review(_ctx(policy, spec=spec))
    codes = {f.code for f in rep.findings}
    assert "FAILURE_MODES_NOT_DOCUMENTED" in codes
    # Highest severity should be HIGH, not HARD_FAIL.
    severities = [f.severity for f in rep.findings]
    assert ReviewSeverity.HIGH in severities
    assert ReviewSeverity.HARD_FAIL not in severities


# ---------------------------------------------------------------------------
# 6-7. DataLeakReviewer
# ---------------------------------------------------------------------------


def test_data_leak_reviewer_hard_fail_on_detected_leak(policy):
    rev = DataLeakReviewer()
    bt = {"lookahead_check": {"passed": False}}
    rep = rev.review(_ctx(policy, bt=bt))
    codes = {f.code for f in rep.findings}
    assert "DATA_LEAK_LOOKAHEAD_DETECTED" in codes
    assert rep.has_hard_fail()


def test_data_leak_reviewer_pass_on_clean(policy):
    rev = DataLeakReviewer()
    bt = _good_backtest(policy)
    rep = rev.review(_ctx(policy, bt=bt))
    assert not rep.has_hard_fail()


# ---------------------------------------------------------------------------
# 8-10. CostReviewer
# ---------------------------------------------------------------------------


def test_cost_reviewer_hard_fail_when_costs_below_50pct(policy):
    rev = CostReviewer()
    cm = policy.cost_model
    expected = cm.commission_bps + cm.spread_bps + cm.slippage_bps
    bt = {"cost_breakdown_bps": expected * 0.30}
    rep = rev.review(_ctx(policy, bt=bt))
    codes = {f.code for f in rep.findings}
    assert "COST_DENIAL" in codes
    assert rep.has_hard_fail()


def test_cost_reviewer_medium_when_costs_50_to_80pct(policy):
    rev = CostReviewer()
    cm = policy.cost_model
    expected = cm.commission_bps + cm.spread_bps + cm.slippage_bps
    bt = {"cost_breakdown_bps": expected * 0.65}
    rep = rev.review(_ctx(policy, bt=bt))
    sevs = [f.severity for f in rep.findings]
    assert ReviewSeverity.MEDIUM in sevs
    assert ReviewSeverity.HARD_FAIL not in sevs


def test_cost_reviewer_pass_when_costs_match(policy):
    rev = CostReviewer()
    cm = policy.cost_model
    expected = cm.commission_bps + cm.spread_bps + cm.slippage_bps
    bt = {"cost_breakdown_bps": expected}
    rep = rev.review(_ctx(policy, bt=bt))
    assert not rep.has_hard_fail()
    assert all(f.severity is not ReviewSeverity.HARD_FAIL for f in rep.findings)


# ---------------------------------------------------------------------------
# 11-12. RegimeReviewer
# ---------------------------------------------------------------------------


def test_regime_reviewer_high_if_single_regime(policy):
    rev = RegimeReviewer()
    bt = {
        "by_regime": {
            "bull": {"sharpe": 1.0},
            "bear": {"sharpe": -0.4},
            "flat": {"sharpe": -0.1},
        }
    }
    rep = rev.review(_ctx(policy, bt=bt))
    sevs = [f.severity for f in rep.findings]
    assert ReviewSeverity.HIGH in sevs


def test_regime_reviewer_medium_when_worst_negative(policy):
    rev = RegimeReviewer()
    bt = {
        "by_regime": {
            "bull": {"sharpe": 1.0},
            "bear": {"sharpe": -0.2},
            "flat": {"sharpe": 0.7},
        }
    }
    rep = rev.review(_ctx(policy, bt=bt))
    sevs = [f.severity for f in rep.findings]
    assert ReviewSeverity.MEDIUM in sevs
    assert ReviewSeverity.HIGH not in sevs


# ---------------------------------------------------------------------------
# 13-14. RiskReviewer
# ---------------------------------------------------------------------------


def test_risk_reviewer_hard_fail_max_dd_breach(policy):
    rev = RiskReviewer()
    bt = {"max_drawdown": 0.50}  # > 0.30 default policy
    rep = rev.review(_ctx(policy, bt=bt))
    codes = {f.code for f in rep.findings}
    assert "RISK_MDD_BREACH" in codes
    assert rep.has_hard_fail()


def test_risk_reviewer_hard_fail_leverage_breach(policy):
    rev = RiskReviewer()
    bt = {"max_leverage": 2.5}  # > 1.0 default
    rep = rev.review(_ctx(policy, bt=bt))
    codes = {f.code for f in rep.findings}
    assert "RISK_LEVERAGE_BREACH" in codes
    assert rep.has_hard_fail()


# ---------------------------------------------------------------------------
# 15-16. DeploymentReviewer
# ---------------------------------------------------------------------------


def test_deployment_reviewer_hard_fail_size_over_10pct_adv(policy):
    rev = DeploymentReviewer()
    bt = {"planned_size_pct_of_adv": 0.20}  # 20% ADV > 10%
    rep = rev.review(_ctx(policy, bt=bt))
    codes = {f.code for f in rep.findings}
    assert "DEPLOY_SIZE_OVER_10PCT_ADV" in codes
    assert rep.has_hard_fail()


def test_deployment_reviewer_medium_shorts_no_borrow(policy):
    rev = DeploymentReviewer()
    spec = _good_spec()
    spec["uses_shorts"] = True
    bt = {"planned_size_pct_of_adv": 0.05}  # safe size
    rep = rev.review(_ctx(policy, spec=spec, bt=bt))
    sevs = [f.severity for f in rep.findings]
    codes = {f.code for f in rep.findings}
    assert "DEPLOY_SHORTS_NO_BORROW_MODEL" in codes
    assert ReviewSeverity.MEDIUM in sevs
    assert ReviewSeverity.HARD_FAIL not in sevs


# ---------------------------------------------------------------------------
# 17-19. AuditorOrchestrator
# ---------------------------------------------------------------------------


def test_orchestrator_default_has_six_reviewers():
    orch = AuditorOrchestrator.default()
    assert len(orch.reviewers) == 6
    names = {r.name for r in orch.reviewers}
    assert names == {
        "HypothesisReviewer",
        "DataLeakReviewer",
        "CostReviewer",
        "RegimeReviewer",
        "RiskReviewer",
        "DeploymentReviewer",
    }


def test_orchestrator_review_aggregates_correctly(policy):
    orch = AuditorOrchestrator.default()
    spec = _good_spec()
    bt = _good_backtest(policy)
    ctx = _ctx(policy, spec=spec, bt=bt)
    rep = orch.review(ctx)
    assert isinstance(rep, AuditReport)
    assert len(rep.reports) == 6
    # No HARD_FAIL on a clean spec/backtest.
    assert rep.has_hard_fail is False
    # Aggregate score is the mean of per-reviewer scores.
    expected = sum(r.score for r in rep.reports) / 6
    assert abs(rep.aggregate_score - expected) < 1e-9
    assert rep.policy_hash == policy.policy_hash


def test_orchestrator_gate_fails_on_any_hard_fail(policy):
    orch = AuditorOrchestrator.default()
    # Inject a HARD_FAIL: blow up max_drawdown.
    spec = _good_spec()
    bt = _good_backtest(policy)
    bt["max_drawdown"] = 0.99
    gate = orch.gate(_ctx(policy, spec=spec, bt=bt))
    assert gate.passed is False
    assert "RISK_MDD_BREACH" in gate.reason
    assert gate.audit_report.has_hard_fail


# ---------------------------------------------------------------------------
# 20-21. LLM augmenter
# ---------------------------------------------------------------------------


def test_llm_augmenter_cannot_upgrade_severity(policy):
    """Augmenter-emitted HIGH/HARD_FAIL findings must be filtered out."""
    def aug(findings, ctx):
        return [
            ReviewFinding(severity=ReviewSeverity.LOW, code="A", title="a",
                          detail="ok"),
            ReviewFinding(severity=ReviewSeverity.HIGH, code="B", title="b",
                          detail="too high"),
            ReviewFinding(severity=ReviewSeverity.HARD_FAIL, code="C",
                          title="c", detail="not allowed"),
        ]
    rev = HypothesisReviewer(llm_augmenter=aug)
    rep = rev.review(_ctx(policy, spec=_good_spec()))
    extras = [f for f in rep.findings if f.code in {"A", "B", "C"}]
    extra_codes = {f.code for f in extras}
    assert "A" in extra_codes
    # HIGH and HARD_FAIL are dropped at the cap.
    assert "B" not in extra_codes
    assert "C" not in extra_codes


def test_llm_augmenter_findings_appended(policy):
    """Augmenter LOW/INFO/MEDIUM findings show up alongside rule findings."""
    def aug(findings, ctx):
        return [
            ReviewFinding(severity=ReviewSeverity.INFO, code="EXTRA_INFO",
                          title="info", detail="extra context"),
            ReviewFinding(severity=ReviewSeverity.MEDIUM, code="EXTRA_MED",
                          title="med", detail="medium"),
        ]
    rev = HypothesisReviewer(llm_augmenter=aug)
    rep = rev.review(_ctx(policy, spec=_good_spec()))
    codes = {f.code for f in rep.findings}
    assert "EXTRA_INFO" in codes
    assert "EXTRA_MED" in codes


def test_cap_augmenter_findings_helper():
    raw = [
        ReviewFinding(severity=ReviewSeverity.LOW, code="L", title="t",
                      detail="d"),
        ReviewFinding(severity=ReviewSeverity.HIGH, code="H", title="t",
                      detail="d"),
    ]
    out = cap_augmenter_findings(raw)
    assert len(out) == 1
    assert out[0].code == "L"
    assert LLM_MAX_SEVERITY is ReviewSeverity.MEDIUM


# ---------------------------------------------------------------------------
# 22. Validation pipeline includes auditor_gate
# ---------------------------------------------------------------------------


def test_validation_pipeline_has_auditor_gate():
    """The default policy lists ``auditor_gate`` in mandatory_gates."""
    from quantforge.validation import pipeline as vpipeline
    gates = vpipeline.get_mandatory_gates()
    assert "auditor_gate" in gates


def test_validation_pipeline_runs_auditor_gate_when_context_provided(policy):
    """validate_pipeline with auditor_context attaches an audit_report.

    Uses a price series spanning both an IS and an OOS slice so the
    canonical tier carve produces two non-empty halves.
    """
    rng = np.random.default_rng(2)
    # Span 2008..2018: IS_ALL = 2008-2012, OOS_DEV = 2013-2018.
    idx = pd.date_range("2008-01-02", periods=2700, freq="B")
    rets = rng.normal(0.0005, 0.012, len(idx))
    prices = pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="SYN")

    from quantforge.validation.pipeline import validate_pipeline
    from quantforge.strategies.library.ma_cross import MACross

    spec = _good_spec()
    bt = _good_backtest(policy)

    ctx = ReviewContext(
        strategy_id="ma_cross",
        strategy_spec=spec,
        backtest_results=bt,
        validation_results=None,
        snapshot_id=None,
        policy=policy,
        extras={},
    )

    rep = validate_pipeline(
        strategy_factory=lambda: MACross(),
        prices=prices, name="ma_cross",
        n_trials_optimization=1,
        auditor_context=ctx,
    )
    assert rep.audit_passed is True
    assert rep.audit_report is not None


# ---------------------------------------------------------------------------
# 23. Snapshot stores audit_report_hash
# ---------------------------------------------------------------------------


def test_snapshot_stores_audit_report_hash(tmp_path, policy):
    from quantforge.core.snapshots import SnapshotStore

    rng = np.random.default_rng(1)
    idx = pd.date_range("2020-01-01", periods=60, freq="B")
    series = pd.Series(100.0 + np.cumsum(rng.normal(0, 0.1, 60)),
                       index=idx, name="Close")
    store = SnapshotStore(root_dir=str(tmp_path))
    snap = store.freeze(series, symbol="SYN", provenance="test")

    orch = AuditorOrchestrator.default()
    audit = orch.review(ReviewContext(
        strategy_id="x", strategy_spec=_good_spec(),
        backtest_results=_good_backtest(policy),
        validation_results=None, snapshot_id=snap.sha256,
        policy=policy, extras={},
    ))
    h = store.attach_audit_report(snap.sha256, audit)
    assert h == audit.content_hash()

    # Round-trip via DB read.
    with sqlite3.connect(store.index_path) as con:
        row = con.execute(
            "SELECT audit_report_hash FROM snapshots WHERE sha256 = ?",
            (snap.sha256,),
        ).fetchone()
    assert row[0] == h


# ---------------------------------------------------------------------------
# 24. CLI smoke
# ---------------------------------------------------------------------------


def test_cli_audit_list_reviewers(capsys):
    """`forge audit list-reviewers` lists the 6 reviewers."""
    from quantforge.cli import forge as cli
    rc = cli.main(["audit", "list-reviewers"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "HypothesisReviewer" in captured
    assert "DataLeakReviewer" in captured
    assert "CostReviewer" in captured
    assert "RegimeReviewer" in captured
    assert "RiskReviewer" in captured
    assert "DeploymentReviewer" in captured


def test_cli_audit_run_smoke(tmp_path, capsys):
    """`forge audit run <id> --backtest <json>` runs end-to-end."""
    from quantforge.cli import forge as cli
    payload = {
        "strategy_spec": _good_spec(),
        "backtest_results": _good_backtest(ProtocolPolicy.default()),
        "validation_results": None,
        "snapshot_id": None,
        "extras": {},
    }
    bt_path = tmp_path / "payload.json"
    bt_path.write_text(json.dumps(payload), encoding="utf-8")
    out_path = tmp_path / "audit.json"
    rc = cli.main([
        "audit", "run", "strat_X",
        "--backtest", str(bt_path),
        "--output", str(out_path),
    ])
    assert rc == 0  # clean spec -> no hard fail
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["has_hard_fail"] is False
    assert len(data["reports"]) == 6
