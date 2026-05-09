"""AuditorOrchestrator: runs a set of ``ReviewerAgent``s, aggregates the
result, and exposes a gate primitive for the validation pipeline.

The aggregator is intentionally simple: PASS iff every reviewer's report
has no HARD_FAIL finding. The aggregate score is the mean of the
individual reviewer scores. ``policy_hash`` is taken from the active
:class:`ProtocolPolicy` so the audit is bound to the protocol it was run
under.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Optional

import pandas as pd

from aurora.agents.auditor.base import (
    ReviewContext,
    ReviewFinding,
    ReviewReport,
    ReviewSeverity,
    ReviewerAgent,
)
from aurora.agents.auditor.reviewers import (
    CostReviewer,
    DataLeakReviewer,
    DeploymentReviewer,
    HypothesisReviewer,
    RegimeReviewer,
    RiskReviewer,
)


@dataclass(frozen=True)
class AuditReport:
    """Aggregate of every reviewer's :class:`ReviewReport`.

    ``has_hard_fail`` is True iff *any* reviewer surfaced a HARD_FAIL.
    The auditor gate refuses promotion when this is True.
    """

    reports: List[ReviewReport]
    has_hard_fail: bool
    aggregate_score: float
    policy_hash: str
    timestamp: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.utcnow())

    # ----- helpers ------------------------------------------------------

    def all_findings(self) -> List[ReviewFinding]:
        out: List[ReviewFinding] = []
        for r in self.reports:
            out.extend(r.findings)
        return out

    def hard_fails(self) -> List[ReviewFinding]:
        return [f for f in self.all_findings()
                if f.severity is ReviewSeverity.HARD_FAIL]

    def to_dict(self) -> dict:
        return {
            "reports": [r.to_dict() for r in self.reports],
            "has_hard_fail": bool(self.has_hard_fail),
            "aggregate_score": float(self.aggregate_score),
            "policy_hash": self.policy_hash,
            "timestamp": pd.Timestamp(self.timestamp).isoformat(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    def content_hash(self) -> str:
        """Deterministic SHA-256 of the audit report's canonical JSON."""
        payload = json.dumps(self.to_dict(), sort_keys=True,
                             separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_markdown(self) -> str:
        lines = [
            "# Audit Report",
            "",
            f"- policy_hash: `{self.policy_hash}`",
            f"- has_hard_fail: **{self.has_hard_fail}**",
            f"- aggregate_score: {self.aggregate_score:.3f}",
            f"- generated: {self.timestamp.isoformat()}",
            "",
        ]
        for rep in self.reports:
            lines.append(f"## {rep.reviewer}")
            lines.append("")
            lines.append(f"- score: {rep.score:.3f}")
            lines.append(f"- summary: {rep.summary}")
            if rep.findings:
                lines.append("")
                lines.append("| severity | code | title |")
                lines.append("|---|---|---|")
                for f in rep.findings:
                    lines.append(
                        f"| {f.severity.value} | `{f.code}` | {f.title} |"
                    )
            lines.append("")
        return "\n".join(lines)


@dataclass(frozen=True)
class GateResult:
    """Outcome of an auditor gate decision.

    ``passed`` is False iff any reviewer report carries HARD_FAIL findings.
    The full :class:`AuditReport` is always preserved on the result for
    downstream transparency / dashboards.
    """

    passed: bool
    audit_report: AuditReport
    reason: str

    def to_dict(self) -> dict:
        return {
            "passed": bool(self.passed),
            "reason": self.reason,
            "audit_report": self.audit_report.to_dict(),
        }


class AuditorOrchestrator:
    """Runs a set of reviewers in parallel and aggregates their reports."""

    def __init__(self, reviewers: Iterable[ReviewerAgent]):
        self.reviewers: List[ReviewerAgent] = list(reviewers)
        if not self.reviewers:
            raise ValueError("AuditorOrchestrator requires >=1 reviewer")

    @classmethod
    def default(cls) -> "AuditorOrchestrator":
        """Return an orchestrator with all six default reviewers."""
        return cls([
            HypothesisReviewer(),
            DataLeakReviewer(),
            CostReviewer(),
            RegimeReviewer(),
            RiskReviewer(),
            DeploymentReviewer(),
        ])

    def review(self, context: ReviewContext,
               *, parallel: bool = False) -> AuditReport:
        """Run every reviewer and aggregate the result.

        ``parallel=True`` uses a ``ThreadPoolExecutor``. Reviewers are
        pure functions so this is safe; sequential remains the default
        because the workload is tiny and parallelism muddies stack
        traces in tests.
        """
        if parallel:
            with ThreadPoolExecutor(max_workers=len(self.reviewers)) as ex:
                reports = list(ex.map(lambda r: r.review(context),
                                      self.reviewers))
        else:
            reports = [r.review(context) for r in self.reviewers]

        any_hard = any(rep.has_hard_fail() for rep in reports)
        agg = sum(r.score for r in reports) / max(1, len(reports))
        return AuditReport(
            reports=reports,
            has_hard_fail=any_hard,
            aggregate_score=float(agg),
            policy_hash=context.policy.policy_hash,
        )

    def gate(self, context: ReviewContext,
             *, parallel: bool = False) -> GateResult:
        """Auditor gate: PASS only if no reviewer reports HARD_FAIL."""
        report = self.review(context, parallel=parallel)
        if report.has_hard_fail:
            hard = [
                f"{f.code}({rep.reviewer})"
                for rep in report.reports
                for f in rep.findings
                if f.severity is ReviewSeverity.HARD_FAIL
            ]
            reason = ("auditor_gate FAIL: HARD_FAIL findings = "
                      + ", ".join(hard))
            return GateResult(passed=False, audit_report=report, reason=reason)
        return GateResult(
            passed=True,
            audit_report=report,
            reason=("auditor_gate PASS: no HARD_FAIL across "
                    f"{len(report.reports)} reviewers."),
        )


__all__ = [
    "AuditorOrchestrator",
    "AuditReport",
    "GateResult",
]
