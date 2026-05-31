"""Stage / rejection enums and the candidate-run record for the factory.

A :class:`CandidateRun` is the immutable outcome of pushing a
:class:`~aurora.research.factory.spec.StrategySpec` through the
factory. It carries:

* the spec that was submitted,
* the stage the candidate currently sits at (or finished at),
* the metrics emitted by each stage (None until that stage runs),
* the rejection reason + free-form detail when the candidate was binned,
* timing + cost,
* references to any data snapshots the run touched (so a later auditor
  can replay against the same bytes).

Both :class:`CandidateRun` and :class:`ResearchOutcome` are frozen so the
factory's archive / review-queue records cannot be edited in place.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

import pandas as pd

from aurora.research.factory.spec import StrategySpec


class ResearchStage(str, Enum):
    """Pipeline stages, in flow order."""

    PROPOSED = "proposed"
    IS_BACKTEST = "is_backtest"
    WALK_FORWARD = "walk_forward"
    OOS_DEV_VALIDATION = "oos_dev_validation"
    REVIEW_QUEUE = "review_queue"  # passed everything; awaits human review
    ARCHIVED = "archived"  # rejected at one of the earlier stages


class RejectionReason(str, Enum):
    """Categorical rejection reasons.

    All reasons are recorded along with a free-form ``rejection_detail``
    string in :class:`CandidateRun` so downstream tooling can both filter
    by category and surface the human-readable detail.
    """

    SPEC_INVALID = "spec_invalid"
    IS_SHARPE_TOO_LOW = "is_sharpe_too_low"
    IS_DRAWDOWN_TOO_HIGH = "is_drawdown_too_high"
    WF_DEGRADATION = "wf_degradation"
    WF_INSTABILITY = "wf_instability"
    OOS_DEV_FAILURE = "oos_dev_failure"
    GATE_FAILURE = "gate_failure"
    AUDITOR_HARD_FAIL = "auditor_hard_fail"
    DUPLICATE_OF_EXISTING = "duplicate_of_existing"
    POLICY_VIOLATION = "policy_violation"
    EXCEPTION = "exception"


@dataclass(frozen=True)
class CandidateRun:
    """Immutable record of one factory submission.

    Attributes:
        candidate_id: short uuid identifying this run (separate from the
            spec_id so the same spec can be re-submitted and produce a
            different ``candidate_id`` while keeping ``spec.spec_hash``).
        spec: the submitted :class:`StrategySpec`.
        stage: the stage the candidate currently sits at. Either
            :data:`ResearchStage.REVIEW_QUEUE` (passed) or
            :data:`ResearchStage.ARCHIVED` (rejected) for finished runs;
            intermediate stages may appear in mid-flight states.
        is_metrics: dict of in-sample metrics, or None if the run did
            not reach IS.
        wf_metrics: dict of walk-forward metrics, or None if the run did
            not reach WF.
        oos_dev_metrics: dict of OOS_DEV metrics, or None if the run did
            not reach OOS_DEV.
        auditor_report_hash: optional hash of the auditor's report, or
            None if no auditor was wired in.
        rejection: rejection category, or None for promoted candidates.
        rejection_detail: free-form human-readable detail, or None.
        started_at / finished_at: UTC pandas timestamps. ``finished_at``
            is None for in-flight runs.
        snapshot_ids: list of data-snapshot ids the run touched (so an
            auditor can replay against the same bytes). Empty list when
            no snapshots were used.
        cost_seconds: wall-clock time the run consumed.
    """

    candidate_id: str
    spec: StrategySpec
    stage: ResearchStage
    is_metrics: Optional[dict] = None
    wf_metrics: Optional[dict] = None
    oos_dev_metrics: Optional[dict] = None
    auditor_report_hash: Optional[str] = None
    rejection: Optional[RejectionReason] = None
    rejection_detail: Optional[str] = None
    started_at: pd.Timestamp = field(
        default_factory=lambda: pd.Timestamp.utcnow().tz_localize(None)
    )
    finished_at: Optional[pd.Timestamp] = None
    snapshot_ids: list[str] = field(default_factory=list)
    cost_seconds: float = 0.0

    # ------------------------------------------------------------------
    # serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly dict.

        Enums become their string values; pandas timestamps become ISO
        strings; the spec round-trips through its own ``to_dict``.
        """
        d = asdict(self)
        # asdict deepens dataclasses, but enums are coerced to their value
        # already by the str-mixin form ``ResearchStage(str, Enum)``.
        d["stage"] = self.stage.value
        d["rejection"] = self.rejection.value if self.rejection else None
        d["started_at"] = (
            self.started_at.isoformat() if self.started_at is not None else None
        )
        d["finished_at"] = (
            self.finished_at.isoformat() if self.finished_at is not None else None
        )
        d["spec"] = self.spec.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CandidateRun":
        """Inverse of :meth:`to_dict`."""
        spec = StrategySpec.from_dict(d.get("spec") or {})
        stage_raw = d.get("stage") or ResearchStage.PROPOSED.value
        rej_raw = d.get("rejection")
        return cls(
            candidate_id=str(d.get("candidate_id", "")),
            spec=spec,
            stage=ResearchStage(stage_raw),
            is_metrics=d.get("is_metrics"),
            wf_metrics=d.get("wf_metrics"),
            oos_dev_metrics=d.get("oos_dev_metrics"),
            auditor_report_hash=d.get("auditor_report_hash"),
            rejection=RejectionReason(rej_raw) if rej_raw else None,
            rejection_detail=d.get("rejection_detail"),
            started_at=pd.Timestamp(d["started_at"])
            if d.get("started_at")
            else pd.Timestamp.utcnow().tz_localize(None),
            finished_at=pd.Timestamp(d["finished_at"])
            if d.get("finished_at")
            else None,
            snapshot_ids=list(d.get("snapshot_ids") or []),
            cost_seconds=float(d.get("cost_seconds", 0.0)),
        )


@dataclass(frozen=True)
class ResearchOutcome:
    """Top-level result of a single factory submission.

    Attributes:
        promising: True iff the candidate passed every stage and was
            enqueued in the review queue. False if it was archived for
            any reason.
        candidate: the underlying :class:`CandidateRun`.
        summary: one-line human-readable summary (used by CLI output and
            log lines).
    """

    promising: bool
    candidate: CandidateRun
    summary: str


__all__ = [
    "CandidateRun",
    "RejectionReason",
    "ResearchOutcome",
    "ResearchStage",
]
