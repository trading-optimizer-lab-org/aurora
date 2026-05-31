"""Aurora auditor: multi-agent reviewer system.

P1.B: 6 specialized reviewer agents (HypothesisReviewer, DataLeakReviewer,
CostReviewer, RegimeReviewer, RiskReviewer, DeploymentReviewer) that emit
deterministic, structured ``ReviewReport``s. The
:class:`AuditorOrchestrator` runs them all and emits an
:class:`AuditReport` plus an optional gate decision. Authority remains
protocol + snapshots + gates -- the LLM (when injected as augmenter) is
severity-capped at MEDIUM and never approves anything single-handedly.
"""
from __future__ import annotations

from aurora.agents.auditor.base import (
    LLM_MAX_SEVERITY,
    LLMAugmenter,
    ReviewContext,
    ReviewFinding,
    ReviewReport,
    ReviewSeverity,
    ReviewerAgent,
    cap_augmenter_findings,
)
from aurora.agents.auditor.orchestrator import (
    AuditReport,
    AuditorOrchestrator,
    GateResult,
)
from aurora.agents.auditor.reviewers import (
    CostReviewer,
    DataLeakReviewer,
    DeploymentReviewer,
    HypothesisReviewer,
    RegimeReviewer,
    RiskReviewer,
)


__all__ = [
    # base
    "ReviewSeverity",
    "ReviewFinding",
    "ReviewReport",
    "ReviewContext",
    "ReviewerAgent",
    "LLMAugmenter",
    "LLM_MAX_SEVERITY",
    "cap_augmenter_findings",
    # reviewers
    "HypothesisReviewer",
    "DataLeakReviewer",
    "CostReviewer",
    "RegimeReviewer",
    "RiskReviewer",
    "DeploymentReviewer",
    # orchestrator
    "AuditorOrchestrator",
    "AuditReport",
    "GateResult",
]
