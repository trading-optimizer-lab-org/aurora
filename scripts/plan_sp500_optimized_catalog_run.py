"""Validate and freeze one optimized SP500 catalog execution plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from aurora.infra.sp500_megarun.catalog_admission import (
    CatalogAdmissionEvidenceV1,
    CatalogRunPlanV1,
    build_catalog_run_plan,
)
from aurora.infra.sp500_megarun.catalog_autotune import (
    CatalogPerformanceHistoryV1,
    CatalogTuningDecisionV1,
    ThermalState,
    select_history_configuration,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_component_inventory import (
    collect_unique_components,
)
from aurora.infra.sp500_megarun.catalog_capacity_qualification import (
    BundleLayoutQualificationV1,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store import (
    RebuildableStoreCandidateV1,
    RebuildableStoreInventoryV1,
    reconcile_verified_store_candidates,
    select_component_store_candidates,
)
from aurora.infra.sp500_megarun.catalog_resume import (
    CatalogResumeWorkManifestV1,
    build_resume_work_manifest,
    load_resume_index,
)
from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)
from aurora.infra.github_performance.merge_planner import (
    MergeResourceProjectionV1,
    ReductionSelectionV1,
    choose_reduction_plan,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    CatalogComponentIdentityV1,
)
from aurora.infra.sp500_megarun.catalog_source_identity import (
    catalog_infrastructure_source_sha256,
    catalog_scientific_source_sha256,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    numeric_runtime_profile_sha256,
)
from aurora.infra.sp500_megarun.strategy_catalog import (
    verify_strategy_catalog_directory,
)


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
BundleCount = Literal[8, 16, 32, 64, 96, 128]


class CatalogComponentRequirementV1(FrozenModel):
    component_id: Sha256
    identity: CatalogComponentIdentityV1
    estimated_bytes: PositiveInt
    source_configuration_sha256: Sha256 | None = None
    runtime_dataset_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _bind_component_id(self) -> CatalogComponentRequirementV1:
        if self.component_id != self.identity.component_key_sha256:
            raise ValueError("CATALOG_COMPONENT_IDENTITY_MISMATCH")
        if self.runtime_dataset_ids != tuple(sorted(set(self.runtime_dataset_ids))):
            raise ValueError("CATALOG_COMPONENT_DATASET_SET_INVALID")
        return self


class CatalogRecipeRequirementV1(FrozenModel):
    strategy_id: str = Field(min_length=1)
    component_ids: tuple[Sha256, ...]
    estimated_seconds_p99: float = Field(gt=0)

    @model_validator(mode="after")
    def _validate_component_set(self) -> CatalogRecipeRequirementV1:
        if (
            not self.component_ids
            or self.component_ids != tuple(sorted(set(self.component_ids)))
        ):
            raise ValueError("CATALOG_RECIPE_COMPONENT_SET_INVALID")
        return self


class CompactMatrixRowV1(FrozenModel):
    worker_id: int = Field(ge=0, le=359)
    descriptor_bundle_artifact: str = Field(min_length=1, max_length=180)
    descriptor_member: str = Field(min_length=1, max_length=240)
    descriptor_sha256: Sha256


class CatalogComponentAssignmentV1(FrozenModel):
    worker_id: int = Field(ge=0, le=359)
    component_ids: tuple[Sha256, ...]
    estimated_bytes: PositiveInt
    preparation_required: bool
    bundle_identity_sha256: Sha256
    source_storage_kind: Literal["actions_cache", "artifact", "missing"]
    cache_lookup_key: str
    cache_persistence_key_prefix: str = Field(min_length=1)
    source_artifact_run_id: int | None = Field(default=None, ge=1)
    source_artifact_id: int | None = Field(default=None, ge=1)
    expected_store_manifest_sha256: Sha256 | None
    runtime_dataset_ids: tuple[str, ...]
    data_partition_artifacts: tuple[str, ...]
    data_partition_manifest_sha256: Sha256
    assignment_artifact: str = Field(min_length=1)
    assignment_member: str = Field(min_length=1)
    assignment_sha256: Sha256
    component_transport_artifact: str = Field(min_length=1)
    descriptor_sha256: Sha256


class CatalogRecipeAssignmentV1(FrozenModel):
    worker_id: int = Field(ge=0, le=359)
    strategy_ids: tuple[str, ...]
    component_bundle_ids: tuple[str, ...]
    projected_seconds_p99: float = Field(gt=0)
    checkpoint_slot_count: Literal[1, 2, 4, 8]
    assignment_artifact: str = Field(min_length=1)
    assignment_member: str = Field(min_length=1)
    assignment_sha256: Sha256
    data_partition_artifacts: tuple[str, ...]
    data_partition_manifest_sha256: Sha256
    component_transport_artifacts: tuple[str, ...]
    component_bundle_manifest_sha256: Sha256
    checkpoint_slot_artifacts: tuple[str, ...]
    checkpoint_slot_manifest_sha256: Sha256
    expected_strategy_manifest_sha256: Sha256
    terminal_attempt_artifact: str = Field(min_length=1)
    descriptor_sha256: Sha256


class StorePreparationPlanV1(FrozenModel):
    identity_sha256: Sha256
    preparation_required: bool
    cached_logical_ids: tuple[str, ...]
    pending_logical_ids: tuple[str, ...]
    worker_objects: tuple[str, ...]
    cache_lookup_keys: tuple[tuple[str, str], ...]


class CatalogGlobalReuseExecutionPlanV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    campaign_id: Sha256
    authority_id: str = Field(min_length=1)
    science_sha256: Sha256
    execution_plan_sha256: Sha256
    required_component_ids: tuple[Sha256, ...]
    cached_component_ids: tuple[Sha256, ...]
    pending_component_ids: tuple[Sha256, ...]
    component_requirements: tuple[CatalogComponentRequirementV1, ...]
    recipe_requirements: tuple[CatalogRecipeRequirementV1, ...]
    component_assignments: tuple[CatalogComponentAssignmentV1, ...]
    cached_component_assignments: tuple[CatalogComponentAssignmentV1, ...]
    recipe_assignments: tuple[CatalogRecipeAssignmentV1, ...]
    component_matrix_a: tuple[CompactMatrixRowV1, ...]
    component_matrix_b: tuple[CompactMatrixRowV1, ...]
    cached_component_matrix_a: tuple[CompactMatrixRowV1, ...]
    cached_component_matrix_b: tuple[CompactMatrixRowV1, ...]
    recipe_matrix_a: tuple[CompactMatrixRowV1, ...]
    recipe_matrix_b: tuple[CompactMatrixRowV1, ...]
    recipe_matrix_c: tuple[CompactMatrixRowV1, ...]
    runtime: StorePreparationPlanV1
    prepared_inputs: StorePreparationPlanV1
    selected_component_bundle_count: BundleCount
    component_cache_bundle_count: int = Field(ge=0, le=128)
    new_cache_entry_count: int = Field(ge=0, le=160)
    cache_uploads_per_minute: int = Field(ge=0, le=160)
    cache_downloads_per_minute: int = Field(ge=0, le=1200)
    unique_required_component_bytes: PositiveInt
    projected_worker_component_download_bytes: PositiveInt
    component_bundles_per_worker_p50: float = Field(ge=0)
    component_bundles_per_worker_p95: float = Field(ge=0)
    component_download_amplification_p50: float = Field(ge=0)
    component_download_amplification_p95: float = Field(ge=0)
    matrix_output_utf16_bytes: int = Field(ge=0, le=512 * 1024)
    reduction_projection: MergeResourceProjectionV1
    hierarchical_reduction_projection: MergeResourceProjectionV1
    reduction_selection: ReductionSelectionV1
    recipe_jobs_depend_on_component_store: Literal[True]
    validation_opened: Literal[False] = False
    locked_opened: Literal[False] = False
    plan_sha256: Sha256


def select_qualified_bundle_layout(
    candidates: tuple[BundleLayoutQualificationV1, ...],
) -> BundleLayoutQualificationV1:
    """Choose measured end-to-end speed only after every safety gate."""

    counts = tuple(candidate.bundle_count for candidate in candidates)
    if counts != (8, 16, 32, 64, 96, 128):
        raise ValueError("CATALOG_LAYOUT_CANDIDATE_SET_INVALID")
    qualified = tuple(
        candidate
        for candidate in candidates
        if candidate.sample_count >= 3
        and candidate.equivalent
        and candidate.memory_safe
        and candidate.disk_safe
        and candidate.runner_timeout_safe
        # Keep 20% of the qualified cache API envelope unused for variance,
        # recovery, and concurrent controller traffic.
        and candidate.projected_cache_uploads_per_minute <= 128
        and candidate.projected_cache_downloads_per_minute <= 960
    )
    if not qualified:
        raise ValueError("CATALOG_LAYOUT_NO_QUALIFIED_CANDIDATE")
    return min(
        qualified,
        key=lambda item: (
            item.projected_end_to_end_p50_seconds,
            item.projected_end_to_end_p95_seconds,
            item.projected_component_download_bytes,
            item.projected_cache_uploads_per_minute
            + item.projected_cache_downloads_per_minute,
            item.bundle_count,
        ),
    )


def select_checkpoint_slot_count(
    *,
    projected_worker_seconds_p99: float,
    upload_verify_seconds_p95: float,
) -> Literal[1, 2, 4, 8]:
    """Use the fewest slots meeting both loss-window and overhead limits."""

    total = float(projected_worker_seconds_p99)
    upload = float(upload_verify_seconds_p95)
    if total <= 0 or upload < 0:
        raise ValueError("CHECKPOINT_PROJECTION_INVALID")
    for slots in (1, 2, 4, 8):
        unpersisted = total / slots
        overhead_fraction = (upload * slots) / total
        if unpersisted <= 600.0 and overhead_fraction <= 0.05:
            return slots
    raise ValueError("CHECKPOINT_OVERHEAD_OR_DURABILITY_UNQUALIFIED")


def _compact_matrix_bytes(*matrices: tuple[CompactMatrixRowV1, ...]) -> int:
    return sum(
        len(
            json.dumps(
                {"include": [row.model_dump(mode="json") for row in matrix]},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-16-le")
        )
        for matrix in matrices
    )


def _document_bytes(value: object) -> bytes:
    if isinstance(value, FrozenModel):
        value = value.model_dump(mode="json")

    def encode_nested(item: object) -> object:
        if isinstance(item, FrozenModel):
            return item.model_dump(mode="json")
        raise TypeError(f"CATALOG_DOCUMENT_VALUE_NOT_JSON:{type(item).__name__}")

    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=encode_nested,
        )
        + "\n"
    ).encode("utf-8")


def _document_sha256(value: object) -> str:
    return hashlib.sha256(_document_bytes(value)).hexdigest()


def _component_schedule_document(
    source_component_ids: tuple[str, ...],
) -> dict[str, object]:
    shard = {
        "shard_index": 0,
        "component_ids": source_component_ids,
        "estimated_seconds": 0.0,
    }
    identity = {
        "schema_version": "1",
        "shards": [shard],
        "tail_ratio": 1.0,
    }
    return {**identity, "plan_sha256": canonical_sha256(identity)}


def _prepared_transport_name(identity_sha256: str, logical_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", logical_id).strip("-.")
    if not safe or len(safe) > 80:
        safe = hashlib.sha256(logical_id.encode("utf-8")).hexdigest()[:24]
    return f"catalog-input-transport-{identity_sha256[:16]}-{safe}"


def _payload_bundle_artifact(
    *,
    family: str,
    execution_plan_sha256: str,
    worker_id: int,
) -> str:
    return (
        f"catalog-{family}-bundle-{execution_plan_sha256[:20]}-"
        f"{worker_id // 64:02d}"
    )


def _source_component_id(requirement: CatalogComponentRequirementV1) -> str:
    return requirement.source_configuration_sha256 or requirement.component_id


def _partition_artifacts_for_datasets(
    *,
    partition_artifacts: dict[str, str],
    runtime_dataset_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if not runtime_dataset_ids:
        core = partition_artifacts.get("runtime-fragment-core")
        return (core,) if core is not None else tuple(sorted(partition_artifacts.values()))
    selected = {
        artifact
        for partition_id, artifact in partition_artifacts.items()
        if partition_id == "runtime-fragment-core"
        or partition_id in runtime_dataset_ids
        or partition_id.removeprefix("runtime-fragment-") in runtime_dataset_ids
    }
    if not selected:
        raise ValueError("CATALOG_COMPONENT_PREPARED_INPUT_UNAVAILABLE")
    return tuple(sorted(selected))


def _matrix_rows(
    *,
    assignments: tuple[
        CatalogComponentAssignmentV1 | CatalogRecipeAssignmentV1,
        ...,
    ],
    bundle_artifact: str,
    member_prefix: str,
) -> tuple[CompactMatrixRowV1, ...]:
    return tuple(
        CompactMatrixRowV1(
            worker_id=assignment.worker_id,
            descriptor_bundle_artifact=bundle_artifact,
            descriptor_member=(
                f"{member_prefix}/worker-{assignment.worker_id:03d}.json"
            ),
            descriptor_sha256=assignment.descriptor_sha256,
        )
        for assignment in assignments
    )


def _percentile(values: tuple[int, ...], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999))
    return float(ordered[index])


def build_global_reuse_execution_plan(
    *,
    contract: RunOptimizationContractV1,
    campaign_id: str,
    authority_id: str,
    science_sha256: str,
    execution_plan_sha256: str,
    component_requirements: tuple[CatalogComponentRequirementV1, ...],
    recipes: tuple[CatalogRecipeRequirementV1, ...],
    store_inventory: RebuildableStoreInventoryV1,
    runtime_identity_sha256: str,
    prepared_input_partition_ids: tuple[str, ...],
    qualifications: tuple[BundleLayoutQualificationV1, ...],
    reduction_projection: MergeResourceProjectionV1,
    hierarchical_reduction_projection: MergeResourceProjectionV1,
    preparation_only: bool = False,
    hot_checkpoint_upload_seconds_p95: float | None = None,
    worker_count_override: int | None = None,
) -> CatalogGlobalReuseExecutionPlanV1:
    """Build a deterministic cold/warm/partial plan before reservation."""
    if not component_requirements or not recipes:
        raise ValueError("CATALOG_GLOBAL_REUSE_WORKLOAD_EMPTY")
    worker_count = (
        contract.execution.workers
        if worker_count_override is None
        else worker_count_override
    )
    if (
        isinstance(worker_count, bool)
        or not isinstance(worker_count, int)
        or not 1 <= worker_count <= 360
    ):
        raise ValueError("CATALOG_WORKER_CEILING_INVALID")
    required_by_id = {
        requirement.component_id: requirement
        for requirement in component_requirements
    }
    if len(required_by_id) != len(component_requirements):
        raise ValueError("CATALOG_COMPONENT_REQUIREMENT_DUPLICATE")
    if tuple(sorted(required_by_id)) != tuple(
        requirement.component_id for requirement in component_requirements
    ):
        component_requirements = tuple(
            sorted(component_requirements, key=lambda item: item.component_id)
        )
    recipe_ids = tuple(recipe.strategy_id for recipe in recipes)
    if len(set(recipe_ids)) != len(recipe_ids):
        raise ValueError("CATALOG_RECIPE_REQUIREMENT_DUPLICATE")
    if any(
        not set(recipe.component_ids).issubset(required_by_id)
        for recipe in recipes
    ):
        raise ValueError("CATALOG_RECIPE_COMPONENT_UNKNOWN")
    if (
        not prepared_input_partition_ids
        or prepared_input_partition_ids
        != tuple(sorted(set(prepared_input_partition_ids)))
    ):
        raise ValueError("CATALOG_PREPARED_PARTITION_SET_INVALID")

    resolved = reconcile_verified_store_candidates(store_inventory)
    reduction_selection = choose_reduction_plan(
        projection=reduction_projection
    )
    if (
        choose_reduction_plan(
            projection=hierarchical_reduction_projection
        ).mode
        != "central"
    ):
        raise ValueError("CATALOG_HIERARCHICAL_REDUCTION_MARGIN_UNPROVEN")
    required_component_ids = tuple(sorted(required_by_id))
    selected_component_candidates = select_component_store_candidates(
        tuple(resolved.values()),
        required_identity_by_id={
            component_id: requirement.identity.component_key_sha256
            for component_id, requirement in required_by_id.items()
        },
    )
    component_candidates: dict[str, RebuildableStoreCandidateV1 | None] = {
        component_id: selected_component_candidates.get(component_id)
        for component_id in required_component_ids
    }
    cached_component_ids = tuple(
        component_id
        for component_id in required_component_ids
        if component_candidates[component_id] is not None
    )
    cached_set = set(cached_component_ids)
    pending_component_ids = tuple(
        component_id
        for component_id in required_component_ids
        if component_id not in cached_set
    )
    layout = (
        select_qualified_bundle_layout(qualifications)
        if qualifications
        else None
    )
    if layout is not None:
        selected_bundle_count = layout.bundle_count
        checkpoint_upload_seconds_p95 = layout.checkpoint_upload_seconds_p95
        projected_cache_uploads = layout.projected_cache_uploads_per_minute
        projected_cache_downloads = layout.projected_cache_downloads_per_minute
        projected_component_download_bytes = (
            layout.projected_component_download_bytes
        )
    elif preparation_only:
        selected_bundle_count = 96 if pending_component_ids else 8
        checkpoint_upload_seconds_p95 = 0.0
        projected_cache_uploads = 0
        projected_cache_downloads = 0
        projected_component_download_bytes = sum(
            required_by_id[item].estimated_bytes for item in pending_component_ids
        )
    elif pending_component_ids:
        raise ValueError("CATALOG_PREPARATION_REQUIRED")
    else:
        if (
            hot_checkpoint_upload_seconds_p95 is None
            or hot_checkpoint_upload_seconds_p95 < 0
        ):
            raise ValueError("CATALOG_HOT_CHECKPOINT_EVIDENCE_REQUIRED")
        selected_bundle_count = 8
        checkpoint_upload_seconds_p95 = hot_checkpoint_upload_seconds_p95
        projected_cache_uploads = 0
        projected_cache_downloads = 0
        projected_component_download_bytes = 0

    runtime_candidate = resolved.get(
        ("runtime", "runtime", str(runtime_identity_sha256))
    )
    if (
        runtime_candidate is not None
        and runtime_candidate.storage_kind != "actions_cache"
    ):
        runtime_candidate = None
    prepared_identity = canonical_sha256(
        {
            "science_sha256": science_sha256,
            "partitions": prepared_input_partition_ids,
            "schema_version": "prepared-input-store-v1",
        }
    )
    prepared_candidates = {
        partition_id: (
            candidate
            if (
                candidate := resolved.get(
                    ("prepared_input", partition_id, prepared_identity)
                )
            )
            is not None
            and candidate.storage_kind == "actions_cache"
            else None
        )
        for partition_id in prepared_input_partition_ids
    }
    cached_partitions = tuple(
        partition_id
        for partition_id in prepared_input_partition_ids
        if prepared_candidates[partition_id] is not None
    )
    cached_partition_set = set(cached_partitions)
    pending_partitions = tuple(
        partition_id
        for partition_id in prepared_input_partition_ids
        if partition_id not in cached_partition_set
    )
    partition_artifacts = {
        partition_id: _prepared_transport_name(prepared_identity, partition_id)
        for partition_id in prepared_input_partition_ids
    }
    runtime_transport = (
        f"catalog-runtime-transport-{runtime_identity_sha256[:24]}"
    )
    runtime = StorePreparationPlanV1(
        identity_sha256=runtime_identity_sha256,
        preparation_required=runtime_candidate is None,
        cached_logical_ids=("runtime",) if runtime_candidate is not None else (),
        pending_logical_ids=() if runtime_candidate is not None else ("runtime",),
        worker_objects=(runtime_transport,),
        cache_lookup_keys=(
            (("runtime", runtime_candidate.cache_key),)
            if runtime_candidate is not None
            and runtime_candidate.storage_kind == "actions_cache"
            and runtime_candidate.cache_key is not None
            else ()
        ),
    )
    prepared_inputs = StorePreparationPlanV1(
        identity_sha256=prepared_identity,
        preparation_required=bool(pending_partitions),
        cached_logical_ids=cached_partitions,
        pending_logical_ids=pending_partitions,
        worker_objects=tuple(
            partition_artifacts[item] for item in prepared_input_partition_ids
        ),
        cache_lookup_keys=tuple(
            (partition_id, candidate.cache_key)
            for partition_id in cached_partitions
            if (candidate := prepared_candidates[partition_id]) is not None
            and candidate.storage_kind == "actions_cache"
            and candidate.cache_key is not None
        ),
    )

    pending_bundle_count = min(
        len(pending_component_ids),
        selected_bundle_count,
        contract.execution.component_workers,
    )
    component_bins: list[list[str]] = [
        [] for _ in range(pending_bundle_count)
    ]
    component_loads = [0] * pending_bundle_count
    for component_id in sorted(
        pending_component_ids,
        key=lambda item: (-required_by_id[item].estimated_bytes, item),
    ):
        worker_id = min(
            range(pending_bundle_count),
            key=lambda index: (component_loads[index], index),
        )
        component_bins[worker_id].append(component_id)
        component_loads[worker_id] += required_by_id[component_id].estimated_bytes

    def component_assignment(
        *,
        worker_id: int,
        component_ids: tuple[str, ...],
        preparation_required: bool,
        candidate: RebuildableStoreCandidateV1 | None,
        family: str,
    ) -> CatalogComponentAssignmentV1:
        requirements = tuple(required_by_id[item] for item in component_ids)
        component_sources = tuple(
            {
                "component_id": item.component_id,
                "source_configuration_sha256": _source_component_id(item),
            }
            for item in sorted(requirements, key=lambda value: value.component_id)
        )
        source_ids = tuple(
            sorted(item["source_configuration_sha256"] for item in component_sources)
        )
        runtime_dataset_ids = tuple(
            sorted(
                {
                    dataset_id
                    for requirement in requirements
                    for dataset_id in requirement.runtime_dataset_ids
                }
            )
        )
        data_artifacts = _partition_artifacts_for_datasets(
            partition_artifacts=partition_artifacts,
            runtime_dataset_ids=runtime_dataset_ids,
        )
        bundle_identity = (
            candidate.identity_sha256
            if candidate is not None
            else canonical_sha256(
                {
                    "schema_version": "component-bundle-v1",
                    "science_sha256": science_sha256,
                    "component_ids": component_ids,
                }
            )
        )
        assignment_artifact = _payload_bundle_artifact(
            family=f"{family}-component-assignments",
            execution_plan_sha256=execution_plan_sha256,
            worker_id=worker_id,
        )
        assignment_member = f"component/worker-{worker_id:03d}.json"
        assignment_document = {
            "schema_version": "1",
            "worker_id": worker_id,
            "component_ids": component_ids,
            "component_sources": component_sources,
            "component_schedule": _component_schedule_document(source_ids),
            "validation_opened": False,
            "locked_opened": False,
        }
        assignment_sha256 = _document_sha256(assignment_document)
        data_manifest_sha256 = canonical_sha256(
            {
                "schema_version": "1",
                "artifacts": data_artifacts,
                "prepared_input_identity_sha256": prepared_identity,
            }
        )
        transport = (
            f"catalog-component-transport-{execution_plan_sha256[:16]}-"
            f"{family}-{worker_id:03d}"
        )
        cache_lookup_key = (
            candidate.cache_key
            if candidate is not None
            and candidate.storage_kind == "actions_cache"
            and candidate.cache_key is not None
            else ""
        )
        cache_prefix = f"aurora-catalog-v1-{bundle_identity}-"
        expected_manifest = (
            candidate.content_manifest_sha256 if candidate is not None else None
        )
        descriptor_document = {
            "schema_version": "1",
            "worker_id": worker_id,
            "campaign_id": campaign_id,
            "execution_plan_sha256": execution_plan_sha256,
            "runtime_transport_artifact": runtime_transport,
            "runtime_mode": contract.runtime_preparation.runtime_mode,
            "runtime_identity_sha256": runtime_identity_sha256,
            "numeric_profile_sha256": contract.science.numeric_profile,
            "assignment_artifact": assignment_artifact,
            "assignment_member": assignment_member,
            "assignment_sha256": assignment_sha256,
            "data_partition_artifacts": data_artifacts,
            "prepared_input_identity_sha256": prepared_identity,
            "data_partition_manifest_sha256": data_manifest_sha256,
            "component_ids": component_ids,
            "expected_component_count": len(component_ids),
            "bundle_identity_sha256": bundle_identity,
            "preparation_required": preparation_required,
            "source_storage_kind": (
                candidate.storage_kind if candidate is not None else "missing"
            ),
            "source_artifact_run_id": (
                candidate.artifact_run_id if candidate is not None else None
            ),
            "source_artifact_id": (
                candidate.artifact_id if candidate is not None else None
            ),
            "component_cache_restore_key": cache_lookup_key,
            "component_cache_persistence_key_prefix": cache_prefix,
            "component_transport_artifact": transport,
            "component_store_manifest_sha256": expected_manifest or "",
            "validation_opened": False,
            "locked_opened": False,
        }
        return CatalogComponentAssignmentV1(
            worker_id=worker_id,
            component_ids=component_ids,
            estimated_bytes=sum(item.estimated_bytes for item in requirements),
            preparation_required=preparation_required,
            bundle_identity_sha256=bundle_identity,
            source_storage_kind=(
                candidate.storage_kind if candidate is not None else "missing"
            ),
            cache_lookup_key=cache_lookup_key,
            cache_persistence_key_prefix=cache_prefix,
            source_artifact_run_id=(
                candidate.artifact_run_id if candidate is not None else None
            ),
            source_artifact_id=(
                candidate.artifact_id if candidate is not None else None
            ),
            expected_store_manifest_sha256=expected_manifest,
            runtime_dataset_ids=runtime_dataset_ids,
            data_partition_artifacts=data_artifacts,
            data_partition_manifest_sha256=data_manifest_sha256,
            assignment_artifact=assignment_artifact,
            assignment_member=assignment_member,
            assignment_sha256=assignment_sha256,
            component_transport_artifact=transport,
            descriptor_sha256=_document_sha256(descriptor_document),
        )

    component_assignments = tuple(
        component_assignment(
            worker_id=worker_id,
            component_ids=tuple(sorted(component_bins[worker_id])),
            preparation_required=True,
            candidate=None,
            family="pending",
        )
        for worker_id in range(pending_bundle_count)
    )
    cached_groups: dict[
        tuple[object, ...],
        tuple[RebuildableStoreCandidateV1, list[str]],
    ] = {}
    for component_id in cached_component_ids:
        candidate = component_candidates[component_id]
        if candidate is None:
            raise ValueError("REBUILDABLE_COMPONENT_LOCATION_MISSING")
        location = (
            candidate.identity_sha256,
            candidate.content_manifest_sha256,
            candidate.content_sha256,
            candidate.storage_kind,
            candidate.cache_key,
            candidate.artifact_run_id,
            candidate.artifact_id,
        )
        if location not in cached_groups:
            cached_groups[location] = (candidate, [])
        cached_groups[location][1].append(component_id)
    cached_component_assignments = tuple(
        component_assignment(
            worker_id=worker_id,
            component_ids=tuple(sorted(component_ids)),
            preparation_required=False,
            candidate=candidate,
            family="cached",
        )
        for worker_id, (_, (candidate, component_ids)) in enumerate(
            sorted(cached_groups.items(), key=lambda item: item[0])
        )
    )
    component_cache_bundle_count = (
        len(component_assignments) + len(cached_component_assignments)
    )
    if (
        component_cache_bundle_count
        > contract.rebuildable_store_execution.maximum_component_cache_bundles_per_campaign
    ):
        raise ValueError("CATALOG_COMPONENT_CACHE_BUNDLE_BUDGET_EXCEEDED")
    if layout is None and not pending_component_ids:
        selected_bundle_count = next(
            (
                count
                for count in (8, 16, 32, 64, 96, 128)
                if count >= component_cache_bundle_count
            ),
            0,
        )
        if selected_bundle_count == 0:
            raise ValueError("CATALOG_COMPONENT_CACHE_BUNDLE_BUDGET_EXCEEDED")
    component_assignment_by_id = {
        component_id: assignment
        for assignment in (
            *component_assignments,
            *cached_component_assignments,
        )
        for component_id in assignment.component_ids
    }
    if set(component_assignment_by_id) != set(required_component_ids):
        raise ValueError("CATALOG_COMPONENT_ASSIGNMENT_COVERAGE_INVALID")

    recipe_worker_count = min(worker_count, len(recipes))
    recipe_bins: list[list[CatalogRecipeRequirementV1]] = [
        [] for _ in range(recipe_worker_count)
    ]
    recipe_components: list[set[str]] = [set() for _ in range(recipe_worker_count)]
    recipe_loads = [0.0] * recipe_worker_count
    for recipe in sorted(
        recipes,
        key=lambda item: (-item.estimated_seconds_p99, item.strategy_id),
    ):
        minimum_load = min(recipe_loads)
        candidates = [
            index
            for index, load in enumerate(recipe_loads)
            if abs(load - minimum_load) <= 1e-12
        ]
        worker_id = min(
            candidates,
            key=lambda index: (
                -len(recipe_components[index].intersection(recipe.component_ids)),
                index,
            ),
        )
        recipe_bins[worker_id].append(recipe)
        recipe_components[worker_id].update(recipe.component_ids)
        recipe_loads[worker_id] += recipe.estimated_seconds_p99
    consumed_component_ids = set().union(*recipe_components)
    unconsumed_component_ids = set(required_component_ids) - consumed_component_ids
    if unconsumed_component_ids:
        recipe_components[0].update(unconsumed_component_ids)
    if layout is None and not pending_component_ids:
        projected_component_download_bytes = sum(
            required_by_id[component_id].estimated_bytes
            for component_ids in recipe_components
            for component_id in component_ids
        )

    recipe_data_artifacts = _partition_artifacts_for_datasets(
        partition_artifacts=partition_artifacts,
        runtime_dataset_ids=(),
    )
    recipe_data_manifest = canonical_sha256(
        {
            "schema_version": "1",
            "artifacts": recipe_data_artifacts,
            "prepared_input_identity_sha256": prepared_identity,
        }
    )
    recipe_assignments: list[CatalogRecipeAssignmentV1] = []
    for worker_id in range(recipe_worker_count):
        strategy_ids = tuple(
            sorted(recipe.strategy_id for recipe in recipe_bins[worker_id])
        )
        component_assignments_for_worker = tuple(
            sorted(
                {
                    component_assignment_by_id[item]
                    for item in recipe_components[worker_id]
                },
                key=lambda item: item.component_transport_artifact,
            )
        )
        component_bundle_ids = tuple(
            item.bundle_identity_sha256
            for item in component_assignments_for_worker
        )
        component_transports = tuple(
            item.component_transport_artifact
            for item in component_assignments_for_worker
        )
        slots = select_checkpoint_slot_count(
            projected_worker_seconds_p99=recipe_loads[worker_id],
            upload_verify_seconds_p95=checkpoint_upload_seconds_p95,
        )
        assignment_artifact = _payload_bundle_artifact(
            family="recipe-assignments",
            execution_plan_sha256=execution_plan_sha256,
            worker_id=worker_id,
        )
        assignment_member = f"recipe/worker-{worker_id:03d}.json"
        strategy_identity = {
            "schema_version": "1",
            "worker_id": worker_id,
            "strategy_ids": strategy_ids,
        }
        expected_strategy_manifest = canonical_sha256(strategy_identity)
        assignment_document = {
            **strategy_identity,
            "expected_strategy_manifest_sha256": expected_strategy_manifest,
        }
        assignment_sha256 = _document_sha256(assignment_document)
        reduction_group_id = worker_id // 24
        checkpoint_artifacts = tuple(
            f"catalog-checkpoint-{execution_plan_sha256[:16]}-"
            f"g{reduction_group_id:02d}-w{worker_id:03d}-s{slot:02d}"
            for slot in range(1, 9)
        )
        checkpoint_manifest = canonical_sha256(
            {
                "schema_version": "1",
                "artifacts": checkpoint_artifacts,
                "slot_count": slots,
            }
        )
        component_manifest = canonical_sha256(
            {
                "schema_version": "1",
                "bundle_ids": component_bundle_ids,
                "artifacts": component_transports,
            }
        )
        terminal_artifact = (
            f"catalog-terminal-attempt-{execution_plan_sha256[:16]}-"
            f"{worker_id:03d}"
        )
        descriptor_document = {
            "worker_id": worker_id,
            "attempt_id": f"{authority_id}:worker:{worker_id:03d}:attempt:1",
            "assignment_artifact": assignment_artifact,
            "assignment_member": assignment_member,
            "assignment_sha256": assignment_sha256,
            "data_partition_artifacts": recipe_data_artifacts,
            "data_partition_manifest_sha256": recipe_data_manifest,
            "component_bundle_artifacts": component_transports,
            "component_bundle_manifest_sha256": component_manifest,
            "prior_checkpoint_chain_artifact": "",
            "checkpoint_slot_artifacts": checkpoint_artifacts,
            "checkpoint_slot_manifest_sha256": checkpoint_manifest,
            "checkpoint_slot_count": slots,
            "expected_strategy_count": len(strategy_ids),
            "expected_strategy_manifest_sha256": expected_strategy_manifest,
        }
        recipe_assignments.append(
            CatalogRecipeAssignmentV1(
                worker_id=worker_id,
                strategy_ids=strategy_ids,
                component_bundle_ids=component_bundle_ids,
                projected_seconds_p99=recipe_loads[worker_id],
                checkpoint_slot_count=slots,
                assignment_artifact=assignment_artifact,
                assignment_member=assignment_member,
                assignment_sha256=assignment_sha256,
                data_partition_artifacts=recipe_data_artifacts,
                data_partition_manifest_sha256=recipe_data_manifest,
                component_transport_artifacts=component_transports,
                component_bundle_manifest_sha256=component_manifest,
                checkpoint_slot_artifacts=checkpoint_artifacts,
                checkpoint_slot_manifest_sha256=checkpoint_manifest,
                expected_strategy_manifest_sha256=expected_strategy_manifest,
                terminal_attempt_artifact=terminal_artifact,
                descriptor_sha256=_document_sha256(descriptor_document),
            )
        )
    checked_recipe_assignments = tuple(recipe_assignments)

    def rows_for(
        assignments: tuple[
            CatalogComponentAssignmentV1 | CatalogRecipeAssignmentV1,
            ...,
        ],
        *,
        family: str,
        member_prefix: str,
    ) -> tuple[CompactMatrixRowV1, ...]:
        return tuple(
            CompactMatrixRowV1(
                worker_id=assignment.worker_id,
                descriptor_bundle_artifact=_payload_bundle_artifact(
                    family=family,
                    execution_plan_sha256=execution_plan_sha256,
                    worker_id=assignment.worker_id,
                ),
                descriptor_member=(
                    f"{member_prefix}/worker-{assignment.worker_id:03d}.json"
                ),
                descriptor_sha256=assignment.descriptor_sha256,
            )
            for assignment in assignments
        )

    component_rows = rows_for(
        component_assignments,
        family="pending-component-descriptors",
        member_prefix="component",
    )
    cached_component_rows = rows_for(
        cached_component_assignments,
        family="cached-component-descriptors",
        member_prefix="component",
    )
    recipe_rows = rows_for(
        checked_recipe_assignments,
        family="recipe-descriptors",
        member_prefix="recipe",
    )
    if len(component_rows) > 240 or len(cached_component_rows) > 240:
        raise ValueError("CATALOG_COMPONENT_MATRIX_LIMIT_EXCEEDED")
    component_matrix_a = component_rows[:120]
    component_matrix_b = component_rows[120:240]
    cached_component_matrix_a = cached_component_rows[:120]
    cached_component_matrix_b = cached_component_rows[120:240]
    recipe_matrix_a = recipe_rows[:120]
    recipe_matrix_b = recipe_rows[120:240]
    recipe_matrix_c = recipe_rows[240:360]

    new_cache_entries = (
        int(runtime.preparation_required)
        + len(pending_partitions)
        + len(component_assignments)
    )
    if (
        new_cache_entries
        > contract.rebuildable_store_execution.maximum_new_cache_entries_per_campaign
    ):
        raise ValueError("CATALOG_CACHE_ENTRY_BUDGET_EXCEEDED")
    cache_uploads = max(
        new_cache_entries,
        projected_cache_uploads,
    )
    observed_cache_downloads = (
        len(cached_component_assignments)
        + len(prepared_inputs.cache_lookup_keys)
        + len(runtime.cache_lookup_keys)
    )
    cache_downloads = max(
        observed_cache_downloads,
        projected_cache_downloads,
    )
    if (
        cache_uploads
        > contract.rebuildable_store_execution.maximum_cache_upload_requests_per_minute
        or cache_downloads
        > contract.rebuildable_store_execution.maximum_cache_download_requests_per_minute
    ):
        raise ValueError("CATALOG_CACHE_REQUEST_RATE_EXCEEDED")

    bundle_counts = tuple(
        len(assignment.component_bundle_ids)
        for assignment in checked_recipe_assignments
    )
    unique_bytes = sum(item.estimated_bytes for item in component_requirements)
    projected_download_bytes = projected_component_download_bytes
    amplification = projected_download_bytes / unique_bytes
    matrix_bytes = _compact_matrix_bytes(
        component_matrix_a,
        component_matrix_b,
        cached_component_matrix_a,
        cached_component_matrix_b,
        recipe_matrix_a,
        recipe_matrix_b,
        recipe_matrix_c,
    )
    identity = {
        "schema_version": "1",
        "campaign_id": campaign_id,
        "authority_id": authority_id,
        "science_sha256": science_sha256,
        "execution_plan_sha256": execution_plan_sha256,
        "required_component_ids": required_component_ids,
        "cached_component_ids": cached_component_ids,
        "pending_component_ids": pending_component_ids,
        "component_requirements": component_requirements,
        "recipe_requirements": tuple(
            sorted(recipes, key=lambda item: item.strategy_id)
        ),
        "component_assignments": component_assignments,
        "cached_component_assignments": cached_component_assignments,
        "recipe_assignments": checked_recipe_assignments,
        "component_matrix_a": component_matrix_a,
        "component_matrix_b": component_matrix_b,
        "cached_component_matrix_a": cached_component_matrix_a,
        "cached_component_matrix_b": cached_component_matrix_b,
        "recipe_matrix_a": recipe_matrix_a,
        "recipe_matrix_b": recipe_matrix_b,
        "recipe_matrix_c": recipe_matrix_c,
        "runtime": runtime,
        "prepared_inputs": prepared_inputs,
        "selected_component_bundle_count": selected_bundle_count,
        "component_cache_bundle_count": component_cache_bundle_count,
        "new_cache_entry_count": new_cache_entries,
        "cache_uploads_per_minute": cache_uploads,
        "cache_downloads_per_minute": cache_downloads,
        "unique_required_component_bytes": unique_bytes,
        "projected_worker_component_download_bytes": projected_download_bytes,
        "component_bundles_per_worker_p50": _percentile(bundle_counts, 0.50),
        "component_bundles_per_worker_p95": _percentile(bundle_counts, 0.95),
        "component_download_amplification_p50": amplification,
        "component_download_amplification_p95": amplification,
        "matrix_output_utf16_bytes": matrix_bytes,
        "reduction_projection": reduction_projection,
        "hierarchical_reduction_projection": (
            hierarchical_reduction_projection
        ),
        "reduction_selection": reduction_selection,
        "recipe_jobs_depend_on_component_store": True,
        "validation_opened": False,
        "locked_opened": False,
    }
    return CatalogGlobalReuseExecutionPlanV1(
        **identity,
        plan_sha256=canonical_sha256(identity),
    )


def _plan_document(
    plan: CatalogGlobalReuseExecutionPlanV1,
    document_type: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    identity = {
        "schema_version": "1",
        "document_type": document_type,
        "campaign_id": plan.campaign_id,
        "authority_id": plan.authority_id,
        "science_sha256": plan.science_sha256,
        "execution_plan_sha256": plan.execution_plan_sha256,
        **dict(payload),
    }
    return {**identity, "content_sha256": canonical_sha256(identity)}


def _component_assignment_document_for_plan(
    plan: CatalogGlobalReuseExecutionPlanV1,
    assignment: CatalogComponentAssignmentV1,
) -> dict[str, object]:
    requirements = {
        item.component_id: item for item in plan.component_requirements
    }
    component_sources = tuple(
        {
            "component_id": component_id,
            "source_configuration_sha256": _source_component_id(
                requirements[component_id]
            ),
        }
        for component_id in assignment.component_ids
    )
    source_ids = tuple(
        sorted(item["source_configuration_sha256"] for item in component_sources)
    )
    return {
        "schema_version": "1",
        "worker_id": assignment.worker_id,
        "component_ids": assignment.component_ids,
        "component_sources": component_sources,
        "component_schedule": _component_schedule_document(source_ids),
        "validation_opened": False,
        "locked_opened": False,
    }


def _component_descriptor_document_for_plan(
    *,
    contract: RunOptimizationContractV1,
    plan: CatalogGlobalReuseExecutionPlanV1,
    assignment: CatalogComponentAssignmentV1,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "worker_id": assignment.worker_id,
        "campaign_id": plan.campaign_id,
        "execution_plan_sha256": plan.execution_plan_sha256,
        "runtime_transport_artifact": plan.runtime.worker_objects[0],
        "runtime_mode": contract.runtime_preparation.runtime_mode,
        "runtime_identity_sha256": plan.runtime.identity_sha256,
        "numeric_profile_sha256": contract.science.numeric_profile,
        "assignment_artifact": assignment.assignment_artifact,
        "assignment_member": assignment.assignment_member,
        "assignment_sha256": assignment.assignment_sha256,
        "data_partition_artifacts": assignment.data_partition_artifacts,
        "prepared_input_identity_sha256": plan.prepared_inputs.identity_sha256,
        "data_partition_manifest_sha256": (
            assignment.data_partition_manifest_sha256
        ),
        "component_ids": assignment.component_ids,
        "expected_component_count": len(assignment.component_ids),
        "bundle_identity_sha256": assignment.bundle_identity_sha256,
        "preparation_required": assignment.preparation_required,
        "source_storage_kind": assignment.source_storage_kind,
        "source_artifact_run_id": assignment.source_artifact_run_id,
        "source_artifact_id": assignment.source_artifact_id,
        "component_cache_restore_key": assignment.cache_lookup_key,
        "component_cache_persistence_key_prefix": (
            assignment.cache_persistence_key_prefix
        ),
        "component_transport_artifact": (
            assignment.component_transport_artifact
        ),
        "component_store_manifest_sha256": (
            assignment.expected_store_manifest_sha256 or ""
        ),
        "validation_opened": False,
        "locked_opened": False,
    }


def _recipe_assignment_document_for_plan(
    assignment: CatalogRecipeAssignmentV1,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "worker_id": assignment.worker_id,
        "strategy_ids": assignment.strategy_ids,
        "expected_strategy_manifest_sha256": (
            assignment.expected_strategy_manifest_sha256
        ),
    }


def _recipe_descriptor_document_for_plan(
    plan: CatalogGlobalReuseExecutionPlanV1,
    assignment: CatalogRecipeAssignmentV1,
) -> dict[str, object]:
    return {
        "worker_id": assignment.worker_id,
        "attempt_id": (
            f"{plan.authority_id}:worker:{assignment.worker_id:03d}:attempt:1"
        ),
        "assignment_artifact": assignment.assignment_artifact,
        "assignment_member": assignment.assignment_member,
        "assignment_sha256": assignment.assignment_sha256,
        "data_partition_artifacts": assignment.data_partition_artifacts,
        "data_partition_manifest_sha256": (
            assignment.data_partition_manifest_sha256
        ),
        "component_bundle_artifacts": (
            assignment.component_transport_artifacts
        ),
        "component_bundle_manifest_sha256": (
            assignment.component_bundle_manifest_sha256
        ),
        "prior_checkpoint_chain_artifact": "",
        "checkpoint_slot_artifacts": assignment.checkpoint_slot_artifacts,
        "checkpoint_slot_manifest_sha256": (
            assignment.checkpoint_slot_manifest_sha256
        ),
        "checkpoint_slot_count": assignment.checkpoint_slot_count,
        "expected_strategy_count": len(assignment.strategy_ids),
        "expected_strategy_manifest_sha256": (
            assignment.expected_strategy_manifest_sha256
        ),
    }


def _write_payload_member(
    root: Path,
    *,
    artifact: str,
    member: str,
    raw: bytes,
) -> None:
    relative = Path(member)
    if (
        not artifact
        or Path(artifact).name != artifact
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise ValueError("CATALOG_PAYLOAD_MEMBER_PATH_INVALID")
    target = root / "payload_artifacts" / artifact / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError("CATALOG_PAYLOAD_MEMBER_CONFLICT")
        return
    target.write_bytes(raw)


def _write_deterministic_zip(
    path: Path,
    members: Mapping[str, bytes],
) -> None:
    with zipfile.ZipFile(path, mode="x", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(members):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("CATALOG_ZIP_MEMBER_PATH_INVALID")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, members[name])


def write_sealed_global_reuse_execution_plan(
    *,
    output_dir: Path,
    contract: RunOptimizationContractV1,
    plan: CatalogGlobalReuseExecutionPlanV1,
    request_sha256: str,
    execution_protocol_sha256: str,
    protected_commit_sha: str,
    decision_sha256: str,
    admission_token_sha256: str,
    controller_binding: Mapping[str, object],
    run_plan: Mapping[str, object],
    resume_work_manifest: Mapping[str, object],
    recipe_dag_bytes: bytes,
    recipe_dag_manifest: Mapping[str, object],
    source_artifacts: Mapping[str, object],
) -> dict[str, object]:
    """Write every immutable plan and exact worker payload byte once."""

    sha_values = {
        "request_sha256": request_sha256,
        "execution_protocol_sha256": execution_protocol_sha256,
        "decision_sha256": decision_sha256,
        "admission_token_sha256": admission_token_sha256,
    }
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in sha_values.values()):
        raise ValueError("CATALOG_SEALED_PLAN_BINDING_HASH_INVALID")
    if not re.fullmatch(r"[0-9a-f]{40}", protected_commit_sha):
        raise ValueError("CATALOG_SEALED_PLAN_SOURCE_SHA_INVALID")
    plan_identity = plan.model_dump(mode="python", exclude={"plan_sha256"})
    if canonical_sha256(plan_identity) != plan.plan_sha256:
        raise ValueError("CATALOG_GLOBAL_REUSE_PLAN_HASH_INVALID")
    if contract.science.validation_opened or contract.science.locked_opened:
        raise ValueError("CATALOG_SEALED_PLAN_BOUNDARY_OPEN")
    source_identity = {
        key: value for key, value in source_artifacts.items() if key != "content_sha256"
    }
    source_payload = source_artifacts.get("payload")
    source_rows = (
        source_payload.get("artifacts")
        if isinstance(source_payload, Mapping)
        else None
    )
    if (
        set(source_artifacts)
        != {"schema_version", "document_type", "payload", "content_sha256"}
        or source_artifacts.get("schema_version") != "1"
        or source_artifacts.get("document_type") != "catalog_source_artifacts_v1"
        or source_artifacts.get("content_sha256") != canonical_sha256(source_identity)
        or not isinstance(source_rows, list)
        or not source_rows
        or len(source_rows) != len(
            {
                str(row.get("contract_name"))
                for row in source_rows
                if isinstance(row, Mapping)
            }
        )
        or any(
            not isinstance(row, Mapping)
            or row.get("validation_opened") is not False
            or row.get("locked_opened") is not False
            for row in source_rows
        )
    ):
        raise ValueError("CATALOG_SEALED_SOURCE_ARTIFACTS_INVALID")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)

    def write_json(name: str, value: object) -> bytes:
        if Path(name).name != name:
            raise ValueError("CATALOG_SEALED_PLAN_FILENAME_INVALID")
        raw = _document_bytes(value)
        (output / name).write_bytes(raw)
        return raw

    resolved_contract_raw = write_json("resolved_contract.json", contract)
    write_json("source_artifacts.json", source_artifacts)
    controller_document = _plan_document(
        plan,
        "controller_binding",
        {"binding": dict(controller_binding)},
    )
    write_json("controller_binding.json", controller_document)
    rebuildable_store_document = _plan_document(
        plan,
        "rebuildable_store_plan",
        {
            "runtime": plan.runtime,
            "prepared_inputs": plan.prepared_inputs,
            "selected_component_bundle_count": (
                plan.selected_component_bundle_count
            ),
            "component_cache_bundle_count": plan.component_cache_bundle_count,
            "new_cache_entry_count": plan.new_cache_entry_count,
            "cache_uploads_per_minute": plan.cache_uploads_per_minute,
            "cache_downloads_per_minute": plan.cache_downloads_per_minute,
        },
    )
    write_json("rebuildable_store_plan.json", rebuildable_store_document)
    logical_recipe_document = _plan_document(
        plan,
        "logical_recipe_manifest",
        {
            "strategy_count": len(plan.recipe_requirements),
            "recipes": plan.recipe_requirements,
        },
    )
    write_json("logical_recipe_manifest.json", logical_recipe_document)
    component_requirement_document = _plan_document(
        plan,
        "component_requirement_manifest",
        {
            "component_count": len(plan.component_requirements),
            "components": plan.component_requirements,
        },
    )
    write_json(
        "component_requirement_manifest.json",
        component_requirement_document,
    )
    component_assignments = (
        *plan.component_assignments,
        *plan.cached_component_assignments,
    )
    component_store_input_document = _plan_document(
        plan,
        "component_store_input_manifest",
        {
            "required_component_ids": plan.required_component_ids,
            "bundles": tuple(
                {
                    "bundle_identity_sha256": item.bundle_identity_sha256,
                    "component_ids": item.component_ids,
                    "component_transport_artifact": (
                        item.component_transport_artifact
                    ),
                    "expected_store_manifest_sha256": (
                        item.expected_store_manifest_sha256
                    ),
                }
                for item in component_assignments
            ),
            "validation_opened": False,
            "locked_opened": False,
        },
    )
    write_json(
        "component_store_input_manifest.json",
        component_store_input_document,
    )
    write_json(
        "pending_component_manifest.json",
        _plan_document(
            plan,
            "pending_component_manifest",
            {
                "component_ids": plan.pending_component_ids,
                "assignments": plan.component_assignments,
            },
        ),
    )
    write_json(
        "cached_component_manifest.json",
        _plan_document(
            plan,
            "cached_component_manifest",
            {
                "component_ids": plan.cached_component_ids,
                "assignments": plan.cached_component_assignments,
            },
        ),
    )

    matrices = {
        "component_matrix_a": plan.component_matrix_a,
        "component_matrix_b": plan.component_matrix_b,
        "cached_component_matrix_a": plan.cached_component_matrix_a,
        "cached_component_matrix_b": plan.cached_component_matrix_b,
        "recipe_matrix_a": plan.recipe_matrix_a,
        "recipe_matrix_b": plan.recipe_matrix_b,
        "recipe_matrix_c": plan.recipe_matrix_c,
    }
    for name, rows in matrices.items():
        write_json(
            f"{name}.json",
            {"include": [row.model_dump(mode="json") for row in rows]},
        )

    run_plan_raw = _document_bytes(dict(run_plan))
    resume_manifest_raw = _document_bytes(dict(resume_work_manifest))
    recipe_dag_manifest_raw = _document_bytes(dict(recipe_dag_manifest))
    recipe_zip_members: dict[str, bytes] = {}
    for assignment in component_assignments:
        assignment_document = _component_assignment_document_for_plan(
            plan,
            assignment,
        )
        assignment_raw = _document_bytes(assignment_document)
        if hashlib.sha256(assignment_raw).hexdigest() != assignment.assignment_sha256:
            raise ValueError("CATALOG_COMPONENT_ASSIGNMENT_HASH_INVALID")
        descriptor_document = _component_descriptor_document_for_plan(
            contract=contract,
            plan=plan,
            assignment=assignment,
        )
        descriptor_raw = _document_bytes(descriptor_document)
        if hashlib.sha256(descriptor_raw).hexdigest() != assignment.descriptor_sha256:
            raise ValueError("CATALOG_COMPONENT_DESCRIPTOR_HASH_INVALID")
        family = (
            "pending" if assignment.preparation_required else "cached"
        )
        descriptor_artifact = _payload_bundle_artifact(
            family=f"{family}-component-descriptors",
            execution_plan_sha256=plan.execution_plan_sha256,
            worker_id=assignment.worker_id,
        )
        _write_payload_member(
            output,
            artifact=descriptor_artifact,
            member=f"component/worker-{assignment.worker_id:03d}.json",
            raw=descriptor_raw,
        )
        _write_payload_member(
            output,
            artifact=assignment.assignment_artifact,
            member=assignment.assignment_member,
            raw=assignment_raw,
        )
        for member, raw in (
            ("resolved_contract.json", resolved_contract_raw),
            ("run_plan.json", run_plan_raw),
        ):
            _write_payload_member(
                output,
                artifact=assignment.assignment_artifact,
                member=member,
                raw=raw,
            )

    for assignment in plan.recipe_assignments:
        assignment_document = _recipe_assignment_document_for_plan(assignment)
        assignment_raw = _document_bytes(assignment_document)
        if hashlib.sha256(assignment_raw).hexdigest() != assignment.assignment_sha256:
            raise ValueError("CATALOG_RECIPE_ASSIGNMENT_HASH_INVALID")
        descriptor_document = _recipe_descriptor_document_for_plan(
            plan,
            assignment,
        )
        descriptor_raw = _document_bytes(descriptor_document)
        if hashlib.sha256(descriptor_raw).hexdigest() != assignment.descriptor_sha256:
            raise ValueError("CATALOG_RECIPE_DESCRIPTOR_HASH_INVALID")
        descriptor_artifact = _payload_bundle_artifact(
            family="recipe-descriptors",
            execution_plan_sha256=plan.execution_plan_sha256,
            worker_id=assignment.worker_id,
        )
        _write_payload_member(
            output,
            artifact=descriptor_artifact,
            member=f"recipe/worker-{assignment.worker_id:03d}.json",
            raw=descriptor_raw,
        )
        _write_payload_member(
            output,
            artifact=assignment.assignment_artifact,
            member=assignment.assignment_member,
            raw=assignment_raw,
        )
        recipe_zip_members[assignment.assignment_member] = assignment_raw
        for member, raw in (
            ("resolved_contract.json", resolved_contract_raw),
            ("run_plan.json", run_plan_raw),
            ("resume_work_manifest.json", resume_manifest_raw),
            ("recipe_dag.parquet", bytes(recipe_dag_bytes)),
            ("recipe_dag_manifest.json", recipe_dag_manifest_raw),
        ):
            _write_payload_member(
                output,
                artifact=assignment.assignment_artifact,
                member=member,
                raw=raw,
            )

    _write_deterministic_zip(
        output / "recipe_assignment_bundle.zip",
        recipe_zip_members,
    )
    worker_artifacts = {
        str(item.worker_id): {
            "checkpoint_slot_artifacts": item.checkpoint_slot_artifacts,
            "terminal_attempt_artifact": item.terminal_attempt_artifact,
        }
        for item in plan.recipe_assignments
    }
    checkpoint_policy = _plan_document(
        plan,
        "checkpoint_policy",
        {
            "maximum_unpersisted_seconds_p99": (
                contract.recovery_execution.maximum_unpersisted_seconds_p99
            ),
            "maximum_checkpoint_overhead_fraction_p95": (
                contract.recovery_execution.maximum_checkpoint_overhead_fraction_p95
            ),
            "workers": tuple(
                {
                    "worker_id": item.worker_id,
                    "checkpoint_slot_count": item.checkpoint_slot_count,
                    "checkpoint_slot_artifacts": item.checkpoint_slot_artifacts,
                    "checkpoint_slot_manifest_sha256": (
                        item.checkpoint_slot_manifest_sha256
                    ),
                }
                for item in plan.recipe_assignments
            ),
        },
    )
    write_json("checkpoint_policy.json", checkpoint_policy)
    selected_reduction_mode = plan.reduction_selection.mode
    group_size = (
        max(1, len(plan.recipe_assignments))
        if selected_reduction_mode == "central"
        else 24
    )
    reduction_groups = []
    for group_id, index in enumerate(
        range(0, len(plan.recipe_assignments), group_size)
    ):
        assignments = plan.recipe_assignments[index : index + group_size]
        worker_ids = tuple(item.worker_id for item in assignments)
        checkpoint_artifacts = tuple(
            artifact
            for item in assignments
            for artifact in item.checkpoint_slot_artifacts[
                : item.checkpoint_slot_count
            ]
        )
        reduction_groups.append(
            {
                "group_id": group_id,
                "worker_ids": worker_ids,
                "checkpoint_artifacts": checkpoint_artifacts,
                "checkpoint_artifact_pattern": (
                    f"catalog-checkpoint-{plan.execution_plan_sha256[:16]}-*"
                    if selected_reduction_mode == "central"
                    else (
                        f"catalog-checkpoint-"
                        f"{plan.execution_plan_sha256[:16]}-"
                        f"g{group_id:02d}-*"
                    )
                ),
                "reduction_artifact": (
                    f"catalog-reduction-group-"
                    f"{plan.execution_plan_sha256[:16]}-g{group_id:02d}"
                ),
            }
        )
    reduction_matrix = {
        "include": [
            {
                "group_id": item["group_id"],
                "checkpoint_artifact_pattern": item[
                    "checkpoint_artifact_pattern"
                ],
                "reduction_artifact": item["reduction_artifact"],
            }
            for item in reduction_groups
        ]
    }
    assignment_by_worker = {
        item.worker_id: item for item in plan.recipe_assignments
    }
    reduction_nodes = []
    for group in reduction_groups:
        direct_children = tuple(
            {
                "child_id": f"worker:{worker_id:03d}",
                "artifact_ids": assignment_by_worker[
                    worker_id
                ].checkpoint_slot_artifacts[
                    : assignment_by_worker[worker_id].checkpoint_slot_count
                ],
                "descriptor_sha256": assignment_by_worker[
                    worker_id
                ].checkpoint_slot_manifest_sha256,
            }
            for worker_id in group["worker_ids"]
        )
        node_identity = {
            "schema_version": "1",
            "node_id": f"l00-g{group['group_id']:03d}",
            "level": 0,
            "group_id": group["group_id"],
            "campaign_id": plan.campaign_id,
            "authority_id": plan.authority_id,
            "science_sha256": plan.science_sha256,
            "execution_plan_sha256": plan.execution_plan_sha256,
            "direct_children": direct_children,
            "output_artifact": group["reduction_artifact"],
            "resource_projection_p99": (
                plan.reduction_projection
                if selected_reduction_mode == "central"
                else plan.hierarchical_reduction_projection
            ),
            "validation_opened": False,
            "locked_opened": False,
        }
        reduction_nodes.append(
            {
                **node_identity,
                "node_descriptor_sha256": canonical_sha256(node_identity),
            }
        )
    root_identity = {
        "schema_version": "1",
        "node_id": "l01-g000",
        "level": 1,
        "group_id": 0,
        "campaign_id": plan.campaign_id,
        "authority_id": plan.authority_id,
        "science_sha256": plan.science_sha256,
        "execution_plan_sha256": plan.execution_plan_sha256,
        "direct_children": tuple(
            {
                "child_id": node["node_id"],
                "artifact_ids": (node["output_artifact"],),
                "descriptor_sha256": node["node_descriptor_sha256"],
            }
            for node in reduction_nodes
        ),
        "output_artifact": f"catalog-final-evidence-{plan.authority_id}",
        "resource_projection_p99": plan.hierarchical_reduction_projection,
        "validation_opened": False,
        "locked_opened": False,
    }
    root_node = {
        **root_identity,
        "node_descriptor_sha256": canonical_sha256(root_identity),
    }
    reduction_plan = _plan_document(
        plan,
        "reduction_plan",
        {
            "group_size": group_size,
            "maximum_group_count": (
                1 if selected_reduction_mode == "central" else 15
            ),
            "fan_in": group_size,
            "maximum_fan_in": (
                360 if selected_reduction_mode == "central" else 30
            ),
            "maximum_levels": 2,
            "selected_mode": selected_reduction_mode,
            "central_eligibility": plan.reduction_selection,
            "groups": tuple(reduction_groups),
            "matrix": reduction_matrix,
            "nodes": tuple(reduction_nodes),
            "root_node": root_node,
            "levels": (
                {
                    "level": 0,
                    "matrix": reduction_matrix,
                    "node_ids": tuple(
                        node["node_id"] for node in reduction_nodes
                    ),
                },
                {
                    "level": 1,
                    "matrix": {
                        "include": (
                            {
                                "group_id": 0,
                                "node_id": root_node["node_id"],
                                "output_artifact": root_node[
                                    "output_artifact"
                                ],
                            },
                        )
                    },
                    "node_ids": (root_node["node_id"],),
                },
            ),
            "reduction_artifact_pattern": (
                f"catalog-reduction-group-"
                f"{plan.execution_plan_sha256[:16]}-*"
            ),
            "final_evidence_artifact": (
                f"catalog-final-evidence-{plan.authority_id}"
            ),
            "validation_opened": False,
            "locked_opened": False,
        },
    )
    write_json("reduction_plan.json", reduction_plan)
    artifact_plan = _plan_document(
        plan,
        "artifact_plan",
        {
            "same_run_transport_retention_days": 1,
            "runtime_transport_artifact": plan.runtime.worker_objects[0],
            "prepared_input_transport_artifacts": plan.prepared_inputs.worker_objects,
            "component_transport_artifacts": tuple(
                item.component_transport_artifact
                for item in component_assignments
            ),
            "worker_artifacts": worker_artifacts,
            "final_evidence_artifact": (
                f"catalog-final-evidence-{plan.authority_id}"
            ),
        },
    )
    write_json("artifact_plan.json", artifact_plan)

    payload_entries = tuple(
        {
            "artifact": path.relative_to(output / "payload_artifacts").parts[0],
            "member": Path(*path.relative_to(output / "payload_artifacts").parts[1:]).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(
            (output / "payload_artifacts").rglob("*"),
            key=lambda item: item.relative_to(output).as_posix(),
        )
        if path.is_file()
    )
    payload_bundle_manifest = _plan_document(
        plan,
        "payload_bundle_manifest",
        {
            "payloads": payload_entries,
            "runtime_transport_artifact": plan.runtime.worker_objects[0],
            "prepared_input_transport_artifacts": plan.prepared_inputs.worker_objects,
            "component_transport_artifacts": tuple(
                item.component_transport_artifact
                for item in component_assignments
            ),
        },
    )
    write_json("payload_bundle_manifest.json", payload_bundle_manifest)

    content_manifest = tuple(
        {
            "path": path.relative_to(output).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(
            output.rglob("*"),
            key=lambda item: item.relative_to(output).as_posix(),
        )
        if path.is_file() and path.name != "execution_plan_receipt.json"
    )
    runtime_cache_keys = dict(plan.runtime.cache_lookup_keys)
    prepared_cache_keys = dict(plan.prepared_inputs.cache_lookup_keys)
    prepared_partition_ids = tuple(
        sorted(
            {
                *plan.prepared_inputs.cached_logical_ids,
                *plan.prepared_inputs.pending_logical_ids,
            }
        )
    )
    if len(prepared_partition_ids) != len(plan.prepared_inputs.worker_objects):
        raise ValueError("CATALOG_PREPARED_PARTITION_OBJECT_COVERAGE_INVALID")
    prepared_partitions = tuple(
        {
            "logical_id": logical_id,
            "transport_artifact": transport_artifact,
            "cache_lookup_key": prepared_cache_keys.get(logical_id, ""),
        }
        for logical_id, transport_artifact in zip(
            prepared_partition_ids,
            plan.prepared_inputs.worker_objects,
            strict=True,
        )
    )
    prepared_core_artifact = next(
        (
            item
            for item in plan.prepared_inputs.worker_objects
            if item.endswith("-runtime-fragment-core")
        ),
        plan.prepared_inputs.worker_objects[0],
    )
    receipt_identity = {
        "schema_version": "1",
        "request_sha256": request_sha256,
        "authority_id": plan.authority_id,
        "campaign_id": plan.campaign_id,
        "science_sha256": plan.science_sha256,
        "execution_plan_sha256": plan.execution_plan_sha256,
        "execution_protocol_sha256": execution_protocol_sha256,
        "protected_commit_sha": protected_commit_sha,
        "decision_sha256": decision_sha256,
        "admission_token_sha256": admission_token_sha256,
        "global_reuse_plan_sha256": plan.plan_sha256,
        "runtime_mode": contract.runtime_preparation.runtime_mode,
        "runtime_identity_sha256": plan.runtime.identity_sha256,
        "runtime_cache_key": runtime_cache_keys.get("runtime", ""),
        "runtime_transport_artifact": plan.runtime.worker_objects[0],
        "numeric_profile_sha256": contract.science.numeric_profile,
        "prepared_input_identity_sha256": plan.prepared_inputs.identity_sha256,
        "prepared_input_cache_key": (
            next(iter(prepared_cache_keys.values()))
            if len(prepared_cache_keys) == 1
            else ""
        ),
        "prepared_input_cache_keys": tuple(sorted(prepared_cache_keys.items())),
        "prepared_input_partitions": prepared_partitions,
        "prepared_input_transport_artifact": prepared_core_artifact,
        "prepared_input_transport_artifacts": plan.prepared_inputs.worker_objects,
        "pending_recipe_count": sum(
            len(item.strategy_ids) for item in plan.recipe_assignments
        ),
        "active_recipe_workers": len(plan.recipe_assignments),
        "final_evidence_artifact": f"catalog-final-evidence-{plan.authority_id}",
        "worker_artifacts": worker_artifacts,
        "content_manifest": content_manifest,
        "content_manifest_sha256": canonical_sha256(content_manifest),
        "validation_opened": False,
        "locked_opened": False,
    }
    receipt = {
        **receipt_identity,
        "receipt_sha256": canonical_sha256(receipt_identity),
    }
    write_json("execution_plan_receipt.json", receipt)
    return receipt


def verify_sealed_global_reuse_execution_plan(
    root: Path,
    *,
    expected_bindings: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Read back every sealed byte and every compact descriptor route."""

    sealed = Path(root).resolve(strict=True)
    required_files = {
        "resolved_contract.json",
        "controller_binding.json",
        "rebuildable_store_plan.json",
        "logical_recipe_manifest.json",
        "component_requirement_manifest.json",
        "component_store_input_manifest.json",
        "pending_component_manifest.json",
        "cached_component_manifest.json",
        "component_matrix_a.json",
        "component_matrix_b.json",
        "cached_component_matrix_a.json",
        "cached_component_matrix_b.json",
        "recipe_assignment_bundle.zip",
        "recipe_matrix_a.json",
        "recipe_matrix_b.json",
        "recipe_matrix_c.json",
        "payload_bundle_manifest.json",
        "checkpoint_policy.json",
        "reduction_plan.json",
        "artifact_plan.json",
        "source_artifacts.json",
        "execution_plan_receipt.json",
    }
    present = {path.name for path in sealed.iterdir() if path.is_file()}
    if not required_files.issubset(present):
        raise ValueError("CATALOG_SEALED_PLAN_FILES_MISSING")
    try:
        receipt = json.loads(
            (sealed / "execution_plan_receipt.json").read_text("utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ValueError("CATALOG_SEALED_PLAN_RECEIPT_INVALID") from exc
    if not isinstance(receipt, dict):
        raise ValueError("CATALOG_SEALED_PLAN_RECEIPT_INVALID")
    receipt_identity = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    if canonical_sha256(receipt_identity) != receipt.get("receipt_sha256"):
        raise ValueError("CATALOG_SEALED_PLAN_RECEIPT_HASH_INVALID")
    if (
        receipt.get("schema_version") != "1"
        or receipt.get("validation_opened") is not False
        or receipt.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_SEALED_PLAN_BOUNDARY_INVALID")
    if expected_bindings is not None and any(
        receipt.get(key) != value for key, value in expected_bindings.items()
    ):
        raise ValueError("CATALOG_SEALED_PLAN_BINDING_INVALID")
    manifest = receipt.get("content_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_INVALID")
    seen_paths: set[str] = set()
    for item in manifest:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_INVALID")
        relative = Path(str(item["path"]))
        relative_text = relative.as_posix()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative_text in seen_paths
        ):
            raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_INVALID")
        seen_paths.add(relative_text)
        target = sealed / relative
        if (
            not target.is_file()
            or target.stat().st_size != item["size_bytes"]
            or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("CATALOG_SEALED_PLAN_CONTENT_INVALID")
    all_sealed_files = {
        path.relative_to(sealed).as_posix()
        for path in sealed.rglob("*")
        if path.is_file() and path.name != "execution_plan_receipt.json"
    }
    if seen_paths != all_sealed_files:
        raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_COVERAGE_INVALID")
    if canonical_sha256(tuple(manifest)) != receipt.get(
        "content_manifest_sha256"
    ):
        raise ValueError("CATALOG_SEALED_PLAN_MANIFEST_HASH_INVALID")

    matrix_names = (
        "component_matrix_a",
        "component_matrix_b",
        "cached_component_matrix_a",
        "cached_component_matrix_b",
        "recipe_matrix_a",
        "recipe_matrix_b",
        "recipe_matrix_c",
    )
    combined_utf16 = 0
    route_keys: set[tuple[str, str]] = set()
    for name in matrix_names:
        try:
            matrix = json.loads((sealed / f"{name}.json").read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("CATALOG_MATRIX_SCHEMA_INVALID") from exc
        rows = matrix.get("include") if isinstance(matrix, dict) else None
        if set(matrix) != {"include"} or not isinstance(rows, list):
            raise ValueError("CATALOG_MATRIX_SCHEMA_INVALID")
        canonical_output = json.dumps(
            matrix,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        combined_utf16 += len(canonical_output.encode("utf-16-le"))
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "worker_id",
                "descriptor_bundle_artifact",
                "descriptor_member",
                "descriptor_sha256",
            }:
                raise ValueError("CATALOG_MATRIX_ROW_INVALID")
            route = (
                str(row["descriptor_bundle_artifact"]),
                str(row["descriptor_member"]),
            )
            if route in route_keys:
                raise ValueError("CATALOG_MATRIX_ROUTE_DUPLICATE")
            route_keys.add(route)
            descriptor = sealed / "payload_artifacts" / route[0] / route[1]
            if (
                not descriptor.is_file()
                or hashlib.sha256(descriptor.read_bytes()).hexdigest()
                != row["descriptor_sha256"]
            ):
                raise ValueError("CATALOG_SEALED_PLAN_CONTENT_INVALID")
    if combined_utf16 > 512 * 1024:
        raise ValueError("CATALOG_MATRIX_OUTPUT_BUDGET_EXCEEDED")

    payload_manifest = json.loads(
        (sealed / "payload_bundle_manifest.json").read_text("utf-8")
    )
    payload_rows = payload_manifest.get("payloads")
    if not isinstance(payload_rows, list) or not payload_rows:
        raise ValueError("CATALOG_PAYLOAD_BUNDLE_MANIFEST_INVALID")
    for item in payload_rows:
        if not isinstance(item, dict) or set(item) != {
            "artifact",
            "member",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("CATALOG_PAYLOAD_BUNDLE_MANIFEST_INVALID")
        target = (
            sealed
            / "payload_artifacts"
            / str(item["artifact"])
            / str(item["member"])
        )
        if (
            not target.is_file()
            or target.stat().st_size != item["size_bytes"]
            or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("CATALOG_SEALED_PLAN_CONTENT_INVALID")
    return receipt


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_PLAN_INPUT_NOT_OBJECT")
    return payload


def _matrix_payload(shards: tuple[int, ...]) -> str:
    return json.dumps(
        {"shard": list(shards)},
        separators=(",", ":"),
        sort_keys=True,
    )


def _component_matrix_payload(worker_count: int) -> str:
    return json.dumps(
        {"component_shard": list(range(worker_count))},
        separators=(",", ":"),
        sort_keys=True,
    )


def apply_qualification_worker_override(
    contract: RunOptimizationContractV1,
    *,
    workers: int,
    qualification_only: bool,
) -> RunOptimizationContractV1:
    """Create one measured worker-count candidate without weakening production."""

    if not qualification_only:
        raise ValueError("WORKER_OVERRIDE_REQUIRES_QUALIFICATION")
    if not 1 <= int(workers) <= 360:
        raise ValueError("WORKER_OVERRIDE_INVALID")
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "workers": int(workers),
    }
    return RunOptimizationContractV1.model_validate(payload)


def apply_qualification_process_override(
    contract: RunOptimizationContractV1,
    *,
    processes_per_worker: int,
    qualification_only: bool,
) -> RunOptimizationContractV1:
    """Create one measured process-count candidate without weakening production."""

    if not qualification_only:
        raise ValueError("PROCESS_OVERRIDE_REQUIRES_QUALIFICATION")
    if int(processes_per_worker) not in (1, 2, 4):
        raise ValueError("PROCESS_OVERRIDE_INVALID")
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "processes_per_worker": int(processes_per_worker),
    }
    return RunOptimizationContractV1.model_validate(payload)


def apply_qualification_component_process_override(
    contract: RunOptimizationContractV1,
    *,
    component_processes_per_worker: int,
    qualification_only: bool,
) -> RunOptimizationContractV1:
    """Measure component CPU topology independently from recipe topology."""

    if not qualification_only:
        raise ValueError("COMPONENT_PROCESS_OVERRIDE_REQUIRES_QUALIFICATION")
    if int(component_processes_per_worker) not in (1, 2, 4):
        raise ValueError("COMPONENT_PROCESS_OVERRIDE_INVALID")
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "component_processes_per_worker": int(component_processes_per_worker),
    }
    return RunOptimizationContractV1.model_validate(payload)


def apply_qualification_component_worker_override(
    contract: RunOptimizationContractV1,
    *,
    component_workers: int,
    qualification_only: bool,
) -> RunOptimizationContractV1:
    """Measure component fan-out independently from recipe fan-out."""

    if not qualification_only:
        raise ValueError("COMPONENT_WORKER_OVERRIDE_REQUIRES_QUALIFICATION")
    if not 1 <= int(component_workers) <= 120:
        raise ValueError("COMPONENT_WORKER_OVERRIDE_INVALID")
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "component_workers": int(component_workers),
    }
    return RunOptimizationContractV1.model_validate(payload)


def apply_compatible_autotune_history(
    contract: RunOptimizationContractV1,
    *,
    history_path: Path | None,
    thermal_state: ThermalState,
) -> tuple[RunOptimizationContractV1, CatalogTuningDecisionV1 | None]:
    """Apply only a three-sample, science-compatible promoted configuration."""

    if history_path is None or not Path(history_path).is_file():
        return contract, None
    history = CatalogPerformanceHistoryV1.load(Path(history_path))
    try:
        decision = select_history_configuration(
            history,
            science_identity_sha256=canonical_sha256(contract.science),
            thermal_state=thermal_state,
            minimum_samples=3,
            previous_best_median_seconds=None,
            max_regression_ratio=contract.acceptance.max_performance_regression_ratio,
            max_memory_fraction=contract.limits.max_memory_fraction,
        )
    except ValueError as exc:
        if str(exc) == "CATALOG_TUNING_NO_SAFE_EQUIVALENT_CANDIDATE":
            return contract, None
        raise
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "workers": decision.workers,
        "component_workers": decision.component_workers,
        "component_processes_per_worker": (
            decision.component_processes_per_worker
        ),
        "processes_per_worker": decision.processes_per_worker,
        "block_size": decision.block_size,
    }
    return RunOptimizationContractV1.model_validate(payload), decision


def build_repository_contract(
    *,
    repo_root: Path,
    policy_path: Path,
    campaign_path: Path,
    catalog_dir: Path,
    selected_config_path: Path | None = None,
) -> RunOptimizationContractV1:
    """Resolve all scientific identities and counts from authoritative files."""

    repo_root = Path(repo_root).resolve()
    policy = _read_json_object(policy_path)
    campaign = _read_json_object(campaign_path)
    boundaries = campaign.get("boundaries")
    scientific_inputs = campaign.get("scientific_inputs")
    if not isinstance(boundaries, dict) or not isinstance(scientific_inputs, dict):
        raise ValueError("CATALOG_CAMPAIGN_CONTRACT_INVALID")
    receipt = verify_strategy_catalog_directory(Path(catalog_dir))
    catalog_path = Path(catalog_dir) / "catalog.jsonl"
    catalog_rows = [
        json.loads(line)
        for line in catalog_path.read_text("utf-8").splitlines()
        if line
    ]
    selected_path = (
        Path(selected_config_path)
        if selected_config_path is not None
        else repo_root / "config/sp500_megarun_selected_dehb_13.json"
    )
    selected_payload = json.loads(selected_path.read_text("utf-8"))
    if not isinstance(selected_payload, list):
        raise ValueError("CATALOG_SELECTED_CONFIG_INVALID")
    canonical_recipes = len(
        {str(row["scientific_recipe_sha256"]) for row in catalog_rows}
    )
    unique_components = collect_unique_components(catalog_rows, selected_payload)
    estimates = policy.get("workload_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("CATALOG_WORKLOAD_ESTIMATES_INVALID")
    prior_cache_hits = int(estimates["expected_prior_cache_hits"])
    if policy.get("numeric_profile") != "derived:dehb_numeric_runtime_v1":
        raise ValueError("CATALOG_NUMERIC_PROFILE_POLICY_INVALID")
    manifest_path = Path(catalog_dir) / "manifest.json"
    payload = {
        "schema_version": policy["schema_version"],
        "optimization_mode": policy["optimization_mode"],
        "allow_unoptimized_run": policy["allow_unoptimized_run"],
        "infrastructure_sha256": catalog_infrastructure_source_sha256(repo_root),
        "science": {
            "evaluator_sha256": catalog_scientific_source_sha256(repo_root),
            "data_snapshot_sha256": scientific_inputs[
                "train_snapshot_manifest_sha256"
            ],
            "catalog_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "train_end": boundaries["search_end"],
            "validation_opened": boundaries["validation_opened"],
            "locked_opened": boundaries["locked_opened"],
            "numeric_profile": numeric_runtime_profile_sha256(),
        },
        "workload": {
            "requested_recipes": int(receipt["strategy_count"]),
            "canonical_recipes": canonical_recipes,
            "unique_components": len(unique_components),
            "expected_new_recipes": canonical_recipes - prior_cache_hits,
            "expected_prior_cache_hits": prior_cache_hits,
            "estimated_position_equivalences": estimates[
                "estimated_position_equivalences"
            ],
        },
        "execution": policy["execution"],
        "limits": policy["limits"],
        "acceptance": policy["acceptance"],
        "runtime_preparation": policy["runtime_preparation"],
        "component_store_execution": policy["component_store_execution"],
        "payload_execution": policy["payload_execution"],
        "prepared_input_execution": policy["prepared_input_execution"],
        "rebuildable_store_execution": policy["rebuildable_store_execution"],
        "recovery_execution": policy["recovery_execution"],
    }
    return RunOptimizationContractV1.model_validate(payload)


def write_catalog_run_plan(
    contract_path: Path,
    evidence_path: Path,
    output_dir: Path,
    *,
    github_output: Path | None = None,
    work_manifest: CatalogResumeWorkManifestV1 | None = None,
) -> CatalogRunPlanV1:
    """Write a plan only after the fail-closed admission controller accepts it."""

    contract = RunOptimizationContractV1.model_validate(
        _read_json_object(contract_path)
    )
    evidence = CatalogAdmissionEvidenceV1.model_validate(
        _read_json_object(evidence_path)
    )
    plan = build_catalog_run_plan(
        contract,
        evidence,
        work_manifest_sha256=(
            work_manifest.manifest_sha256 if work_manifest is not None else "0" * 64
        ),
        pending_recipe_count=(
            len(work_manifest.pending_strategy_ids)
            if work_manifest is not None
            else None
        ),
        cached_recipe_count=(
            len(work_manifest.cached_strategy_ids)
            if work_manifest is not None
            else 0
        ),
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "resolved_contract.json").write_text(
        contract.model_dump_json(indent=2) + "\n",
        "utf-8",
    )
    (output_dir / "admission_evidence.json").write_text(
        evidence.model_dump_json(indent=2) + "\n",
        "utf-8",
    )
    (output_dir / "run_plan.json").write_text(
        plan.model_dump_json(indent=2) + "\n",
        "utf-8",
    )
    if work_manifest is not None:
        (output_dir / "resume_work_manifest.json").write_text(
            work_manifest.model_dump_json(indent=2) + "\n",
            "utf-8",
        )
    if github_output is not None:
        matrices = list(plan.matrices)
        matrices.extend([tuple()] * (3 - len(matrices)))
        if len(matrices) != 3:
            raise ValueError("CATALOG_PLAN_MATRIX_COUNT_INVALID")
        lines = [
            f"matrix_a={_matrix_payload(matrices[0])}",
            f"matrix_b={_matrix_payload(matrices[1])}",
            f"matrix_c={_matrix_payload(matrices[2])}",
            f"admission_token_sha256={plan.admission_token_sha256}",
            f"workers={plan.workers}",
            f"active_workers={plan.active_workers}",
            f"component_workers={plan.component_workers}",
            "component_matrix="
            f"{_component_matrix_payload(plan.component_workers)}",
            f"pending_recipe_count={plan.pending_recipe_count}",
            f"cached_recipe_count={plan.cached_recipe_count}",
            "component_processes_per_worker="
            f"{plan.component_processes_per_worker}",
            f"processes_per_worker={plan.processes_per_worker}",
            f"block_size={plan.block_size}",
        ]
        Path(github_output).write_text("\n".join(lines) + "\n", "utf-8")
    return plan


def write_repository_catalog_run_plan(
    *,
    repo_root: Path,
    policy_path: Path,
    campaign_path: Path,
    catalog_dir: Path,
    selected_config_path: Path | None = None,
    evidence_path: Path,
    output_dir: Path,
    github_output: Path | None = None,
    resume_roots: tuple[Path, ...] = (),
    benchmark_workers: int | None = None,
    benchmark_processes: int | None = None,
    benchmark_component_processes: int | None = None,
    benchmark_component_workers: int | None = None,
    autotune_history_path: Path | None = None,
    thermal_state: ThermalState = "cold",
) -> CatalogRunPlanV1:
    """Resolve the immutable contract from the checkout before admission."""

    contract = build_repository_contract(
        repo_root=repo_root,
        policy_path=policy_path,
        campaign_path=campaign_path,
        catalog_dir=catalog_dir,
        selected_config_path=selected_config_path,
    )
    contract, autotune_decision = apply_compatible_autotune_history(
        contract,
        history_path=autotune_history_path,
        thermal_state=thermal_state,
    )
    if benchmark_workers is not None:
        evidence = CatalogAdmissionEvidenceV1.model_validate(
            _read_json_object(evidence_path)
        )
        contract = apply_qualification_worker_override(
            contract,
            workers=benchmark_workers,
            qualification_only=evidence.qualification_only,
        )
    if benchmark_processes is not None:
        evidence = CatalogAdmissionEvidenceV1.model_validate(
            _read_json_object(evidence_path)
        )
        contract = apply_qualification_process_override(
            contract,
            processes_per_worker=benchmark_processes,
            qualification_only=evidence.qualification_only,
        )
    if benchmark_component_processes is not None:
        evidence = CatalogAdmissionEvidenceV1.model_validate(
            _read_json_object(evidence_path)
        )
        contract = apply_qualification_component_process_override(
            contract,
            component_processes_per_worker=benchmark_component_processes,
            qualification_only=evidence.qualification_only,
        )
    if benchmark_component_workers is not None:
        evidence = CatalogAdmissionEvidenceV1.model_validate(
            _read_json_object(evidence_path)
        )
        contract = apply_qualification_component_worker_override(
            contract,
            component_workers=benchmark_component_workers,
            qualification_only=evidence.qualification_only,
        )
    resolved_path = Path(output_dir).parent / "resolved-contract-input.json"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(contract.model_dump_json(indent=2) + "\n", "utf-8")
    catalog_rows = [
        json.loads(line)
        for line in (Path(catalog_dir) / "catalog.jsonl").read_text("utf-8").splitlines()
        if line
    ]
    science_identity_sha256 = canonical_sha256(contract.science)
    resume_index = load_resume_index(
        resume_roots,
        expected_science_identity_sha256=science_identity_sha256,
        expected_catalog_manifest_sha256=contract.science.catalog_manifest_sha256,
    )
    work_manifest = build_resume_work_manifest(
        tuple(str(row["strategy_id"]) for row in catalog_rows),
        cached_strategy_ids=resume_index.strategy_ids,
        maximum_workers=contract.execution.workers,
    )
    try:
        plan = write_catalog_run_plan(
            resolved_path,
            evidence_path,
            output_dir,
            github_output=github_output,
            work_manifest=work_manifest,
        )
        if autotune_decision is not None:
            (Path(output_dir) / "autotune_decision.json").write_text(
                autotune_decision.model_dump_json(indent=2) + "\n",
                "utf-8",
            )
        return plan
    finally:
        resolved_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--contract", type=Path)
    source.add_argument("--policy", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--catalog-dir", type=Path)
    parser.add_argument("--selected-config", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--resume-root", type=Path, action="append", default=[])
    parser.add_argument("--benchmark-workers", type=int, default=0)
    parser.add_argument("--benchmark-processes", type=int, default=0)
    parser.add_argument("--benchmark-component-processes", type=int, default=0)
    parser.add_argument("--benchmark-component-workers", type=int, default=0)
    parser.add_argument("--autotune-history", type=Path)
    parser.add_argument(
        "--thermal-state",
        choices=("cold", "component_warm", "fully_hot"),
        default="cold",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.contract is not None:
        write_catalog_run_plan(
            args.contract,
            args.evidence,
            args.output_dir,
            github_output=args.github_output,
        )
    else:
        if args.repo_root is None or args.campaign is None or args.catalog_dir is None:
            raise SystemExit(
                "--policy requires --repo-root, --campaign and --catalog-dir"
            )
        write_repository_catalog_run_plan(
            repo_root=args.repo_root,
            policy_path=args.policy,
            campaign_path=args.campaign,
            catalog_dir=args.catalog_dir,
            selected_config_path=args.selected_config,
            evidence_path=args.evidence,
            output_dir=args.output_dir,
            github_output=args.github_output,
            resume_roots=tuple(args.resume_root),
            benchmark_workers=(
                args.benchmark_workers if args.benchmark_workers else None
            ),
            benchmark_processes=(
                args.benchmark_processes if args.benchmark_processes else None
            ),
            benchmark_component_processes=(
                args.benchmark_component_processes
                if args.benchmark_component_processes
                else None
            ),
            benchmark_component_workers=(
                args.benchmark_component_workers
                if args.benchmark_component_workers
                else None
            ),
            autotune_history_path=args.autotune_history,
            thermal_state=args.thermal_state,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
