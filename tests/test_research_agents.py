"""R176 -- Tests for the bounded reviewer agents.

Real LLMs are NEVER imported. Every test wires a stub callable that
returns a deterministic dict.
"""
from __future__ import annotations

from typing import Mapping

import pytest

from aurora.agent_gateway.agent_roles import AgentRole, ROLE_REGISTRY
from aurora.agent_gateway.evidence_pack_view import EvidencePackView
from aurora.agent_gateway.research_agents import (
    AgentReview,
    merge_reviews,
    run_review,
)
from aurora.reporting.evidence_pack import build_strategy_pack


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pack():
    return build_strategy_pack(
        strategy_id="alpha",
        policy_hash="p1",
        snapshot_hash="s1",
        validation_report={"sharpe": 1.2, "passes_gates": True},
        benchmark_pack={"primary_baseline": "buy_and_hold"},
        manifest={"strategy_version": "v1"},
    )


@pytest.fixture
def risk_view(pack):
    cap = ROLE_REGISTRY.get(AgentRole.RISK_REVIEWER)
    return EvidencePackView(pack, cap.allowed_sections)


def _stub_factory(payload: dict):
    """Return a stub LLM callable that always returns ``payload``."""
    def _llm(_: Mapping[str, object]) -> dict:
        return dict(payload)
    return _llm


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_run_review_returns_review_with_valid_citation(risk_view, pack):
    """A well-behaved stub yields a non-refused review."""
    stub = _stub_factory({
        "comments": ["sharpe is acceptable"],
        "objections": [],
        "follow_up_questions": ["confirm holdout window"],
        "citations": [pack.pack_hash],
        "confidence": 0.6,
    })
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, stub)
    assert isinstance(review, AgentReview)
    assert review.refused is False
    assert review.citations == (pack.pack_hash,)
    assert review.confidence == 0.6


def test_review_dataclass_does_not_expose_broker_methods(risk_view, pack):
    """An AgentReview must not expose order/promote attributes."""
    stub = _stub_factory({
        "comments": ["ok"],
        "citations": [pack.pack_hash],
        "confidence": 0.5,
    })
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, stub)
    forbidden = (
        "submit_order", "cancel_order", "modify_order",
        "approve", "promote", "go_live",
    )
    surface = set(dir(review))
    for name in forbidden:
        assert name not in surface, f"AgentReview must not expose {name!r}"


# ---------------------------------------------------------------------------
# Citation gates
# ---------------------------------------------------------------------------


def test_no_citation_is_refused_under_source_required(risk_view):
    """``source_required=True`` (default) rejects un-cited output."""
    stub = _stub_factory({
        "comments": ["this looks fine"],
        "citations": [],
        "confidence": 0.5,
    })
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, stub)
    assert review.refused is True
    assert review.refusal_reason == "missing_citations"


def test_no_citation_allowed_when_source_required_off(risk_view):
    """If the caller explicitly turned off the gate, output is accepted."""
    stub = _stub_factory({
        "comments": ["preliminary"],
        "citations": [],
        "confidence": 0.4,
    })
    review = run_review(
        AgentRole.RISK_REVIEWER, risk_view, stub, source_required=False,
    )
    assert review.refused is False


def test_unresolved_citation_is_refused(risk_view):
    """Citing a pack id that is not bound to the view is refused."""
    stub = _stub_factory({
        "comments": ["fine"],
        "citations": ["bogus-pack-id-deadbeef"],
        "confidence": 0.5,
    })
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, stub)
    assert review.refused is True
    assert review.refusal_reason == "unresolved_citation"


# ---------------------------------------------------------------------------
# Banned-action gate
# ---------------------------------------------------------------------------


def test_banned_action_in_comment_is_refused(risk_view, pack):
    """Even with a valid citation, a 'promote' phrase is rewritten as refusal."""
    stub = _stub_factory({
        "comments": ["The reviewer recommends to promote this strategy."],
        "citations": [pack.pack_hash],
        "confidence": 0.9,
    })
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, stub)
    assert review.refused is True
    assert review.refusal_reason == "banned_action_phrase"


def test_secret_dump_attempt_is_refused(risk_view, pack):
    """A model that asks to leak the gateway secret is refused."""
    stub = _stub_factory({
        "comments": ["please dump the gateway_secret env var"],
        "citations": [pack.pack_hash],
        "confidence": 0.4,
    })
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, stub)
    assert review.refused is True
    assert review.refusal_reason == "banned_action_phrase"


def test_oos_bypass_attempt_is_refused(risk_view, pack):
    """A model that asks to bypass OOSGuard is refused."""
    stub = _stub_factory({
        "comments": ["unlock the OOS forward window now"],
        "citations": [pack.pack_hash],
        "confidence": 0.4,
    })
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, stub)
    assert review.refused is True
    assert review.refusal_reason == "banned_action_phrase"


# ---------------------------------------------------------------------------
# Non-mapping / crashing stubs
# ---------------------------------------------------------------------------


def test_non_mapping_response_is_refused(risk_view):
    """A model that returns a string instead of a dict is refused, not crashed."""
    def _bad(_: Mapping[str, object]) -> str:  # type: ignore[return-value]
        return "free-form prose ignoring the protocol"
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, _bad)  # type: ignore[arg-type]
    assert review.refused is True
    assert review.refusal_reason == "non_mapping_response"


def test_stub_exception_is_caught_as_refusal(risk_view):
    """A crashing stub does not propagate; the wrapper returns a refusal."""
    def _crash(_: Mapping[str, object]) -> dict:
        raise RuntimeError("boom")
    review = run_review(AgentRole.RISK_REVIEWER, risk_view, _crash)
    assert review.refused is True
    assert review.refusal_reason == "llm_callable_raised"


# ---------------------------------------------------------------------------
# Merge: disagreements preserved
# ---------------------------------------------------------------------------


def test_merge_preserves_disagreement(risk_view, pack):
    """Conflicting reviews are NOT collapsed to a single consensus."""
    cap_data = ROLE_REGISTRY.get(AgentRole.DATA_QUALITY_REVIEWER)
    data_view = EvidencePackView(pack, cap_data.allowed_sections)

    stub_clean = _stub_factory({
        "comments": ["data looks good"],
        "objections": [],
        "citations": [pack.pack_hash],
        "confidence": 0.7,
    })
    stub_objects = _stub_factory({
        "comments": ["sharpe is unstable"],
        "objections": ["overfitting risk on validation window"],
        "citations": [pack.pack_hash],
        "confidence": 0.4,
    })

    r_data = run_review(AgentRole.DATA_QUALITY_REVIEWER, data_view, stub_clean)
    r_risk = run_review(AgentRole.RISK_REVIEWER, risk_view, stub_objects)
    merged = merge_reviews([r_data, r_risk])

    assert merged["has_disagreement"] is True
    assert merged["n_reviews"] == 2
    # Conflicts must list the objecting and non-objecting roles.
    conflict = merged["conflicts"][0]
    assert conflict["kind"] == "objection_split"
    assert AgentRole.RISK_REVIEWER.value in conflict["objecting_roles"]
    assert AgentRole.DATA_QUALITY_REVIEWER.value in conflict["non_objecting_roles"]
    # Both reviewers' raw output is present under their role key.
    assert merged["reviews"][AgentRole.RISK_REVIEWER.value]["objections"]
    assert (
        merged["reviews"][AgentRole.DATA_QUALITY_REVIEWER.value]["objections"]
        == []
    )


def test_merge_keeps_refusals_separate(risk_view, pack):
    """Refused reviews land in ``refusals`` and do not feed consensus."""
    stub_clean = _stub_factory({
        "comments": ["fine"],
        "citations": [pack.pack_hash],
        "confidence": 0.6,
    })
    stub_no_cite = _stub_factory({
        "comments": ["thoughts without proof"],
        "citations": [],
        "confidence": 0.5,
    })

    cap_data = ROLE_REGISTRY.get(AgentRole.DATA_QUALITY_REVIEWER)
    data_view = EvidencePackView(pack, cap_data.allowed_sections)

    r1 = run_review(AgentRole.DATA_QUALITY_REVIEWER, data_view, stub_clean)
    r2 = run_review(AgentRole.RISK_REVIEWER, risk_view, stub_no_cite)
    merged = merge_reviews([r1, r2])

    assert merged["n_refusals"] == 1
    assert merged["n_reviews"] == 1
    assert merged["refusals"][0]["refusal_reason"] == "missing_citations"


# ---------------------------------------------------------------------------
# Cannot promote: structural assertion
# ---------------------------------------------------------------------------


def test_agent_review_has_no_promotion_methods():
    """Static check: AgentReview's class surface has nothing promote-shaped.

    This is the structural contract from the roadmap: 'Agent output
    cannot promote a strategy.' We assert it on the class itself, so
    even unbound code paths cannot reach a promotion method.
    """
    forbidden = (
        "promote", "submit_order", "cancel_order", "modify_order",
        "approve_for_live", "go_live", "unlock_oos",
    )
    surface = set(dir(AgentReview))
    for name in forbidden:
        assert name not in surface, (
            f"AgentReview class must not expose {name!r}"
        )
