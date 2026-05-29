"""Main orchestration loop for Aurora autonomous research."""
from __future__ import annotations

import shutil
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from aurora.core.runtime_paths import base_data_dir
from aurora.research.agent_loop.actions import AgentActionType, AgentStatus
from aurora.research.agent_loop.executor import AgentActionExecutor
from aurora.research.agent_loop.goal import load_goal_spec
from aurora.research.agent_loop.guards import AgentLoopGuard
from aurora.research.agent_loop.planner_codex import CodexCliPlanner
from aurora.research.agent_loop.reports import write_agent_report
from aurora.research.agent_loop.state import (
    AgentRunState,
    append_jsonl,
    load_agent_state,
    new_agent_state,
)
from aurora.research.agent_loop.worktree import prepare_agent_worktree


@dataclass(frozen=True)
class AgentLoopResult:
    state: AgentRunState
    steps: list[dict[str, Any]]
    report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.report


def run_agent_loop(
    *,
    goal_path: str | Path,
    run_root: str | Path | None = None,
    max_agent_steps: int | None = None,
    dry_run_codex: bool = True,
    dry_run_worktree: bool = True,
    codex_provider: str = "dry-run",
    repo_root: str | Path | None = None,
    candidates_per_round: int = 50_000,
    max_search_hours: float = 2.0,
    rounds_per_batch: int = 3,
    cpu_workers: int = 3,
    round_workers: int = 1,
    resume_run_dir: str | Path | None = None,
) -> AgentLoopResult:
    """Run the autonomous loop until objective, stop request or step cap."""

    goal = load_goal_spec(goal_path)
    root = Path(run_root) if run_root else base_data_dir() / "agent_loop"
    if resume_run_dir is None:
        run_id = _new_run_id()
        run_dir = root / run_id
        state = new_agent_state(run_dir, goal_id=goal.goal_id, run_id=run_id)
        shutil.copyfile(Path(goal_path), run_dir / "goal.yaml")
        resumed = False
    else:
        run_dir = Path(resume_run_dir)
        state = load_agent_state(run_dir)
        if state.goal_id != goal.goal_id:
            raise ValueError(
                f"resume goal mismatch: state has {state.goal_id!r}, "
                f"goal file has {goal.goal_id!r}"
            )
        resumed = True

    repo = Path(repo_root) if repo_root else Path.cwd()
    if state.worktree_path is None:
        state.worktree_path = prepare_agent_worktree(
            repo_root=repo,
            run_root=run_dir,
            goal_id=goal.goal_id,
            run_id=state.run_id,
            dry_run=dry_run_worktree,
        )
        state.save()

    planner = CodexCliPlanner(
        dry_run=dry_run_codex or codex_provider == "dry-run",
    )
    guard = AgentLoopGuard(repo_root=repo)
    executor = AgentActionExecutor(
        candidates_per_round=candidates_per_round,
        max_search_hours=max_search_hours,
        rounds_per_batch=rounds_per_batch,
        cpu_workers=cpu_workers,
        round_workers=round_workers,
    )
    steps: list[dict[str, Any]] = _read_step_records(run_dir) if resumed else []
    max_steps = max_agent_steps if max_agent_steps is not None else 1_000_000
    pending_action: dict[str, object] | None = (
        _resume_pending_action(state)
        if resumed
        else {"action": AgentActionType.RUN_AUTOSEARCH.value}
    )

    while state.step < max_steps:
        _refresh_external_stop_request(state)
        if state.status in {
            AgentStatus.OBJECTIVE_MET.value,
            AgentStatus.PAUSED_ALL_ROUTES_BLOCKED.value,
            AgentStatus.STOP_REQUESTED.value,
        }:
            break
        if state.stop_requested:
            state.status = AgentStatus.STOP_REQUESTED.value
            state.save()
            break

        if pending_action is None:
            pending_action = planner.plan_next(
                goal=goal,
                state=state.to_dict(),
                worktree=state.worktree_path or run_dir,
                context={"previous_steps": steps[-3:]},
            )
        pending_action = _force_search_after_non_search_cycle(
            pending_action,
            run_dir=run_dir,
            steps=steps,
        )

        action = guard.validate(action=pending_action, goal=goal, state=state)
        state.step += 1
        state.last_action = str(action["action"])
        append_jsonl(run_dir / "decisions.jsonl", {
            "step": state.step,
            "action": action,
        })
        result = executor.execute(action=action, goal=goal, state=state)
        _refresh_external_stop_request(state)
        record = {
            "step": state.step,
            "action": action["action"],
            "result": result,
        }
        steps.append(record)
        append_jsonl(run_dir / "action_queue.jsonl", record)

        if state.objective_met:
            state.status = AgentStatus.OBJECTIVE_MET.value
            pending_action = None
        elif str(action["action"]) == AgentActionType.RUN_AUTOSEARCH.value:
            pending_action = _planner_action_after_search_failure(
                planner=planner,
                goal=goal,
                state=state,
                run_dir=run_dir,
                steps=steps,
                result=result,
            )
        elif str(action["action"]) in {
            AgentActionType.DISCOVER_SOURCES.value,
            AgentActionType.DISCOVER_STRATEGY_IDEAS.value,
        }:
            next_action = result.get("next_action")
            pending_action = (
                next_action
                if isinstance(next_action, dict)
                else {"action": AgentActionType.RUN_AUTOSEARCH.value}
            )
        else:
            next_action = result.get("next_action") if isinstance(result, dict) else None
            pending_action = (
                next_action
                if isinstance(next_action, dict)
                else {"action": AgentActionType.RUN_AUTOSEARCH.value}
            )
        state.save()

    if (
        state.step >= max_steps
        and not state.objective_met
        and state.status
        not in {
            AgentStatus.PAUSED_ALL_ROUTES_BLOCKED.value,
        }
    ):
        state.status = AgentStatus.BLOCKED_BUT_CONTINUING.value
        state.save()

    report = write_agent_report(state=state, steps=steps)
    return AgentLoopResult(state=state, steps=steps, report=report)


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _planner_action_after_search_failure(
    *,
    planner: CodexCliPlanner,
    goal,
    state: AgentRunState,
    run_dir: Path,
    steps: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, object]:
    if state.rounds_without_improvement >= 2:
        return {"action": AgentActionType.DISCOVER_STRATEGY_IDEAS.value}
    if planner.dry_run:
        return {"action": AgentActionType.DISCOVER_SOURCES.value}
    try:
        return planner.plan_next(
            goal=goal,
            state=state.to_dict(),
            worktree=state.worktree_path or run_dir,
            context={
                "previous_steps": steps[-3:],
                "last_search_result": result,
                "preferred_safe_actions": [
                    AgentActionType.ASK_CODEX_FOR_IDEAS.value,
                    AgentActionType.ASK_CODEX_FOR_FAILURE_REVIEW.value,
                    AgentActionType.DISCOVER_STRATEGY_IDEAS.value,
                    AgentActionType.DISCOVER_SOURCES.value,
                ],
            },
        )
    except Exception as exc:
        append_jsonl(run_dir / "blocked_routes.jsonl", {
            "route": "codex_planner",
            "reason": str(exc),
        })
        return {"action": AgentActionType.DISCOVER_SOURCES.value}


def _refresh_external_stop_request(state: AgentRunState) -> None:
    """Pull a stop request written by another process into the live loop."""

    try:
        disk_state = load_agent_state(state.run_dir)
    except FileNotFoundError:
        return
    if disk_state.stop_requested:
        state.stop_requested = True
        state.status = AgentStatus.STOP_REQUESTED.value


def _read_step_records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "action_queue.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "step" in payload and "action" in payload:
            records.append(payload)
    return records


def _force_search_after_non_search_cycle(
    action: dict[str, object],
    *,
    run_dir: Path,
    steps: list[dict[str, Any]],
    limit: int = 8,
) -> dict[str, object]:
    if action.get("action") == AgentActionType.RUN_AUTOSEARCH.value:
        return action
    streak = 0
    for step in reversed(steps):
        if step.get("action") == AgentActionType.RUN_AUTOSEARCH.value:
            break
        streak += 1
    if streak < limit:
        return action
    forced = {"action": AgentActionType.RUN_AUTOSEARCH.value}
    append_jsonl(run_dir / "decisions.jsonl", {
        "event": "forced_autosearch_after_non_search_cycle",
        "streak": streak,
        "replaced_action": action,
        "forced_action": forced,
    })
    return forced


def _resume_pending_action(state: AgentRunState) -> dict[str, object] | None:
    if state.status in {
        AgentStatus.OBJECTIVE_MET.value,
        AgentStatus.STOP_REQUESTED.value,
    }:
        return None
    task = _latest_unhandled_source_task(state)
    if task is not None:
        return task
    if state.last_action == AgentActionType.RUN_AUTOSEARCH.value:
        return {"action": AgentActionType.DISCOVER_SOURCES.value}
    return {"action": AgentActionType.RUN_AUTOSEARCH.value}


def _latest_unhandled_source_task(state: AgentRunState) -> dict[str, object] | None:
    path = state.run_dir / "source_tasks.jsonl"
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("status") != "queued":
            continue
        if payload.get("action") != AgentActionType.BUILD_SOURCE_CONNECTOR.value:
            continue
        source = payload.get("source")
        source_id = (
            source.get("source_id")
            if isinstance(source, dict)
            else payload.get("source_id")
        )
        if isinstance(source_id, str) and (
            source_id in state.built_sources or source_id in state.blocked_sources
        ):
            continue
        return payload
    return None


__all__ = ["AgentLoopResult", "run_agent_loop"]
