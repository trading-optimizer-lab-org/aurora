"""Operator-facing explanation pack (Phase 7 / Candidate G).

Aggregates :class:`AgentComment` records into a single immutable bundle
without collapsing disagreement. The pack carries a fixed
``non_authority_warning`` so any consumer (CLI, dashboard, report)
shows operators that the agents do not approve promotions or submit
orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Tuple

from quantforge.agent_gateway.research_agents import AgentComment, AgentRole


_DEFAULT_NON_AUTHORITY_WARNING = (
    "Agents do not approve promotions or submit orders. Operator decision "
    "required."
)


@dataclass(frozen=True)
class ExplanationPack:
    """Operator-facing explanation pack.

    Attributes:
        thesis: short top-level thesis derived from the comments.
        evidence: tuple of cited evidence identifiers in stable order.
        objections: agent claims with low confidence (<0.5) preserved as
            objections rather than dropped.
        risks: explicit risk-flagged claims from the RISK agent.
        missing_data: notes from agents that flagged missing evidence.
        required_followup: list of follow-up actions the operator must
            take (e.g. re-run validation, refresh data contract).
        disagreements: list of (role_a, role_b, summary) triples; never
            collapsed into a single answer.
        non_authority_warning: fixed string reminding operators that
            agents do not have authority to promote or trade.
    """

    thesis: str
    evidence: Tuple[str, ...]
    objections: Tuple[str, ...]
    risks: Tuple[str, ...]
    missing_data: Tuple[str, ...]
    required_followup: Tuple[str, ...]
    disagreements: List[Tuple[AgentRole, AgentRole, str]] = field(default_factory=list)
    non_authority_warning: str = _DEFAULT_NON_AUTHORITY_WARNING


def _dedup_preserve_order(items: Iterable[str]) -> Tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def build_explanation_pack(comments: List[AgentComment]) -> ExplanationPack:
    """Aggregate ``comments`` into an :class:`ExplanationPack`.

    Disagreements are preserved verbatim: every entry in any comment's
    :attr:`AgentComment.disagreement_with` becomes a
    ``(self.role, target_role, claim)`` triple in the resulting pack.
    Multiple disagreements from a single comment all survive.
    """
    if not comments:
        return ExplanationPack(
            thesis="No agent commentary supplied.",
            evidence=(),
            objections=(),
            risks=(),
            missing_data=("no agent comments were provided",),
            required_followup=("re-run the research-agent layer with a populated evidence pack",),
            disagreements=[],
        )

    evidence: list[str] = []
    objections: list[str] = []
    risks: list[str] = []
    missing_data: list[str] = []
    followup: list[str] = []
    disagreements: List[Tuple[AgentRole, AgentRole, str]] = []

    for comment in comments:
        evidence.extend(comment.cited_evidence)
        if comment.confidence < 0.5:
            objections.append(f"[{comment.role.value}] {comment.claim}")
        if comment.role is AgentRole.RISK:
            risks.append(comment.claim)
        if "missing" in comment.claim.lower() or not comment.cited_evidence:
            missing_data.append(f"[{comment.role.value}] {comment.claim}")
        if comment.role is AgentRole.REPORT_EXPLAINER:
            followup.append(
                "operator review required before any promotion or live action"
            )
        for other_role in comment.disagreement_with:
            disagreements.append((comment.role, other_role, comment.claim))

    # Thesis: pick the report explainer's claim if we have one, else the
    # highest-confidence comment.
    explainer = next(
        (c for c in comments if c.role is AgentRole.REPORT_EXPLAINER),
        None,
    )
    if explainer is not None:
        thesis = explainer.claim
    else:
        top = max(comments, key=lambda c: c.confidence)
        thesis = top.claim

    if not followup:
        followup.append("operator review required before any promotion or live action")

    return ExplanationPack(
        thesis=thesis,
        evidence=_dedup_preserve_order(evidence),
        objections=tuple(objections),
        risks=tuple(risks),
        missing_data=tuple(missing_data),
        required_followup=_dedup_preserve_order(followup),
        disagreements=disagreements,
    )


__all__ = [
    "ExplanationPack",
    "build_explanation_pack",
]
