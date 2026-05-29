"""Hard guards for Aurora autonomous research loops."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from aurora.research.agent_loop.actions import validate_agent_action
from aurora.research.agent_loop.goal import AgentGoalSpec
from aurora.research.agent_loop.state import AgentRunState


class AgentProtocolViolation(RuntimeError):
    """Raised when the autonomous loop attempts an unsafe operation."""


class AgentLoopGuard:
    """Enforce non-negotiable loop rules before each action."""

    def __init__(self, *, repo_root: Path):
        self.repo_root = repo_root.resolve()

    def validate(
        self,
        *,
        action: Mapping[str, object],
        goal: AgentGoalSpec,
        state: AgentRunState,
    ) -> dict[str, object]:
        safe_action = validate_agent_action(action)
        if goal.protocol.open_locked:
            raise AgentProtocolViolation("locked must remain closed during agent-loop")
        if state.locked_opened:
            raise AgentProtocolViolation("locked was opened; stop this investigation")
        if state.worktree_path is None:
            raise AgentProtocolViolation("agent-loop requires an isolated worktree")
        if not state.worktree_path.exists():
            raise AgentProtocolViolation("agent-loop worktree does not exist")
        if state.worktree_path.resolve() == self.repo_root:
            raise AgentProtocolViolation("agent-loop may not run directly in main worktree")
        return safe_action


__all__ = ["AgentLoopGuard", "AgentProtocolViolation"]
