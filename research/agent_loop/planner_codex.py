"""Codex CLI planner for Aurora autonomous research loops."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from aurora.research.agent_loop.actions import (
    AgentActionType,
    validate_agent_action,
)
from aurora.research.agent_loop.goal import AgentGoalSpec


Runner = Callable[[list[str], Path], str]


class CodexCliPlanner:
    """Plan next actions with local authenticated ``codex exec``."""

    def __init__(
        self,
        *,
        dry_run: bool = True,
        runner: Runner | None = None,
        codex_bin: str = "codex",
        timeout_seconds: int = 1800,
    ):
        self.dry_run = dry_run
        self.runner = runner or self._run_codex
        self.codex_bin = codex_bin
        self.timeout_seconds = int(timeout_seconds)

    def plan_next(
        self,
        *,
        goal: AgentGoalSpec,
        state: Mapping[str, Any],
        worktree: Path,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        if self.dry_run:
            if int(state.get("step", 0)) <= 0:
                return {"action": AgentActionType.RUN_AUTOSEARCH.value}
            return {"action": AgentActionType.DISCOVER_SOURCES.value}

        prompt = self._prompt(goal=goal, state=state, context=context or {})
        raw = self.runner(
            [self.codex_bin, "--search", "exec", "-C", str(worktree), prompt],
            worktree,
        )
        payload = _extract_action_json(raw)
        if not isinstance(payload, dict):
            raise ValueError("Codex planner JSON must be an object")
        return validate_agent_action(payload)

    @staticmethod
    def _prompt(
        *,
        goal: AgentGoalSpec,
        state: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> str:
        return (
            "You are Aurora Planner. Return ONLY JSON, no markdown. "
            "Schema: {\"action\":\"RUN_AUTOSEARCH|DISCOVER_SOURCES|"
            "DISCOVER_STRATEGY_IDEAS|"
            "ASK_CODEX_FOR_IDEAS|ASK_CODEX_FOR_FAILURE_REVIEW|"
            "ASK_CODEX_FOR_CONNECTOR_PLAN|BUILD_SOURCE_CONNECTOR|"
            "VALIDATE_NEW_DATA|GENERATE_FEATURE_SET|RUN_TRAIN_SEARCH|"
            "RUN_ROBUSTNESS|RUN_VALIDATION_EXAM|ARCHIVE_FAILED_IDEA|"
            "EXPAND_CATALOG|WRITE_REPORT\", \"reason\":\"...\"}. "
            "Use DISCOVER_STRATEGY_IDEAS when fresh literature should be searched "
            "through the local ESTUDIOS project. "
            "When action is ASK_CODEX_FOR_IDEAS, include an 'ideas' array. "
            "Each idea must be {\"idea_id\":\"safe_unique_id\", "
            "\"features\":[\"causal feature names\"], "
            "\"rule_family\":\"drawdown_volatility|trend_stress_combo|"
            "defensive_ratio_blend|regime_switch\", "
            "\"hypothesis\":\"...\", \"allowed_data\":[\"train only\"], "
            "\"forbidden\":[\"locked\", \"future data\"]}. "
            "Never request locked access, live trading, pushing to main, "
            "deleting data, or silencing tests. "
            f"Goal: {json.dumps(goal.to_dict(), sort_keys=True)}. "
            f"State: {json.dumps(dict(state), default=str, sort_keys=True)}. "
            f"Context: {json.dumps(dict(context), default=str, sort_keys=True)}."
        )

    def _run_codex(self, cmd: list[str], cwd: Path) -> str:
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Codex planner timed out after {self.timeout_seconds} seconds"
            ) from exc
        return proc.stdout.strip()


def _extract_action_json(raw: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    try:
        direct = json.loads(raw)
        if isinstance(direct, dict):
            candidates.append(direct)
    except json.JSONDecodeError:
        pass
    for line in raw.splitlines():
        text = line.strip()
        if not text.startswith("{") or not text.endswith("}"):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    decoder = json.JSONDecoder()
    for idx, char in enumerate(raw):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    for candidate in reversed(candidates):
        if "action" in candidate:
            return candidate
    raise ValueError("Codex planner must return a JSON action object")


__all__ = ["CodexCliPlanner"]
