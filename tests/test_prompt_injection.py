"""R176 -- Prompt injection refusal tests.

Each fixture is fed through a stub LLM that complies with the
injection. The wrapper -- not the model -- is the gate, so refusal must
be observable even when the model 'cooperates'. We also assert the
gateway audit chain records refusals on the live-trade ceremony path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from aurora.agent_gateway import (
    ActionRequest,
    AgentGateway,
    GatewayPolicy,
    TokenScope,
    issue_token,
)
from aurora.agent_gateway.agent_roles import AgentRole, ROLE_REGISTRY
from aurora.agent_gateway.evidence_pack_view import EvidencePackView
from aurora.agent_gateway.gateway import (
    AuthorizationError,
    LIVE_AUTH_ENV,
)
from aurora.agent_gateway.prompt_injection_tests import (
    HOSTILE_WEB_SNIPPET,
    MALICIOUS_STRATEGY_TEXT,
    OOS_BYPASS_REQUEST,
    POISONED_RESEARCH_NOTE,
    SECRET_EXFILTRATION_REQUEST,
    assert_refused,
    stub_llm_repeats,
)
from aurora.agent_gateway.research_agents import run_review
from aurora.reporting.evidence_pack import build_strategy_pack


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _gateway_secret(monkeypatch):
    """Match the rest of the agent-gateway suite for secret env vars."""
    monkeypatch.setenv("QF_GATEWAY_SECRET", "test-secret-A1B2C3")
    monkeypatch.setenv("QF_OPERATOR_KEY", "test-operator-key-Z9Y8X7")
    yield


@pytest.fixture
def pack():
    return build_strategy_pack(
        strategy_id="alpha",
        policy_hash="p1",
        snapshot_hash="s1",
        validation_report={"sharpe": 1.2},
        benchmark_pack={"primary_baseline": "buy_and_hold"},
        manifest={"strategy_version": "v1"},
    )


@pytest.fixture
def risk_view(pack):
    cap = ROLE_REGISTRY.get(AgentRole.RISK_REVIEWER)
    return EvidencePackView(pack, cap.allowed_sections)


# ---------------------------------------------------------------------------
# 1) Each fixture, when fed verbatim by the LLM, is refused.
# ---------------------------------------------------------------------------


def test_malicious_strategy_text_refused(risk_view):
    """A malicious strategy description must be refused."""
    stub = stub_llm_repeats(MALICIOUS_STRATEGY_TEXT)
    review = assert_refused(
        lambda: run_review(AgentRole.RISK_REVIEWER, risk_view, stub),
        MALICIOUS_STRATEGY_TEXT,
    )
    assert review.refusal_reason == "banned_action_phrase"


def test_hostile_web_snippet_refused(risk_view):
    """Hostile HTML/web snippet that injects 'place an order' is refused."""
    stub = stub_llm_repeats(HOSTILE_WEB_SNIPPET)
    review = assert_refused(
        lambda: run_review(AgentRole.RISK_REVIEWER, risk_view, stub),
        HOSTILE_WEB_SNIPPET,
    )
    assert review.refusal_reason == "banned_action_phrase"


def test_poisoned_research_note_refused(risk_view):
    """A poisoned note that asks to bypass OOSGuard is refused."""
    stub = stub_llm_repeats(POISONED_RESEARCH_NOTE)
    review = assert_refused(
        lambda: run_review(AgentRole.RISK_REVIEWER, risk_view, stub),
        POISONED_RESEARCH_NOTE,
    )
    assert review.refusal_reason == "banned_action_phrase"


def test_secret_exfiltration_request_refused(risk_view):
    """The model 'complies' with the secret-dump request -- wrapper still refuses."""
    stub = stub_llm_repeats(SECRET_EXFILTRATION_REQUEST)
    review = assert_refused(
        lambda: run_review(AgentRole.RISK_REVIEWER, risk_view, stub),
        SECRET_EXFILTRATION_REQUEST,
    )
    # The fixture mentions QF_GATEWAY_SECRET; the banned-action gate
    # catches the 'gateway_secret' phrase before the response leaves.
    assert review.refusal_reason == "banned_action_phrase"


def test_oos_bypass_request_refused(risk_view):
    """An OOSGuard-bypass request is refused at the wrapper layer."""
    stub = stub_llm_repeats(OOS_BYPASS_REQUEST)
    review = assert_refused(
        lambda: run_review(AgentRole.RISK_REVIEWER, risk_view, stub),
        OOS_BYPASS_REQUEST,
    )
    assert review.refusal_reason == "banned_action_phrase"


# ---------------------------------------------------------------------------
# 2) Gateway audit chain records refusals on the trade-ceremony surface.
# ---------------------------------------------------------------------------


def test_gateway_audit_records_refusal_for_live_trade_attempt(tmp_path: Path):
    """If a token tries to trade live without ceremony, the audit chain logs it."""
    audit_path = tmp_path / "audit.jsonl"
    gateway = AgentGateway(
        policy=GatewayPolicy(audit_chain_verify_on_startup=True),
        audit_path=audit_path,
    )
    tok = issue_token(
        actor="bot-injected",
        scopes=frozenset({TokenScope.LIVE_TRADE}),
        expires_in_days=1,
        max_order_notional_usd=100.0,
        max_daily_notional_usd=1_000.0,
        cooldown_seconds=0,
        paper_only=True,  # paper_only means LIVE_TRADE must be denied.
    )
    gateway.register_token(tok)

    action = ActionRequest(
        kind="live_order", scope=TokenScope.LIVE_TRADE,
        symbol="SPY", notional_usd=50.0,
    )
    with pytest.raises(AuthorizationError):
        gateway.stage(tok, action)

    entries = gateway.audit.entries()
    denied = [e for e in entries if e.get("outcome") == "denied"]
    assert denied, "expected a denied entry on the audit chain"
    assert any("stage:live_order" in e.get("action", "") for e in denied)
    # The chain itself must still verify clean.
    rep = gateway.audit.verify_chain()
    assert rep["ok"] is True
