"""Auditor base types: ReviewSeverity, ReviewFinding, ReviewReport, ReviewerAgent.

The auditor is a multi-agent reviewer system. Each ``ReviewerAgent`` runs a
deterministic rule-based check against a ``ReviewContext`` and produces a
``ReviewReport``. The LLM (when injected) is an optional augmenter -- it can
add extra LOW/INFO findings but cannot raise severity. Authority remains
protocol + snapshots + gates: a HARD_FAIL finding from any reviewer blocks
strategy promotion via the auditor gate, but the LLM cannot single-handedly
approve anything.
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from quantforge.core.protocol_policy import ProtocolPolicy


class ReviewSeverity(str, Enum):
    """Severity of a single ``ReviewFinding``.

    ``HARD_FAIL`` is the blocking level: any HARD_FAIL finding causes the
    auditor gate to refuse promotion. The LLM-augmenter pathway is capped
    at ``MEDIUM`` -- the LLM cannot raise severity to HIGH or HARD_FAIL,
    that is the rule engine's exclusive responsibility.
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    HARD_FAIL = "hard_fail"

    @classmethod
    def order(cls) -> Dict["ReviewSeverity", int]:
        """Numeric ordering for severity comparison."""
        return {
            cls.INFO: 0,
            cls.LOW: 1,
            cls.MEDIUM: 2,
            cls.HIGH: 3,
            cls.HARD_FAIL: 4,
        }

    def rank(self) -> int:
        return self.order()[self]


# Maximum severity that an LLM augmenter is allowed to emit.
# HIGH and HARD_FAIL are reserved for the deterministic rule engine.
LLM_MAX_SEVERITY: ReviewSeverity = ReviewSeverity.MEDIUM


@dataclass(frozen=True)
class ReviewFinding:
    """A single immutable finding from a reviewer.

    ``code`` is a stable identifier (e.g. ``"DATA_LEAK_LOOKAHEAD_DETECTED"``)
    that downstream consumers can pattern-match without parsing free text.
    """

    severity: ReviewSeverity
    code: str
    title: str
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggested_action: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Severity is an Enum -- emit the value not the repr.
        d["severity"] = self.severity.value
        return d


@dataclass(frozen=True)
class ReviewReport:
    """One reviewer's structured report on a strategy.

    ``score`` is a heuristic 0..1 number for ranking / aggregation; it is
    informational only and does NOT decide promotion. ``policy_hash``
    binds the review to a specific :class:`ProtocolPolicy` version so a
    review is invalidated when the protocol changes.
    """

    reviewer: str
    target_strategy_id: str
    target_run_id: Optional[str]
    findings: List[ReviewFinding]
    summary: str
    score: float
    timestamp: pd.Timestamp
    policy_hash: str

    def has_hard_fail(self) -> bool:
        return any(f.severity is ReviewSeverity.HARD_FAIL for f in self.findings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "target_strategy_id": self.target_strategy_id,
            "target_run_id": self.target_run_id,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "score": float(self.score),
            "timestamp": pd.Timestamp(self.timestamp).isoformat(),
            "policy_hash": self.policy_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    def content_hash(self) -> str:
        """Deterministic SHA-256 of the report's canonical JSON."""
        payload = json.dumps(self.to_dict(), sort_keys=True,
                             separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ReviewContext:
    """Bundle of inputs every reviewer receives.

    ``strategy_spec`` is the high-level strategy description (hypothesis,
    expected_edge, regime_dependence, ...). ``backtest_results`` carries
    the numeric output of a backtest (equity, returns, trades, costs,
    by-regime breakdown). ``validation_results`` is optional but, when
    present, lets reviewers compare backtest against gate output.

    The reviewer code MUST NOT mutate these fields. ``extras`` is a
    free-form dict for future extensions (e.g. capacity estimates,
    operational fingerprints).
    """

    strategy_id: str
    strategy_spec: Dict[str, Any]
    backtest_results: Dict[str, Any]
    validation_results: Optional[Dict[str, Any]]
    snapshot_id: Optional[str]
    policy: ProtocolPolicy
    extras: Dict[str, Any] = field(default_factory=dict)


# Type alias for an LLM augmenter. Receives the rule-based findings + the
# raw context, and returns *additional* findings (capped at MEDIUM).
LLMAugmenter = Callable[
    [List[ReviewFinding], ReviewContext], List[ReviewFinding]
]


def cap_augmenter_findings(findings: List[ReviewFinding]) -> List[ReviewFinding]:
    """Drop any augmenter-emitted finding above ``LLM_MAX_SEVERITY``.

    The LLM augmenter pathway is non-binding: HIGH / HARD_FAIL are
    reserved for the deterministic rule engine. Any finding above the
    cap is silently filtered out. Returning a NEW list keeps the
    immutability contract.
    """
    cap = LLM_MAX_SEVERITY.rank()
    return [f for f in findings if f.severity.rank() <= cap]


class ReviewerAgent(ABC):
    """Base class for a single reviewer agent.

    Subclasses implement :meth:`review` as a *pure function* of the
    ``ReviewContext`` (no I/O, no random, no global state). The optional
    ``llm_augmenter`` is consulted AFTER the rule findings are computed
    and is severity-capped via :func:`cap_augmenter_findings`.
    """

    name: str

    def __init__(self, llm_augmenter: Optional[LLMAugmenter] = None):
        self.llm_augmenter = llm_augmenter

    @abstractmethod
    def review(self, context: ReviewContext) -> ReviewReport:
        ...

    # ----- helpers ------------------------------------------------------

    def _augment(self, findings: List[ReviewFinding],
                 context: ReviewContext) -> List[ReviewFinding]:
        """Run the LLM augmenter if provided, then apply the severity cap."""
        if self.llm_augmenter is None:
            return list(findings)
        try:
            extra = list(self.llm_augmenter(list(findings), context))
        except Exception:
            # Augmenters are best-effort; an LLM failure must not break
            # the deterministic review pipeline.
            return list(findings)
        capped = cap_augmenter_findings(extra)
        return list(findings) + list(capped)

    @staticmethod
    def _score_from_findings(findings: List[ReviewFinding]) -> float:
        """Heuristic 0..1 score: 1.0 if no findings, decays with severity.

        Each finding deducts a fraction of the score proportional to its
        severity rank. HARD_FAIL clamps the score to 0.
        """
        if any(f.severity is ReviewSeverity.HARD_FAIL for f in findings):
            return 0.0
        if not findings:
            return 1.0
        # weights chosen so a HIGH-only review still produces a non-trivial score.
        weights = {
            ReviewSeverity.INFO: 0.01,
            ReviewSeverity.LOW: 0.05,
            ReviewSeverity.MEDIUM: 0.15,
            ReviewSeverity.HIGH: 0.30,
        }
        deduction = sum(weights.get(f.severity, 0.0) for f in findings)
        return max(0.0, 1.0 - deduction)


__all__ = [
    "ReviewSeverity",
    "ReviewFinding",
    "ReviewReport",
    "ReviewContext",
    "ReviewerAgent",
    "LLMAugmenter",
    "LLM_MAX_SEVERITY",
    "cap_augmenter_findings",
]
