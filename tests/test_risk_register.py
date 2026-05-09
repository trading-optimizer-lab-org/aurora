"""Tests for ``quantforge.governance`` (Phase 6 / Candidate D).

Coverage:

* Promotion gate: missing record, expired record, hash mismatch,
  wrong approval status, warning threshold breach.
* Maker-checker order: out-of-order calls raise ``ApprovalError``.
* Override: requires non-empty actor + reason; emits an audit event;
  records a REJECTED tail entry.
* Retired strategy cannot be promoted to live without a fresh record.
* Lifecycle transitions: illegal direct DRAFT -> LIVE; legal full path
  DRAFT -> RESEARCHING -> ... -> LIVE through the maker-checker flow.
* Persistence: write + read round-trip, multi-version lookup, latest().
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aurora.governance import (
    ApprovalError,
    ApprovalStatus,
    LifecycleError,
    LifecycleState,
    MakerCheckerFlow,
    RiskRegister,
    StrategyRiskRecord,
    gate_promotion,
    transition,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def register_path(tmp_path, monkeypatch) -> Path:
    """Isolated risk register JSONL path."""
    p = tmp_path / "risk_register.jsonl"
    monkeypatch.setenv("QF_RISK_REGISTER", str(p))
    monkeypatch.setenv("QF_DATA_DIR", str(tmp_path))
    return p


@pytest.fixture
def register(register_path) -> RiskRegister:
    return RiskRegister(path=register_path)


@pytest.fixture
def flow(register, tmp_path) -> MakerCheckerFlow:
    return MakerCheckerFlow(
        register=register, audit_log_path=tmp_path / "governance_audit.jsonl",
    )


def _draft_record(
    *,
    strategy_id: str = "alpha-1",
    version: str = "1.0",
    expiry_iso: str = "2099-12-31",
    policy_hash: str = "p" * 64,
    snapshot_hash: str = "s" * 64,
    strategy_hash: str = "x" * 64,
    validation_evidence_hash: str = "v" * 64,
    data_contract_hash: str = "d" * 64,
) -> StrategyRiskRecord:
    return StrategyRiskRecord(
        strategy_id=strategy_id,
        version=version,
        intended_use="Mean reversion on liquid US equities.",
        limitations=("not for crypto", "not for low-liquidity names"),
        assumptions=("daily bars are reliable",),
        owner="alice",
        reviewer=None,
        risk_owner=None,
        operator=None,
        approval_status=ApprovalStatus.DRAFT,
        policy_hash=policy_hash,
        snapshot_hash=snapshot_hash,
        strategy_hash=strategy_hash,
        validation_evidence_hash=validation_evidence_hash,
        data_contract_hash=data_contract_hash,
        risk_limits={"max_gross": 1.0, "max_per_name": 0.05},
        expiry_iso=expiry_iso,
        revalidation_iso="2099-06-30",
        created_at_iso="2026-05-09T00:00:00+00:00",
        last_updated_iso="2026-05-09T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Gate refusals
# ---------------------------------------------------------------------------
def test_gate_refuses_without_record(register):
    reasons = gate_promotion(
        strategy_id="missing", version="1.0",
        target_state=LifecycleState.LIVE,
        register=register, today="2026-05-09",
    )
    assert reasons == ["missing risk record"]


def test_gate_refuses_when_expired(register, flow):
    rec = _draft_record(expiry_iso="2025-01-01")
    register.register(rec)
    reasons = gate_promotion(
        strategy_id=rec.strategy_id, version=rec.version,
        target_state=LifecycleState.PAPER,
        register=register, today="2026-05-09",
    )
    assert any("expired" in r for r in reasons)


def test_gate_refuses_live_without_operator_approval(register):
    register.register(_draft_record())
    reasons = gate_promotion(
        strategy_id="alpha-1", version="1.0",
        target_state=LifecycleState.LIVE,
        register=register, today="2026-05-09",
    )
    assert any("operator_approved" in r for r in reasons)


def test_gate_refuses_on_hash_mismatch(register, flow):
    rec = _draft_record()
    flow.propose(rec, actor="alice")
    flow.review(register.get(rec.strategy_id, rec.version), actor="bob")
    flow.approve_risk(register.get(rec.strategy_id, rec.version), actor="carol")
    flow.approve_operator(register.get(rec.strategy_id, rec.version), actor="dave")
    reasons = gate_promotion(
        strategy_id=rec.strategy_id, version=rec.version,
        target_state=LifecycleState.LIVE,
        register=register, today="2026-05-09",
        current_strategy_hash="DIFFERENT" * 8,
    )
    assert any("strategy_hash mismatch" in r for r in reasons)


def test_gate_refuses_when_warning_threshold_exceeded(register, flow):
    rec = _draft_record()
    flow.propose(rec, actor="alice")
    flow.review(register.get(rec.strategy_id, rec.version), actor="bob")
    flow.approve_risk(register.get(rec.strategy_id, rec.version), actor="carol")
    flow.approve_operator(register.get(rec.strategy_id, rec.version), actor="dave")
    reasons = gate_promotion(
        strategy_id=rec.strategy_id, version=rec.version,
        target_state=LifecycleState.LIVE,
        register=register, today="2026-05-09",
        open_warnings=5, warning_threshold=3,
    )
    assert any("open_warnings=5" in r for r in reasons)


def test_gate_passes_when_record_complete(register, flow):
    rec = _draft_record()
    flow.propose(rec, actor="alice")
    flow.review(register.get(rec.strategy_id, rec.version), actor="bob")
    flow.approve_risk(register.get(rec.strategy_id, rec.version), actor="carol")
    flow.approve_operator(register.get(rec.strategy_id, rec.version), actor="dave")
    reasons = gate_promotion(
        strategy_id=rec.strategy_id, version=rec.version,
        target_state=LifecycleState.LIVE,
        register=register, today="2026-05-09",
        current_policy_hash=rec.policy_hash,
        current_snapshot_hash=rec.snapshot_hash,
        current_strategy_hash=rec.strategy_hash,
        current_validation_evidence_hash=rec.validation_evidence_hash,
        current_data_contract_hash=rec.data_contract_hash,
    )
    assert reasons == []


# ---------------------------------------------------------------------------
# Maker-checker ordering
# ---------------------------------------------------------------------------
def test_operator_cannot_approve_before_risk_owner(flow, register):
    rec = _draft_record()
    flow.propose(rec, actor="alice")
    proposed = register.get(rec.strategy_id, rec.version)
    # Skip reviewer + risk_owner straight to operator -> must refuse.
    with pytest.raises(ApprovalError):
        flow.approve_operator(proposed, actor="dave")


def test_review_requires_proposed_first(flow):
    rec = _draft_record()
    with pytest.raises(ApprovalError):
        # Reviewer cannot act on a still-DRAFT record.
        flow.review(rec, actor="bob")


def test_actor_must_be_non_empty(flow):
    rec = _draft_record()
    with pytest.raises(ApprovalError):
        flow.propose(rec, actor="")


# ---------------------------------------------------------------------------
# Override
# ---------------------------------------------------------------------------
def test_override_requires_actor_and_reason(flow, register):
    rec = _draft_record()
    flow.propose(rec, actor="alice")
    proposed = register.get(rec.strategy_id, rec.version)
    with pytest.raises(ApprovalError):
        flow.override(proposed, actor="dave", reason="")
    with pytest.raises(ApprovalError):
        flow.override(proposed, actor="", reason="bad evidence")


def test_override_appends_audit_event_and_rejects_record(flow, register, tmp_path):
    rec = _draft_record()
    flow.propose(rec, actor="alice")
    proposed = register.get(rec.strategy_id, rec.version)
    rejected = flow.override(proposed, actor="dave", reason="bad cost model")
    assert rejected.approval_status == ApprovalStatus.REJECTED
    # Latest record in the register should be the rejection.
    assert register.get(rec.strategy_id, rec.version).approval_status == ApprovalStatus.REJECTED
    # Override emits exactly one ApprovalEvent into the flow's event list.
    assert len(flow.events) >= 1
    assert flow.events[-1].action.startswith("override:")
    assert flow.events[-1].audit_hash  # canonical sha256 is filled in.


# ---------------------------------------------------------------------------
# Retired strategy cannot be promoted to live without a new record
# ---------------------------------------------------------------------------
def test_retired_strategy_cannot_be_promoted_to_live(register, flow):
    # Promote one version through to OPERATOR_APPROVED, then mark it
    # retired by writing a fresh record with REJECTED status. Promotion
    # gate must refuse a live target until a *new* record arrives.
    rec = _draft_record(version="1.0")
    flow.propose(rec, actor="alice")
    flow.review(register.get(rec.strategy_id, rec.version), actor="bob")
    flow.approve_risk(register.get(rec.strategy_id, rec.version), actor="carol")
    flow.approve_operator(register.get(rec.strategy_id, rec.version), actor="dave")
    # Operator overrides (retires) the strategy.
    flow.override(register.get(rec.strategy_id, rec.version),
                  actor="dave", reason="retired post-incident")
    reasons = gate_promotion(
        strategy_id=rec.strategy_id, version=rec.version,
        target_state=LifecycleState.LIVE,
        register=register, today="2026-05-09",
    )
    assert any("operator_approved" in r for r in reasons)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
def test_lifecycle_draft_to_live_direct_is_illegal():
    with pytest.raises(LifecycleError):
        transition(LifecycleState.DRAFT, LifecycleState.LIVE)


def test_lifecycle_full_legal_path(flow, register):
    rec = _draft_record()
    flow.propose(rec, actor="alice")
    proposed = register.get(rec.strategy_id, rec.version)
    flow.review(proposed, actor="bob")
    reviewed = register.get(rec.strategy_id, rec.version)
    flow.approve_risk(reviewed, actor="carol")
    risk_ok = register.get(rec.strategy_id, rec.version)
    flow.approve_operator(risk_ok, actor="dave")
    operator_ok = register.get(rec.strategy_id, rec.version)

    # DRAFT -> RESEARCHING -> VALIDATED -> OOS_APPROVED -> SHADOW
    state = transition(LifecycleState.DRAFT, LifecycleState.RESEARCHING)
    state = transition(state, LifecycleState.VALIDATED)
    state = transition(state, LifecycleState.OOS_APPROVED)
    state = transition(state, LifecycleState.SHADOW, record=operator_ok)
    state = transition(state, LifecycleState.PAPER, record=operator_ok)
    state = transition(state, LifecycleState.CANARY, record=operator_ok)
    state = transition(state, LifecycleState.LIVE, record=operator_ok)
    assert state == LifecycleState.LIVE


def test_lifecycle_paper_requires_risk_approval():
    rec_reviewed = _draft_record()
    rec_reviewed = StrategyRiskRecord(
        **{**rec_reviewed.__dict__, "approval_status": ApprovalStatus.REVIEWED},
    )
    # SHADOW -> PAPER demands at least RISK_APPROVED. REVIEWED is not enough.
    with pytest.raises(LifecycleError):
        transition(LifecycleState.SHADOW, LifecycleState.PAPER, record=rec_reviewed)


def test_lifecycle_evidence_required_when_transition_demands_record():
    # OOS_APPROVED -> SHADOW requires a record. None must raise.
    with pytest.raises(LifecycleError):
        transition(LifecycleState.OOS_APPROVED, LifecycleState.SHADOW, record=None)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_register_round_trip(register_path, tmp_path):
    reg1 = RiskRegister(path=register_path)
    rec = _draft_record()
    reg1.register(rec)
    # Open a fresh register pointing at the same file.
    reg2 = RiskRegister(path=register_path)
    fetched = reg2.get(rec.strategy_id, rec.version)
    assert fetched is not None
    assert fetched.strategy_id == rec.strategy_id
    assert fetched.policy_hash == rec.policy_hash
    assert fetched.risk_limits == rec.risk_limits
    assert fetched.limitations == rec.limitations
    assert fetched.approval_status == ApprovalStatus.DRAFT


def test_register_latest_picks_most_recent(register, flow):
    rec_v1 = _draft_record(version="1.0")
    register.register(rec_v1)
    rec_v2 = StrategyRiskRecord(
        **{
            **rec_v1.__dict__,
            "version": "2.0",
            "last_updated_iso": "2026-06-01T00:00:00+00:00",
        }
    )
    register.register(rec_v2)
    latest = register.latest("alpha-1")
    assert latest is not None
    assert latest.version == "2.0"


def test_is_approved_and_is_expired(register, flow):
    rec = _draft_record(expiry_iso="2025-01-01")
    flow.propose(rec, actor="alice")
    flow.review(register.get(rec.strategy_id, rec.version), actor="bob")
    flow.approve_risk(register.get(rec.strategy_id, rec.version), actor="carol")
    flow.approve_operator(register.get(rec.strategy_id, rec.version), actor="dave")
    assert register.is_approved(rec.strategy_id, rec.version) is True
    assert register.is_expired(rec.strategy_id, rec.version, today="2026-05-09") is True
    assert register.is_expired(rec.strategy_id, rec.version, today="2024-12-31") is False
