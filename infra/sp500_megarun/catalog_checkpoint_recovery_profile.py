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
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import (
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)

from .catalog_request_contract import FrozenModel, Sha256

if TYPE_CHECKING:
    from .catalog_reduction_recovery_profile import RecoveryPredecessorBindings


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
CHECKPOINT_RECOVERY_SOURCE8_TARGET_GENERATION = 9
CHECKPOINT_RECOVERY_SOURCE8_GENERATION = 8
CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256 = (
    "f337320f4ebb3c863581b632e18e15eeba364621363310ed31fc120677f84fe0"
)
CHECKPOINT_RECOVERY_SOURCE8_ISSUE_NUMBER = 353
CHECKPOINT_RECOVERY_SOURCE8_RUN_ID = 35708742966
CHECKPOINT_RECOVERY_SOURCE8_RUN_ATTEMPT = 1
CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA = (
    "9f22f9a1f7c6f2646f888c228a4899d0188f586c"
)
CHECKPOINT_RECOVERY_SOURCE8_EXECUTION_PLAN_SHA256 = (
    "c56fe177f2c7e24b3fcd42ed6182e52e5fc0e9465c5a45409ea3ebc2eb2c6cca"
)
CHECKPOINT_RECOVERY_SOURCE8_PLAN_RECEIPT_SHA256 = (
    "be0434a61abad0ff0d6eafe1a82d915d552c8e9ba8db96cf622b1afe65d1da0c"
)
CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256 = (
    "3e2ec6564b33f71be4bd89b5958ffd436f60ff193d082488e4307b7e8438a348"
)
CHECKPOINT_RECOVERY_SOURCE8_EXPECTED_RESULT_COUNT = 37258
CHECKPOINT_RECOVERY_SOURCE8_WORKER_COUNT = 60
CHECKPOINT_RECOVERY_SOURCE8_SLOT_COUNT = 2
CHECKPOINT_RECOVERY_SOURCE8_CHECKPOINT_RESULT_COUNT = 18628
CHECKPOINT_RECOVERY_INHERITED_PROFILE_SHA256 = (
    "fc3aff1e9ccfc0e4608e510a538f8ce839c371669585b8b680a658e54d7e81b7"
)
CHECKPOINT_RECOVERY_CONTINUATION_TARGET_GENERATION = 10
CHECKPOINT_RECOVERY_CONTINUATION_SOURCE_GENERATION = 8
CHECKPOINT_RECOVERY_CONTINUATION_PREDECESSOR_GENERATION = 9
CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256 = (
    "a0fdcfe2209caf1f03d6ee4db54fcc34b1488198cafb41bc0ef7461332b409bd"
)
CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER = 360
CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID = 35756495166
CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT = 1
CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA = (
    "48104e8cb94d9bd1d6aef1d82b2fbeb42e2bf70c"
)
CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256 = (
    "eff7be753ea517597a6ba5ac0b20a17e3e87d02e4faac875259b15b2f9e5825b"
)
CHECKPOINT_RECOVERY_SOURCE8_TARGET_GENERATIONS = frozenset({9, 10})
CHECKPOINT_RECOVERY_SUPPORTED_TARGET_GENERATIONS = frozenset({8, 9, 10})
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
    """Closed source-bound profiles for target generations 8, 9, and 10."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"]
    campaign_key: Literal["sp500-optimized-catalog-v1"]
    target_generation: Literal[8, 9, 10]
    source_generation: Literal[7, 8] = 7
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
    inherited_profile_sha256: Sha256 | None = None
    artifacts: tuple[CheckpointRecoveryArtifactV1, ...]

    @model_serializer(mode="wrap")
    def _serialize_legacy_profile_without_optional_fields(
        self, handler: SerializerFunctionWrapHandler
    ) -> Any:
        """Keep the protected generation-8 canonical JSON byte-for-byte stable."""

        value = handler(self)
        if isinstance(value, dict) and self.inherited_profile_sha256 is None:
            value.pop("inherited_profile_sha256", None)
        return value

    @property
    def worker_count(self) -> int:
        return len(self.worker_ids)

    @property
    def slot_count(self) -> int:
        return (
            CHECKPOINT_RECOVERY_SOURCE8_SLOT_COUNT
            if self.target_generation in CHECKPOINT_RECOVERY_SOURCE8_TARGET_GENERATIONS
            else CHECKPOINT_RECOVERY_SLOT_COUNT
        )

    @property
    def checkpoint_result_count(self) -> int:
        if self.target_generation in CHECKPOINT_RECOVERY_SOURCE8_TARGET_GENERATIONS:
            return self.expected_result_count - CHECKPOINT_RECOVERY_EXPECTED_RESULT_COUNT
        return self.expected_result_count

    @property
    def total_checkpoint_count(self) -> int:
        if self.target_generation in CHECKPOINT_RECOVERY_SOURCE8_TARGET_GENERATIONS:
            return CHECKPOINT_RECOVERY_CHECKPOINT_COUNT * 2
        return CHECKPOINT_RECOVERY_CHECKPOINT_COUNT

    @property
    def source_terminal_receipt_sha256(self) -> str | None:
        if self.target_generation in CHECKPOINT_RECOVERY_SOURCE8_TARGET_GENERATIONS:
            return CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256
        return None

    @property
    def predecessor_bindings(self) -> RecoveryPredecessorBindings | None:
        """Return only the closed immediate predecessor for continuation 10."""

        if self.target_generation != CHECKPOINT_RECOVERY_CONTINUATION_TARGET_GENERATION:
            return None
        from .catalog_reduction_recovery_profile import RecoveryPredecessorBindings

        return RecoveryPredecessorBindings(
            generation=CHECKPOINT_RECOVERY_CONTINUATION_PREDECESSOR_GENERATION,
            request_sha256=CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
            issue_number=CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
            run_id=CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
            run_attempt=CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT,
            protected_commit_sha=CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
            terminal_receipt_sha256=CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256,
            decision_sha256=None,
        )

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
        expected_source_generation = (
            CHECKPOINT_RECOVERY_SOURCE_GENERATION
            if self.target_generation == CHECKPOINT_RECOVERY_TARGET_GENERATION
            else CHECKPOINT_RECOVERY_SOURCE8_GENERATION
        )
        if self.source_generation != expected_source_generation:
            raise ValueError("checkpoint recovery source and target generations mismatch")

        if self.target_generation == CHECKPOINT_RECOVERY_TARGET_GENERATION:
            expected = {
                "source_request_sha256": CHECKPOINT_RECOVERY_SOURCE_REQUEST_SHA256,
                "source_issue_number": CHECKPOINT_RECOVERY_SOURCE_ISSUE_NUMBER,
                "source_run_id": CHECKPOINT_RECOVERY_SOURCE_RUN_ID,
                "source_run_attempt": CHECKPOINT_RECOVERY_SOURCE_RUN_ATTEMPT,
                "source_protected_commit_sha": CHECKPOINT_RECOVERY_SOURCE_PROTECTED_COMMIT_SHA,
                "source_plan_receipt_sha256": CHECKPOINT_RECOVERY_SOURCE_PLAN_RECEIPT_SHA256,
                "science_sha256": CHECKPOINT_RECOVERY_SCIENCE_SHA256,
                "expected_result_count": CHECKPOINT_RECOVERY_EXPECTED_RESULT_COUNT,
                "expected_total_count": CHECKPOINT_RECOVERY_EXPECTED_TOTAL_COUNT,
            }
            expected_worker_count = CHECKPOINT_RECOVERY_WORKER_COUNT
            if self.inherited_profile_sha256 is not None:
                raise ValueError("generation-8 profile cannot inherit another profile")
        else:
            expected = {
                "source_request_sha256": CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256,
                "source_issue_number": CHECKPOINT_RECOVERY_SOURCE8_ISSUE_NUMBER,
                "source_run_id": CHECKPOINT_RECOVERY_SOURCE8_RUN_ID,
                "source_run_attempt": CHECKPOINT_RECOVERY_SOURCE8_RUN_ATTEMPT,
                "source_protected_commit_sha": CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA,
                "source_plan_receipt_sha256": CHECKPOINT_RECOVERY_SOURCE8_PLAN_RECEIPT_SHA256,
                "science_sha256": CHECKPOINT_RECOVERY_SCIENCE_SHA256,
                "expected_result_count": CHECKPOINT_RECOVERY_SOURCE8_EXPECTED_RESULT_COUNT,
                "expected_total_count": CHECKPOINT_RECOVERY_SOURCE8_EXPECTED_RESULT_COUNT,
            }
            expected_worker_count = CHECKPOINT_RECOVERY_SOURCE8_WORKER_COUNT
            if self.inherited_profile_sha256 != CHECKPOINT_RECOVERY_INHERITED_PROFILE_SHA256:
                raise ValueError("generation-9/10 inherited profile binding mismatch")

        if any(getattr(self, key) != value for key, value in expected.items()):
            raise ValueError("protected checkpoint recovery profile mismatch")

        bindings = self.source_plan_bindings
        if (
            bindings["request_sha256"] != self.source_request_sha256
            or bindings["protected_commit_sha"] != self.source_protected_commit_sha
            or bindings["science_sha256"] != self.science_sha256
            or bindings["execution_plan_sha256"]
            != (
                CHECKPOINT_RECOVERY_EXECUTION_PLAN_SHA256
                if self.target_generation == CHECKPOINT_RECOVERY_TARGET_GENERATION
                else CHECKPOINT_RECOVERY_SOURCE8_EXECUTION_PLAN_SHA256
            )
        ):
            raise ValueError("incompatible checkpoint recovery source bindings")

        if len(self.worker_ids) != expected_worker_count:
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
            for slot_index in range(1, self.slot_count + 1)
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
    """Load the closed generation-8/9 profile set."""

    try:
        payload = _read_config(repo_root)
        if (
            type(payload) is not dict
            or set(payload) != {"schema_version", "profiles"}
            or payload["schema_version"] != "1"
            or type(payload["profiles"]) is not list
            or not payload["profiles"]
            or len(payload["profiles"]) > len(CHECKPOINT_RECOVERY_SUPPORTED_TARGET_GENERATIONS)
        ):
            raise ValueError("invalid protected checkpoint profile root")
        profiles = tuple(
            CheckpointRecoveryProfileV1.model_validate(row)
            for row in payload["profiles"]
        )
        profile_keys = tuple((profile.campaign_key, profile.target_generation) for profile in profiles)
        if (
            any(
                profile.campaign_key != CHECKPOINT_RECOVERY_CAMPAIGN_KEY
                or profile.target_generation not in CHECKPOINT_RECOVERY_SUPPORTED_TARGET_GENERATIONS
                for profile in profiles
            )
            or len(set(profile_keys)) != len(profile_keys)
        ):
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
    """Select the requested closed profile, or return ``None`` off target."""

    if (
        type(campaign_key) is not str
        or type(target_generation) is not int
        or campaign_key != CHECKPOINT_RECOVERY_CAMPAIGN_KEY
        or target_generation not in CHECKPOINT_RECOVERY_SUPPORTED_TARGET_GENERATIONS
    ):
        return None
    if target_generation == CHECKPOINT_RECOVERY_SOURCE8_TARGET_GENERATION:
        config_path = Path(repo_root) / CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH
        if not config_path.is_file():
            return None
    profiles = load_checkpoint_recovery_profiles(repo_root)
    matches = tuple(
        profile
        for profile in profiles
        if profile.campaign_key == campaign_key
        and profile.target_generation == target_generation
    )
    if len(matches) > 1:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_NOT_FOUND")
    return matches[0] if matches else None


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
    matches = tuple(
        profile
        for profile in protected
        if profile.campaign_key == candidate.campaign_key
        and profile.target_generation == candidate.target_generation
    )
    if len(matches) != 1 or candidate != matches[0]:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_MISMATCH")
    return candidate


CatalogCheckpointRecoveryArtifactV1 = CheckpointRecoveryArtifactV1
CatalogCheckpointRecoveryProfileV1 = CheckpointRecoveryProfileV1


__all__ = [
    "CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH",
    "CHECKPOINT_RECOVERY_CAMPAIGN_KEY",
    "CHECKPOINT_RECOVERY_TARGET_GENERATION",
    "CHECKPOINT_RECOVERY_SUPPORTED_TARGET_GENERATIONS",
    "CHECKPOINT_RECOVERY_CONTINUATION_TARGET_GENERATION",
    "CHECKPOINT_RECOVERY_CONTINUATION_SOURCE_GENERATION",
    "CHECKPOINT_RECOVERY_CONTINUATION_PREDECESSOR_GENERATION",
    "CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256",
    "CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER",
    "CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID",
    "CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT",
    "CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA",
    "CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256",
    "CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256",
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
