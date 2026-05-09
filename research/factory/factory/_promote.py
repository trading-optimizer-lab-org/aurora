"""Promote phase: archive helpers + lineage + read queries.

Module-private mixin. Public API stays at
``aurora.research.factory.factory``.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional, TYPE_CHECKING

import pandas as pd

from aurora.research.factory.factory._helpers import (
    _atomic_jsonl_append,
    _read_jsonl,
)
from aurora.research.factory.lineage import LineageGraph
from aurora.research.factory.outcomes import (
    CandidateRun,
    RejectionReason,
    ResearchOutcome,
    ResearchStage,
)
from aurora.research.factory.spec import StrategySpec

if TYPE_CHECKING:
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.research.factory.factory._config import ResearchPipelineConfig
    from aurora.research.factory.factory._helpers import _AuditorProtocol


class _PromoteMixin:
    """Archive + listing + lineage helpers."""

    # Attribute declarations so mypy can resolve attribute access.
    config: "ResearchPipelineConfig"
    policy: "ProtocolPolicy"
    registry: Any
    auditor: Optional["_AuditorProtocol"]
    _backtest_fn: Callable[..., dict]
    _walk_forward_fn: Callable[..., dict]
    _data_loader: Callable[..., pd.Series]
    triage_engine: Any
    _MAX_TIER: str

    if TYPE_CHECKING:
        # Method signatures provided by sibling mixins. Declared here so
        # mypy can resolve cross-mixin attribute access without runtime
        # impact.
        def _close_experiment(
            self,
            experiment_id: Optional[str],
            *,
            success: bool,
            score: Optional[float] = None,
            notes: str = "",
        ) -> None: ...

    # ------------------------------------------------------------------
    # query helpers
    # ------------------------------------------------------------------

    def list_review_queue(self) -> list[CandidateRun]:
        """Read the review queue JSONL into a list of :class:`CandidateRun`."""
        return [CandidateRun.from_dict(d)
                for d in _read_jsonl(self.config.review_queue_path)]

    def list_archived(
        self, since: Optional[pd.Timestamp] = None,
    ) -> list[CandidateRun]:
        """Read the archive JSONL.

        Args:
            since: optional cutoff. When provided, only returns candidates
                whose ``started_at`` is >= ``since``.
        """
        records = _read_jsonl(self.config.archive_path)
        out = [CandidateRun.from_dict(d) for d in records]
        if since is not None:
            since_ts = pd.Timestamp(since)
            out = [c for c in out if c.started_at >= since_ts]
        return out

    def get_lineage(self, spec_id: str) -> list[CandidateRun]:
        """Return all candidates in the lineage chain of ``spec_id``.

        Builds the lineage graph from BOTH the review queue and the
        archive (so a parent that was promoted while a child was
        archived still shows up). Returns the chain root-first followed
        by the spec_id itself.
        """
        graph = LineageGraph()
        graph.build(self.list_review_queue())
        graph.build(self.list_archived())
        return graph.lineage_chain(spec_id)

    # ------------------------------------------------------------------
    # archive helper
    # ------------------------------------------------------------------

    def _archive(
        self,
        *,
        candidate_id: str,
        spec: StrategySpec,
        stage: ResearchStage,
        rejection: RejectionReason,
        detail: str,
        started_at: pd.Timestamp,
        t0: float,
        is_metrics: Optional[dict] = None,
        wf_metrics: Optional[dict] = None,
        oos_dev_metrics: Optional[dict] = None,
        auditor_report_hash: Optional[str] = None,
        experiment_id: Optional[str] = None,
    ) -> ResearchOutcome:
        """Build + persist an archived :class:`CandidateRun`.

        Always writes to the archive JSONL even when the registry write
        fails -- the JSONL archive is the canonical record; the registry
        is best-effort metadata.
        """
        finished = pd.Timestamp.utcnow().tz_localize(None)
        cand = CandidateRun(
            candidate_id=candidate_id,
            spec=spec,
            stage=ResearchStage.ARCHIVED,
            is_metrics=is_metrics,
            wf_metrics=wf_metrics,
            oos_dev_metrics=oos_dev_metrics,
            auditor_report_hash=auditor_report_hash,
            rejection=rejection,
            rejection_detail=detail,
            started_at=started_at,
            finished_at=finished,
            cost_seconds=time.perf_counter() - t0,
        )
        _atomic_jsonl_append(self.config.archive_path, cand.to_dict())
        self._close_experiment(
            experiment_id, success=False, score=None, notes=f"{rejection.value}: {detail}",
        )
        summary = (
            f"ARCHIVED {spec.name} stage={stage.value} "
            f"reason={rejection.value} ({detail})"
        )
        return ResearchOutcome(promising=False, candidate=cand, summary=summary)
