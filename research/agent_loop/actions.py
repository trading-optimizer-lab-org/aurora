"""Action and status policy for Aurora autonomous research loops."""
from __future__ import annotations

from enum import Enum
from typing import Mapping


class AgentStatus(str, Enum):
    RUNNING = "RUNNING"
    SEARCHING_STRATEGY = "SEARCHING_STRATEGY"
    DISCOVERING_SOURCES = "DISCOVERING_SOURCES"
    BUILDING_CONNECTOR = "BUILDING_CONNECTOR"
    VALIDATING_DATA = "VALIDATING_DATA"
    GENERATING_FEATURES = "GENERATING_FEATURES"
    RUNNING_ROBUSTNESS = "RUNNING_ROBUSTNESS"
    VALIDATION_EXAM = "VALIDATION_EXAM"
    OBJECTIVE_MET = "OBJECTIVE_MET"
    BLOCKED_BUT_CONTINUING = "BLOCKED_BUT_CONTINUING"
    PAUSED_ALL_ROUTES_BLOCKED = "PAUSED_ALL_ROUTES_BLOCKED"
    STOPPED_NO_IMPROVEMENT = "STOPPED_NO_IMPROVEMENT"
    STOP_REQUESTED = "STOP_REQUESTED"


class AgentActionType(str, Enum):
    RUN_AUTOSEARCH = "RUN_AUTOSEARCH"
    DISCOVER_SOURCES = "DISCOVER_SOURCES"
    DISCOVER_STRATEGY_IDEAS = "DISCOVER_STRATEGY_IDEAS"
    ASK_CODEX_FOR_IDEAS = "ASK_CODEX_FOR_IDEAS"
    ASK_CODEX_FOR_FAILURE_REVIEW = "ASK_CODEX_FOR_FAILURE_REVIEW"
    ASK_CODEX_FOR_CONNECTOR_PLAN = "ASK_CODEX_FOR_CONNECTOR_PLAN"
    BUILD_SOURCE_CONNECTOR = "BUILD_SOURCE_CONNECTOR"
    VALIDATE_NEW_DATA = "VALIDATE_NEW_DATA"
    GENERATE_FEATURE_SET = "GENERATE_FEATURE_SET"
    RUN_KRONOS_SEARCH = "RUN_KRONOS_SEARCH"
    RUN_TRAIN_SEARCH = "RUN_TRAIN_SEARCH"
    RUN_ROBUSTNESS = "RUN_ROBUSTNESS"
    RUN_VALIDATION_EXAM = "RUN_VALIDATION_EXAM"
    ARCHIVE_FAILED_IDEA = "ARCHIVE_FAILED_IDEA"
    EXPAND_CATALOG = "EXPAND_CATALOG"
    WRITE_REPORT = "WRITE_REPORT"


FORBIDDEN_AGENT_ACTIONS = frozenset({
    "OPEN_LOCKED_DURING_SEARCH",
    "USE_LOCKED_FOR_SELECTION",
    "TRADE_LIVE",
    "PUSH_TO_MAIN",
    "DELETE_RUNTIME_DATA",
    "SILENCE_TESTS_TO_PASS",
    "DECLARE_SUCCESS_WITHOUT_GATES",
})

ALLOWED_AGENT_ACTIONS = frozenset(action.value for action in AgentActionType)


class ForbiddenAgentActionError(ValueError):
    """Raised when a planner asks for an unsafe or unknown action."""


def validate_agent_action(action: Mapping[str, object]) -> dict[str, object]:
    """Validate and normalize an action dictionary."""

    raw = str(action.get("action", "")).strip()
    if raw in FORBIDDEN_AGENT_ACTIONS:
        raise ForbiddenAgentActionError(f"forbidden agent action: {raw}")
    if raw not in ALLOWED_AGENT_ACTIONS:
        raise ForbiddenAgentActionError(f"unknown agent action: {raw}")
    out = dict(action)
    out["action"] = raw
    return out


__all__ = [
    "ALLOWED_AGENT_ACTIONS",
    "FORBIDDEN_AGENT_ACTIONS",
    "AgentActionType",
    "AgentStatus",
    "ForbiddenAgentActionError",
    "validate_agent_action",
]
