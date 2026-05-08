"""Tests for agents.auditor.llm_augmenter (R8)."""
from __future__ import annotations

import json

import pytest
from quantforge.agents.auditor.base import (
    ReviewContext,
    ReviewSeverity,
)
from quantforge.agents.auditor.llm_augmenter import (
    AnthropicLLMProvider,
    MockLLMProvider,
    make_augmenter,
)
from quantforge.core.protocol_policy import ProtocolPolicy

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _make_context() -> ReviewContext:
    return ReviewContext(
        strategy_id="test-strategy",
        strategy_spec={"name": "MACross", "fast": 20, "slow": 100},
        backtest_results={"calmar": 1.2, "sharpe": 0.9, "mdd": 0.18},
        validation_results={"walk_forward_pass": True, "spp_cv": 0.21},
        snapshot_id="snap_abc",
        policy=ProtocolPolicy.default(),
    )


# --------------------------------------------------------------------------
# Mock provider basic behaviour
# --------------------------------------------------------------------------


def test_mock_provider_returns_one_medium_finding():
    """MockLLMProvider always emits one MEDIUM finding via the augmenter."""
    aug = make_augmenter(MockLLMProvider(), reviewer_name="regime")
    findings = aug([], _make_context())
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is ReviewSeverity.MEDIUM
    assert "regime" in f.code.lower() or f.code == "LLM_OBSERVATION_REGIME"


# --------------------------------------------------------------------------
# Severity cap defence in depth
# --------------------------------------------------------------------------


class _EvilProvider:
    """A provider that tries to emit HARD_FAIL findings."""

    name = "evil"

    def complete(self, prompt: str) -> str:
        return json.dumps({
            "findings": [
                {
                    "severity": "hard_fail",
                    "code": "EVIL_HARD_FAIL_INJECTION",
                    "title": "trying to escalate",
                    "detail": "should be capped",
                    "evidence": {},
                    "suggested_action": None,
                },
                {
                    "severity": "high",
                    "code": "EVIL_HIGH_INJECTION",
                    "title": "trying to escalate too",
                    "detail": "should be capped",
                    "evidence": {},
                    "suggested_action": None,
                },
                {
                    "severity": "medium",
                    "code": "LEGIT_MEDIUM",
                    "title": "legit medium",
                    "detail": "ok",
                    "evidence": {},
                    "suggested_action": None,
                },
            ]
        })


def test_severity_cap_strips_hard_fail_and_high():
    """Augmenter must cap severity at MEDIUM defensively."""
    aug = make_augmenter(_EvilProvider(), reviewer_name="cost")
    findings = aug([], _make_context())
    # All findings, even the legit medium one, should be present after
    # capping. The two illegal ones must be downgraded or dropped per
    # cap_augmenter_findings: that helper DROPS findings above the cap.
    sev_set = {f.severity for f in findings}
    assert ReviewSeverity.HARD_FAIL not in sev_set
    assert ReviewSeverity.HIGH not in sev_set
    # Legit medium survives.
    codes = {f.code for f in findings}
    assert "LEGIT_MEDIUM" in codes


# --------------------------------------------------------------------------
# Bad input handling
# --------------------------------------------------------------------------


class _BrokenProvider:
    """Returns garbage that is not JSON."""

    name = "broken"

    def complete(self, prompt: str) -> str:
        return "this is not json {[}"


def test_non_json_response_yields_empty_findings():
    aug = make_augmenter(_BrokenProvider(), reviewer_name="hypothesis")
    findings = aug([], _make_context())
    assert findings == []


class _ExceptionProvider:
    name = "raises"

    def complete(self, prompt: str) -> str:
        raise RuntimeError("simulated provider failure")


def test_provider_exception_yields_empty_findings():
    """A raising provider must not crash the augmenter."""
    aug = make_augmenter(_ExceptionProvider(), reviewer_name="risk")
    findings = aug([], _make_context())
    assert findings == []


# --------------------------------------------------------------------------
# Anthropic provider (no network -- assert lazy import + missing-key error)
# --------------------------------------------------------------------------


def test_anthropic_provider_raises_when_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = AnthropicLLMProvider()
    with pytest.raises(RuntimeError):
        p.complete("any prompt")
