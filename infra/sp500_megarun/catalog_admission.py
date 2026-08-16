"""Admission controller for optimized SP500 catalog runs."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import Field

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)


class CatalogAdmissionEvidenceV1(FrozenModel):
    estimated_tail_ratio_p99_p50: Annotated[float, Field(ge=1.0)]
    estimated_result_bytes_per_recipe: Annotated[int, Field(ge=1)]
    estimated_peak_memory_bytes: Annotated[int, Field(ge=1)]
    available_memory_bytes: Annotated[int, Field(ge=1)]
    cache_compatible: bool
    manifest_verified: bool
    previous_regression_unresolved: bool
    workflow_uses_optimized_entrypoint: bool
    qualification_only: bool = False

    @property
    def evidence_sha256(self) -> str:
        return canonical_sha256(self)


class CatalogAdmissionReportV1(FrozenModel):
    schema_version: str = "1"
    accepted: bool
    violations: tuple[str, ...]
    contract_sha256: Sha256
    evidence_sha256: Sha256
    admission_token_sha256: Sha256 | None
    expected_physical_component_builds: int
    expected_redundant_component_build_ratio: float
    qualification_only: bool = False
    validation_opened: bool = False
    locked_opened: bool = False


class CatalogRunPlanV1(FrozenModel):
    schema_version: str = "1"
    contract_sha256: Sha256
    evidence_sha256: Sha256
    admission_token_sha256: Sha256
    workers: Annotated[int, Field(ge=1, le=360)]
    processes_per_worker: Annotated[int, Field(ge=1, le=4)]
    block_size: Annotated[int, Field(ge=1)]
    matrices: tuple[tuple[int, ...], ...]
    expected_physical_component_builds: int
    qualification_only: bool = False
    validation_opened: bool = False
    locked_opened: bool = False


def _admission_token(
    contract_sha256: str,
    evidence_sha256: str,
) -> str:
    payload = (
        b"aurora-catalog-admission-v1\0"
        + contract_sha256.encode("ascii")
        + evidence_sha256.encode("ascii")
    )
    return hashlib.sha256(payload).hexdigest()


def admit_catalog_run(
    contract: RunOptimizationContractV1,
    evidence: CatalogAdmissionEvidenceV1,
) -> CatalogAdmissionReportV1:
    """Return a token only when every optimization and science gate passes."""

    violations: list[str] = []
    if not evidence.qualification_only and (
        evidence.estimated_tail_ratio_p99_p50
        > contract.limits.max_expected_tail_ratio_p99_p50
    ):
        violations.append("TAIL_RATIO_EXCEEDED")
    if not evidence.qualification_only and (
        evidence.estimated_result_bytes_per_recipe
        > contract.limits.max_result_bytes_per_recipe
    ):
        violations.append("RESULT_BYTES_BUDGET_EXCEEDED")
    memory_fraction = (
        evidence.estimated_peak_memory_bytes / evidence.available_memory_bytes
    )
    if memory_fraction > contract.limits.max_memory_fraction:
        violations.append("MEMORY_BUDGET_EXCEEDED")
    if not evidence.qualification_only and not evidence.cache_compatible:
        violations.append("CACHE_INCOMPATIBLE")
    if not evidence.manifest_verified:
        violations.append("MANIFEST_UNVERIFIED")
    if evidence.previous_regression_unresolved:
        violations.append("PREVIOUS_REGRESSION_UNRESOLVED")
    if not evidence.workflow_uses_optimized_entrypoint:
        violations.append("OPTIMIZED_ENTRYPOINT_BYPASSED")

    expected_physical = (
        contract.workload.unique_components
        + contract.execution.component_replication_budget
    )
    redundant_ratio = (
        contract.execution.component_replication_budget / expected_physical
        if expected_physical
        else 0.0
    )
    contract_sha256 = contract.contract_sha256
    evidence_sha256 = evidence.evidence_sha256
    accepted = not violations
    return CatalogAdmissionReportV1(
        accepted=accepted,
        violations=tuple(violations),
        contract_sha256=contract_sha256,
        evidence_sha256=evidence_sha256,
        admission_token_sha256=(
            _admission_token(contract_sha256, evidence_sha256)
            if accepted
            else None
        ),
        expected_physical_component_builds=expected_physical,
        expected_redundant_component_build_ratio=redundant_ratio,
        qualification_only=evidence.qualification_only,
    )


def validate_catalog_entrypoint(workflow_path: Path) -> tuple[str, ...]:
    """Require legacy/public callers to delegate to the guarded workflow."""

    try:
        payload = yaml.safe_load(Path(workflow_path).read_text("utf-8"))
    except (OSError, yaml.YAMLError):
        return ("CATALOG_WORKFLOW_PARSE_FAILED",)
    if not isinstance(payload, Mapping):
        return ("CATALOG_WORKFLOW_PARSE_FAILED",)
    jobs = payload.get("jobs")
    if not isinstance(jobs, Mapping) or len(jobs) != 1:
        return ("CATALOG_OPTIMIZED_ENTRYPOINT_REQUIRED",)
    job = next(iter(jobs.values()))
    if (
        not isinstance(job, Mapping)
        or job.get("uses") != "./.github/workflows/catalog-optimized-run.yml"
    ):
        return ("CATALOG_OPTIMIZED_ENTRYPOINT_REQUIRED",)
    return ()


def build_catalog_run_plan(
    contract: RunOptimizationContractV1,
    evidence: CatalogAdmissionEvidenceV1,
) -> CatalogRunPlanV1:
    """Freeze one admitted matrix plan without losing or duplicating shards."""

    admission = admit_catalog_run(contract, evidence)
    if not admission.accepted or admission.admission_token_sha256 is None:
        raise ValueError(
            "CATALOG_RUN_NOT_ADMITTED:" + ",".join(admission.violations)
        )
    shard_indices = tuple(range(contract.execution.workers))
    matrices = tuple(
        shard_indices[start : start + 120]
        for start in range(0, len(shard_indices), 120)
    )
    return CatalogRunPlanV1(
        contract_sha256=admission.contract_sha256,
        evidence_sha256=admission.evidence_sha256,
        admission_token_sha256=admission.admission_token_sha256,
        workers=contract.execution.workers,
        processes_per_worker=contract.execution.processes_per_worker,
        block_size=contract.execution.block_size,
        matrices=matrices,
        expected_physical_component_builds=(
            admission.expected_physical_component_builds
        ),
        qualification_only=admission.qualification_only,
    )


def verify_catalog_worker_admission(
    plan_path: Path,
    *,
    admission_token_sha256: str,
    shard_index: int,
    total_shards: int,
) -> CatalogRunPlanV1:
    """Fail before data loading unless this worker belongs to the exact plan."""

    try:
        payload = json.loads(Path(plan_path).read_text("utf-8"))
        plan = CatalogRunPlanV1.model_validate(payload)
    except (OSError, ValueError) as exc:
        raise ValueError("CATALOG_RUN_PLAN_INVALID") from exc
    if not hmac.compare_digest(
        plan.admission_token_sha256,
        str(admission_token_sha256),
    ):
        raise ValueError("CATALOG_ADMISSION_TOKEN_INVALID")
    planned_shards = tuple(shard for matrix in plan.matrices for shard in matrix)
    if (
        total_shards != plan.workers
        or shard_index not in planned_shards
        or planned_shards != tuple(range(plan.workers))
    ):
        raise ValueError("CATALOG_PLAN_PARTITION_INVALID")
    if plan.validation_opened or plan.locked_opened:
        raise ValueError("CATALOG_PROTECTED_PERIOD_OPENED")
    return plan


def verify_catalog_plan_token(
    plan_path: Path,
    *,
    admission_token_sha256: str,
) -> CatalogRunPlanV1:
    """Verify an admitted plan for non-recipe stages such as component build."""

    try:
        payload = json.loads(Path(plan_path).read_text("utf-8"))
        plan = CatalogRunPlanV1.model_validate(payload)
    except (OSError, ValueError) as exc:
        raise ValueError("CATALOG_RUN_PLAN_INVALID") from exc
    if not hmac.compare_digest(
        plan.admission_token_sha256,
        str(admission_token_sha256),
    ):
        raise ValueError("CATALOG_ADMISSION_TOKEN_INVALID")
    if plan.validation_opened or plan.locked_opened:
        raise ValueError("CATALOG_PROTECTED_PERIOD_OPENED")
    return plan


__all__ = [
    "CatalogAdmissionEvidenceV1",
    "CatalogAdmissionReportV1",
    "CatalogRunPlanV1",
    "admit_catalog_run",
    "build_catalog_run_plan",
    "validate_catalog_entrypoint",
    "verify_catalog_worker_admission",
    "verify_catalog_plan_token",
]
