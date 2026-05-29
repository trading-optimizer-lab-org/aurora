"""Persistent state for Aurora autonomous research loops."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aurora.research.agent_loop.actions import AgentStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentRunState:
    run_id: str
    goal_id: str
    status: str
    step: int
    run_dir: Path
    worktree_path: Path | None = None
    objective_met: bool = False
    locked_opened: bool = False
    stop_requested: bool = False
    blocked_routes: list[str] = field(default_factory=list)
    last_action: str | None = None
    research_rounds: int = 0
    rounds_without_improvement: int = 0
    best_score: float | None = None
    built_sources: list[str] = field(default_factory=list)
    blocked_sources: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["run_dir"] = str(self.run_dir)
        payload["worktree_path"] = None if self.worktree_path is None else str(self.worktree_path)
        return payload

    def save(self) -> None:
        self.updated_at = _now()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "state.json").write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )


def new_agent_state(run_dir: Path, *, goal_id: str, run_id: str) -> AgentRunState:
    state = AgentRunState(
        run_id=run_id,
        goal_id=goal_id,
        status=AgentStatus.RUNNING.value,
        step=0,
        run_dir=run_dir,
    )
    state.save()
    return state


def load_agent_state(run_dir: str | Path) -> AgentRunState:
    root = Path(run_dir)
    data = json.loads((root / "state.json").read_text(encoding="utf-8"))
    return AgentRunState(
        run_id=str(data["run_id"]),
        goal_id=str(data["goal_id"]),
        status=str(data["status"]),
        step=int(data["step"]),
        run_dir=Path(data["run_dir"]),
        worktree_path=None if data.get("worktree_path") is None else Path(data["worktree_path"]),
        objective_met=bool(data.get("objective_met", False)),
        locked_opened=bool(data.get("locked_opened", False)),
        stop_requested=bool(data.get("stop_requested", False)),
        blocked_routes=list(data.get("blocked_routes", [])),
        last_action=data.get("last_action"),
        research_rounds=int(data.get("research_rounds", 0)),
        rounds_without_improvement=int(data.get("rounds_without_improvement", 0)),
        best_score=(
            None if data.get("best_score") is None else float(data["best_score"])
        ),
        built_sources=list(data.get("built_sources", [])),
        blocked_sources=list(data.get("blocked_sources", [])),
        created_at=str(data.get("created_at", _now())),
        updated_at=str(data.get("updated_at", _now())),
    )


def request_agent_stop(run_dir: str | Path) -> AgentRunState:
    state = load_agent_state(run_dir)
    state.status = AgentStatus.STOP_REQUESTED.value
    state.stop_requested = True
    state.save()
    append_jsonl(state.run_dir / "decisions.jsonl", {
        "event": "stop_requested",
        "run_id": state.run_id,
        "at": _now(),
    })
    return state


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


__all__ = [
    "AgentRunState",
    "append_jsonl",
    "load_agent_state",
    "new_agent_state",
    "request_agent_stop",
]
