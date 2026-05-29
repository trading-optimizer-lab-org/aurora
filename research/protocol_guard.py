"""Generic research protocol guard.

This module is deliberately domain-neutral. It does not know whether a
research project is about SPY strategies, factor screens, papers, ML models
or portfolio rules. It only enforces the workflow:

* declare the protocol before searching;
* select only from allowed phases;
* treat locked phases as report-only;
* require a passed robustness run before locked can be reported;
* block further candidate generation after a locked result was observed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

import pandas as pd

from aurora.research.ledger import LedgerEvent, LedgerEventType, ResearchLedger


DEFAULT_ROBUSTNESS_CHECKS = (
    "reproducibility",
    "lookahead",
    "stress",
)


class LockedResearchPhaseError(RuntimeError):
    """Raised when research tries to use a locked phase for selection."""


@dataclass(frozen=True)
class ResearchProtocolSpec:
    """Generic contract for one research project.

    ``allowed_selection_phases`` are the only phases that may influence
    candidate choice. ``locked_phases`` may be reported after selection, but
    must never be used to pick or tune the candidate.
    """

    project_id: str
    objective: str
    metric: str
    allowed_selection_phases: tuple[str, ...]
    locked_phases: tuple[str, ...]
    constraints: Mapping[str, Any] = field(default_factory=dict)
    robustness_checks: tuple[str, ...] = DEFAULT_ROBUSTNESS_CHECKS
    max_trials: int | None = None
    selection_data_end: str | None = None
    locked_data_start: str | None = None
    locked_data_end: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id is required")
        if not self.objective.strip():
            raise ValueError("objective is required")
        if not self.metric.strip():
            raise ValueError("metric is required")
        if not self.allowed_selection_phases:
            raise ValueError("at least one allowed selection phase is required")
        cleaned_robustness = tuple(str(check).strip() for check in self.robustness_checks)
        if any(not check for check in cleaned_robustness):
            raise ValueError("robustness checks cannot be empty")
        if len(set(cleaned_robustness)) < 3:
            raise ValueError(
                "at least three distinct robustness checks are required"
            )
        overlap = set(self.allowed_selection_phases) & set(self.locked_phases)
        if overlap:
            raise ValueError(
                "phases cannot be both selectable and locked: "
                + ", ".join(sorted(overlap))
            )
        if self.selection_data_end and self.locked_data_start:
            selection_end = pd.Timestamp(self.selection_data_end)
            locked_start = pd.Timestamp(self.locked_data_start)
            if selection_end >= locked_start:
                raise ValueError("selection_data_end must be before locked_data_start")

    @property
    def known_phases(self) -> set[str]:
        return set(self.allowed_selection_phases) | set(self.locked_phases)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_selection_phases"] = list(self.allowed_selection_phases)
        payload["locked_phases"] = list(self.locked_phases)
        payload["constraints"] = dict(self.constraints)
        payload["robustness_checks"] = list(self.robustness_checks)
        return payload


class ResearchProtocolGuard:
    """Ledger-backed guard for a single research project."""

    def __init__(self, spec: ResearchProtocolSpec, ledger: ResearchLedger) -> None:
        self.spec = spec
        self.ledger = ledger

    def declare(self, *, actor: str, payload: Mapping[str, Any] | None = None) -> LedgerEvent:
        body = self.spec.to_payload()
        existing = [
            event for event in self.ledger.events(project_id=self.spec.project_id)
            if event.event_type is LedgerEventType.PROTOCOL_DECLARED
        ]
        if existing:
            previous = existing[-1].payload
            conflicts = [
                key for key, value in body.items()
                if previous.get(key) != value
                # Legacy protocol declarations created before the robustness
                # checklist became mandatory did not store this field. Accept
                # those old declarations, but still reject explicit conflicts
                # when both sides define it.
                and not (key == "robustness_checks" and key not in previous)
            ]
            if conflicts:
                raise LockedResearchPhaseError(
                    "research protocol already declared with different "
                    "contract fields: " + ", ".join(sorted(conflicts))
                )
            return existing[-1]
        if payload:
            body.update(dict(payload))
        return self.ledger.append(
            LedgerEventType.PROTOCOL_DECLARED,
            project_id=self.spec.project_id,
            actor=actor,
            payload=body,
        )

    def record_candidate_generated(
        self,
        candidate_id: str,
        *,
        actor: str,
        payload: Mapping[str, Any] | None = None,
    ) -> LedgerEvent:
        self._assert_protocol_declared()
        self._assert_locked_not_observed()
        self._assert_non_empty_candidate_id(candidate_id)
        body = {"candidate_id": candidate_id}
        if payload:
            body.update(dict(payload))
        return self.ledger.append(
            LedgerEventType.CANDIDATE_GENERATED,
            project_id=self.spec.project_id,
            actor=actor,
            payload=body,
        )

    def record_selection(
        self,
        candidate_id: str,
        *,
        phases_used: Sequence[str],
        metrics: Mapping[str, Any],
        actor: str,
        payload: Mapping[str, Any] | None = None,
    ) -> LedgerEvent:
        self._assert_protocol_declared()
        self._assert_locked_not_observed()
        self._assert_non_empty_candidate_id(candidate_id)
        self._assert_candidate_generated(candidate_id)
        self.assert_selection_phases(phases_used)
        body = {
            "candidate_id": candidate_id,
            "phases_used": list(phases_used),
            "metrics": dict(metrics),
        }
        if payload:
            body.update(dict(payload))
        return self.ledger.append(
            LedgerEventType.SELECTION_RUN,
            project_id=self.spec.project_id,
            actor=actor,
            payload=body,
        )

    def record_robustness_run(
        self,
        candidate_id: str,
        *,
        checks: Sequence[str],
        passed: bool,
        metrics: Mapping[str, Any] | None = None,
        actor: str,
        payload: Mapping[str, Any] | None = None,
    ) -> LedgerEvent:
        """Record the mandatory robustness gate for a candidate.

        The protocol deliberately keeps the check names generic because a
        paper-replication project, a trading strategy and an execution model
        need different stress tests. The common rule is strict: the event must
        exist, it must name the selected candidate, and ``passed`` must be true
        before locked data can be reported.
        """
        self._assert_protocol_declared()
        self._assert_locked_not_observed()
        self._assert_non_empty_candidate_id(candidate_id)
        self._assert_candidate_generated(candidate_id)
        cleaned_checks = tuple(str(check).strip() for check in checks)
        if not cleaned_checks or any(not check for check in cleaned_checks):
            raise ValueError("at least one robustness check is required")
        unique_checks = tuple(dict.fromkeys(cleaned_checks))
        if passed and len(unique_checks) < 3:
            raise ValueError(
                "a passed robustness run requires at least three distinct checks"
            )
        if passed and not metrics:
            raise ValueError("a passed robustness run requires metrics evidence")
        body = {
            "candidate_id": candidate_id,
            "checks": list(unique_checks),
            "passed": bool(passed),
            "metrics": dict(metrics or {}),
        }
        if payload:
            body.update(dict(payload))
        return self.ledger.append(
            LedgerEventType.ROBUSTNESS_RUN,
            project_id=self.spec.project_id,
            actor=actor,
            payload=body,
        )

    def record_locked_result(
        self,
        candidate_id: str,
        *,
        phase: str,
        metrics: Mapping[str, Any],
        actor: str,
        payload: Mapping[str, Any] | None = None,
    ) -> LedgerEvent:
        self._assert_protocol_declared()
        self._assert_locked_not_observed()
        self._assert_non_empty_candidate_id(candidate_id)
        if phase not in self.spec.locked_phases:
            raise LockedResearchPhaseError(f"{phase!r} is not a locked phase")
        selected = self._selected_candidate()
        if selected is None:
            raise LockedResearchPhaseError("locked result cannot be reported before selection")
        if selected != candidate_id:
            raise LockedResearchPhaseError(
                f"locked result candidate {candidate_id!r} is not the selected candidate {selected!r}"
            )
        self._assert_robustness_passed(candidate_id)
        if not metrics:
            raise ValueError("locked result requires metrics evidence")
        body = {
            "candidate_id": candidate_id,
            "phase": phase,
            "metrics": dict(metrics),
            "report_only": True,
        }
        if payload:
            body.update(dict(payload))
        return self.ledger.append(
            LedgerEventType.LOCKED_RESULT_REPORTED,
            project_id=self.spec.project_id,
            actor=actor,
            payload=body,
        )

    def assert_robustness_passed(self, candidate_id: str) -> None:
        self._assert_robustness_passed(candidate_id)

    def assert_selection_data(self, data: Any, *, label: str = "data") -> None:
        """Reject selection data that contains rows from a locked period."""
        idx = _datetime_index(data, label=label)
        if len(idx) == 0:
            return
        max_ts = pd.Timestamp(idx.max()).tz_localize(None)
        if self.spec.locked_data_start:
            locked_start = pd.Timestamp(self.spec.locked_data_start)
            if max_ts >= locked_start:
                raise LockedResearchPhaseError(
                    f"{label} contains locked data at or after "
                    f"{locked_start.date().isoformat()}"
                )
        if self.spec.selection_data_end:
            selection_end = pd.Timestamp(self.spec.selection_data_end)
            if max_ts > selection_end:
                raise LockedResearchPhaseError(
                    f"{label} extends beyond selection_data_end "
                    f"{selection_end.date().isoformat()}"
                )

    def restrict_to_selection_data(self, data: Any) -> Any:
        """Return a physical copy with locked rows removed."""
        idx = _datetime_index(data, label="data")
        if len(idx) == 0:
            return data.copy()
        mask = pd.Series(True, index=idx)
        if self.spec.locked_data_start:
            mask &= idx < pd.Timestamp(self.spec.locked_data_start)
        if self.spec.selection_data_end:
            mask &= idx <= pd.Timestamp(self.spec.selection_data_end)
        visible = data.loc[mask.to_numpy()].copy()
        self.assert_selection_data(visible)
        return visible

    def assert_selection_phases(self, phases: Sequence[str]) -> None:
        unknown = sorted(set(phases) - self.spec.known_phases)
        if unknown:
            raise LockedResearchPhaseError(
                "unknown phase used in selection: " + ", ".join(unknown)
            )
        locked = sorted(set(phases) & set(self.spec.locked_phases))
        if locked:
            raise LockedResearchPhaseError(
                "locked phases cannot be used for selection: " + ", ".join(locked)
            )

    def _selected_candidate(self) -> str | None:
        for event in reversed(self.ledger.events(project_id=self.spec.project_id)):
            if event.event_type is LedgerEventType.SELECTION_RUN:
                candidate_id = event.payload.get("candidate_id")
                return str(candidate_id) if candidate_id is not None else None
        return None

    def _assert_protocol_declared(self) -> None:
        for event in self.ledger.events(project_id=self.spec.project_id):
            if event.event_type is LedgerEventType.PROTOCOL_DECLARED:
                return
        raise LockedResearchPhaseError(
            "research protocol must be declared before generating, selecting, "
            "validating, or reporting candidates"
        )

    def _assert_locked_not_observed(self) -> None:
        for event in self.ledger.events(project_id=self.spec.project_id):
            if event.event_type is LedgerEventType.LOCKED_RESULT_REPORTED:
                raise LockedResearchPhaseError(
                    "candidate generation is blocked because a locked result "
                    "has already been reported"
                )

    def _assert_candidate_generated(self, candidate_id: str) -> None:
        for event in self.ledger.events(project_id=self.spec.project_id):
            if event.event_type is not LedgerEventType.CANDIDATE_GENERATED:
                continue
            if str(event.payload.get("candidate_id")) == candidate_id:
                return
        raise LockedResearchPhaseError(
            f"candidate {candidate_id!r} must be generated before selection "
            "or robustness can be recorded"
        )

    @staticmethod
    def _assert_non_empty_candidate_id(candidate_id: str) -> None:
        if not str(candidate_id).strip():
            raise ValueError("candidate_id is required")

    def _assert_robustness_passed(self, candidate_id: str) -> None:
        events = self.ledger.events(project_id=self.spec.project_id)
        selected_index = None
        for idx, event in enumerate(events):
            if event.event_type is not LedgerEventType.SELECTION_RUN:
                continue
            if str(event.payload.get("candidate_id")) == candidate_id:
                selected_index = idx
        for idx, event in reversed(list(enumerate(events))):
            if event.event_type is not LedgerEventType.ROBUSTNESS_RUN:
                continue
            if str(event.payload.get("candidate_id")) != candidate_id:
                continue
            if selected_index is not None and idx < selected_index:
                raise LockedResearchPhaseError(
                    "locked result cannot be reported because robustness "
                    "was recorded before selection"
                )
            if event.payload.get("passed") is True:
                return
            raise LockedResearchPhaseError(
                "locked result cannot be reported because the latest "
                "robustness run did not pass"
            )
        raise LockedResearchPhaseError(
            "locked result cannot be reported before a passed robustness run"
        )


def _datetime_index(data: Any, *, label: str) -> pd.DatetimeIndex:
    if isinstance(data, pd.DatetimeIndex):
        idx = data
    elif isinstance(data, pd.Index):
        idx = pd.DatetimeIndex(data)
    elif hasattr(data, "index"):
        idx = pd.DatetimeIndex(data.index)
    else:
        raise TypeError(f"{label} must have a DatetimeIndex")
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return pd.DatetimeIndex(idx)


__all__ = [
    "LockedResearchPhaseError",
    "DEFAULT_ROBUSTNESS_CHECKS",
    "ResearchProtocolGuard",
    "ResearchProtocolSpec",
]
