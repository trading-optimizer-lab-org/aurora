"""LLM augmenter for the auditor pipeline (R8).

The deterministic reviewers are the load-bearing piece of the auditor.
This module adds an *optional* LLM observation pathway. By design:

- The augmenter can only emit findings at severity ``MEDIUM`` or below.
  HIGH / HARD_FAIL are stripped at output time. The cap is also enforced
  one layer up by :func:`agents.auditor.base.cap_augmenter_findings`, so
  even a buggy augmenter cannot escalate.
- The augmenter is offline by default. A :class:`MockLLMProvider`
  produces deterministic output suitable for tests and CI. Real
  providers (Anthropic, OpenAI) are lazily imported and only used when
  explicitly wired in.
- The augmenter never sees private credentials. Provider classes read
  API keys from environment variables; nothing is persisted to disk.
- An augmenter exception never breaks the deterministic review (caught
  upstream in ``ReviewerAgent._augment``).

Wiring example::

    from quantforge.agents.auditor.llm_augmenter import (
        MockLLMProvider, make_augmenter,
    )
    from quantforge.agents.auditor.reviewers import RegimeReviewer

    aug = make_augmenter(MockLLMProvider(), reviewer_name="regime")
    rev = RegimeReviewer(llm_augmenter=aug)

The mock provider returns one ``MEDIUM`` observation per call -- enough
to exercise the augmenter pipeline in tests without network or
credentials.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from quantforge.agents.auditor.base import (
    LLM_MAX_SEVERITY,
    LLMAugmenter,
    ReviewContext,
    ReviewFinding,
    ReviewSeverity,
    cap_augmenter_findings,
)

# --------------------------------------------------------------------------
# Provider protocol
# --------------------------------------------------------------------------


class LLMProvider(Protocol):
    """Minimal interface every LLM provider must implement.

    Implementations may be sync HTTP wrappers or canned responses. The
    augmenter only needs a single ``complete`` call that maps a string
    prompt to a string response. Streaming, tool use, and multi-turn
    chat are intentionally out of scope here -- the augmenter is a
    one-shot text-in, text-out worker.
    """

    name: str

    def complete(self, prompt: str) -> str:  # pragma: no cover - protocol
        ...


# --------------------------------------------------------------------------
# MockLLMProvider -- offline, deterministic
# --------------------------------------------------------------------------


@dataclass
class MockLLMProvider:
    """Deterministic mock provider for tests and CI.

    Returns a fixed JSON payload that the augmenter parser understands.
    The payload encodes a single ``MEDIUM`` observation referencing the
    reviewer name extracted from the prompt header. No network, no
    credentials.
    """

    name: str = "mock-llm-1"

    def complete(self, prompt: str) -> str:
        reviewer = _extract_reviewer_name(prompt) or "unknown"
        payload = {
            "findings": [
                {
                    "severity": "medium",
                    "code": f"LLM_OBSERVATION_{reviewer.upper()}",
                    "title": f"LLM observation from {reviewer}",
                    "detail": (
                        "Mock provider observation. Replace with a real "
                        "LLM provider for production augmentation."
                    ),
                    "evidence": {"provider": self.name, "reviewer": reviewer},
                    "suggested_action": None,
                }
            ]
        }
        return json.dumps(payload)


# --------------------------------------------------------------------------
# AnthropicLLMProvider -- lazy import, env-keyed
# --------------------------------------------------------------------------


@dataclass
class AnthropicLLMProvider:
    """Provider backed by the Anthropic SDK.

    Lazy import: the ``anthropic`` package is only loaded on the first
    ``complete`` call so the auditor module stays importable without
    the optional dependency.
    """

    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 512
    api_key_env: str = "ANTHROPIC_API_KEY"
    name: str = "anthropic"

    def complete(self, prompt: str) -> str:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - import diagnostics
            raise RuntimeError(
                "anthropic SDK is not installed; install with `pip install "
                "quantforge[llm]` or use MockLLMProvider"
            ) from exc

        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"{self.api_key_env} is not set; refusing to call Anthropic API"
            )

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        # The SDK returns a content list; we take the first text block.
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                return block.text  # type: ignore[no-any-return]
        return ""


# --------------------------------------------------------------------------
# Prompt templates per reviewer kind
# --------------------------------------------------------------------------


_PROMPT_HEADER = (
    "You are an LLM augmenter for the QuantForge auditor pipeline.\n"
    "REVIEWER: {reviewer}\n"
    "STRATEGY: {strategy_id}\n"
    "POLICY_HASH: {policy_hash}\n"
    "Your job is to read the deterministic findings and the strategy "
    "context, and emit ADDITIONAL qualitative observations as JSON. You "
    "MUST NOT use severity 'high' or 'hard_fail' -- those are reserved "
    "for the deterministic reviewers. Cap is 'medium'.\n"
)

_PROMPT_BODY = (
    "Existing rule findings (JSON):\n{rule_findings}\n\n"
    "Strategy spec (JSON):\n{spec}\n\n"
    "Backtest summary (JSON):\n{backtest_summary}\n\n"
    "Validation summary (JSON):\n{validation_summary}\n\n"
    "Output a single JSON object with key 'findings'. Each item must "
    "have keys: severity, code, title, detail, evidence (object), "
    "suggested_action (string or null). Return JSON only, no prose."
)


def _build_prompt(reviewer_name: str, context: ReviewContext,
                  rule_findings: list[ReviewFinding]) -> str:
    head = _PROMPT_HEADER.format(
        reviewer=reviewer_name,
        strategy_id=context.strategy_id,
        policy_hash=context.policy.policy_hash,
    )
    body = _PROMPT_BODY.format(
        rule_findings=json.dumps(
            [f.to_dict() for f in rule_findings], sort_keys=True
        ),
        spec=json.dumps(context.strategy_spec, sort_keys=True, default=str),
        backtest_summary=json.dumps(
            _trim_summary(context.backtest_results), sort_keys=True, default=str
        ),
        validation_summary=json.dumps(
            _trim_summary(context.validation_results or {}),
            sort_keys=True, default=str,
        ),
    )
    return head + "\n" + body


def _trim_summary(d: dict[str, Any], max_keys: int = 25) -> dict[str, Any]:
    """Drop large array values from the summary that goes into the prompt.

    Backtest results carry equity/returns arrays that would blow the
    context window. We drop any value whose JSON representation exceeds
    a small length budget, keeping scalar fields for the LLM to reason on.
    """
    out: dict[str, Any] = {}
    for k, v in list(d.items())[:max_keys]:
        try:
            s = json.dumps(v, default=str)
        except (TypeError, ValueError):
            continue
        if len(s) > 400:
            out[k] = f"<elided len={len(s)}>"
        else:
            out[k] = v
    return out


def _extract_reviewer_name(prompt: str) -> str | None:
    """Read the ``REVIEWER:`` line from a prompt produced by ``_build_prompt``."""
    for line in prompt.splitlines():
        if line.startswith("REVIEWER:"):
            return line.split(":", 1)[1].strip() or None
    return None


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------


def _parse_response(raw: str) -> list[ReviewFinding]:
    """Parse an LLM response into structured findings.

    Lenient: a non-JSON response yields an empty finding list rather than
    crashing the augmenter. Any malformed entry is skipped.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    items = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []

    out: list[ReviewFinding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sev_raw = str(item.get("severity", "info")).lower()
        try:
            sev = ReviewSeverity(sev_raw)
        except ValueError:
            sev = ReviewSeverity.INFO
        # Hard cap at the augmenter level too -- defence in depth.
        if sev.rank() > LLM_MAX_SEVERITY.rank():
            sev = LLM_MAX_SEVERITY

        code = str(item.get("code") or "LLM_OBSERVATION")
        title = str(item.get("title") or "LLM observation")
        detail = str(item.get("detail") or "")
        evidence = item.get("evidence") or {}
        if not isinstance(evidence, dict):
            evidence = {"raw": str(evidence)}
        suggested_action = item.get("suggested_action")
        if suggested_action is not None and not isinstance(suggested_action, str):
            suggested_action = str(suggested_action)
        out.append(
            ReviewFinding(
                severity=sev,
                code=code,
                title=title,
                detail=detail,
                evidence=evidence,
                suggested_action=suggested_action,
            )
        )
    return out


# --------------------------------------------------------------------------
# Augmenter factory
# --------------------------------------------------------------------------


def make_augmenter(
    provider: LLMProvider,
    reviewer_name: str,
) -> LLMAugmenter:
    """Return an :class:`LLMAugmenter` callable bound to ``provider``.

    The returned callable has the signature expected by
    :class:`agents.auditor.base.ReviewerAgent` and applies the severity
    cap defensively before returning.
    """

    def _augmenter(
        rule_findings: list[ReviewFinding],
        context: ReviewContext,
    ) -> list[ReviewFinding]:
        prompt = _build_prompt(reviewer_name, context, rule_findings)
        try:
            raw = provider.complete(prompt)
        except Exception:
            # Failures here must not break the deterministic pipeline;
            # ReviewerAgent._augment already guards, but cap inside too.
            return []
        parsed = _parse_response(raw)
        return cap_augmenter_findings(parsed)

    return _augmenter


__all__ = [
    "LLMProvider",
    "MockLLMProvider",
    "AnthropicLLMProvider",
    "make_augmenter",
]
