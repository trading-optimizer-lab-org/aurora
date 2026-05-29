"""Watchdog and recovery helpers for Aurora autonomous research loops."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aurora.core.runtime_paths import base_data_dir
from aurora.research.agent_loop.actions import AgentStatus
from aurora.research.agent_loop.reports import write_agent_report
from aurora.research.agent_loop.state import (
    AgentRunState,
    append_jsonl,
    load_agent_state,
)


TERMINAL_STATUSES = frozenset({
    AgentStatus.OBJECTIVE_MET.value,
    AgentStatus.PAUSED_ALL_ROUTES_BLOCKED.value,
    AgentStatus.STOP_REQUESTED.value,
})


@dataclass(frozen=True)
class AgentRuntimeInspection:
    """Current runtime view of a persisted agent loop run."""

    run_id: str
    run_dir: Path
    state_status: str
    locked_opened: bool
    objective_met: bool
    stop_requested: bool
    report_exists: bool
    pid: int | None
    process_alive: bool
    stale_seconds: float
    stale: bool
    needs_recovery: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "state_status": self.state_status,
            "locked_opened": self.locked_opened,
            "objective_met": self.objective_met,
            "stop_requested": self.stop_requested,
            "report_exists": self.report_exists,
            "pid": self.pid,
            "process_alive": self.process_alive,
            "stale_seconds": round(self.stale_seconds, 3),
            "stale": self.stale,
            "needs_recovery": self.needs_recovery,
            "reason": self.reason,
        }


def inspect_agent_runtime(
    run_dir: str | Path,
    *,
    max_stale_seconds: float = 600.0,
    pid_alive: Callable[[int], bool] | None = None,
    ignored_pids: set[int] | None = None,
    now: datetime | None = None,
) -> AgentRuntimeInspection:
    """Inspect whether a persisted run appears alive or recoverable."""

    state = load_agent_state(run_dir)
    report_exists = (state.run_dir / "reports" / "agent_report.json").exists()
    pid = _read_pid_for_run(state)
    ignored = set(ignored_pids or {os.getpid()})
    process_alive = bool(
        pid is not None
        and pid not in ignored
        and (pid_alive or is_pid_alive)(pid)
    )
    stale_seconds = _seconds_since(state.updated_at, now=now)
    stale = stale_seconds >= max(0.0, float(max_stale_seconds))
    terminal = state.status in TERMINAL_STATUSES

    if terminal:
        reason = "terminal_state"
        needs_recovery = False
    elif process_alive:
        reason = "process_alive"
        needs_recovery = False
    elif not stale:
        reason = "recent_state_without_process"
        needs_recovery = False
    else:
        reason = "stale_state_without_process"
        needs_recovery = True

    return AgentRuntimeInspection(
        run_id=state.run_id,
        run_dir=state.run_dir,
        state_status=state.status,
        locked_opened=state.locked_opened,
        objective_met=state.objective_met,
        stop_requested=state.stop_requested,
        report_exists=report_exists,
        pid=pid,
        process_alive=process_alive,
        stale_seconds=stale_seconds,
        stale=stale,
        needs_recovery=needs_recovery,
        reason=reason,
    )


def write_unclean_stop_report(
    run_dir: str | Path,
    *,
    inspection: AgentRuntimeInspection | None = None,
) -> dict[str, Any]:
    """Write a report for a run that stopped without its normal final report."""

    state = load_agent_state(run_dir)
    inspection = inspection or inspect_agent_runtime(state.run_dir, max_stale_seconds=0)
    append_jsonl(state.run_dir / "watchdog.jsonl", {
        "event": "unclean_stop_detected",
        "inspection": inspection.to_dict(),
        "at": _now(),
    })
    steps = _read_step_records(state.run_dir)
    report = write_agent_report(state=state, steps=steps)
    report["watchdog"] = {
        "unclean_stop_detected": True,
        "inspection": inspection.to_dict(),
        "recommendation": "resume_with_agent_watchdog_restart",
    }
    reports_dir = state.run_dir / "reports"
    (reports_dir / "agent_watchdog_report.json").write_text(
        _json_dumps(report),
        encoding="utf-8",
    )
    return report


def recover_or_restart_agent_run(
    *,
    run_dir: str | Path,
    max_stale_seconds: float = 600.0,
    restart: bool = False,
    run_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Diagnose a run and optionally resume it if it is stale and dead."""

    inspection = inspect_agent_runtime(
        run_dir,
        max_stale_seconds=max_stale_seconds,
    )
    payload: dict[str, Any] = {
        "inspection": inspection.to_dict(),
        "restarted": False,
    }
    if not inspection.needs_recovery:
        return payload

    write_unclean_stop_report(inspection.run_dir, inspection=inspection)
    if not restart:
        payload["report_written"] = True
        return payload

    from aurora.research.agent_loop.loop import run_agent_loop

    kwargs = dict(run_kwargs or {})
    kwargs.setdefault("goal_path", inspection.run_dir / "goal.yaml")
    kwargs.setdefault("resume_run_dir", inspection.run_dir)
    result = run_agent_loop(**kwargs)
    payload["restarted"] = True
    payload["result"] = result.to_dict()
    return payload


def supervise_agent_run(
    *,
    run_dir: str | Path,
    max_stale_seconds: float = 600.0,
    poll_seconds: float = 60.0,
    run_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep a run alive until it reaches one of Aurora's terminal states."""

    root = Path(run_dir)
    last_payload: dict[str, Any] = {}
    while True:
        state = load_agent_state(root)
        if state.status in TERMINAL_STATUSES or state.objective_met or state.stop_requested:
            return {
                "supervised": True,
                "finished": True,
                "state": state.to_dict(),
                "last_payload": last_payload,
            }

        try:
            last_payload = recover_or_restart_agent_run(
                run_dir=root,
                max_stale_seconds=max_stale_seconds,
                restart=True,
                run_kwargs=run_kwargs,
            )
        except Exception as exc:
            append_jsonl(root / "watchdog.jsonl", {
                "event": "supervisor_restart_failed",
                "error": str(exc),
                "at": _now(),
            })
            last_payload = {
                "supervised": True,
                "restart_error": str(exc),
            }

        state = load_agent_state(root)
        if state.status in TERMINAL_STATUSES or state.objective_met or state.stop_requested:
            return {
                "supervised": True,
                "finished": True,
                "state": state.to_dict(),
                "last_payload": last_payload,
            }
        time.sleep(max(1.0, float(poll_seconds)))


def is_pid_alive(pid: int) -> bool:
    """Return whether ``pid`` appears alive using only the standard library."""

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_pid_for_run(state: AgentRunState) -> int | None:
    launcher_dir = base_data_dir() / "agent_loop_launcher"
    candidates = [
        launcher_dir / f"agent_loop_{state.run_id}.pid",
        state.run_dir / "agent_loop.pid",
    ]
    for path in candidates:
        pid = _read_pid(path)
        if pid is not None:
            return pid
    return None


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _seconds_since(value: str, *, now: datetime | None = None) -> float:
    current = now or datetime.now(timezone.utc)
    try:
        then = datetime.fromisoformat(value)
    except ValueError:
        return float("inf")
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (current - then).total_seconds())


def _read_step_records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "action_queue.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            import json

            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, default=str, sort_keys=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "AgentRuntimeInspection",
    "inspect_agent_runtime",
    "is_pid_alive",
    "recover_or_restart_agent_run",
    "supervise_agent_run",
    "write_unclean_stop_report",
]
