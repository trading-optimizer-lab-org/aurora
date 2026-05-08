"""Re-optimization scheduler (R93).

Companion to R10 auto-loop. Re-validates approved strategies on a
configurable cadence:

- weekly walk-forward refresh,
- monthly full pipeline rerun,
- quarterly OOS_LOCKED reseat (with ceremony).

The scheduler returns a calendar of which strategy is up next; the
auto-loop runner consumes the calendar and fires the actual job.
This module is deliberately separate from the runner so the schedule
math is testable.

Pairs with R141 (refit-cadence optimiser) which selects the cadence
per strategy from data; the scheduler USES that cadence here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ReoptJob:
    """A single re-optimisation job on the schedule."""

    strategy_id: str
    job_type: str  # "walk_forward" | "full_pipeline" | "oos_locked_reseat"
    due_date: date
    last_run: Optional[date] = None
    rationale: str = ""


@dataclass
class ScheduleConfig:
    """Per-strategy cadence settings.

    Attributes:
        walk_forward_days: cadence for the cheap walk-forward refresh.
        full_pipeline_days: cadence for the full validation gate rerun.
        oos_reseat_days: cadence for the OOS_LOCKED reseat ceremony.
    """

    walk_forward_days: int = 7
    full_pipeline_days: int = 30
    oos_reseat_days: int = 90


def schedule_for(
    *,
    strategy_id: str,
    config: ScheduleConfig,
    last_runs: Dict[str, Optional[date]],
    today: date,
) -> List[ReoptJob]:
    """Compute pending jobs for one strategy as of ``today``.

    Args:
        strategy_id: which strategy.
        config: per-strategy cadence.
        last_runs: dict of job_type -> date last completed (or None).
        today: today's date.

    Returns:
        list of jobs that are due (due_date <= today) plus the next
        upcoming job per type. Already-completed jobs whose next run
        is in the future are NOT returned.
    """
    out: List[ReoptJob] = []
    for job_type, days in (
        ("walk_forward", config.walk_forward_days),
        ("full_pipeline", config.full_pipeline_days),
        ("oos_locked_reseat", config.oos_reseat_days),
    ):
        last = last_runs.get(job_type)
        if last is None:
            due = today
            rationale = f"never run; first {job_type} due now"
        else:
            due = last + timedelta(days=days)
            rationale = (
                f"last {job_type} on {last.isoformat()}; cadence {days}d "
                f"-> due {due.isoformat()}"
            )
        if due <= today:
            out.append(ReoptJob(
                strategy_id=strategy_id,
                job_type=job_type,
                due_date=due,
                last_run=last,
                rationale=rationale,
            ))
    return out


def upcoming_calendar(
    *,
    strategies: Dict[str, ScheduleConfig],
    last_runs_by_strategy: Dict[str, Dict[str, Optional[date]]],
    today: date,
    horizon_days: int = 30,
) -> List[ReoptJob]:
    """Calendar view of every job due within the horizon."""
    end = today + timedelta(days=horizon_days)
    out: List[ReoptJob] = []
    for sid, cfg in strategies.items():
        runs = last_runs_by_strategy.get(sid, {})
        for job_type, days in (
            ("walk_forward", cfg.walk_forward_days),
            ("full_pipeline", cfg.full_pipeline_days),
            ("oos_locked_reseat", cfg.oos_reseat_days),
        ):
            last = runs.get(job_type)
            if last is None:
                due = today
            else:
                due = last + timedelta(days=days)
            if due <= end:
                out.append(ReoptJob(
                    strategy_id=sid,
                    job_type=job_type,
                    due_date=due,
                    last_run=last,
                    rationale=(
                        f"last {job_type} on "
                        f"{last.isoformat() if last else 'never'}; due {due.isoformat()}"
                    ),
                ))
    out.sort(key=lambda j: j.due_date)
    return out


__all__ = [
    "ReoptJob",
    "ScheduleConfig",
    "schedule_for",
    "upcoming_calendar",
]
