"""Small, fail-closed admission contracts for the catalog fast path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .catalog_campaign_registry import CatalogCampaignEntryV1, CatalogEngineId
from .catalog_request_contract import (
    CAMPAIGN_KEY_PATTERN,
    CatalogRunRequestV1,
    FrozenModel,
    Sha256,
)


CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]+$")]
CatalogPublicState = Literal[
    "PREPARING",
    "PREPARED",
    "QUEUED",
    "RUNNING",
    "RECOVERING",
    "SUCCESS",
    "BLOCKED",
]

REQUEST_MAX_AGE = timedelta(minutes=30)
REQUEST_FUTURE_TOLERANCE = timedelta(minutes=5)


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _as_utc(value: datetime, *, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(code)
    return value.astimezone(timezone.utc)


def _safe_repository_file(root: Path, relative: str) -> Path:
    candidate = (root / PurePosixPath(relative)).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError("CATALOG_PREPARATION_PATH_INVALID")
    return candidate


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CatalogPreparationIdentityV1(FrozenModel):
    """Every repository input that invalidates a prepared campaign."""

    schema_version: Literal["1"]
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    engine_id: CatalogEngineId
    protected_commit_sha: CommitSha
    campaign_definition_sha256: Sha256
    scientific_contract_sha256: Sha256
    dependency_lock_sha256: Sha256
    optimization_policy_sha256: Sha256
    data_contract_sha256: Sha256
    feature_contract_sha256: Sha256
    catalog_manifest_sha256: Sha256
    selected_config_sha256: Sha256

    @property
    def preparation_key_sha256(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"))


def build_catalog_preparation_identity(
    *,
    repo_root: Path,
    registry_entry: CatalogCampaignEntryV1,
    protected_commit_sha: str,
) -> CatalogPreparationIdentityV1:
    """Verify the registered closure and derive one exact preparation key."""

    from .catalog_campaign_definition_builder import (
        verify_catalog_campaign_definition,
    )
    from .catalog_campaign_definition_contract import (
        parse_catalog_campaign_definition_bytes,
    )

    root = Path(repo_root).resolve(strict=True)
    if Path(repo_root).is_symlink() or not root.is_dir():
        raise ValueError("CATALOG_PREPARATION_REPOSITORY_INVALID")
    manifest_path = _safe_repository_file(
        root,
        registry_entry.definition_manifest_path,
    )
    manifest = parse_catalog_campaign_definition_bytes(manifest_path.read_bytes())
    verified = verify_catalog_campaign_definition(
        repo_root=root,
        registry_entry=registry_entry,
        manifest=manifest,
    )
    return CatalogPreparationIdentityV1(
        schema_version="1",
        campaign_key=registry_entry.campaign_key,
        engine_id=registry_entry.engine_id,
        protected_commit_sha=protected_commit_sha,
        campaign_definition_sha256=verified.campaign_definition_sha256,
        scientific_contract_sha256=registry_entry.scientific_contract_sha256,
        dependency_lock_sha256=_file_sha256(
            _safe_repository_file(root, "requirements/catalog-optimized.lock")
        ),
        optimization_policy_sha256=_file_sha256(
            _safe_repository_file(root, registry_entry.optimization_policy_path)
        ),
        data_contract_sha256=_file_sha256(
            _safe_repository_file(root, registry_entry.data_contract_path)
        ),
        feature_contract_sha256=_file_sha256(
            _safe_repository_file(root, registry_entry.feature_contract_path)
        ),
        catalog_manifest_sha256=_file_sha256(
            _safe_repository_file(
                root,
                f"{registry_entry.catalog_dir}/manifest.json",
            )
        ),
        selected_config_sha256=_file_sha256(
            _safe_repository_file(root, registry_entry.selected_config_path)
        ),
    )


class CatalogPreparedReceiptV1(FrozenModel):
    """Content-bound proof that one campaign may use the short launch path."""

    schema_version: Literal["1"] = "1"
    status: Literal["PREPARED"] = "PREPARED"
    identity: CatalogPreparationIdentityV1
    generated_at: datetime
    runtime_identity_sha256: Sha256
    prepared_input_identity_sha256: Sha256
    component_store_manifest_sha256: Sha256
    execution_plan_template_sha256: Sha256
    required_cache_keys: tuple[str, ...]
    logical_recipe_count: int = Field(ge=1)
    unique_component_count: int = Field(ge=1)
    qualified_worker_ceiling: int = Field(ge=1, le=360)
    production_dependency_smoke_passed: Literal[True]
    recipe_worker_build_allowed: Literal[False]
    receipt_sha256: Sha256

    @field_validator("generated_at")
    @classmethod
    def _generated_at_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value, code="CATALOG_PREPARED_TIME_INVALID")

    @field_validator("required_cache_keys")
    @classmethod
    def _required_cache_keys_are_canonical(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if (
            not value
            or value != tuple(sorted(set(value)))
            or any(
                not item
                or item.strip() != item
                or len(item) > 512
                or any(ord(character) < 32 for character in item)
                for item in value
            )
        ):
            raise ValueError("CATALOG_PREPARED_CACHE_KEYS_INVALID")
        return value

    @model_validator(mode="after")
    def _verify_receipt_hash(self) -> "CatalogPreparedReceiptV1":
        identity = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != _canonical_sha256(identity):
            raise ValueError("CATALOG_PREPARED_RECEIPT_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        identity: CatalogPreparationIdentityV1,
        generated_at: datetime,
        runtime_identity_sha256: str,
        prepared_input_identity_sha256: str,
        component_store_manifest_sha256: str,
        execution_plan_template_sha256: str,
        required_cache_keys: tuple[str, ...],
        logical_recipe_count: int,
        unique_component_count: int,
        qualified_worker_ceiling: int,
        production_dependency_smoke_passed: bool,
        recipe_worker_build_allowed: bool,
    ) -> "CatalogPreparedReceiptV1":
        normalized_at = _as_utc(
            generated_at,
            code="CATALOG_PREPARED_TIME_INVALID",
        )
        values = {
            "schema_version": "1",
            "status": "PREPARED",
            "identity": identity.model_dump(mode="json"),
            "generated_at": normalized_at.isoformat().replace("+00:00", "Z"),
            "runtime_identity_sha256": runtime_identity_sha256,
            "prepared_input_identity_sha256": prepared_input_identity_sha256,
            "component_store_manifest_sha256": component_store_manifest_sha256,
            "execution_plan_template_sha256": execution_plan_template_sha256,
            "required_cache_keys": required_cache_keys,
            "logical_recipe_count": logical_recipe_count,
            "unique_component_count": unique_component_count,
            "qualified_worker_ceiling": qualified_worker_ceiling,
            "production_dependency_smoke_passed": production_dependency_smoke_passed,
            "recipe_worker_build_allowed": recipe_worker_build_allowed,
        }
        return cls.model_validate(
            {**values, "receipt_sha256": _canonical_sha256(values)}
        )


class ExistingCatalogLaunchV1(FrozenModel):
    submission_key_sha256: Sha256
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    state: Literal["QUEUED", "RUNNING", "RECOVERING", "SUCCESS", "BLOCKED"]
    run_id: int = Field(ge=1)


class CatalogFastGateSnapshotV1(FrozenModel):
    """Small live snapshot consumed by one serialized admission job."""

    schema_version: Literal["1"]
    observed_at: datetime
    protected_commit_sha: CommitSha
    controller_enabled: bool
    production_armed: bool
    current_safe_free_capacity: int = Field(ge=0, le=360)
    existing_launches: tuple[ExistingCatalogLaunchV1, ...]
    active_campaign_keys: tuple[str, ...]

    @field_validator("observed_at")
    @classmethod
    def _observed_at_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value, code="CATALOG_GATE_TIME_INVALID")

    @field_validator("active_campaign_keys")
    @classmethod
    def _active_campaigns_are_canonical(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("CATALOG_ACTIVE_CAMPAIGNS_INVALID")
        return value

    @field_validator("existing_launches")
    @classmethod
    def _existing_launches_are_unique(
        cls,
        value: tuple[ExistingCatalogLaunchV1, ...],
    ) -> tuple[ExistingCatalogLaunchV1, ...]:
        keys = tuple(item.submission_key_sha256 for item in value)
        if len(keys) != len(set(keys)):
            raise ValueError("CATALOG_EXISTING_LAUNCHES_INVALID")
        return value


class CatalogFastLaunchDecisionV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    state: CatalogPublicState
    reason_code: ReasonCode
    request_sha256: Sha256
    submission_key_sha256: Sha256
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    prepared_receipt_sha256: Sha256 | None
    selected_workers: int = Field(ge=0, le=360)
    launch_required: bool
    existing_run_id: int | None = Field(default=None, ge=1)
    decided_at: datetime
    expires_at: datetime
    decision_sha256: Sha256

    @field_validator("decided_at", "expires_at")
    @classmethod
    def _times_are_utc(cls, value: datetime) -> datetime:
        return _as_utc(value, code="CATALOG_GATE_TIME_INVALID")

    @model_validator(mode="after")
    def _validate_decision(self) -> "CatalogFastLaunchDecisionV1":
        if self.launch_required:
            if self.state != "QUEUED" or self.selected_workers < 1:
                raise ValueError("CATALOG_FAST_DECISION_INVALID")
        elif self.state == "BLOCKED" and self.selected_workers != 0:
            raise ValueError("CATALOG_FAST_DECISION_INVALID")
        if self.existing_run_id is not None and self.launch_required:
            raise ValueError("CATALOG_FAST_DECISION_INVALID")
        identity = self.model_dump(mode="json", exclude={"decision_sha256"})
        if self.decision_sha256 != _canonical_sha256(identity):
            raise ValueError("CATALOG_FAST_DECISION_HASH_INVALID")
        return self

    @classmethod
    def create(cls, **values: object) -> "CatalogFastLaunchDecisionV1":
        identity = {
            "schema_version": "1",
            **values,
        }
        identity["decided_at"] = _as_utc(
            identity["decided_at"],  # type: ignore[arg-type]
            code="CATALOG_GATE_TIME_INVALID",
        ).isoformat().replace("+00:00", "Z")
        identity["expires_at"] = _as_utc(
            identity["expires_at"],  # type: ignore[arg-type]
            code="CATALOG_GATE_TIME_INVALID",
        ).isoformat().replace("+00:00", "Z")
        return cls.model_validate(
            {**identity, "decision_sha256": _canonical_sha256(identity)}
        )


def _blocked_decision(
    *,
    request: CatalogRunRequestV1,
    snapshot: CatalogFastGateSnapshotV1,
    expires_at: datetime,
    reason_code: str,
    prepared_receipt_sha256: str | None,
) -> CatalogFastLaunchDecisionV1:
    return CatalogFastLaunchDecisionV1.create(
        state="BLOCKED",
        reason_code=reason_code,
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256=prepared_receipt_sha256,
        selected_workers=0,
        launch_required=False,
        existing_run_id=None,
        decided_at=snapshot.observed_at,
        expires_at=expires_at,
    )


def decide_fast_catalog_launch(
    *,
    request: CatalogRunRequestV1,
    registry_entry: CatalogCampaignEntryV1,
    prepared_receipt: CatalogPreparedReceiptV1,
    expected_preparation_identity: CatalogPreparationIdentityV1,
    snapshot: CatalogFastGateSnapshotV1,
    issue_created_at: datetime,
) -> CatalogFastLaunchDecisionV1:
    """Admit, adopt, or block one request without doing scientific work."""

    created_at = _as_utc(issue_created_at, code="CATALOG_REQUEST_TIME_INVALID")
    expires_at = created_at + REQUEST_MAX_AGE
    prepared_hash = prepared_receipt.receipt_sha256

    if created_at > snapshot.observed_at + REQUEST_FUTURE_TOLERANCE:
        return _blocked_decision(
            request=request,
            snapshot=snapshot,
            expires_at=expires_at,
            reason_code="CATALOG_REQUEST_TIME_INVALID",
            prepared_receipt_sha256=prepared_hash,
        )
    if snapshot.observed_at > expires_at:
        return _blocked_decision(
            request=request,
            snapshot=snapshot,
            expires_at=expires_at,
            reason_code="CATALOG_REQUEST_EXPIRED",
            prepared_receipt_sha256=prepared_hash,
        )
    if not snapshot.controller_enabled:
        return _blocked_decision(
            request=request,
            snapshot=snapshot,
            expires_at=expires_at,
            reason_code="CATALOG_CONTROLLER_DISABLED",
            prepared_receipt_sha256=prepared_hash,
        )
    if not snapshot.production_armed:
        return _blocked_decision(
            request=request,
            snapshot=snapshot,
            expires_at=expires_at,
            reason_code="CATALOG_PRODUCTION_DISARMED",
            prepared_receipt_sha256=prepared_hash,
        )
    if not registry_entry.active or request.campaign_key != registry_entry.campaign_key:
        return _blocked_decision(
            request=request,
            snapshot=snapshot,
            expires_at=expires_at,
            reason_code="CATALOG_CAMPAIGN_NOT_REGISTERED",
            prepared_receipt_sha256=prepared_hash,
        )

    identity = prepared_receipt.identity
    preparation_matches = (
        identity == expected_preparation_identity
        and expected_preparation_identity.protected_commit_sha
        == snapshot.protected_commit_sha
        and identity.campaign_key == registry_entry.campaign_key
        and identity.engine_id == registry_entry.engine_id
        and identity.protected_commit_sha == snapshot.protected_commit_sha
        and identity.campaign_definition_sha256
        == request.campaign_definition_sha256
        and identity.scientific_contract_sha256
        == registry_entry.scientific_contract_sha256
    )
    if not preparation_matches:
        return _blocked_decision(
            request=request,
            snapshot=snapshot,
            expires_at=expires_at,
            reason_code="CATALOG_PREPARATION_STALE",
            prepared_receipt_sha256=prepared_hash,
        )

    existing_by_key = {
        item.submission_key_sha256: item for item in snapshot.existing_launches
    }
    existing = existing_by_key.get(request.submission_key_sha256)
    if existing is not None:
        return CatalogFastLaunchDecisionV1.create(
            state=existing.state,
            reason_code=f"CATALOG_REQUEST_ALREADY_{existing.state}",
            request_sha256=request.request_sha256,
            submission_key_sha256=request.submission_key_sha256,
            campaign_key=request.campaign_key,
            prepared_receipt_sha256=prepared_hash,
            selected_workers=0,
            launch_required=False,
            existing_run_id=existing.run_id,
            decided_at=snapshot.observed_at,
            expires_at=expires_at,
        )
    if request.campaign_key in snapshot.active_campaign_keys:
        return _blocked_decision(
            request=request,
            snapshot=snapshot,
            expires_at=expires_at,
            reason_code="CATALOG_CAMPAIGN_BUSY",
            prepared_receipt_sha256=prepared_hash,
        )
    if snapshot.current_safe_free_capacity < 1:
        return _blocked_decision(
            request=request,
            snapshot=snapshot,
            expires_at=expires_at,
            reason_code="CATALOG_FREE_CAPACITY_UNAVAILABLE",
            prepared_receipt_sha256=prepared_hash,
        )

    selected_workers = min(
        registry_entry.max_free_workers,
        prepared_receipt.qualified_worker_ceiling,
        snapshot.current_safe_free_capacity,
    )
    return CatalogFastLaunchDecisionV1.create(
        state="QUEUED",
        reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256=prepared_hash,
        selected_workers=selected_workers,
        launch_required=True,
        existing_run_id=None,
        decided_at=snapshot.observed_at,
        expires_at=expires_at,
    )


class CatalogExecutionSampleV1(FrozenModel):
    """One measured free-runner topology, including provider queue time."""

    workers: int = Field(ge=1, le=360)
    component_workers: int = Field(ge=1, le=120)
    component_processes_per_worker: int = Field(ge=1, le=4)
    processes_per_worker: int = Field(ge=1, le=4)
    block_size: int = Field(ge=1)
    queue_seconds: float = Field(ge=0)
    setup_seconds: float = Field(ge=0)
    compute_seconds: float = Field(ge=0)
    reduction_seconds: float = Field(ge=0)
    equivalent: bool
    free_resources_only: bool

    @property
    def request_to_completion_seconds(self) -> float:
        return (
            self.queue_seconds
            + self.setup_seconds
            + self.compute_seconds
            + self.reduction_seconds
        )


def select_fast_execution_configuration(
    samples: tuple[CatalogExecutionSampleV1, ...],
    *,
    maximum_workers: int,
    current_safe_free_capacity: int,
) -> CatalogExecutionSampleV1:
    """Select measured end-to-end speed, never compute speed in isolation."""

    if not 1 <= maximum_workers <= 360 or not 1 <= current_safe_free_capacity <= 360:
        raise ValueError("CATALOG_WORKER_CEILING_INVALID")
    ceiling = min(maximum_workers, current_safe_free_capacity)
    eligible = tuple(
        sample
        for sample in samples
        if sample.equivalent
        and sample.free_resources_only
        and sample.workers <= ceiling
    )
    if not eligible:
        raise ValueError("CATALOG_FAST_CONFIGURATION_UNAVAILABLE")
    return min(
        eligible,
        key=lambda sample: (
            sample.request_to_completion_seconds,
            sample.workers,
            sample.component_workers,
            sample.component_processes_per_worker,
            sample.processes_per_worker,
            sample.block_size,
        ),
    )


_TRANSIENT_FAILURES = frozenset(
    {
        "GITHUB_ACTIONS_SERVICE_UNAVAILABLE",
        "GITHUB_ARTIFACT_DOWNLOAD_TRANSIENT",
        "GITHUB_CACHE_SERVICE_TRANSIENT",
        "GITHUB_RATE_LIMIT_TRANSIENT",
        "GITHUB_RUNNER_LOST",
        "NETWORK_TRANSIENT",
    }
)


def should_retry_catalog_failure(reason_code: str, *, occurrences: int) -> bool:
    """Permit at most two retries, and only for a closed transient set."""

    if occurrences < 1:
        raise ValueError("CATALOG_FAILURE_OCCURRENCE_INVALID")
    return reason_code in _TRANSIENT_FAILURES and occurrences < 3


class CatalogTerminalReceiptV1(FrozenModel):
    """One content-bound terminal result with complete timing separation."""

    schema_version: Literal["1"] = "1"
    state: Literal["SUCCESS", "BLOCKED"]
    reason_code: ReasonCode
    request_sha256: Sha256
    submission_key_sha256: Sha256
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    prepared_receipt_sha256: Sha256 | None
    engine_run_id: int | None = Field(default=None, ge=1)
    run_url: Annotated[
        str,
        StringConstraints(pattern=r"^https://[^\s]+$"),
    ] | None = None
    expected_recipe_count: int = Field(ge=1)
    observed_recipe_count: int = Field(ge=0)
    queue_seconds: float = Field(ge=0)
    preparation_seconds: float = Field(ge=0)
    computation_seconds: float = Field(ge=0)
    recovery_seconds: float = Field(ge=0)
    reduction_seconds: float = Field(ge=0)
    recovered_block_count: int = Field(ge=0)
    failure_class: Literal["request", "infrastructure", "scientific"] | None
    result_science_sha256: Sha256 | None
    created_at: datetime
    receipt_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        return _as_utc(value, code="CATALOG_TERMINAL_TIME_INVALID")

    @model_validator(mode="after")
    def _terminal_shape_and_hash_are_exact(self) -> "CatalogTerminalReceiptV1":
        if self.observed_recipe_count > self.expected_recipe_count:
            raise ValueError("CATALOG_TERMINAL_COVERAGE_INVALID")
        if self.state == "SUCCESS":
            if (
                self.reason_code != "CATALOG_RUN_SUCCESS"
                or self.prepared_receipt_sha256 is None
                or self.observed_recipe_count != self.expected_recipe_count
                or self.failure_class is not None
                or self.result_science_sha256 is None
                or self.engine_run_id is None
                or self.run_url is None
            ):
                raise ValueError("CATALOG_TERMINAL_COVERAGE_INVALID")
        elif (
            self.reason_code == "CATALOG_RUN_SUCCESS"
            or self.failure_class is None
        ):
            raise ValueError("CATALOG_TERMINAL_BLOCK_REASON_REQUIRED")
        identity = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != _canonical_sha256(identity):
            raise ValueError("CATALOG_TERMINAL_RECEIPT_HASH_INVALID")
        return self

    @classmethod
    def create(cls, **values: object) -> "CatalogTerminalReceiptV1":
        identity = {"schema_version": "1", **values}
        identity["created_at"] = _as_utc(
            identity["created_at"],  # type: ignore[arg-type]
            code="CATALOG_TERMINAL_TIME_INVALID",
        ).isoformat().replace("+00:00", "Z")
        return cls.model_validate(
            {**identity, "receipt_sha256": _canonical_sha256(identity)}
        )


__all__ = [
    "CatalogExecutionSampleV1",
    "CatalogFastGateSnapshotV1",
    "CatalogFastLaunchDecisionV1",
    "CatalogPreparedReceiptV1",
    "CatalogPreparationIdentityV1",
    "CatalogTerminalReceiptV1",
    "ExistingCatalogLaunchV1",
    "build_catalog_preparation_identity",
    "decide_fast_catalog_launch",
    "select_fast_execution_configuration",
    "should_retry_catalog_failure",
]
