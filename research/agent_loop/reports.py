"""Reports for Aurora autonomous research loops."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aurora.research.agent_loop.state import AgentRunState


def write_agent_report(
    *,
    state: AgentRunState,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    reports_dir = state.run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state.to_dict(),
        "steps": steps,
    }
    (reports_dir / "agent_report.json").write_text(
        json.dumps(payload, indent=2, default=str, sort_keys=True),
        encoding="utf-8",
    )
    (reports_dir / "agent_report.md").write_text(
        _markdown(payload),
        encoding="utf-8",
    )
    return payload


def read_agent_report(run_dir: str | Path) -> dict[str, Any]:
    return json.loads(
        (Path(run_dir) / "reports" / "agent_report.json").read_text(encoding="utf-8")
    )


def _markdown(payload: dict[str, Any]) -> str:
    state = payload["state"]
    return "\n".join([
        "# Aurora Agent Loop",
        "",
        f"Run: {state['run_id']}",
        f"Goal: {state['goal_id']}",
        f"Status: {state['status']}",
        f"Objective met: {str(state['objective_met']).lower()}",
        f"Locked opened: {str(state['locked_opened']).lower()}",
        f"Stop requested: {str(state.get('stop_requested', False)).lower()}",
        f"Last action: {state.get('last_action') or 'none'}",
        f"Worktree: {state.get('worktree_path') or 'none'}",
        f"Steps: {len(payload['steps'])}",
        f"Research rounds: {state.get('research_rounds', 0)}",
        f"Rounds without improvement: {state.get('rounds_without_improvement', 0)}",
        f"Best score: {state.get('best_score')}",
        "",
        "## Sources",
        "",
        f"Built: {_join_items(state.get('built_sources', []))}",
        f"Blocked: {_join_items(state.get('blocked_sources', []))}",
    ])


def _join_items(items: object) -> str:
    if not isinstance(items, list) or not items:
        return "none"
    return ", ".join(str(item) for item in items)


__all__ = ["read_agent_report", "write_agent_report"]
