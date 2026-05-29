"""Goal contract parsing for Aurora autonomous research loops."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class AgentGoalConstraints:
    only_long_or_short: bool
    always_fully_invested: bool
    leverage_allowed: bool
    cash_allowed: bool
    traded_assets: tuple[str, ...]
    external_signals_allowed: bool


@dataclass(frozen=True)
class AgentGoalProtocol:
    optimise_on: str
    validation_role: str
    locked_role: str
    open_locked: bool
    robustness_required: bool
    trial_logging_required: bool


@dataclass(frozen=True)
class AgentGoalLoopPolicy:
    stop_when_objective_met: bool
    continue_on_failure: bool
    pause_only_when_all_routes_blocked: bool
    no_improvement_round_limit: int | None = None


@dataclass(frozen=True)
class AgentGoalSpec:
    goal_id: str
    instrument: str
    target_metric: str
    target_value: float
    constraints: AgentGoalConstraints
    protocol: AgentGoalProtocol
    loop: AgentGoalLoopPolicy

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "instrument": self.instrument,
            "target_metric": self.target_metric,
            "target_value": self.target_value,
            "constraints": {
                "only_long_or_short": self.constraints.only_long_or_short,
                "always_fully_invested": self.constraints.always_fully_invested,
                "leverage_allowed": self.constraints.leverage_allowed,
                "cash_allowed": self.constraints.cash_allowed,
                "traded_assets": list(self.constraints.traded_assets),
                "external_signals_allowed": self.constraints.external_signals_allowed,
            },
            "protocol": {
                "optimise_on": self.protocol.optimise_on,
                "validation_role": self.protocol.validation_role,
                "locked_role": self.protocol.locked_role,
                "open_locked": self.protocol.open_locked,
                "robustness_required": self.protocol.robustness_required,
                "trial_logging_required": self.protocol.trial_logging_required,
            },
            "loop": {
                "stop_when_objective_met": self.loop.stop_when_objective_met,
                "continue_on_failure": self.loop.continue_on_failure,
                "pause_only_when_all_routes_blocked": (
                    self.loop.pause_only_when_all_routes_blocked
                ),
            },
        }


def load_goal_spec(path: str | Path) -> AgentGoalSpec:
    """Load and validate an agent goal YAML file."""

    goal_path = Path(path)
    data = yaml.safe_load(goal_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        raise ValueError("goal yaml must contain a mapping")
    constraints = _mapping(data, "constraints")
    protocol = _mapping(data, "protocol")
    loop = _mapping(data, "loop")
    spec = AgentGoalSpec(
        goal_id=_required_str(data, "goal_id"),
        instrument=_required_str(data, "instrument"),
        target_metric=_required_str(data, "target_metric"),
        target_value=float(data.get("target_value")),
        constraints=AgentGoalConstraints(
            only_long_or_short=bool(constraints.get("only_long_or_short")),
            always_fully_invested=bool(constraints.get("always_fully_invested")),
            leverage_allowed=bool(constraints.get("leverage_allowed")),
            cash_allowed=bool(constraints.get("cash_allowed")),
            traded_assets=tuple(str(x) for x in constraints.get("traded_assets", ())),
            external_signals_allowed=bool(constraints.get("external_signals_allowed")),
        ),
        protocol=AgentGoalProtocol(
            optimise_on=str(protocol.get("optimise_on", "")),
            validation_role=str(protocol.get("validation_role", "")),
            locked_role=str(protocol.get("locked_role", "")),
            open_locked=bool(protocol.get("open_locked")),
            robustness_required=bool(protocol.get("robustness_required")),
            trial_logging_required=bool(protocol.get("trial_logging_required")),
        ),
        loop=AgentGoalLoopPolicy(
            stop_when_objective_met=bool(loop.get("stop_when_objective_met")),
            continue_on_failure=bool(loop.get("continue_on_failure")),
            pause_only_when_all_routes_blocked=bool(
                loop.get("pause_only_when_all_routes_blocked")
            ),
            no_improvement_round_limit=None,
        ),
    )
    _validate_goal(spec)
    return spec


def _mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"goal section {key!r} must be a mapping")
    return value


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise ValueError(f"goal field {key!r} is required")
    return value


def _validate_goal(spec: AgentGoalSpec) -> None:
    if spec.protocol.open_locked:
        raise ValueError("goal protocol open_locked must be false for agent-loop")
    if not spec.constraints.traded_assets:
        raise ValueError("goal constraints traded_assets must not be empty")
    if spec.instrument not in spec.constraints.traded_assets:
        raise ValueError("instrument must be included in traded_assets")
    if spec.target_value <= 0:
        raise ValueError("target_value must be positive")
    if spec.protocol.optimise_on != "train":
        raise ValueError("agent-loop only supports optimise_on=train")
    if spec.protocol.validation_role != "exam_only":
        raise ValueError("validation_role must be exam_only")
    if spec.protocol.locked_role != "final_only":
        raise ValueError("locked_role must be final_only")
    if not spec.loop.stop_when_objective_met:
        raise ValueError("stop_when_objective_met must be true")
    if not spec.loop.continue_on_failure:
        raise ValueError("continue_on_failure must be true")
    if spec.loop.pause_only_when_all_routes_blocked:
        raise ValueError(
            "pause_only_when_all_routes_blocked must be false; "
            "agent-loop stops only on objective or explicit stop request"
        )


__all__ = [
    "AgentGoalConstraints",
    "AgentGoalLoopPolicy",
    "AgentGoalProtocol",
    "AgentGoalSpec",
    "load_goal_spec",
]
