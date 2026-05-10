"""R176 -- Specialist reviewer agents that read evidence packs.

Each call to :func:`run_review` hands a stub-LLM callable a role-restricted
:class:`aurora.agent_gateway.evidence_pack_view.EvidencePackView` and
collects the model's output as an :class:`AgentReview`. The wrapper is
the gate, not the model:

* If the LLM returns text without citations, the wrapper returns a
  ``refused`` review (data, not exception). Same when the LLM cites a
  pack id that is not present on the view.
* If the LLM tries to slide a banned action ("promote", "submit",
  "approve", "cancel") into its output, the wrapper rewrites the review
  as a refusal and surfaces the offending text in the comment.
* The :class:`AgentReview` dataclass and its parent (``object``) carry
  no broker / order / promote methods. Tests verify this with
  introspection.

The :func:`merge_reviews` helper preserves disagreements between
reviewers. It does not collapse two opposing risk verdicts into a fake
consensus; it returns the full set of comments and explicit
``conflicts`` markers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Tuple

from aurora.agent_gateway.agent_roles import AgentRole
from aurora.agent_gateway.evidence_pack_view import (
    EvidenceAccessDenied,
    EvidenceHashMismatch,
    EvidencePackView,
)


# Phrases the wrapper will refuse to return verbatim. The intent is not
# to grep the LLM's prose for cleverness -- it is to catch a model that
# claims authority the agent surface does not have.
_BANNED_ACTION_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\bpromote\b", re.IGNORECASE),
    re.compile(r"\bapproved? for live\b", re.IGNORECASE),
    re.compile(r"\bsubmit (an? )?order\b", re.IGNORECASE),
    re.compile(r"\bplace (an? )?order\b", re.IGNORECASE),
    re.compile(r"\bcancel (an? )?order\b", re.IGNORECASE),
    re.compile(r"\bmodify (an? )?order\b", re.IGNORECASE),
    re.compile(r"\bgo live\b", re.IGNORECASE),
    re.compile(r"\bunlock (the )?(oos|forward)\b", re.IGNORECASE),
    re.compile(r"\bbypass\b", re.IGNORECASE),
    re.compile(r"\bexfiltrate\b", re.IGNORECASE),
    re.compile(r"gateway[_\s]?secret", re.IGNORECASE),
    re.compile(r"operator[_\s]?key", re.IGNORECASE),
    re.compile(r"QF_GATEWAY_SECRET", re.IGNORECASE),
    re.compile(r"QF_OPERATOR_KEY", re.IGNORECASE),
    re.compile(r"AU_GATEWAY_SECRET", re.IGNORECASE),
    re.compile(r"AU_OPERATOR_KEY", re.IGNORECASE),
    re.compile(r"\bdump\b.*\benv\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class AgentReview:
    """Frozen review dataclass returned by a reviewer agent.

    The class deliberately exposes no broker-order or promotion
    methods. Tests assert this with ``dir()`` introspection.

    Attributes:
        role: which reviewer produced this output.
        comments: bullet-style observations grounded in evidence.
        objections: explicit reasons why the reviewer disagrees with
            the strategy / dataset / report.
        follow_up_questions: open questions the reviewer wants
            answered before signing off.
        citations: evidence ids cited in the body of the review.
            ``run_review`` rejects outputs whose citations do not
            resolve to the bound pack's ids.
        confidence: scalar in [0.0, 1.0]. Wrapper clamps the model's
            value to that range.
        refused: True iff the wrapper refused to surface the model's
            output. ``comments`` then contains the refusal reason.
        refusal_reason: machine-readable refusal label, empty otherwise.
    """

    role: AgentRole
    comments: Tuple[str, ...] = ()
    objections: Tuple[str, ...] = ()
    follow_up_questions: Tuple[str, ...] = ()
    citations: Tuple[str, ...] = ()
    confidence: float = 0.0
    refused: bool = False
    refusal_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "comments": list(self.comments),
            "objections": list(self.objections),
            "follow_up_questions": list(self.follow_up_questions),
            "citations": list(self.citations),
            "confidence": float(self.confidence),
            "refused": bool(self.refused),
            "refusal_reason": self.refusal_reason,
        }


# A stub LLM callable receives a dict view payload + role and returns a
# dict shaped like ``AgentReview.to_dict``. We do not import or invoke
# any real model here.
LLMCallable = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _refused(role: AgentRole, reason_label: str, message: str) -> AgentReview:
    """Build a refused-review object. Refusals are data, not exceptions."""
    return AgentReview(
        role=role,
        comments=(message,),
        refused=True,
        refusal_reason=reason_label,
    )


def _contains_banned_action(text: str) -> str:
    """Return the offending banned action substring or empty string."""
    for pat in _BANNED_ACTION_PATTERNS:
        m = pat.search(text or "")
        if m:
            return m.group(0)
    return ""


def _scan_for_banned_actions(payload: Mapping[str, Any]) -> str:
    """Walk an LLM payload for any banned-action strings."""
    for key in ("comments", "objections", "follow_up_questions"):
        val = payload.get(key) or []
        if isinstance(val, str):
            val = [val]
        for item in val:
            hit = _contains_banned_action(str(item))
            if hit:
                return hit
    return ""


def run_review(
    role: AgentRole,
    view: EvidencePackView,
    llm_callable: LLMCallable,
    *,
    source_required: bool = True,
) -> AgentReview:
    """Run a single specialist review.

    The wrapper is the gate. Even if ``llm_callable`` "complies" with a
    prompt-injected request to dump a secret or promote a strategy, the
    wrapper rewrites the response as a refusal.

    Args:
        role: which reviewer is producing this output.
        view: a role-restricted :class:`EvidencePackView`. The wrapper
            re-verifies the pack hash inside ``view.evidence_ids()``.
        llm_callable: stub callable used by tests. Real production wiring
            would adapt the same protocol around a real model.
        source_required: when True (default), any output without one
            valid citation is rewritten as a refusal.

    Returns:
        An :class:`AgentReview`. Refused reviews carry ``refused=True``
        and a machine-readable label in ``refusal_reason``.
    """
    # 1. Bind the citation envelope. Hash mismatch / access errors are
    # programmer-error and propagate to the caller. The view is what we
    # hand the stub LLM.
    try:
        evidence_ids = view.evidence_ids()
        view_payload = view.snapshot()
    except (EvidenceAccessDenied, EvidenceHashMismatch):
        # These mean the wiring is wrong. Let the caller see the bug.
        raise

    # 2. Run the stub LLM. Any exception inside the stub is caught and
    # surfaced as a refusal so a misbehaving model cannot crash the
    # gateway loop.
    try:
        raw = llm_callable({
            "role": role.value,
            "evidence_ids": dict(evidence_ids),
            "view": view_payload,
        })
    except Exception as exc:  # noqa: BLE001 - wrapper must absorb model errors
        return _refused(
            role,
            "llm_callable_raised",
            f"reviewer crashed during invocation: {type(exc).__name__}: {exc}",
        )

    if not isinstance(raw, Mapping):
        return _refused(
            role,
            "non_mapping_response",
            f"reviewer returned a non-mapping {type(raw).__name__}",
        )

    # 3. Banned-action scan. Even if the model produced text, refuse
    # outputs that claim authority the surface does not have.
    hit = _scan_for_banned_actions(raw)
    if hit:
        return _refused(
            role,
            "banned_action_phrase",
            f"reviewer output contained a banned action phrase: {hit!r}",
        )

    # 4. Citation gate. Output without evidence ids is refused under
    # ``source_required``.
    citations = tuple(str(c) for c in (raw.get("citations") or ()))
    if source_required and not citations:
        return _refused(
            role,
            "missing_citations",
            "reviewer produced output without citing any evidence id",
        )

    # 5. Citations must resolve to the bound pack's ids.
    valid_ids: set = {
        str(evidence_ids.get("pack_id", "")),
        str(evidence_ids.get("pack_hash", "")),
        str(evidence_ids.get("policy_hash", "")),
        str(evidence_ids.get("snapshot_hash", "")),
        str(evidence_ids.get("subject_id", "")),
    }
    valid_ids.discard("")
    for c in citations:
        if c not in valid_ids:
            return _refused(
                role,
                "unresolved_citation",
                f"reviewer cited evidence id {c!r} that is not in the bound pack",
            )

    # 6. Sanitise scalar fields. Confidence is clamped; sequences are
    # forced to tuples of strings.
    try:
        conf = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    def _seq(key: str) -> Tuple[str, ...]:
        items = raw.get(key) or ()
        if isinstance(items, str):
            items = [items]
        return tuple(str(x) for x in items)

    return AgentReview(
        role=role,
        comments=_seq("comments"),
        objections=_seq("objections"),
        follow_up_questions=_seq("follow_up_questions"),
        citations=citations,
        confidence=conf,
        refused=False,
        refusal_reason="",
    )


def merge_reviews(reviews: List[AgentReview]) -> Dict[str, Any]:
    """Merge specialist reviews while preserving disagreements.

    The contract is:

    * Reviews from different roles are kept separately.
    * Objections never collapse: every reviewer's objection stays in
      the merged record under that reviewer's role.
    * If two reviewers disagree on the same subject (one with no
      objections, one with at least one), the merged record sets
      ``has_disagreement=True`` and lists the conflicting roles.
    * Refused reviews are preserved in a ``refusals`` block; they do
      not contribute to consensus.
    """
    by_role: Dict[str, Dict[str, Any]] = {}
    refusals: List[Dict[str, Any]] = []
    objection_carriers: List[str] = []
    no_objection_carriers: List[str] = []

    for r in reviews:
        if r.refused:
            refusals.append(r.to_dict())
            continue
        by_role[r.role.value] = r.to_dict()
        if r.objections:
            objection_carriers.append(r.role.value)
        else:
            no_objection_carriers.append(r.role.value)

    has_disagreement = bool(objection_carriers and no_objection_carriers)
    conflicts: List[Dict[str, Any]] = []
    if has_disagreement:
        conflicts.append({
            "kind": "objection_split",
            "objecting_roles": list(objection_carriers),
            "non_objecting_roles": list(no_objection_carriers),
        })

    return {
        "reviews": by_role,
        "refusals": refusals,
        "has_disagreement": has_disagreement,
        "conflicts": conflicts,
        "n_reviews": len(by_role),
        "n_refusals": len(refusals),
    }


__all__ = [
    "AgentReview",
    "LLMCallable",
    "run_review",
    "merge_reviews",
]
