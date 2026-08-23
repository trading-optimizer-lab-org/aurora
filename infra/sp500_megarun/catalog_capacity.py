"""Conservative, evidence-bound capacity admission for catalog campaigns."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)


MAX_CATALOG_WORKERS = 360
MAX_GITHUB_MATRIX_JOBS = 256
MAX_CACHE_ENTRIES_PER_CAMPAIGN = 160
MAX_COMPONENT_BUNDLES = 128
MAX_CACHE_UPLOADS_PER_MINUTE = 160
MAX_CACHE_DOWNLOADS_PER_MINUTE = 1200
CACHE_STORAGE_LIMIT_BYTES = 10 * 1024**3
CACHE_RETENTION_DAYS = 90
ARTIFACT_TRANSPORT_RETENTION_DAYS = 1
CAPACITY_EVIDENCE_MAX_AGE = timedelta(days=7)
LIVE_SNAPSHOT_MAX_AGE = timedelta(minutes=5)
MAX_FUTURE_SKEW = timedelta(seconds=30)
ARTIFACT_REPORTING_WINDOW = timedelta(hours=12)
CACHE_REPORTING_WINDOW = timedelta(minutes=5)
MIN_TOPOLOGY_SAMPLES = 3


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


class StorageObjectV1(FrozenModel):
    """One object visible in a complete live artifact/package/cache inventory."""

    object_id: str = Field(min_length=1)
    size_bytes: Annotated[int, Field(ge=0)]


class StorageWriteReceiptV1(FrozenModel):
    """A verified write that may not yet be reflected by GitHub telemetry."""

    object_id: str = Field(min_length=1)
    size_bytes: Annotated[int, Field(ge=0)]
    written_at: datetime
    receipt_sha256: Sha256

    @field_validator("written_at")
    @classmethod
    def _validate_written_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, field="written_at")


class CatalogCapacityProfileV1(FrozenModel):
    """Previously qualified structural ceiling; never a live availability guess."""

    schema_version: Literal["1"] = "1"
    organization: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    repository_visibility: Literal["public"]
    plan: str = Field(min_length=1)
    runner_image: Literal["ubuntu-24.04"] = "ubuntu-24.04"
    standard_runner_only: Literal[True] = True
    larger_runners_allowed: Literal[False] = False
    self_hosted_runners_allowed: Literal[False] = False
    maximum_concurrent_jobs: Annotated[int, Field(ge=1, le=MAX_CATALOG_WORKERS)]
    proven_uncontended_floor: Annotated[int, Field(ge=1, le=MAX_CATALOG_WORKERS)]
    matrix_job_ceiling: Literal[256] = 256
    maximum_active_heavy_catalog_campaigns: Literal[1] = 1
    topology_qualified: bool
    topology_sample_count: Annotated[int, Field(ge=0)]
    qualified_at: datetime
    included_shared_artifact_package_storage_bytes: Annotated[int, Field(ge=1)]
    cache_storage_limit_bytes: Literal[CACHE_STORAGE_LIMIT_BYTES] = (
        CACHE_STORAGE_LIMIT_BYTES
    )
    cache_retention_days: Literal[CACHE_RETENTION_DAYS] = CACHE_RETENTION_DAYS
    organization_sha256: Sha256
    repository_plan_sha256: Sha256
    runner_class_sha256: Sha256
    capacity_contract_sha256: Sha256
    qualification_receipt_sha256: Sha256
    qualification_run_ids: tuple[str, ...]
    profile_sha256: Sha256

    @field_validator("qualified_at")
    @classmethod
    def _validate_qualified_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, field="qualified_at")

    @model_validator(mode="after")
    def _validate_profile(self) -> "CatalogCapacityProfileV1":
        if self.proven_uncontended_floor > self.maximum_concurrent_jobs:
            raise ValueError("CAPACITY_SAFE_FLOOR_EXCEEDS_MAXIMUM")
        if len(set(self.qualification_run_ids)) != len(
            self.qualification_run_ids
        ):
            raise ValueError("CAPACITY_QUALIFICATION_RUN_IDS_DUPLICATE")
        if self.profile_sha256 != canonical_sha256(
            self.model_dump(mode="python", exclude={"profile_sha256"})
        ):
            raise ValueError("CAPACITY_PROFILE_HASH_INVALID")
        return self

    @classmethod
    def create(cls, **values: object) -> "CatalogCapacityProfileV1":
        identity = {"schema_version": "1", **values}
        identity.pop("profile_sha256", None)
        if isinstance(identity.get("qualified_at"), datetime):
            identity["qualified_at"] = _aware_utc(
                identity["qualified_at"],
                field="qualified_at",
            )
        candidate = cls.model_construct(
            **identity,
            profile_sha256="0" * 64,
        )
        complete = candidate.model_dump(
            mode="python",
            exclude={"profile_sha256"},
        )
        return cls(**complete, profile_sha256=canonical_sha256(complete))


class CatalogLiveCapacitySnapshotV1(FrozenModel):
    """Complete live facts used once for a deterministic admission decision."""

    schema_version: Literal["1"] = "1"
    observed_at: datetime
    calibration_observed_at: datetime
    available_standard_jobs: Annotated[
        int | None,
        Field(default=None, ge=0, le=MAX_CATALOG_WORKERS),
    ]
    fresh_runner_health: bool
    runner_image: str
    standard_runner_only: bool
    larger_runners_enabled: bool
    self_hosted_runners_enabled: bool
    zero_actions_spend_budget_verified: bool
    zero_actions_storage_budget_verified: bool
    zero_cache_storage_budget_verified: bool
    zero_spend_budgets_receipt_sha256: Sha256 | None
    cache_storage_limit_bytes: int | None
    cache_retention_days: int | None
    artifact_package_inventory_complete: bool
    artifact_package_recent_writes_complete: bool
    reported_shared_artifact_package_storage_bytes: Annotated[
        int | None,
        Field(default=None, ge=0),
    ]
    artifact_package_objects: tuple[StorageObjectV1, ...]
    artifact_package_recent_writes: tuple[StorageWriteReceiptV1, ...]
    cache_inventory_complete: bool
    cache_recent_writes_complete: bool
    reported_cache_storage_bytes: Annotated[
        int | None,
        Field(default=None, ge=0),
    ]
    cache_objects: tuple[StorageObjectV1, ...]
    cache_recent_writes: tuple[StorageWriteReceiptV1, ...]
    authority_ledger_observable: bool
    authority_ledger_complete: bool
    authority_ledger_stable: bool
    authority_ledger_conflicting: bool
    active_heavy_campaign_ids: tuple[Sha256, ...]
    requested_campaign_id: Sha256
    organization_sha256: Sha256
    repository_plan_sha256: Sha256
    runner_class_sha256: Sha256
    capacity_contract_sha256: Sha256
    calibration_receipt_sha256: Sha256
    live_snapshot_sha256: Sha256

    @field_validator("observed_at", "calibration_observed_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime) -> datetime:
        return _aware_utc(value, field="capacity timestamp")

    @model_validator(mode="after")
    def _validate_snapshot(self) -> "CatalogLiveCapacitySnapshotV1":
        if len(set(self.active_heavy_campaign_ids)) != len(
            self.active_heavy_campaign_ids
        ):
            raise ValueError("HEAVY_CAMPAIGN_LEASE_CONFLICT")
        if self.live_snapshot_sha256 != canonical_sha256(
            self.model_dump(mode="python", exclude={"live_snapshot_sha256"})
        ):
            raise ValueError("LIVE_CAPACITY_SNAPSHOT_HASH_INVALID")
        return self

    @classmethod
    def create(cls, **values: object) -> "CatalogLiveCapacitySnapshotV1":
        identity = {"schema_version": "1", **values}
        identity.pop("live_snapshot_sha256", None)
        for field in ("observed_at", "calibration_observed_at"):
            if isinstance(identity.get(field), datetime):
                identity[field] = _aware_utc(identity[field], field=field)
        candidate = cls.model_construct(
            **identity,
            live_snapshot_sha256="0" * 64,
        )
        complete = candidate.model_dump(
            mode="python",
            exclude={"live_snapshot_sha256"},
        )
        return cls(
            **complete,
            live_snapshot_sha256=canonical_sha256(complete),
        )


class CatalogCapacityWorkloadV1(FrozenModel):
    """Operational envelope for fixed catalog science and fixed logical units."""

    registered_maximum_workers: Annotated[
        int,
        Field(ge=1, le=MAX_CATALOG_WORKERS),
    ]
    logical_work_units: Annotated[int, Field(ge=1)]
    processes_per_worker: Annotated[int, Field(ge=1)]
    component_workers: Annotated[int, Field(ge=1, le=MAX_CATALOG_WORKERS)]
    component_processes_per_worker: Annotated[int, Field(ge=1)]
    topology_sample_count: Annotated[int, Field(ge=0)]
    memory_fraction_p50: float = Field(ge=0)
    memory_fraction_p95: float = Field(ge=0)
    memory_fraction_p99: float = Field(ge=0)
    disk_fraction_p50: float = Field(ge=0)
    disk_fraction_p95: float = Field(ge=0)
    disk_fraction_p99: float = Field(ge=0)
    runner_start_seconds_p50: float = Field(ge=0)
    runner_start_seconds_p95: float = Field(ge=0)
    runner_start_seconds_p99: float = Field(ge=0)
    unit_seconds_p50: float = Field(ge=0)
    unit_seconds_p95: float = Field(ge=0)
    unit_seconds_p99: float = Field(ge=0)
    projected_artifact_storage_bytes: Annotated[int, Field(ge=0)]
    projected_cache_storage_bytes: Annotated[int, Field(ge=0)]
    planned_new_cache_entry_count: Annotated[int, Field(ge=0)]
    selected_component_bundle_count: Annotated[int, Field(ge=0)]
    planned_cache_upload_requests_per_minute_peak: Annotated[int, Field(ge=0)]
    planned_cache_download_requests_per_minute_peak: Annotated[int, Field(ge=0)]
    artifact_transport_retention_days: Annotated[int, Field(ge=1)]
    estimated_paid_runner_minutes: Annotated[int, Field(ge=0)]
    estimated_paid_actions_cost: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _validate_distributions(self) -> "CatalogCapacityWorkloadV1":
        triples = (
            (
                self.memory_fraction_p50,
                self.memory_fraction_p95,
                self.memory_fraction_p99,
            ),
            (
                self.disk_fraction_p50,
                self.disk_fraction_p95,
                self.disk_fraction_p99,
            ),
            (
                self.runner_start_seconds_p50,
                self.runner_start_seconds_p95,
                self.runner_start_seconds_p99,
            ),
            (
                self.unit_seconds_p50,
                self.unit_seconds_p95,
                self.unit_seconds_p99,
            ),
        )
        if any(
            not all(math.isfinite(value) for value in triple)
            or tuple(sorted(triple)) != triple
            for triple in triples
        ):
            raise ValueError("CAPACITY_DISTRIBUTION_INVALID")
        return self


class CatalogCapacityDecisionV1(FrozenModel):
    """Canonical result of one exact structural, live, and workload snapshot."""

    schema_version: Literal["1"] = "1"
    profile_sha256: Sha256
    live_snapshot_sha256: Sha256
    runner_image: Literal["ubuntu-24.04"]
    standard_runner_only: Literal[True]
    workers: Annotated[int, Field(ge=0, le=MAX_CATALOG_WORKERS)]
    matrix_sizes: tuple[Annotated[int, Field(ge=1, le=256)], ...]
    processes_per_worker: Annotated[int, Field(ge=1)]
    component_workers: Annotated[int, Field(ge=0, le=MAX_CATALOG_WORKERS)]
    component_processes_per_worker: Annotated[int, Field(ge=1)]
    memory_fraction_p50: float
    memory_fraction_p95: float
    memory_fraction_p99: float
    disk_fraction_p50: float
    disk_fraction_p95: float
    disk_fraction_p99: float
    runner_start_seconds_p50: float
    runner_start_seconds_p95: float
    runner_start_seconds_p99: float
    unit_seconds_p50: float
    unit_seconds_p95: float
    unit_seconds_p99: float
    estimated_paid_runner_minutes: Literal[0]
    zero_spend_budgets_receipt_sha256: Sha256
    projected_artifact_storage_bytes: Annotated[int, Field(ge=0)]
    reported_shared_artifact_package_storage_bytes: Annotated[int, Field(ge=0)]
    reconciled_live_artifact_package_storage_bytes: Annotated[int, Field(ge=0)]
    unreflected_artifact_package_upload_bytes_12h: Annotated[int, Field(ge=0)]
    verified_free_artifact_headroom_bytes: Annotated[int, Field(ge=0)]
    artifact_storage_safety_reserve_bytes: Annotated[int, Field(ge=0)]
    projected_cache_storage_bytes: Annotated[int, Field(ge=0)]
    reported_cache_storage_bytes: Annotated[int, Field(ge=0)]
    reconciled_live_cache_storage_bytes: Annotated[int, Field(ge=0)]
    unreflected_cache_save_bytes_5m: Annotated[int, Field(ge=0)]
    verified_free_cache_headroom_bytes: Annotated[int, Field(ge=0)]
    cache_storage_safety_reserve_bytes: Annotated[int, Field(ge=0)]
    planned_new_cache_entry_count: Annotated[int, Field(ge=0)]
    selected_component_bundle_count: Annotated[int, Field(ge=0)]
    planned_cache_upload_requests_per_minute_peak: Annotated[int, Field(ge=0)]
    planned_cache_download_requests_per_minute_peak: Annotated[int, Field(ge=0)]
    estimated_paid_actions_cost: Literal[0]
    admission_status: Literal["READY", "DEFERRED"]
    decision_reason: str
    retry_not_before: datetime | None
    campaign_identity_changed: Literal[False] = False
    decision_sha256: Sha256

    @field_validator("retry_not_before")
    @classmethod
    def _validate_retry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _aware_utc(value, field="retry_not_before")

    @model_validator(mode="after")
    def _validate_decision(self) -> "CatalogCapacityDecisionV1":
        if sum(self.matrix_sizes) != self.workers:
            raise ValueError("CAPACITY_MATRIX_COVERAGE_INVALID")
        if self.admission_status == "READY" and self.workers == 0:
            raise ValueError("CAPACITY_READY_WITHOUT_WORKERS")
        if self.admission_status == "DEFERRED" and (
            self.workers != 0 or self.retry_not_before is None
        ):
            raise ValueError("CAPACITY_DEFERRED_SHAPE_INVALID")
        if self.decision_sha256 != canonical_sha256(
            self.model_dump(mode="python", exclude={"decision_sha256"})
        ):
            raise ValueError("CAPACITY_DECISION_HASH_INVALID")
        return self

    @classmethod
    def create(cls, **values: object) -> "CatalogCapacityDecisionV1":
        identity = {"schema_version": "1", **values}
        identity.pop("decision_sha256", None)
        if isinstance(identity.get("retry_not_before"), datetime):
            identity["retry_not_before"] = _aware_utc(
                identity["retry_not_before"],
                field="retry_not_before",
            )
        candidate = cls.model_construct(
            **identity,
            decision_sha256="0" * 64,
        )
        complete = candidate.model_dump(
            mode="python",
            exclude={"decision_sha256"},
        )
        return cls(**complete, decision_sha256=canonical_sha256(complete))


def split_catalog_worker_matrix(
    workers: int,
    *,
    matrix_ceiling: int = MAX_GITHUB_MATRIX_JOBS,
) -> tuple[tuple[int, ...], ...]:
    """Split exact worker IDs across GitHub matrices without loss or overlap."""

    if isinstance(workers, bool) or not 0 <= workers <= MAX_CATALOG_WORKERS:
        raise ValueError("workers must be between 0 and 360")
    if not 1 <= matrix_ceiling <= MAX_GITHUB_MATRIX_JOBS:
        raise ValueError("matrix_ceiling must be between 1 and 256")
    worker_ids = tuple(range(workers))
    return tuple(
        worker_ids[start : start + matrix_ceiling]
        for start in range(0, workers, matrix_ceiling)
    )


def pack_catalog_work_units(
    work_unit_ids: Sequence[object],
    *,
    workers: int,
) -> tuple[tuple[object, ...], ...]:
    """Deterministically assign every fixed logical unit exactly once."""

    units = tuple(work_unit_ids)
    if workers < 1:
        raise ValueError("workers must be positive")
    if workers > len(units):
        raise ValueError("workers cannot exceed logical work units")
    if len({repr(item) for item in units}) != len(units):
        raise ValueError("work unit IDs must be unique")
    buckets: list[list[object]] = [[] for _ in range(workers)]
    for index, unit in enumerate(units):
        buckets[index % workers].append(unit)
    return tuple(tuple(bucket) for bucket in buckets)


def _storage_usage(
    *,
    objects: Iterable[StorageObjectV1],
    writes: Iterable[StorageWriteReceiptV1],
    now: datetime,
    window: timedelta,
    error_prefix: str,
) -> tuple[int, int]:
    object_rows = tuple(objects)
    object_sizes: dict[str, int] = {}
    for item in object_rows:
        previous = object_sizes.get(item.object_id)
        if previous is not None and previous != item.size_bytes:
            raise ValueError(f"{error_prefix}_UNPROVEN")
        if previous is not None:
            raise ValueError(f"{error_prefix}_UNPROVEN")
        object_sizes[item.object_id] = item.size_bytes

    receipt_rows: dict[str, StorageWriteReceiptV1] = {}
    writes_by_object: dict[str, int] = {}
    lower = now - window
    upper = now + MAX_FUTURE_SKEW
    for item in writes:
        if item.written_at > upper:
            raise ValueError(f"{error_prefix}_UNPROVEN")
        if item.written_at < lower:
            continue
        previous_receipt = receipt_rows.get(item.receipt_sha256)
        if previous_receipt is not None and previous_receipt != item:
            raise ValueError(f"{error_prefix}_UNPROVEN")
        receipt_rows[item.receipt_sha256] = item
        previous_size = writes_by_object.get(item.object_id)
        if previous_size is not None and previous_size != item.size_bytes:
            raise ValueError(f"{error_prefix}_UNPROVEN")
        writes_by_object[item.object_id] = item.size_bytes

    reconciled = sum(object_sizes.values())
    unreflected = sum(
        size
        for object_id, size in writes_by_object.items()
        if object_id not in object_sizes
    )
    return reconciled, unreflected


def _require_fresh(
    observed_at: datetime,
    *,
    now: datetime,
    maximum_age: timedelta,
    reason: str,
) -> None:
    age = now - observed_at
    if age > maximum_age or age < -MAX_FUTURE_SKEW:
        raise ValueError(reason)


def _require_compatible_hashes(
    profile: CatalogCapacityProfileV1,
    live: CatalogLiveCapacitySnapshotV1,
) -> None:
    fields = (
        "organization_sha256",
        "repository_plan_sha256",
        "runner_class_sha256",
        "capacity_contract_sha256",
    )
    if any(getattr(profile, field) != getattr(live, field) for field in fields):
        raise ValueError("CAPACITY_TOPOLOGY_UNQUALIFIED")


def _base_decision_values(
    *,
    profile: CatalogCapacityProfileV1,
    live: CatalogLiveCapacitySnapshotV1,
    workload: CatalogCapacityWorkloadV1,
    artifact_reconciled: int,
    artifact_unreflected: int,
    artifact_headroom: int,
    artifact_reserve: int,
    cache_reconciled: int,
    cache_unreflected: int,
    cache_headroom: int,
    cache_reserve: int,
) -> dict[str, object]:
    return {
        "profile_sha256": profile.profile_sha256,
        "live_snapshot_sha256": live.live_snapshot_sha256,
        "runner_image": "ubuntu-24.04",
        "standard_runner_only": True,
        "processes_per_worker": workload.processes_per_worker,
        "component_processes_per_worker": (
            workload.component_processes_per_worker
        ),
        "memory_fraction_p50": workload.memory_fraction_p50,
        "memory_fraction_p95": workload.memory_fraction_p95,
        "memory_fraction_p99": workload.memory_fraction_p99,
        "disk_fraction_p50": workload.disk_fraction_p50,
        "disk_fraction_p95": workload.disk_fraction_p95,
        "disk_fraction_p99": workload.disk_fraction_p99,
        "runner_start_seconds_p50": workload.runner_start_seconds_p50,
        "runner_start_seconds_p95": workload.runner_start_seconds_p95,
        "runner_start_seconds_p99": workload.runner_start_seconds_p99,
        "unit_seconds_p50": workload.unit_seconds_p50,
        "unit_seconds_p95": workload.unit_seconds_p95,
        "unit_seconds_p99": workload.unit_seconds_p99,
        "estimated_paid_runner_minutes": 0,
        "zero_spend_budgets_receipt_sha256": (
            live.zero_spend_budgets_receipt_sha256
        ),
        "projected_artifact_storage_bytes": (
            workload.projected_artifact_storage_bytes
        ),
        "reported_shared_artifact_package_storage_bytes": (
            live.reported_shared_artifact_package_storage_bytes
        ),
        "reconciled_live_artifact_package_storage_bytes": artifact_reconciled,
        "unreflected_artifact_package_upload_bytes_12h": artifact_unreflected,
        "verified_free_artifact_headroom_bytes": artifact_headroom,
        "artifact_storage_safety_reserve_bytes": artifact_reserve,
        "projected_cache_storage_bytes": workload.projected_cache_storage_bytes,
        "reported_cache_storage_bytes": live.reported_cache_storage_bytes,
        "reconciled_live_cache_storage_bytes": cache_reconciled,
        "unreflected_cache_save_bytes_5m": cache_unreflected,
        "verified_free_cache_headroom_bytes": cache_headroom,
        "cache_storage_safety_reserve_bytes": cache_reserve,
        "planned_new_cache_entry_count": workload.planned_new_cache_entry_count,
        "selected_component_bundle_count": workload.selected_component_bundle_count,
        "planned_cache_upload_requests_per_minute_peak": (
            workload.planned_cache_upload_requests_per_minute_peak
        ),
        "planned_cache_download_requests_per_minute_peak": (
            workload.planned_cache_download_requests_per_minute_peak
        ),
        "estimated_paid_actions_cost": 0,
        "campaign_identity_changed": False,
    }


def select_safe_catalog_capacity(
    *,
    profile: CatalogCapacityProfileV1,
    live: CatalogLiveCapacitySnapshotV1,
    workload: CatalogCapacityWorkloadV1,
    now: datetime,
) -> CatalogCapacityDecisionV1:
    """Select only capacity supported by fresh, exact, free evidence."""

    now = _aware_utc(now, field="now")
    _require_fresh(
        profile.qualified_at,
        now=now,
        maximum_age=CAPACITY_EVIDENCE_MAX_AGE,
        reason="CAPACITY_PROFILE_STALE",
    )
    if (
        not profile.topology_qualified
        or profile.topology_sample_count < MIN_TOPOLOGY_SAMPLES
        or workload.topology_sample_count < MIN_TOPOLOGY_SAMPLES
    ):
        raise ValueError("CAPACITY_TOPOLOGY_UNQUALIFIED")
    _require_compatible_hashes(profile, live)
    _require_fresh(
        live.observed_at,
        now=now,
        maximum_age=LIVE_SNAPSHOT_MAX_AGE,
        reason="LIVE_CAPACITY_SNAPSHOT_STALE",
    )
    _require_fresh(
        live.calibration_observed_at,
        now=now,
        maximum_age=CAPACITY_EVIDENCE_MAX_AGE,
        reason="LIVE_CAPACITY_HEALTH_STALE",
    )
    if not live.fresh_runner_health:
        raise ValueError("LIVE_CAPACITY_HEALTH_MISSING")
    if live.runner_image != "ubuntu-24.04":
        raise ValueError("STANDARD_RUNNER_IMAGE_REQUIRED")
    if not live.standard_runner_only:
        raise ValueError("STANDARD_RUNNER_ONLY_REQUIRED")
    if workload.estimated_paid_runner_minutes != 0:
        raise ValueError("PAID_RUNNER_FORBIDDEN")
    if workload.estimated_paid_actions_cost != 0:
        raise ValueError("PAID_ACTIONS_COST_FORBIDDEN")
    if live.larger_runners_enabled:
        raise ValueError("LARGER_RUNNER_FORBIDDEN")
    if live.self_hosted_runners_enabled:
        raise ValueError("SELF_HOSTED_RUNNER_FORBIDDEN")
    if not live.zero_actions_spend_budget_verified:
        raise ValueError("ZERO_ACTIONS_SPEND_BUDGET_REQUIRED")
    if not live.zero_actions_storage_budget_verified:
        raise ValueError("ZERO_ACTIONS_STORAGE_BUDGET_REQUIRED")
    if not live.zero_cache_storage_budget_verified:
        raise ValueError("ZERO_CACHE_STORAGE_BUDGET_REQUIRED")
    if live.zero_spend_budgets_receipt_sha256 is None:
        raise ValueError("ZERO_SPEND_BUDGET_RECEIPT_REQUIRED")
    if live.cache_storage_limit_bytes != CACHE_STORAGE_LIMIT_BYTES:
        raise ValueError("FREE_CACHE_STORAGE_LIMIT_REQUIRED")
    if live.cache_retention_days != CACHE_RETENTION_DAYS:
        raise ValueError("FREE_CACHE_RETENTION_REQUIRED")
    if workload.artifact_transport_retention_days != 1:
        raise ValueError("ARTIFACT_TRANSPORT_RETENTION_INVALID")
    if workload.planned_new_cache_entry_count > MAX_CACHE_ENTRIES_PER_CAMPAIGN:
        raise ValueError("CACHE_ENTRY_LIMIT_EXCEEDED")
    if workload.selected_component_bundle_count > MAX_COMPONENT_BUNDLES:
        raise ValueError("COMPONENT_BUNDLE_LIMIT_EXCEEDED")
    if (
        workload.planned_cache_upload_requests_per_minute_peak
        > MAX_CACHE_UPLOADS_PER_MINUTE
    ):
        raise ValueError("CACHE_UPLOAD_RATE_LIMIT_EXCEEDED")
    if (
        workload.planned_cache_download_requests_per_minute_peak
        > MAX_CACHE_DOWNLOADS_PER_MINUTE
    ):
        raise ValueError("CACHE_DOWNLOAD_RATE_LIMIT_EXCEEDED")
    if workload.memory_fraction_p99 > 0.70:
        raise ValueError("CAPACITY_MEMORY_MARGIN_INSUFFICIENT")
    if workload.disk_fraction_p99 > 0.70:
        raise ValueError("CAPACITY_DISK_MARGIN_INSUFFICIENT")

    if (
        not live.authority_ledger_observable
        or not live.authority_ledger_complete
        or not live.authority_ledger_stable
        or live.authority_ledger_conflicting
        or len(live.active_heavy_campaign_ids)
        > profile.maximum_active_heavy_catalog_campaigns
    ):
        raise ValueError("HEAVY_CAMPAIGN_LEASE_UNPROVEN")

    if (
        not live.artifact_package_inventory_complete
        or not live.artifact_package_recent_writes_complete
        or live.reported_shared_artifact_package_storage_bytes is None
    ):
        raise ValueError("FREE_ARTIFACT_STORAGE_UNPROVEN")
    artifact_reconciled, artifact_unreflected = _storage_usage(
        objects=live.artifact_package_objects,
        writes=live.artifact_package_recent_writes,
        now=now,
        window=ARTIFACT_REPORTING_WINDOW,
        error_prefix="FREE_ARTIFACT_STORAGE",
    )
    artifact_reserve = (
        profile.included_shared_artifact_package_storage_bytes * 20 // 100
    )
    artifact_observed = max(
        live.reported_shared_artifact_package_storage_bytes,
        artifact_reconciled,
    ) + artifact_unreflected
    artifact_headroom = max(
        0,
        profile.included_shared_artifact_package_storage_bytes
        - artifact_reserve
        - artifact_observed,
    )
    if workload.projected_artifact_storage_bytes > artifact_headroom:
        raise ValueError("FREE_ARTIFACT_STORAGE_INSUFFICIENT")

    if (
        not live.cache_inventory_complete
        or not live.cache_recent_writes_complete
        or live.reported_cache_storage_bytes is None
    ):
        raise ValueError("FREE_CACHE_STORAGE_UNPROVEN")
    cache_reconciled, cache_unreflected = _storage_usage(
        objects=live.cache_objects,
        writes=live.cache_recent_writes,
        now=now,
        window=CACHE_REPORTING_WINDOW,
        error_prefix="FREE_CACHE_STORAGE",
    )
    cache_reserve = CACHE_STORAGE_LIMIT_BYTES * 10 // 100
    cache_observed = max(
        live.reported_cache_storage_bytes,
        cache_reconciled,
    ) + cache_unreflected
    cache_headroom = max(
        0,
        CACHE_STORAGE_LIMIT_BYTES - cache_reserve - cache_observed,
    )
    if workload.projected_cache_storage_bytes > cache_headroom:
        raise ValueError("FREE_CACHE_STORAGE_INSUFFICIENT")

    base = _base_decision_values(
        profile=profile,
        live=live,
        workload=workload,
        artifact_reconciled=artifact_reconciled,
        artifact_unreflected=artifact_unreflected,
        artifact_headroom=artifact_headroom,
        artifact_reserve=artifact_reserve,
        cache_reconciled=cache_reconciled,
        cache_unreflected=cache_unreflected,
        cache_headroom=cache_headroom,
        cache_reserve=cache_reserve,
    )
    distinct_active = tuple(
        campaign_id
        for campaign_id in live.active_heavy_campaign_ids
        if campaign_id != live.requested_campaign_id
    )
    if distinct_active:
        return CatalogCapacityDecisionV1.create(
            **base,
            workers=0,
            matrix_sizes=(),
            component_workers=0,
            admission_status="DEFERRED",
            decision_reason="HEAVY_CATALOG_CAMPAIGN_LEASE_HELD",
            retry_not_before=now + timedelta(minutes=5),
        )

    if live.available_standard_jobs is None:
        available = profile.proven_uncontended_floor
        reason = "ACCOUNT_USAGE_UNKNOWN_USING_SAFE_FLOOR"
    else:
        available = live.available_standard_jobs
        reason = "HIGHEST_PROVEN_FREE_CAPACITY_SELECTED"
    workers = min(
        MAX_CATALOG_WORKERS,
        workload.registered_maximum_workers,
        profile.maximum_concurrent_jobs,
        available,
        workload.logical_work_units,
    )
    if workers == 0:
        return CatalogCapacityDecisionV1.create(
            **base,
            workers=0,
            matrix_sizes=(),
            component_workers=0,
            admission_status="DEFERRED",
            decision_reason="STANDARD_RUNNER_CAPACITY_TEMPORARILY_UNAVAILABLE",
            retry_not_before=now + timedelta(minutes=5),
        )
    matrices = split_catalog_worker_matrix(workers)
    return CatalogCapacityDecisionV1.create(
        **base,
        workers=workers,
        matrix_sizes=tuple(len(matrix) for matrix in matrices),
        component_workers=min(workload.component_workers, workers),
        admission_status="READY",
        decision_reason=reason,
        retry_not_before=None,
    )


__all__ = [
    "ARTIFACT_REPORTING_WINDOW",
    "CACHE_REPORTING_WINDOW",
    "CACHE_STORAGE_LIMIT_BYTES",
    "CatalogCapacityDecisionV1",
    "CatalogCapacityProfileV1",
    "CatalogCapacityWorkloadV1",
    "CatalogLiveCapacitySnapshotV1",
    "StorageObjectV1",
    "StorageWriteReceiptV1",
    "pack_catalog_work_units",
    "select_safe_catalog_capacity",
    "split_catalog_worker_matrix",
]
