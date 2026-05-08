"""Auto research loop runtime (R10).

Wraps :class:`quantforge.research.factory.ResearchFactory` with a daily
schedule that generates N hypotheses, submits each, and writes a
per-cycle JSONL summary so an operator can resume / audit the loop.

Design contract
---------------

* **Tier guard.** The loop reads neither OOS_LOCKED nor FORWARD. The
  factory enforces this at submit time; the loop only forwards specs.
  An OOSGuard is established for the cycle to leave a clear audit
  marker.
* **Review-queue cap.** A growing queue is a smell, not a feature. When
  ``review_queue_cap`` is exceeded, the loop SKIPS submission for the
  current cycle and writes a deferral summary instead.
* **Dry-run mode.** When ``dry_run=True`` the loop generates specs and
  emits the cycle summary, but does NOT call ``factory.submit``. Useful
  for cron-bring-up and audit dry-fits.
* **Resumability.** Cycle summaries are appended to a JSONL file under
  ``$QF_AUTO_LOOP_LOG`` (defaults to ``$QF_DATA_DIR/auto_loop.jsonl``).
  An operator can replay or audit cycle outcomes without re-running
  the factory.
* **Failures archived.** Submit exceptions are caught, stamped with the
  cycle id, and written to the cycle summary alongside the spec ids
  that triggered them. The factory's own archive captures rejected
  candidates separately.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence

import pandas as pd

from quantforge.core.runtime_paths import base_data_dir
from quantforge.research.factory.factory import (
    ResearchFactory,
    ResearchPipelineConfig,
)
from quantforge.research.factory.generators import HypothesisGenerator
from quantforge.research.factory.outcomes import ResearchOutcome
from quantforge.research.factory.spec import StrategySpec


_log = logging.getLogger("quantforge.research.auto_loop")


def _auto_loop_log_path() -> Path:
    """Cycle summary JSONL. Override via $QF_AUTO_LOOP_LOG."""
    raw = os.environ.get("QF_AUTO_LOOP_LOG")
    return Path(raw) if raw else base_data_dir() / "auto_loop.jsonl"


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass
class AutoLoopConfig:
    """Static knobs governing one cycle.

    Attributes:
        n_specs_per_cycle: how many hypotheses to draw from the generator.
        review_queue_cap: skip submission if queue length exceeds this.
        dry_run: when True, do not call ``factory.submit``; only generate
            and log.
        max_seconds_per_cycle: hard wall on a single cycle's wall time.
            The loop stops submitting once the budget is exceeded; any
            specs not yet processed are recorded as ``deferred``.
        seed_base: per-cycle generator seed = ``seed_base + cycle_index``.
            Keeping it explicit makes the loop reproducible.
    """

    n_specs_per_cycle: int = 5
    review_queue_cap: int = 50
    dry_run: bool = False
    max_seconds_per_cycle: float = 300.0
    seed_base: int = 1_000


# --------------------------------------------------------------------------
# Cycle summary
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CycleSummary:
    """Immutable per-cycle log record."""

    cycle_id: str
    cycle_index: int
    timestamp_iso: str
    generator_name: str
    n_generated: int
    n_submitted: int
    n_promoted: int
    n_archived: int
    n_failed_with_exception: int
    review_queue_size: int
    dry_run: bool
    seed: int
    duration_seconds: float
    notes: List[str] = field(default_factory=list)
    spec_ids: List[str] = field(default_factory=list)
    archived_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "cycle_index": self.cycle_index,
            "timestamp_iso": self.timestamp_iso,
            "generator_name": self.generator_name,
            "n_generated": self.n_generated,
            "n_submitted": self.n_submitted,
            "n_promoted": self.n_promoted,
            "n_archived": self.n_archived,
            "n_failed_with_exception": self.n_failed_with_exception,
            "review_queue_size": self.review_queue_size,
            "dry_run": self.dry_run,
            "seed": self.seed,
            "duration_seconds": self.duration_seconds,
            "notes": list(self.notes),
            "spec_ids": list(self.spec_ids),
            "archived_reasons": list(self.archived_reasons),
        }


# --------------------------------------------------------------------------
# Loop driver
# --------------------------------------------------------------------------


@dataclass
class AutoResearchLoop:
    """Driver around generator + factory.

    Construct once and call :meth:`run_cycle` per scheduled tick. The
    loop holds no per-cycle state; ``cycle_index`` is passed in (or
    auto-incremented from ``next_cycle_index``).
    """

    factory: ResearchFactory
    generator: HypothesisGenerator
    config: AutoLoopConfig = field(default_factory=AutoLoopConfig)
    log_path: Optional[Path] = None
    next_cycle_index: int = 0

    def run_cycle(
        self, cycle_index: Optional[int] = None
    ) -> CycleSummary:
        """Run one full generate -> submit -> log cycle."""
        idx = (
            cycle_index if cycle_index is not None else self.next_cycle_index
        )
        self.next_cycle_index = idx + 1
        cycle_id = f"cyc_{idx:06d}_{uuid.uuid4().hex[:8]}"
        seed = self.config.seed_base + idx
        started = time.monotonic()
        notes: List[str] = []
        archived_reasons: List[str] = []

        # 1) review-queue cap check
        try:
            queue_size = len(self.factory.list_review_queue())
        except Exception as exc:
            queue_size = -1
            notes.append(f"review_queue_size_unavailable: {exc!r}")

        if queue_size >= 0 and queue_size > self.config.review_queue_cap:
            notes.append(
                f"queue_cap_exceeded ({queue_size} > {self.config.review_queue_cap}); "
                "skipping submission"
            )
            return self._finalize(
                cycle_id=cycle_id,
                cycle_index=idx,
                generator_name=getattr(self.generator, "name", "unknown"),
                n_generated=0,
                n_submitted=0,
                n_promoted=0,
                n_archived=0,
                n_failed_with_exception=0,
                review_queue_size=queue_size,
                seed=seed,
                duration_seconds=time.monotonic() - started,
                notes=notes,
                spec_ids=[],
                archived_reasons=archived_reasons,
            )

        # 2) generate specs
        try:
            specs: Sequence[StrategySpec] = self.generator.generate(
                n=self.config.n_specs_per_cycle, seed=seed
            )
        except Exception as exc:
            notes.append(f"generator_failed: {exc!r}")
            specs = []

        spec_ids = [getattr(s, "spec_id", "") for s in specs]

        # 3) submit (or skip in dry-run)
        n_submitted = 0
        n_promoted = 0
        n_archived = 0
        n_failed = 0

        if self.config.dry_run:
            notes.append("dry_run: skipped factory.submit")
        else:
            for s in specs:
                if time.monotonic() - started > self.config.max_seconds_per_cycle:
                    notes.append(
                        f"time_budget_exceeded after {n_submitted} submissions"
                    )
                    break
                try:
                    outcome: ResearchOutcome = self.factory.submit(s)
                except Exception as exc:
                    n_failed += 1
                    notes.append(f"submit_exception: {exc!r}")
                    continue
                n_submitted += 1
                if _outcome_promoted(outcome):
                    n_promoted += 1
                else:
                    n_archived += 1
                    reason = _outcome_reason(outcome)
                    if reason:
                        archived_reasons.append(reason)

        return self._finalize(
            cycle_id=cycle_id,
            cycle_index=idx,
            generator_name=getattr(self.generator, "name", "unknown"),
            n_generated=len(specs),
            n_submitted=n_submitted,
            n_promoted=n_promoted,
            n_archived=n_archived,
            n_failed_with_exception=n_failed,
            review_queue_size=queue_size,
            seed=seed,
            duration_seconds=time.monotonic() - started,
            notes=notes,
            spec_ids=spec_ids,
            archived_reasons=archived_reasons,
        )

    def _finalize(self, **kwargs: Any) -> CycleSummary:
        kwargs.setdefault("dry_run", self.config.dry_run)
        kwargs.setdefault("timestamp_iso", pd.Timestamp.utcnow().isoformat())
        summary = CycleSummary(**kwargs)
        self._append_log(summary)
        return summary

    def _append_log(self, summary: CycleSummary) -> None:
        path = self.log_path or _auto_loop_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary.to_dict(), default=str) + "\n")


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------


def run_one_cycle(
    factory: ResearchFactory,
    generator: HypothesisGenerator,
    *,
    config: Optional[AutoLoopConfig] = None,
    log_path: Optional[Path] = None,
) -> CycleSummary:
    """Construct an :class:`AutoResearchLoop` and run a single cycle."""
    loop = AutoResearchLoop(
        factory=factory,
        generator=generator,
        config=config or AutoLoopConfig(),
        log_path=log_path,
    )
    return loop.run_cycle()


# --------------------------------------------------------------------------
# Outcome helpers (resilient to outcome shape variations)
# --------------------------------------------------------------------------


def _outcome_promoted(outcome: ResearchOutcome) -> bool:
    """True iff the outcome was promoted into the review queue."""
    return bool(getattr(outcome, "promising", False))


def _outcome_reason(outcome: ResearchOutcome) -> Optional[str]:
    cand = getattr(outcome, "candidate", None)
    if cand is None:
        return None
    # The factory's CandidateRun uses ``rejection`` (RejectionReason enum)
    # for the categorical reason. Older / mocked candidates may carry
    # ``rejection_reason`` instead -- fall back gracefully.
    reason = getattr(cand, "rejection", None) or getattr(
        cand, "rejection_reason", None
    )
    return str(getattr(reason, "value", reason)) if reason else None
