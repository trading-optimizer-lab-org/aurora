"""Mandatory research protocol enforcement helpers.

This module is intentionally small and boring. CLI commands and research
pipelines use it to make the unified operating protocol unavoidable:
every decision-bearing run gets a protocol declaration, a minimal ledger
chain, and a candidate-generation record before validation can happen.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from aurora.core.runtime_paths import base_data_dir
from aurora.research.ledger import LedgerEventType, ResearchLedger
from aurora.research.protocol_guard import (
    LockedResearchPhaseError,
    ResearchProtocolGuard,
    ResearchProtocolSpec,
)


def default_research_ledger_path() -> Path:
    return base_data_dir() / "research_protocol_ledger.jsonl"


def make_project_id(*parts: object) -> str:
    raw = "_".join(str(p).strip().lower() for p in parts if str(p).strip())
    cleaned = []
    last_was_sep = False
    for ch in raw:
        ok = ch.isalnum()
        if ok:
            cleaned.append(ch)
            last_was_sep = False
        elif not last_was_sep:
            cleaned.append("_")
            last_was_sep = True
    return "".join(cleaned).strip("_") or "aurora_research"


def ensure_mandatory_research_protocol(
    *,
    project_id: str,
    objective: str,
    metric: str,
    universe: Sequence[str],
    providers: Sequence[str],
    date_range: Mapping[str, Any],
    features: Sequence[str],
    seed: int | str | None,
    candidate_id: str,
    allowed_selection_phases: Sequence[str] = ("train", "validation", "oos_dev"),
    locked_phases: Sequence[str] = ("oos_locked", "forward"),
    constraints: Mapping[str, Any] | None = None,
    robustness_checks: Sequence[str] | None = None,
    max_trials: int | None = None,
    selection_data_end: str | None = None,
    locked_data_start: str | None = None,
    locked_data_end: str | None = None,
    actor: str = "aurora",
    ledger_path: str | Path | None = None,
) -> ResearchProtocolGuard:
    """Declare and populate the mandatory ledger chain for a research run.

    The function is idempotent for the static declaration events and
    intentionally non-idempotent for ``candidate_generated``. Re-running
    a project records extra search pressure. If locked has already been
    reported, candidate generation raises through ``ResearchProtocolGuard``.
    """

    ledger = ResearchLedger(
        Path(ledger_path) if ledger_path is not None
        else default_research_ledger_path()
    )
    spec = ResearchProtocolSpec(
        project_id=project_id,
        objective=objective,
        metric=metric,
        allowed_selection_phases=tuple(allowed_selection_phases),
        locked_phases=tuple(locked_phases),
        constraints=dict(constraints or {}),
        robustness_checks=tuple(robustness_checks) if robustness_checks else (
            "reproducibility",
            "lookahead",
            "stress",
        ),
        max_trials=max_trials,
        selection_data_end=selection_data_end,
        locked_data_start=locked_data_start,
        locked_data_end=locked_data_end,
    )
    guard = ResearchProtocolGuard(spec, ledger)
    try:
        guard.declare(actor=actor)
    except LockedResearchPhaseError as exc:
        if "different contract fields" not in str(exc):
            raise
        project_id = f"{project_id}_{_contract_suffix(spec.to_payload())}"
        spec = ResearchProtocolSpec(
            project_id=project_id,
            objective=objective,
            metric=metric,
            allowed_selection_phases=tuple(allowed_selection_phases),
            locked_phases=tuple(locked_phases),
            constraints=dict(constraints or {}),
            robustness_checks=tuple(robustness_checks) if robustness_checks else (
                "reproducibility",
                "lookahead",
                "stress",
            ),
            max_trials=max_trials,
            selection_data_end=selection_data_end,
            locked_data_start=locked_data_start,
            locked_data_end=locked_data_end,
        )
        guard = ResearchProtocolGuard(spec, ledger)
        guard.declare(
            actor=actor,
            payload={
                "base_project_id": project_id.rsplit("_", 1)[0],
                "contract_collision_resolved": True,
            },
        )

    _append_once(
        ledger,
        project_id,
        LedgerEventType.UNIVERSE_SELECTED,
        actor=actor,
        payload={"universe": list(universe)},
    )
    _append_once(
        ledger,
        project_id,
        LedgerEventType.PROVIDER_SET,
        actor=actor,
        payload={"providers": list(providers)},
    )
    _append_once(
        ledger,
        project_id,
        LedgerEventType.DATE_RANGE_SET,
        actor=actor,
        payload=dict(date_range),
    )
    _append_once(
        ledger,
        project_id,
        LedgerEventType.FEATURE_SET,
        actor=actor,
        payload={"features": list(features)},
    )
    _append_once(
        ledger,
        project_id,
        LedgerEventType.PARAMETER_GRID,
        actor=actor,
        payload={"n_choices": int(max_trials) if max_trials is not None else 1},
    )
    _append_once(
        ledger,
        project_id,
        LedgerEventType.SEED_SET,
        actor=actor,
        payload={"seed": seed},
    )

    guard.record_candidate_generated(
        candidate_id,
        actor=actor,
        payload={
            "objective": objective,
            "metric": metric,
            "constraints": dict(constraints or {}),
        },
    )
    ledger.assert_ready_for_validation(project_id)
    return guard


def record_validation_run(
    guard: ResearchProtocolGuard,
    *,
    candidate_id: str,
    actor: str = "aurora",
    metrics: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    body = {"candidate_id": candidate_id, "metrics": dict(metrics or {})}
    if payload:
        body.update(dict(payload))
    guard.ledger.append(
        LedgerEventType.VALIDATION_RUN,
        project_id=guard.spec.project_id,
        actor=actor,
        payload=body,
    )


def record_robustness_run(
    guard: ResearchProtocolGuard,
    *,
    candidate_id: str,
    checks: Sequence[str],
    passed: bool,
    actor: str = "aurora",
    metrics: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> None:
    guard.record_robustness_run(
        candidate_id,
        checks=checks,
        passed=passed,
        metrics=metrics or {},
        actor=actor,
        payload=payload,
    )


def _append_once(
    ledger: ResearchLedger,
    project_id: str,
    event_type: LedgerEventType,
    *,
    actor: str,
    payload: Mapping[str, Any],
) -> None:
    if any(
        event.event_type is event_type
        for event in ledger.events(project_id=project_id)
    ):
        return
    ledger.append(
        event_type,
        project_id=project_id,
        actor=actor,
        payload=dict(payload),
    )


def _contract_suffix(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(payload), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]


__all__ = [
    "default_research_ledger_path",
    "ensure_mandatory_research_protocol",
    "make_project_id",
    "record_robustness_run",
    "record_validation_run",
]
