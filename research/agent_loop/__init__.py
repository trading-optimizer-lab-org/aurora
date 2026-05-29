"""Autonomous research loop primitives for Aurora."""
from aurora.research.agent_loop.actions import (
    ALLOWED_AGENT_ACTIONS,
    FORBIDDEN_AGENT_ACTIONS,
    AgentActionType,
    AgentStatus,
    ForbiddenAgentActionError,
    validate_agent_action,
)
from aurora.research.agent_loop.goal import AgentGoalSpec, load_goal_spec
from aurora.research.agent_loop.loop import AgentLoopResult, run_agent_loop
from aurora.research.agent_loop.state import AgentRunState, load_agent_state
from aurora.research.agent_loop.watchdog import (
    AgentRuntimeInspection,
    inspect_agent_runtime,
    recover_or_restart_agent_run,
)

__all__ = [
    "ALLOWED_AGENT_ACTIONS",
    "FORBIDDEN_AGENT_ACTIONS",
    "AgentActionType",
    "AgentGoalSpec",
    "AgentLoopResult",
    "AgentRunState",
    "AgentRuntimeInspection",
    "AgentStatus",
    "ForbiddenAgentActionError",
    "inspect_agent_runtime",
    "load_agent_state",
    "load_goal_spec",
    "recover_or_restart_agent_run",
    "run_agent_loop",
    "validate_agent_action",
]
