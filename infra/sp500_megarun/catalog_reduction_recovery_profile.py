"""Closed protected profile for the selective catalog reduction recovery.

This module only describes already-published gen7 evidence that a gen8 or gen9 canary
may reuse.  It does not read or write current authority, manifests, tokens,
lineage, worker output, or any new scientific result.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, cast

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from .catalog_request_contract import CatalogRunRequestV1, FrozenModel, Sha256
from .catalog_sealed_plan import verify_sealed_global_reuse_execution_plan


RECOVERY_CONFIG_RELATIVE_PATH = "config/catalog_reduction_recovery_profiles_v1.json"
RECOVERY_CAMPAIGN_KEY = "catalog-fast-canary-v1"
RECOVERY_TARGET_GENERATION = 8
RECOVERY_TARGET_GENERATIONS = frozenset({8, 9})
RECOVERY_PREDECESSOR_REQUEST_SHA256 = (
    "a0749c8833b52612096d8a820f3a46f5af48ce52848f8bfc02377f3236996896"
)
RECOVERY_GROUP_RECEIPT_SHA256 = "e7e2b1b22a70cbfcdba840f25d4b6e87656a3d1a9eb6e155e08f2d4a3e03fbd7"

_CONFIG_MAX_BYTES = 64 * 1024
_ARTIFACT_NAME = r"^[A-Za-z0-9][A-Za-z0-9.-]{0,199}$"
_ARTIFACT_DIGEST = r"^sha256:[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_AUTHORITY_ID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_STRATEGY_ID = r"^SCV1-[0-9a-f]{64}$"

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
_EXPECTED_SOURCE_PLAN_BINDINGS = {
    "request_sha256": RECOVERY_PREDECESSOR_REQUEST_SHA256,
    "decision_sha256": "c9471a1431226acc4ef70bfd815ac2a6e0cc2bc011865b61d5d045244b0ebc7c",
    "protected_commit_sha": "fc77968dceeb93b332c143cc367b99128f488093",
    "authority_id": "b7102536-d7fa-5dc8-a438-d456bd2313c5",
    "campaign_id": "cf367334c63ed4e8a087ca3730b718e94e5e914877327a23c069f4989725173e",
    "science_sha256": "57a24398bba9779f2095d20dc50f15975cd04949964055ae322411a3d57906a2",
    "execution_plan_sha256": "64ea4c3c11181f4aa47a545c81da55d5d3e67ee406d78b0ddf3d0867ebe03f25",
    "execution_protocol_sha256": "e4f267c15125890abf6d1cc4e8889fa8975bf407b89d80306f59ac0691245631",
}
_EXPECTED_STRATEGY_IDS = (
    "SCV1-0008de8188a0dfedb69e2087fa0786d8876821d9dfaeaf970a6b3f830fc031b0",
    "SCV1-0009261998f567e326cbcff4b17ed79c26420ecd05771957455abfdb0cfdda0a",
    "SCV1-000aec232b3b9f37549bab3388af27d55b6e1c57ac2192525a985f8d437b3b7b",
    "SCV1-000c5a76a3c0dac7d7dd53a1cffe80b86b511dc5cc447830033209746bd771fa",
    "SCV1-000ca745fd2a8fe5ac48e736fdcf7ae52b8dec69e68363e1b18b903cdb414dd4",
    "SCV1-00122340e81efb755e5586b43a952a5e1801bc131060752e2ac2487d6463661c",
    "SCV1-001937e4fad670d10fd93267f0c65a5a643a59dfc1d22e2b4d92c1c08d6ddf40",
    "SCV1-002e6ef7635802db02a3ed6deca385d1f368d0d080f5389d5feb0edc54b1a7f4",
)


@dataclass(frozen=True)
class RecoveryPredecessorBindings:
    """Protected authorization identity, never serialized into source evidence."""

    generation: int
    request_sha256: str
    issue_number: int
    run_id: int
    run_attempt: int
    protected_commit_sha: str
    terminal_receipt_sha256: str
    decision_sha256: str | None = None


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class ReductionRecoveryArtifactV1(FrozenModel):
    """One immutable source artifact required by the reduction reader."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    role: Literal["plan", "group"]
    artifact_id: int = Field(strict=True, gt=0)
    artifact_name: str = Field(pattern=_ARTIFACT_NAME)
    digest: str = Field(pattern=_ARTIFACT_DIGEST)
    receipt_sha256: Sha256 | None
    size_bytes: int = Field(strict=True, gt=0, le=64 * 1024 * 1024)
    publisher_job_name: str = Field(min_length=1, max_length=512)
    publish_step_name: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _validate_role_contract(self) -> "ReductionRecoveryArtifactV1":
        expected: tuple[int, str, str, str | None, int, str, str]
        if self.role == "plan":
            expected = (
                10582715279,
                "catalog-sealed-execution-plan-b7102536-d7fa-5dc8-a438-d456bd2313c5",
                "sha256:ed2d84bf6cc297eeeed6692003670d68d9916a5f71c2485c421ed670219d7472",
                None,
                175878,
                "gate",
                "Publish the already-materialized sealed plan",
            )
        else:
            expected = (
                10582565863,
                "catalog-reduction-group-64ea4c3c11181f4a-g00",
                "sha256:1f32af1a9468e01a21fbb2e2869b945e273ed68a74eaf1b3153bc74588706e47",
                RECOVERY_GROUP_RECEIPT_SHA256,
                28148,
                "engine / reduce_groups (catalog-checkpoint-64ea4c3c11181f4a-g00-*, 0, "
                "catalog-reduction-group-64ea4c3c1118...",
                "Upload one bounded reduction group",
            )
        actual = (
            self.artifact_id,
            self.artifact_name,
            self.digest,
            self.receipt_sha256,
            self.size_bytes,
            self.publisher_job_name,
            self.publish_step_name,
        )
        if actual != expected:
            raise ValueError("protected recovery artifact mismatch")
        return self


class ReductionRecoveryProfileV1(FrozenModel):
    """One of two closed recovery targets sharing immutable gen7 evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"]
    campaign_key: Literal["catalog-fast-canary-v1"]
    target_generation: Literal[8, 9]
    source_request_sha256: Sha256
    source_issue_number: int = Field(strict=True, gt=0)
    source_run_id: int = Field(strict=True, gt=0)
    source_run_attempt: int = Field(strict=True, gt=0)
    source_terminal_receipt_sha256: Sha256
    source_plan_bindings: dict[str, str]
    source_plan_receipt_sha256: Sha256
    science_sha256: Sha256
    catalog_manifest_sha256: Sha256
    strategy_ids: tuple[str, ...]
    artifacts: tuple[ReductionRecoveryArtifactV1, ...]

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
            if not re.fullmatch(r"[0-9a-f]{64}", value[key]):
                raise ValueError(f"invalid {key} source binding")
        if not re.fullmatch(_COMMIT, value["protected_commit_sha"]):
            raise ValueError("invalid protected commit source binding")
        if not re.fullmatch(_AUTHORITY_ID, value["authority_id"]):
            raise ValueError("invalid authority source binding")
        return value

    @field_validator("strategy_ids", mode="before")
    @classmethod
    def _validate_strategy_input(cls, value: object) -> object:
        if type(value) not in (list, tuple):
            raise ValueError("strategy_ids must be a sequence")
        items = cast(list[object] | tuple[object, ...], value)
        if len(items) != len(_EXPECTED_STRATEGY_IDS) or any(
            type(item) is not str or not re.fullmatch(_STRATEGY_ID, item) for item in items
        ):
            raise ValueError("strategy_ids are invalid")
        return tuple(items)

    @field_validator("artifacts", mode="before")
    @classmethod
    def _validate_artifact_input(cls, value: object) -> object:
        if type(value) not in (list, tuple):
            raise ValueError("artifacts must contain the plan and group")
        items = cast(list[object] | tuple[object, ...], value)
        if len(items) != 2:
            raise ValueError("artifacts must contain the plan and group")
        return tuple(items)

    @model_validator(mode="after")
    def _validate_protected_values(self) -> "ReductionRecoveryProfileV1":
        expected_scalars = (
            self.schema_version,
            self.campaign_key,
            self.source_request_sha256,
            self.source_issue_number,
            self.source_run_id,
            self.source_run_attempt,
            self.source_terminal_receipt_sha256,
            self.source_plan_receipt_sha256,
            self.science_sha256,
            self.catalog_manifest_sha256,
        )
        required_scalars = (
            "1",
            RECOVERY_CAMPAIGN_KEY,
            RECOVERY_PREDECESSOR_REQUEST_SHA256,
            323,
            35436320227,
            1,
            "67224b935b44f2d7598e2b28d9cb686d4eee89a046d0ec3b0482db4aba9d8cc4",
            "d4d0734b231aa346930b8654e26a9ae52cc4cf24098b2ab97815d4a13a11af04",
            "57a24398bba9779f2095d20dc50f15975cd04949964055ae322411a3d57906a2",
            "2de5b6a09fb10b71adff0f45af450f30c7f3dbfb196bfea8f01f92d4cf3cb981",
        )
        if expected_scalars != required_scalars:
            raise ValueError("protected recovery profile mismatch")
        if self.source_plan_bindings != _EXPECTED_SOURCE_PLAN_BINDINGS:
            raise ValueError("protected recovery bindings mismatch")
        if self.strategy_ids != _EXPECTED_STRATEGY_IDS:
            raise ValueError("protected recovery strategies mismatch")
        if len(self.artifacts) != 2 or tuple(artifact.role for artifact in self.artifacts) != (
            "plan",
            "group",
        ):
            raise ValueError("protected recovery artifacts mismatch")
        if self.source_request_sha256 != self.source_plan_bindings["request_sha256"]:
            raise ValueError("profile source request binding mismatch")
        if self.science_sha256 != self.source_plan_bindings["science_sha256"]:
            raise ValueError("profile science binding mismatch")
        return self

    @property
    def source_generation(self) -> int:
        """Both protected targets reuse gen7; this is not target minus one."""

        return 7

    @property
    def predecessor_bindings(self) -> RecoveryPredecessorBindings:
        """Separate immediate authorization from immutable source provenance."""

        if self.target_generation == 8:
            return RecoveryPredecessorBindings(
                generation=7,
                request_sha256=RECOVERY_PREDECESSOR_REQUEST_SHA256,
                issue_number=323,
                run_id=35436320227,
                run_attempt=1,
                protected_commit_sha="fc77968dceeb93b332c143cc367b99128f488093",
                terminal_receipt_sha256="67224b935b44f2d7598e2b28d9cb686d4eee89a046d0ec3b0482db4aba9d8cc4",
                decision_sha256="c9471a1431226acc4ef70bfd815ac2a6e0cc2bc011865b61d5d045244b0ebc7c",
            )
        if self.target_generation == 9:
            return RecoveryPredecessorBindings(
                generation=8,
                request_sha256="70d15409754069379635e7ff1d9a6990d8b30dff68fce16531cee875d16e719f",
                issue_number=328,
                run_id=35454099484,
                run_attempt=1,
                protected_commit_sha="41d904b66c33bb8d0150aa14c7ca2564afd3f154",
                terminal_receipt_sha256="a10a880af0c3a3bd4ebd69958f5e4761cf3c620da32abddaff080a346b8a0193",
                decision_sha256="91e1e0bb41a76b5014d8d705cb67ccb5b163c24c2551bd1d84cc91ab37ccf023",
            )
        raise ValueError("CATALOG_REDUCTION_RECOVERY_PROFILE_MISMATCH")

    @property
    def profile_sha256(self) -> str:
        """SHA-256 of the canonical closed ``model_dump(mode='json')``."""

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
    root = repo_root.resolve(strict=True)
    path = root / RECOVERY_CONFIG_RELATIVE_PATH
    if (
        repo_root.is_symlink()
        or path.is_symlink()
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


def load_reduction_recovery_profiles(repo_root: Path) -> tuple[ReductionRecoveryProfileV1, ...]:
    """Load exactly the two distinct protected recovery targets."""

    try:
        payload = _read_config(repo_root)
        if (
            type(payload) is not dict
            or set(payload) != {"schema_version", "profiles"}
            or payload["schema_version"] != "1"
            or type(payload["profiles"]) is not list
            or len(payload["profiles"]) != 2
        ):
            raise ValueError("invalid protected profile root")
        profiles = tuple(ReductionRecoveryProfileV1.model_validate(row) for row in payload["profiles"])
        if {(row.campaign_key, row.target_generation) for row in profiles} != {
            (RECOVERY_CAMPAIGN_KEY, generation) for generation in RECOVERY_TARGET_GENERATIONS
        }:
            raise ValueError("invalid protected profile targets")
        return profiles
    except (OSError, TypeError, ValueError, UnicodeError, RecursionError, ValidationError) as exc:
        if str(exc) == "CATALOG_REDUCTION_RECOVERY_CONFIG_INVALID":
            raise
        raise ValueError("CATALOG_REDUCTION_RECOVERY_CONFIG_INVALID") from exc


def load_reduction_recovery_profile(
    repo_root: Path, request: CatalogRunRequestV1
) -> ReductionRecoveryProfileV1 | None:
    """Select a protected target and require its exact immediate predecessor."""

    if not isinstance(request, CatalogRunRequestV1):
        raise ValueError("CATALOG_REDUCTION_RECOVERY_REQUEST_INVALID")
    if (
        request.campaign_key != RECOVERY_CAMPAIGN_KEY
        or request.launch_generation not in RECOVERY_TARGET_GENERATIONS
    ):
        return None
    profiles = load_reduction_recovery_profiles(repo_root)
    matches = tuple(
        profile
        for profile in profiles
        if (
            profile.campaign_key == request.campaign_key
            and profile.target_generation == request.launch_generation
        )
    )
    if len(matches) != 1:
        raise ValueError("CATALOG_REDUCTION_RECOVERY_PROFILE_NOT_FOUND")
    if request.previous_terminal_request_sha256 != matches[0].predecessor_bindings.request_sha256:
        raise ValueError("CATALOG_REDUCTION_RECOVERY_PREDECESSOR_MISMATCH")
    return matches[0]


def validate_exact_profile(
    repo_root: Path, payload: Mapping[str, object] | ReductionRecoveryProfileV1
) -> ReductionRecoveryProfileV1:
    """Require exact equality with the protected profile for this target."""

    protected = load_reduction_recovery_profiles(repo_root)
    try:
        candidate = (
            payload
            if isinstance(payload, ReductionRecoveryProfileV1)
            else ReductionRecoveryProfileV1.model_validate(payload)
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError("CATALOG_REDUCTION_RECOVERY_PROFILE_MISMATCH") from exc
    matches = tuple(
        profile for profile in protected
        if (profile.campaign_key, profile.target_generation)
        == (candidate.campaign_key, candidate.target_generation)
    )
    if len(matches) != 1 or candidate != matches[0]:
        raise ValueError("CATALOG_REDUCTION_RECOVERY_PROFILE_MISMATCH")
    return candidate


def read_sealed_reduction_recovery_profile(
    repo_root: Path,
    sealed_plan: Path,
    *,
    expected_bindings: Mapping[str, str] | None = None,
) -> ReductionRecoveryProfileV1 | None:
    """Read only a protected profile bound into the current admission seal."""
    verify_sealed_global_reuse_execution_plan(sealed_plan, expected_bindings=expected_bindings)
    binding_path = sealed_plan / "controller_binding.json"
    binding = json.loads(binding_path.read_text("utf-8"))
    bound = binding.get("binding", {}).get("reduction_recovery_sha256")
    path = sealed_plan / "reduction_recovery.json"
    if not path.exists() and bound is None:
        return None
    if path.is_symlink() or not path.is_file() or not isinstance(bound, str):
        raise ValueError("CATALOG_REDUCTION_RECOVERY_SEAL_INVALID")
    payload = json.loads(path.read_text("utf-8"), object_pairs_hook=_reject_duplicate_keys,
                         parse_constant=_reject_nonfinite)
    profile = validate_exact_profile(repo_root, payload)
    if profile.profile_sha256 != bound:
        raise ValueError("CATALOG_REDUCTION_RECOVERY_SEAL_INVALID")
    return profile
