"""Closed, source-bound profile for SP500 checkpoint recovery.

This module is deliberately a controller-light contract.  It validates the
authenticated profile emitted by the parent configuration step; it does not
read GitHub, inspect checkpoint bytes, import a scientific dataframe runtime,
or derive a source result set.  The configuration is the only place where
the authenticated artifact pins live.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from .catalog_request_contract import FrozenModel, Sha256


CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH = "config/catalog_checkpoint_recovery_profiles_v1.json"
CHECKPOINT_RECOVERY_CAMPAIGN_KEY = "sp500-optimized-catalog-v1"
CHECKPOINT_RECOVERY_TARGET_GENERATION = 8
CHECKPOINT_RECOVERY_SOURCE_GENERATION = 7
CHECKPOINT_RECOVERY_SOURCE_REQUEST_SHA256 = (
    "db7838f228058a301bb369a02e7133096cc48846cf0be8d6dac79372152ba2e1"
)
CHECKPOINT_RECOVERY_SOURCE_ISSUE_NUMBER = 339
CHECKPOINT_RECOVERY_SOURCE_RUN_ID = 35504391586
CHECKPOINT_RECOVERY_SOURCE_RUN_ATTEMPT = 1
CHECKPOINT_RECOVERY_SOURCE_PROTECTED_COMMIT_SHA = (
    "d12a374ab84bfb4e79bd5039343ffd5bd963c115"
)
CHECKPOINT_RECOVERY_EXECUTION_PLAN_SHA256 = (
    "d2bce38b7382cc9dbcb3327337b68ef037813bb2310fe3157016b443070da9b9"
)
CHECKPOINT_RECOVERY_SCIENCE_SHA256 = (
    "f0e8c6db17a915f7c5f1dfec7d49ce5a69375c7252c23b49d82283120266419f"
)
CHECKPOINT_RECOVERY_SOURCE_PLAN_RECEIPT_SHA256 = (
    "6f7707ae33b710a0114d67c9b5bb12f204a08003c273332415341c978d08e889"
)
CHECKPOINT_RECOVERY_EXPECTED_RESULT_COUNT = 18630
CHECKPOINT_RECOVERY_EXPECTED_TOTAL_COUNT = 37258
CHECKPOINT_RECOVERY_WORKER_COUNT = 30
CHECKPOINT_RECOVERY_SLOT_COUNT = 4
CHECKPOINT_RECOVERY_CHECKPOINT_COUNT = (
    CHECKPOINT_RECOVERY_WORKER_COUNT * CHECKPOINT_RECOVERY_SLOT_COUNT
)
_CONFIG_MAX_BYTES = 256 * 1024

# Keep aliases in the same vocabulary as the older closed recovery profile.
RECOVERY_CONFIG_RELATIVE_PATH = CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH
RECOVERY_CAMPAIGN_KEY = CHECKPOINT_RECOVERY_CAMPAIGN_KEY
RECOVERY_TARGET_GENERATION = CHECKPOINT_RECOVERY_TARGET_GENERATION

_SOURCE_PLAN_BINDING_KEYS = frozenset(
    {
        "request_sha256",
        "decision_sha256",
        "protected_commit_sha",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,255}$")
_ARTIFACT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_cached_strategy_ids_sha256(strategy_ids: Sequence[str]) -> str:
    """Hash a sorted, unique source-plan strategy-id sequence canonically.

    The full strategy-id list belongs to the sealed source plan and source
    worker, never to this small protected configuration.
    """

    if isinstance(strategy_ids, (str, bytes)) or not isinstance(strategy_ids, Sequence):
        raise ValueError("cached strategy ids must be a sequence")
    values = tuple(strategy_ids)
    if (
        not values
        or any(type(value) is not str or not value for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("cached strategy ids must be non-empty and unique")
    return hashlib.sha256(_canonical_json_bytes(sorted(values))).hexdigest()


# Short spelling useful to source-worker callers without duplicating the
# canonicalization rule.
cached_strategy_ids_sha256 = canonical_cached_strategy_ids_sha256


class CheckpointRecoveryArtifactV1(FrozenModel):
    """One immutable GitHub artifact pin in the protected recovery profile."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    role: Literal["plan", "checkpoint"]
    artifact_id: int = Field(strict=True, gt=0)
    artifact_name: str = Field(min_length=1, max_length=256)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    size_bytes: int = Field(strict=True, gt=0, le=256 * 1024 * 1024)
    publisher_job_name: str = Field(min_length=1, max_length=512)
    publish_step_name: str = Field(min_length=1, max_length=256)
    worker_id: int | None = Field(default=None, strict=True, ge=0)
    slot_index: int | None = Field(default=None, strict=True, ge=1, le=4)

    @field_validator("artifact_name")
    @classmethod
    def _validate_artifact_name(cls, value: str) -> str:
        if _ARTIFACT_NAME.fullmatch(value) is None:
            raise ValueError("invalid checkpoint recovery artifact name")
        return value

    @model_validator(mode="after")
    def _validate_role_coordinates(self) -> "CheckpointRecoveryArtifactV1":
        if self.role == "plan":
            if self.worker_id is not None or self.slot_index is not None:
                raise ValueError("plan artifact cannot have worker coordinates")
        elif self.worker_id is None or self.slot_index is None:
            raise ValueError("checkpoint artifact requires worker and slot")
        return self


class CheckpointRecoveryProfileV1(FrozenModel):
    """The sole protected source-7 profile for target generation 8."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"]
    campaign_key: Literal["sp500-optimized-catalog-v1"]
    target_generation: Literal[8]
    source_generation: Literal[7] = 7
    source_issue_number: int = Field(strict=True, gt=0)
    source_run_id: int = Field(strict=True, gt=0)
    source_run_attempt: int = Field(strict=True, gt=0)
    source_request_sha256: Sha256
    source_protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_plan_bindings: dict[str, str]
    source_plan_receipt_sha256: Sha256
    science_sha256: Sha256
    catalog_manifest_sha256: Sha256
    worker_ids: tuple[int, ...]
    expected_result_count: int = Field(strict=True, gt=0)
    expected_total_count: int = Field(strict=True, gt=0)
    cached_strategy_ids_sha256: Sha256
    artifacts: tuple[CheckpointRecoveryArtifactV1, ...]

    @field_validator("source_plan_bindings", mode="before")
    @classmethod
    def _validate_binding_input(cls, value: object) -> object:
        if type(value) is not dict or any(
            type(key) is not str or type(item) is not str for key, item in value.items()
        ):
            raise ValueError("source_plan_bindings must be a strict string dictionary")
        if set(value) != _SOURCE_PLAN_BINDING_KEYS:
            raise ValueError("source_plan_bindings keys are closed")
        return value

    @field_validator("source_plan_bindings")
    @classmethod
    def _validate_binding_values(cls, value: dict[str, str]) -> dict[str, str]:
        for key in (
            "request_sha256",
            "decision_sha256",
            "campaign_id",
            "science_sha256",
            "execution_plan_sha256",
            "execution_protocol_sha256",
        ):
            if _SHA256.fullmatch(value[key]) is None:
                raise ValueError(f"invalid {key} source binding")
        if _COMMIT.fullmatch(value["protected_commit_sha"]) is None:
            raise ValueError("invalid protected commit source binding")
        if _AUTHORITY_ID.fullmatch(value["authority_id"]) is None:
            raise ValueError("invalid authority source binding")
        return value

    @field_validator("worker_ids", mode="before")
    @classmethod
    def _validate_worker_input(cls, value: object) -> object:
        if type(value) not in (list, tuple):
            raise ValueError("worker_ids must be a sequence")
        items = cast(list[object] | tuple[object, ...], value)
        if any(type(item) is not int or item < 0 for item in items):
            raise ValueError("worker_ids must contain strict non-negative integers")
        return tuple(items)

    @field_validator("artifacts", mode="before")
    @classmethod
    def _validate_artifact_input(cls, value: object) -> object:
        if type(value) not in (list, tuple):
            raise ValueError("artifacts must be a sequence")
        items = cast(list[object] | tuple[object, ...], value)
        if len(items) != CHECKPOINT_RECOVERY_CHECKPOINT_COUNT + 1:
            raise ValueError("checkpoint recovery artifact count is closed")
        return tuple(items)

    @model_validator(mode="after")
    def _validate_protected_values(self) -> "CheckpointRecoveryProfileV1":
        if (
            self.source_request_sha256 != CHECKPOINT_RECOVERY_SOURCE_REQUEST_SHA256
            or self.source_issue_number != CHECKPOINT_RECOVERY_SOURCE_ISSUE_NUMBER
            or self.source_run_id != CHECKPOINT_RECOVERY_SOURCE_RUN_ID
            or self.source_run_attempt != CHECKPOINT_RECOVERY_SOURCE_RUN_ATTEMPT
            or self.source_protected_commit_sha
            != CHECKPOINT_RECOVERY_SOURCE_PROTECTED_COMMIT_SHA
            or self.source_plan_receipt_sha256
            != CHECKPOINT_RECOVERY_SOURCE_PLAN_RECEIPT_SHA256
            or self.science_sha256 != CHECKPOINT_RECOVERY_SCIENCE_SHA256
            or self.expected_result_count != CHECKPOINT_RECOVERY_EXPECTED_RESULT_COUNT
            or self.expected_total_count != CHECKPOINT_RECOVERY_EXPECTED_TOTAL_COUNT
        ):
            raise ValueError("protected checkpoint recovery profile mismatch")

        bindings = self.source_plan_bindings
        if (
            bindings["request_sha256"] != self.source_request_sha256
            or bindings["protected_commit_sha"] != self.source_protected_commit_sha
            or bindings["science_sha256"] != self.science_sha256
            or bindings["execution_plan_sha256"]
            != CHECKPOINT_RECOVERY_EXECUTION_PLAN_SHA256
        ):
            raise ValueError("incompatible checkpoint recovery source bindings")

        if len(self.worker_ids) != CHECKPOINT_RECOVERY_WORKER_COUNT:
            raise ValueError("checkpoint recovery worker count is closed")
        if tuple(self.worker_ids) != tuple(sorted(set(self.worker_ids))):
            raise ValueError("checkpoint recovery worker ids must be sorted and unique")

        plan_artifacts = tuple(item for item in self.artifacts if item.role == "plan")
        checkpoint_artifacts = tuple(
            item for item in self.artifacts if item.role == "checkpoint"
        )
        if len(plan_artifacts) != 1 or len(checkpoint_artifacts) != CHECKPOINT_RECOVERY_CHECKPOINT_COUNT:
            raise ValueError("checkpoint recovery artifact roles are closed")
        if self.artifacts[0].role != "plan" or self.artifacts[0] != plan_artifacts[0]:
            raise ValueError("checkpoint recovery plan artifact must be first")

        artifact_ids = tuple(item.artifact_id for item in self.artifacts)
        artifact_names = tuple(item.artifact_name for item in self.artifacts)
        artifact_digests = tuple(item.digest for item in self.artifacts)
        if (
            len(set(artifact_ids)) != len(artifact_ids)
            or len(set(artifact_names)) != len(artifact_names)
            or len(set(artifact_digests)) != len(artifact_digests)
        ):
            raise ValueError("checkpoint recovery artifacts must be unique")

        worker_set = set(self.worker_ids)
        coordinate_set = {(item.worker_id, item.slot_index) for item in checkpoint_artifacts}
        expected_coordinates = {
            (worker_id, slot_index)
            for worker_id in worker_set
            for slot_index in range(1, CHECKPOINT_RECOVERY_SLOT_COUNT + 1)
        }
        if coordinate_set != expected_coordinates:
            raise ValueError("checkpoint recovery worker and slot coverage is incomplete")
        if tuple(
            (item.worker_id, item.slot_index) for item in checkpoint_artifacts
        ) != tuple(sorted(expected_coordinates)):
            raise ValueError("checkpoint recovery checkpoints must be canonically ordered")

        return self

    @property
    def profile_sha256(self) -> str:
        """SHA-256 of the canonical JSON representation of this profile."""

        return hashlib.sha256(_canonical_json_bytes(self.model_dump(mode="json"))).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _read_config(repo_root: Path) -> object:
    supplied_root = Path(repo_root)
    root = supplied_root.resolve(strict=True)
    path = root / CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH
    if (
        supplied_root.is_symlink()
        or not root.is_dir()
        or path.is_symlink()
        or not path.is_file()
        or not path.resolve(strict=True).is_relative_to(root)
    ):
        raise ValueError("unsafe protected configuration path")
    raw = path.read_bytes()
    if len(raw) > _CONFIG_MAX_BYTES:
        raise ValueError("oversized protected configuration")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )


def load_checkpoint_recovery_profiles(
    repo_root: Path,
) -> tuple[CheckpointRecoveryProfileV1, ...]:
    """Load exactly one protected checkpoint recovery profile."""

    try:
        payload = _read_config(repo_root)
        if (
            type(payload) is not dict
            or set(payload) != {"schema_version", "profiles"}
            or payload["schema_version"] != "1"
            or type(payload["profiles"]) is not list
            or len(payload["profiles"]) != 1
        ):
            raise ValueError("invalid protected checkpoint profile root")
        profiles = tuple(
            CheckpointRecoveryProfileV1.model_validate(row)
            for row in payload["profiles"]
        )
        if len(profiles) != 1 or (
            profiles[0].campaign_key,
            profiles[0].target_generation,
        ) != (CHECKPOINT_RECOVERY_CAMPAIGN_KEY, CHECKPOINT_RECOVERY_TARGET_GENERATION):
            raise ValueError("invalid protected checkpoint profile target")
        return profiles
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        UnicodeError,
        RecursionError,
        ValidationError,
    ) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID") from exc


def load_checkpoint_recovery_profile(
    repo_root: Path,
    campaign_key: str,
    target_generation: int,
) -> CheckpointRecoveryProfileV1 | None:
    """Select the sole protected profile, or return ``None`` off target."""

    if (
        type(campaign_key) is not str
        or type(target_generation) is not int
        or campaign_key != CHECKPOINT_RECOVERY_CAMPAIGN_KEY
        or target_generation != CHECKPOINT_RECOVERY_TARGET_GENERATION
    ):
        return None
    profiles = load_checkpoint_recovery_profiles(repo_root)
    if len(profiles) != 1:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_NOT_FOUND")
    return profiles[0]


def validate_exact_checkpoint_profile(
    repo_root: Path,
    payload: Mapping[str, object] | CheckpointRecoveryProfileV1,
) -> CheckpointRecoveryProfileV1:
    """Require byte-level contract equality with the protected profile model."""

    protected = load_checkpoint_recovery_profiles(repo_root)
    try:
        candidate = (
            payload
            if isinstance(payload, CheckpointRecoveryProfileV1)
            else CheckpointRecoveryProfileV1.model_validate(payload)
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_MISMATCH") from exc
    if len(protected) != 1 or candidate != protected[0]:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_MISMATCH")
    return candidate


CatalogCheckpointRecoveryArtifactV1 = CheckpointRecoveryArtifactV1
CatalogCheckpointRecoveryProfileV1 = CheckpointRecoveryProfileV1


__all__ = [
    "CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH",
    "CHECKPOINT_RECOVERY_CAMPAIGN_KEY",
    "CHECKPOINT_RECOVERY_TARGET_GENERATION",
    "CheckpointRecoveryArtifactV1",
    "CheckpointRecoveryProfileV1",
    "CatalogCheckpointRecoveryArtifactV1",
    "CatalogCheckpointRecoveryProfileV1",
    "canonical_cached_strategy_ids_sha256",
    "cached_strategy_ids_sha256",
    "load_checkpoint_recovery_profiles",
    "load_checkpoint_recovery_profile",
    "validate_exact_checkpoint_profile",
]
