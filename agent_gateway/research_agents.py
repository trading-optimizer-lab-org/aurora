"""Research-agent layer (Phase 7 / Candidate G).

Defines the explicit agent roles, the abstract :class:`ResearchAgent`
base, and concrete deterministic stubs for each role. These agents are
explanation / challenge actors above the protocol spine. They consume
:class:`EvidencePack` instances and emit :class:`AgentComment` records;
they never approve promotions, never submit orders, never read locked
data and never call an LLM in this layer (deterministic stubs only).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple

from quantforge.agent_gateway.evidence_pack import (
    EvidencePack,
    MissingEvidenceError,
    assert_no_oos_access,
)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class AgentRole(str, Enum):
    """Explicit, allowlisted agent roles for the research-support layer."""

    DATA_QUALITY = "data_quality"
    STRATEGY_SUMMARY = "strategy_summary"
    RISK = "risk"
    EXECUTION_COST = "execution_cost"
    REGIME = "regime"
    REPORT_EXPLAINER = "report_explainer"


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentComment:
    """Single comment emitted by an agent.

    Attributes:
        role: which agent produced the comment.
        claim: short natural-language claim.
        confidence: in [0.0, 1.0].
        cited_evidence: tuple of evidence identifiers (snapshot hash,
            validation report path, etc.). May be empty in the default
            constructor; in source-required mode the caller must invoke
            :func:`make_comment` with ``source_required=True`` to enforce
            non-empty citations.
        disagreement_with: tuple of roles this comment explicitly
            disagrees with. Preserved verbatim by
            :func:`build_explanation_pack`.
    """

    role: AgentRole
    claim: str
    confidence: float
    cited_evidence: Tuple[str, ...] = ()
    disagreement_with: Tuple[AgentRole, ...] = field(default_factory=tuple)


def make_comment(
    *,
    role: AgentRole,
    claim: str,
    confidence: float,
    cited_evidence: Tuple[str, ...] = (),
    disagreement_with: Tuple[AgentRole, ...] = (),
    source_required: bool = False,
) -> AgentComment:
    """Construct an :class:`AgentComment` with optional source enforcement.

    When ``source_required`` is True an empty ``cited_evidence`` raises
    :class:`ValueError` ("Agent output without source fails in
    source-required mode"). The default-constructor path on
    :class:`AgentComment` itself remains unchanged so light-weight tests
    can still build a comment without citations.
    """
    if source_required and not cited_evidence:
        raise ValueError(
            "agent comment requires at least one cited evidence item in "
            "source-required mode"
        )
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0, 1]; got {confidence!r}")
    return AgentComment(
        role=role,
        claim=claim,
        confidence=confidence,
        cited_evidence=cited_evidence,
        disagreement_with=disagreement_with,
    )


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ResearchAgent(ABC):
    """Abstract base for a single research agent.

    Subclasses set the class attribute :attr:`role` and implement
    :meth:`review`. The base ``__init__`` enforces that a role is set so
    every concrete agent is identifiable in the audit trail.
    """

    role: AgentRole

    def __init__(self) -> None:
        cls_role = getattr(type(self), "role", None)
        if not isinstance(cls_role, AgentRole):
            raise TypeError(
                f"{type(self).__name__} must declare an AgentRole class attribute"
            )

    @abstractmethod
    def review(self, evidence: EvidencePack) -> AgentComment:
        """Return a single :class:`AgentComment` based on ``evidence``."""
        raise NotImplementedError


def _guard_evidence(evidence: EvidencePack) -> None:
    """Common pre-checks every concrete agent runs before commenting.

    - Refuse empty packs (no snapshot hash) -> MissingEvidenceError.
    - Refuse packs that reference locked OOS / FORWARD partitions ->
      ForbiddenAccessError (raised by ``assert_no_oos_access``).
    """
    if evidence.snapshot_hash is None and evidence.validation_hash is None:
        raise MissingEvidenceError(
            "evidence pack lacks both snapshot_hash and validation_hash"
        )
    assert_no_oos_access(evidence)


def _evidence_citations(evidence: EvidencePack) -> Tuple[str, ...]:
    """Build a deterministic citation tuple from the pack."""
    cites: list[str] = []
    if evidence.snapshot_hash is not None:
        cites.append(f"snapshot:{evidence.snapshot_hash}")
    if evidence.policy_hash is not None:
        cites.append(f"policy:{evidence.policy_hash}")
    if evidence.validation_hash is not None:
        cites.append(f"validation:{evidence.validation_hash}")
    if evidence.strategy_hash is not None:
        cites.append(f"strategy:{evidence.strategy_hash}")
    if evidence.data_contract_hash is not None:
        cites.append(f"data_contract:{evidence.data_contract_hash}")
    cites.extend(f"audit:{ref}" for ref in evidence.audit_references)
    cites.extend(f"report:{path}" for path in evidence.source_report_paths)
    return tuple(cites)


# ---------------------------------------------------------------------------
# Concrete deterministic stubs
# ---------------------------------------------------------------------------


class DataQualityAgent(ResearchAgent):
    """Comments on data-contract coverage and snapshot freshness."""

    role = AgentRole.DATA_QUALITY

    def review(self, evidence: EvidencePack) -> AgentComment:
        _guard_evidence(evidence)
        if evidence.data_contract_hash is None:
            claim = "data contract hash missing -- coverage cannot be confirmed"
            confidence = 0.2
        else:
            claim = (
                "data contract hash present and snapshot bound to policy; "
                "coverage looks consistent"
            )
            confidence = 0.7
        return AgentComment(
            role=self.role,
            claim=claim,
            confidence=confidence,
            cited_evidence=_evidence_citations(evidence),
        )


class StrategySummaryAgent(ResearchAgent):
    """Summarises the strategy spec referenced in the evidence pack."""

    role = AgentRole.STRATEGY_SUMMARY

    def review(self, evidence: EvidencePack) -> AgentComment:
        _guard_evidence(evidence)
        if evidence.strategy_hash is None:
            claim = "no strategy hash in evidence pack -- cannot summarise"
            confidence = 0.1
        else:
            claim = (
                f"strategy {evidence.strategy_hash[:8]}... reviewed against the "
                "validation report; summary follows the cited evidence only"
            )
            confidence = 0.6
        return AgentComment(
            role=self.role,
            claim=claim,
            confidence=confidence,
            cited_evidence=_evidence_citations(evidence),
        )


class RiskAgent(ResearchAgent):
    """Flags risk concerns drawn strictly from the validation report."""

    role = AgentRole.RISK

    def review(self, evidence: EvidencePack) -> AgentComment:
        _guard_evidence(evidence)
        if evidence.validation_hash is None:
            claim = "validation report missing -- risk assessment unavailable"
            confidence = 0.1
        else:
            claim = (
                "tail-risk metrics drawn from validation report; operator must "
                "review drawdown and exposure caps before promotion"
            )
            confidence = 0.5
        return AgentComment(
            role=self.role,
            claim=claim,
            confidence=confidence,
            cited_evidence=_evidence_citations(evidence),
        )


class ExecutionCostAgent(ResearchAgent):
    """Comments on transaction cost and slippage assumptions."""

    role = AgentRole.EXECUTION_COST

    def review(self, evidence: EvidencePack) -> AgentComment:
        _guard_evidence(evidence)
        claim = (
            "cost model and slippage assumptions inherit the snapshot "
            "policy_hash; live deviation must be re-validated"
        )
        confidence = 0.55
        return AgentComment(
            role=self.role,
            claim=claim,
            confidence=confidence,
            cited_evidence=_evidence_citations(evidence),
        )


class RegimeAgent(ResearchAgent):
    """Comments on regime-classification coverage."""

    role = AgentRole.REGIME

    def review(self, evidence: EvidencePack) -> AgentComment:
        _guard_evidence(evidence)
        claim = (
            "regime coverage assessed only via the cited validation slices; "
            "out-of-regime behaviour is unknown"
        )
        confidence = 0.45
        return AgentComment(
            role=self.role,
            claim=claim,
            confidence=confidence,
            cited_evidence=_evidence_citations(evidence),
        )


class ReportExplainerAgent(ResearchAgent):
    """Translates the evidence pack into operator-facing explanation text."""

    role = AgentRole.REPORT_EXPLAINER

    def review(self, evidence: EvidencePack) -> AgentComment:
        _guard_evidence(evidence)
        claim = (
            "operator-facing explanation pack assembled from cited evidence "
            "only; agents do not approve or submit orders"
        )
        confidence = 0.65
        return AgentComment(
            role=self.role,
            claim=claim,
            confidence=confidence,
            cited_evidence=_evidence_citations(evidence),
        )


# ---------------------------------------------------------------------------
# Convenience: default ordered roster
# ---------------------------------------------------------------------------


def default_agents() -> Tuple[ResearchAgent, ...]:
    """Return one instance of each concrete agent in deterministic order."""
    return (
        DataQualityAgent(),
        StrategySummaryAgent(),
        RiskAgent(),
        ExecutionCostAgent(),
        RegimeAgent(),
        ReportExplainerAgent(),
    )


__all__ = [
    "AgentRole",
    "AgentComment",
    "ResearchAgent",
    "DataQualityAgent",
    "StrategySummaryAgent",
    "RiskAgent",
    "ExecutionCostAgent",
    "RegimeAgent",
    "ReportExplainerAgent",
    "default_agents",
    "make_comment",
]
