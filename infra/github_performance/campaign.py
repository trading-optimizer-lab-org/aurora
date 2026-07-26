"""Immutable, resumable campaign state for GitHub-only execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import (
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    canonical_sha256,
    deep_freeze_json,
    deep_thaw_json,
)


class CampaignPhase(str, Enum):
    PLANNED = "planned"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    REPLANNING = "replanning"
    READY_TO_MERGE = "ready_to_merge"
    MERGING = "merging"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    BLOCKED_EXTERNAL = "blocked_external"
    BLOCKED_HARD_FAILURE = "blocked_hard_failure"


class CampaignStateIntegrityError(RuntimeError):
    """Raised when immutable state or its latest pointer is invalid."""


class CampaignTransitionError(RuntimeError):
    """Raised when a transition would alter science or lose valid work."""


OPERATIONAL_REPLAN_FIELDS = frozenset(
    {
        "batch_size",
        "threads",
        "shard_size",
        "partitioning",
        "checkpoint_interval_seconds",
        "compression",
        "merge_fan_in",
        "requested_parallelism",
    }
)


class CampaignState(FrozenModel):
    schema_version: Literal["1"] = "1"
    campaign_id: str
    version: int = Field(ge=0)
    previous_state_sha256: str | None
    state_sha256: str
    phase: CampaignPhase
    scientific_contract_sha256: str
    logical_unit_manifest_sha256: str
    logical_unit_count: int = Field(ge=0)
    completed_unit_manifest_sha256: str | None
    completed_unit_count: int = Field(ge=0)
    pending_unit_count: int = Field(ge=0)
    active_plan_sha256: str
    operational_overrides: Mapping[str, Any]
    verified_source_artifacts: tuple[str, ...]
    active_attempt_ids: tuple[str, ...]
    wave: int = Field(ge=0)
    merge_only: bool
    compute_scheduled: bool
    hard_failure_reason: str | None
    created_at: datetime

    @field_validator(
        "state_sha256",
        "scientific_contract_sha256",
        "logical_unit_manifest_sha256",
        "active_plan_sha256",
        mode="after",
    )
    @classmethod
    def _require_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError("expected lowercase sha256")
        return value

    @field_validator("previous_state_sha256", "completed_unit_manifest_sha256")
    @classmethod
    def _require_optional_sha256(cls, value: str | None) -> str | None:
        if value is not None:
            cls._require_sha256(value)
        return value

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @field_validator("operational_overrides", mode="after")
    @classmethod
    def _freeze_overrides(
        cls,
        value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        unknown = set(value) - OPERATIONAL_REPLAN_FIELDS
        if unknown:
            raise ValueError(
                "non-operational replan fields: " + ",".join(sorted(unknown))
            )
        return deep_freeze_json(value)

    @field_serializer("operational_overrides")
    def _serialize_overrides(
        self,
        value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return deep_thaw_json(value)

    @model_validator(mode="after")
    def _validate_state(self) -> CampaignState:
        if self.completed_unit_count + self.pending_unit_count != (
            self.logical_unit_count
        ):
            raise ValueError("campaign unit counts do not reconcile")
        if self.version == 0 and self.previous_state_sha256 is not None:
            raise ValueError("initial state cannot have a predecessor")
        if self.version > 0 and self.previous_state_sha256 is None:
            raise ValueError("non-initial state requires predecessor")
        if self.completed_unit_count and (
            self.completed_unit_manifest_sha256 is None
        ):
            raise ValueError("completed units require immutable evidence")
        if self.merge_only and self.compute_scheduled:
            raise ValueError("merge-only cannot schedule compute")
        if canonical_sha256(_state_payload(self)) != self.state_sha256:
            raise ValueError("campaign state content hash mismatch")
        return self


def _state_payload(state: CampaignState | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(state, CampaignState):
        payload = deep_thaw_json(state)
    else:
        payload = deep_thaw_json(state)
    payload.pop("state_sha256", None)
    return payload


def _build_state(payload: Mapping[str, Any]) -> CampaignState:
    material = deep_thaw_json(payload)
    material.pop("state_sha256", None)
    material["state_sha256"] = canonical_sha256(material)
    return CampaignState.model_validate(material)


def initialize_campaign_state(
    *,
    campaign_id: str,
    scientific_contract_sha256: str,
    logical_unit_manifest_sha256: str,
    logical_unit_count: int,
    active_plan_sha256: str,
    created_at: datetime,
) -> CampaignState:
    return _build_state(
        {
            "schema_version": "1",
            "campaign_id": campaign_id,
            "version": 0,
            "previous_state_sha256": None,
            "phase": CampaignPhase.PLANNED,
            "scientific_contract_sha256": scientific_contract_sha256,
            "logical_unit_manifest_sha256": (
                logical_unit_manifest_sha256
            ),
            "logical_unit_count": logical_unit_count,
            "completed_unit_manifest_sha256": None,
            "completed_unit_count": 0,
            "pending_unit_count": logical_unit_count,
            "active_plan_sha256": active_plan_sha256,
            "operational_overrides": {},
            "verified_source_artifacts": (),
            "active_attempt_ids": (),
            "wave": 0,
            "merge_only": False,
            "compute_scheduled": True,
            "hard_failure_reason": None,
            "created_at": created_at,
        }
    )


_TERMINAL_PHASES = frozenset(
    {
        CampaignPhase.COMPLETED,
        CampaignPhase.BLOCKED_HARD_FAILURE,
    }
)


def transition_campaign_state(
    previous: CampaignState,
    *,
    phase: CampaignPhase,
    completed_unit_count: int | None = None,
    completed_unit_manifest_sha256: str | None = None,
    pending_unit_count: int | None = None,
    active_plan_sha256: str | None = None,
    operational_overrides: Mapping[str, Any] | None = None,
    verified_source_artifacts: tuple[str, ...] | None = None,
    active_attempt_ids: tuple[str, ...] | None = None,
    wave: int | None = None,
    merge_only: bool | None = None,
    compute_scheduled: bool | None = None,
    hard_failure_reason: str | None = None,
    created_at: datetime,
) -> CampaignState:
    if previous.phase in _TERMINAL_PHASES:
        raise CampaignTransitionError("terminal campaign cannot transition")
    completed = (
        previous.completed_unit_count
        if completed_unit_count is None
        else completed_unit_count
    )
    if completed < previous.completed_unit_count:
        raise CampaignTransitionError("completed units cannot regress")
    pending = (
        previous.logical_unit_count - completed
        if pending_unit_count is None
        else pending_unit_count
    )
    completed_sha = (
        previous.completed_unit_manifest_sha256
        if completed_unit_manifest_sha256 is None
        else completed_unit_manifest_sha256
    )
    if completed and completed_sha is None:
        raise CampaignTransitionError(
            "completed units require immutable manifest"
        )
    merge_mode = previous.merge_only if merge_only is None else merge_only
    default_compute = phase in {
        CampaignPhase.PLANNED,
        CampaignPhase.EXECUTING,
        CampaignPhase.RECOVERING,
        CampaignPhase.REPLANNING,
    }
    compute = default_compute if compute_scheduled is None else compute_scheduled
    if merge_mode:
        compute = False
    return _build_state(
        {
            "schema_version": "1",
            "campaign_id": previous.campaign_id,
            "version": previous.version + 1,
            "previous_state_sha256": previous.state_sha256,
            "phase": phase,
            "scientific_contract_sha256": (
                previous.scientific_contract_sha256
            ),
            "logical_unit_manifest_sha256": (
                previous.logical_unit_manifest_sha256
            ),
            "logical_unit_count": previous.logical_unit_count,
            "completed_unit_manifest_sha256": completed_sha,
            "completed_unit_count": completed,
            "pending_unit_count": pending,
            "active_plan_sha256": (
                active_plan_sha256 or previous.active_plan_sha256
            ),
            "operational_overrides": (
                operational_overrides
                if operational_overrides is not None
                else previous.operational_overrides
            ),
            "verified_source_artifacts": (
                tuple(sorted(verified_source_artifacts))
                if verified_source_artifacts is not None
                else previous.verified_source_artifacts
            ),
            "active_attempt_ids": (
                tuple(sorted(active_attempt_ids))
                if active_attempt_ids is not None
                else previous.active_attempt_ids
            ),
            "wave": previous.wave if wave is None else wave,
            "merge_only": merge_mode,
            "compute_scheduled": compute,
            "hard_failure_reason": hard_failure_reason,
            "created_at": created_at,
        }
    )


def replan_campaign_state(
    previous: CampaignState,
    *,
    new_plan_sha256: str,
    logical_unit_manifest_sha256: str,
    completed_unit_manifest_sha256: str | None,
    operational_overrides: Mapping[str, Any],
    created_at: datetime,
) -> CampaignState:
    if (
        logical_unit_manifest_sha256
        != previous.logical_unit_manifest_sha256
    ):
        raise CampaignTransitionError(
            "replan cannot change logical unit manifest"
        )
    if (
        completed_unit_manifest_sha256
        != previous.completed_unit_manifest_sha256
    ):
        raise CampaignTransitionError(
            "replan cannot change completed unit evidence"
        )
    unknown = set(operational_overrides) - OPERATIONAL_REPLAN_FIELDS
    if unknown:
        raise CampaignTransitionError(
            "replan contains non-operational fields: "
            + ",".join(sorted(unknown))
        )
    return transition_campaign_state(
        previous,
        phase=CampaignPhase.PLANNED,
        active_plan_sha256=new_plan_sha256,
        operational_overrides=operational_overrides,
        merge_only=False,
        compute_scheduled=True,
        created_at=created_at,
    )


def begin_merge_only(
    previous: CampaignState,
    *,
    source_artifacts: tuple[str, ...],
    created_at: datetime,
) -> CampaignState:
    sources = tuple(sorted(source_artifacts))
    if previous.pending_unit_count:
        raise CampaignTransitionError(
            "merge-only requires every logical unit to be terminal"
        )
    if not sources or sources != tuple(
        sorted(previous.verified_source_artifacts)
    ):
        raise CampaignTransitionError(
            "merge-only source artifacts are not exactly verified"
        )
    return transition_campaign_state(
        previous,
        phase=CampaignPhase.MERGING,
        verified_source_artifacts=sources,
        merge_only=True,
        compute_scheduled=False,
        created_at=created_at,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_filename(version: int) -> str:
    return f"campaign_state_v{version:06d}.json"


def _atomic_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = deep_thaw_json(payload)
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _write_latest_pointer(root: Path, state: CampaignState, path: Path) -> Path:
    return _atomic_json(
        root / "campaign_state_latest.json",
        {
            "schema_version": "1",
            "campaign_id": state.campaign_id,
            "version": state.version,
            "state_file": path.name,
            "state_sha256": _file_sha256(path),
            "content_sha256": state.state_sha256,
        },
    )


def write_campaign_state(state: CampaignState, root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / _state_filename(state.version)
    if path.exists():
        raise CampaignStateIntegrityError(
            f"immutable state already exists: {path.name}"
        )
    pointer = root / "campaign_state_latest.json"
    if pointer.exists():
        latest = load_latest_campaign_state(root)
        if state.version != latest.version + 1:
            raise CampaignStateIntegrityError(
                "campaign state version is not monotonic"
            )
        if state.previous_state_sha256 != latest.state_sha256:
            raise CampaignStateIntegrityError(
                "campaign state predecessor mismatch"
            )
    elif state.version != 0:
        raise CampaignStateIntegrityError(
            "non-initial state requires latest pointer"
        )
    _atomic_json(path, state)
    _write_latest_pointer(root, state, path)
    return path


def load_latest_campaign_state(root: Path) -> CampaignState:
    root = Path(root)
    pointer_path = root / "campaign_state_latest.json"
    if not pointer_path.is_file():
        raise FileNotFoundError(pointer_path)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    filename = str(pointer.get("state_file", ""))
    if Path(filename).name != filename or not filename.startswith(
        "campaign_state_v"
    ):
        raise CampaignStateIntegrityError("invalid campaign state pointer")
    state_path = root / filename
    if not state_path.is_file():
        raise CampaignStateIntegrityError("pointed campaign state is missing")
    if _file_sha256(state_path) != pointer.get("state_sha256"):
        raise CampaignStateIntegrityError("state hash mismatch")
    try:
        state = CampaignState.model_validate_json(
            state_path.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise CampaignStateIntegrityError(str(exc)) from exc
    if (
        pointer.get("campaign_id") != state.campaign_id
        or pointer.get("version") != state.version
        or pointer.get("content_sha256") != state.state_sha256
    ):
        raise CampaignStateIntegrityError("latest pointer identity mismatch")
    return state


def resume_campaign_state(
    root: Path,
    *,
    campaign_id: str,
) -> CampaignState:
    """Recover the highest valid contiguous state and repair its pointer."""

    root = Path(root)
    paths = sorted(root.glob("campaign_state_v[0-9][0-9][0-9][0-9][0-9][0-9].json"))
    if not paths:
        raise FileNotFoundError("no immutable campaign state exists")
    states: list[CampaignState] = []
    for path in paths:
        try:
            state = CampaignState.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except ValueError as exc:
            raise CampaignStateIntegrityError(str(exc)) from exc
        if state.campaign_id != campaign_id:
            continue
        expected_version = len(states)
        if state.version != expected_version:
            break
        if states and (
            state.previous_state_sha256 != states[-1].state_sha256
        ):
            break
        states.append(state)
    if not states:
        raise CampaignStateIntegrityError(
            "no valid contiguous campaign state chain"
        )
    latest = states[-1]
    latest_path = root / _state_filename(latest.version)
    _write_latest_pointer(root, latest, latest_path)
    return latest
