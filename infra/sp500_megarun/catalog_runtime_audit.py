"""Verify one catalog run used only the sealed commit and standard free runners."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .catalog_request_contract import FrozenModel, Sha256


def _canonical_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _rows(value: object, *, root: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Mapping):
        raw_rows = value.get(root)
        pages: Sequence[object] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        pages = value
        raw_rows = None
    else:
        raise ValueError("CATALOG_RUNTIME_AUDIT_PAGINATION_INVALID")
    output: list[Mapping[str, Any]] = []
    if raw_rows is not None:
        pages = (value,)
    for page in pages:
        if not isinstance(page, Mapping):
            raise ValueError("CATALOG_RUNTIME_AUDIT_PAGINATION_INVALID")
        current = page.get(root)
        if not isinstance(current, Sequence) or isinstance(current, (str, bytes)):
            raise ValueError("CATALOG_RUNTIME_AUDIT_PAGINATION_INVALID")
        for row in current:
            if not isinstance(row, Mapping):
                raise ValueError("CATALOG_RUNTIME_AUDIT_PAGINATION_INVALID")
            output.append(row)
    ids = [row.get("id") for row in output]
    if (
        any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in ids)
        or len(ids) != len(set(ids))
    ):
        raise ValueError("CATALOG_RUNTIME_AUDIT_PAGINATION_INVALID")
    return tuple(output)


_MATRIX_SKIP_JOBS = {
    "component_matrix_a_count": "build_components_a",
    "component_matrix_b_count": "build_components_b",
    "cached_component_matrix_a_count": "materialize_cached_components_a",
    "cached_component_matrix_b_count": "materialize_cached_components_b",
    "recipe_matrix_a_count": "evaluate_a",
    "recipe_matrix_b_count": "evaluate_b",
    "recipe_matrix_c_count": "evaluate_c",
    "payload_artifact_count": "publish_sealed_payload_artifacts",
    "reduction_matrix_count": "reduce_groups",
}


def allowed_skips_from_verified_outputs(
    evidence: object, *, binding: Mapping[str, str],
) -> frozenset[str]:
    """Consume protected workflow outputs, never the jobs being audited.

    The caller must obtain these facts from the plan-verification and recovery
    jobs in the same protected run. Matching a binding does not authenticate an
    arbitrary caller-supplied document.
    """
    error = "CATALOG_RUNTIME_AUDIT_SKIP_POLICY_INVALID"
    if (
        not isinstance(evidence, Mapping)
        or set(evidence) != {"binding", "matrix_counts", "reconcile_status", "recovery"}
        or evidence.get("binding") != dict(binding)
    ):
        raise ValueError(error)
    counts = evidence.get("matrix_counts")
    if not isinstance(counts, Mapping) or set(counts) != set(_MATRIX_SKIP_JOBS):
        raise ValueError(error)
    if any(type(count) is not int or count < 0 for count in counts.values()):
        raise ValueError(error)
    allowed = {
        f"engine / {job}" for count_name, job in _MATRIX_SKIP_JOBS.items()
        if counts[count_name] == 0
    }
    waves = evidence.get("recovery")
    if not isinstance(waves, list) or len(waves) != 2:
        raise ValueError(error)
    previous = evidence.get("reconcile_status")
    if previous not in {"retry", "replan"}:
        raise ValueError(error)
    for wave_number, wave in enumerate(waves, 1):
        if not isinstance(wave, Mapping) or set(wave) != {"status", "has_matrix_a", "has_matrix_b"}:
            raise ValueError(error)
        if previous == "complete":
            if any(value != "" for value in wave.values()):
                raise ValueError(error)
            allowed.add(f"engine / recovery_wave_{wave_number}")
            continue
        if wave["status"] not in {"complete", "retry", "replan"}:
            raise ValueError(error)
        for suffix in ("a", "b"):
            needed = wave[f"has_matrix_{suffix}"]
            if needed not in {"true", "false"}:
                raise ValueError(error)
            if needed == "false":
                allowed.add(f"engine / recovery_wave_{wave_number} / retry_{suffix}")
        previous = wave["status"]
    if previous != "complete":
        raise ValueError(error)
    return frozenset(allowed)


class CatalogRuntimeAuditV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    request_sha256: Sha256
    authority_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    campaign_id: Sha256
    science_sha256: Sha256
    execution_plan_sha256: Sha256
    execution_protocol_sha256: Sha256
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    run_id: int = Field(ge=1)
    run_attempt: int = Field(ge=1)
    repository_visibility: Literal["public"]
    workflow_path: str
    job_ids: tuple[int, ...]
    artifact_ids: tuple[int, ...]
    job_inventory_sha256: Sha256
    artifact_inventory_sha256: Sha256
    standard_runner_only: Literal[True]
    paid_runner_minutes: Literal[0]
    estimated_paid_actions_cost_microusd: Literal[0]
    cold_end_to_end_and_warm_recipe_throughput_separate: Literal[True]
    strategies_per_minute: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    components_reused: int | None = Field(default=None, ge=0)
    components_computed_once: int | None = Field(default=None, ge=0)
    selective_retries: int | None = Field(default=None, ge=0)
    validation_opened: Literal[False]
    locked_opened: Literal[False]
    audited_at: datetime
    receipt_sha256: Sha256

    @field_validator("audited_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_RUNTIME_AUDIT_TIME_INVALID")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _hash(self) -> "CatalogRuntimeAuditV1":
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if _sha256(payload) != self.receipt_sha256:
            raise ValueError("CATALOG_RUNTIME_AUDIT_HASH_INVALID")
        if tuple(sorted(self.job_ids)) != self.job_ids:
            raise ValueError("CATALOG_RUNTIME_AUDIT_JOB_INVENTORY_INVALID")
        if tuple(sorted(self.artifact_ids)) != self.artifact_ids:
            raise ValueError("CATALOG_RUNTIME_AUDIT_ARTIFACT_INVENTORY_INVALID")
        return self


def build_catalog_runtime_audit(
    *,
    binding: Mapping[str, str],
    run: Mapping[str, Any],
    repository: Mapping[str, Any],
    jobs_pages: object,
    jobs_confirmation_pages: object,
    artifacts_pages: object,
    artifacts_confirmation_pages: object,
    run_id: int,
    run_attempt: int,
    audited_at: datetime,
    components_reused: int | None = None,
    components_computed_once: int | None = None,
    selective_retries: int | None = None,
    allowed_skipped_job_names: frozenset[str] = frozenset(),
) -> CatalogRuntimeAuditV1:
    """Build a receipt only from two complete, stable inventories."""

    required_binding = {
        "request_sha256",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
        "protected_commit_sha",
    }
    if set(binding) != required_binding:
        raise ValueError("CATALOG_RUNTIME_AUDIT_BINDING_INVALID")
    jobs = _rows(jobs_pages, root="jobs")
    jobs_confirmation = _rows(jobs_confirmation_pages, root="jobs")
    artifacts = _rows(artifacts_pages, root="artifacts")
    artifacts_confirmation = _rows(
        artifacts_confirmation_pages,
        root="artifacts",
    )
    job_ids = tuple(sorted(int(row["id"]) for row in jobs))
    artifact_ids = tuple(sorted(int(row["id"]) for row in artifacts))
    if job_ids != tuple(sorted(int(row["id"]) for row in jobs_confirmation)):
        raise ValueError("CATALOG_RUNTIME_AUDIT_JOB_INVENTORY_UNSTABLE")
    if artifact_ids != tuple(
        sorted(int(row["id"]) for row in artifacts_confirmation)
    ):
        raise ValueError("CATALOG_RUNTIME_AUDIT_ARTIFACT_INVENTORY_UNSTABLE")
    if not jobs:
        raise ValueError("CATALOG_RUNTIME_AUDIT_JOB_INVENTORY_INVALID")
    if not isinstance(allowed_skipped_job_names, frozenset) or any(
        not isinstance(name, str) or not name for name in allowed_skipped_job_names
    ):
        raise ValueError("CATALOG_RUNTIME_AUDIT_SKIP_POLICY_INVALID")
    confirmation_by_id = {job["id"]: job for job in jobs_confirmation}
    for job in jobs:
        labels = job.get("labels")
        if job.get("conclusion") == "skipped":
            if job.get("name") not in allowed_skipped_job_names:
                raise ValueError("CATALOG_RUNTIME_AUDIT_UNEXPECTED_SKIPPED_JOB")
            confirmation = confirmation_by_id[job["id"]]
            if any(
                confirmation.get(key) != job.get(key)
                for key in ("name", "conclusion", "labels", "status")
            ):
                raise ValueError("CATALOG_RUNTIME_AUDIT_JOB_INVENTORY_UNSTABLE")
            if labels == []:
                continue
        if (
            not isinstance(labels, Sequence)
            or isinstance(labels, (str, bytes))
            or "ubuntu-24.04" not in labels
            or any(str(label).casefold() == "self-hosted" for label in labels)
        ):
            raise ValueError("CATALOG_RUNTIME_AUDIT_NONSTANDARD_RUNNER")
    run_repository = run.get("repository")
    run_repository_name = (
        run_repository.get("full_name")
        if isinstance(run_repository, Mapping)
        else None
    )
    if (
        run.get("id") != run_id
        or run.get("run_attempt") != run_attempt
        or run.get("head_sha") != binding["protected_commit_sha"]
        or run_repository_name != "trading-optimizer-lab-org/aurora"
        or repository.get("full_name") != run_repository_name
        or repository.get("visibility") != "public"
        or repository.get("private") is not False
        or not isinstance(run.get("path"), str)
    ):
        raise ValueError("CATALOG_RUNTIME_AUDIT_RUN_IDENTITY_INVALID")
    payload: dict[str, object] = {
        "schema_version": "1",
        **dict(binding),
        "run_id": run_id,
        "run_attempt": run_attempt,
        "repository_visibility": "public",
        "workflow_path": run["path"],
        "job_ids": job_ids,
        "artifact_ids": artifact_ids,
        "job_inventory_sha256": _sha256(
            sorted(
                (
                    int(row["id"]),
                    str(row.get("name")),
                    str(row.get("conclusion")),
                    tuple(str(label) for label in row.get("labels", ())),
                    str(row.get("runner_group_name")),
                )
                for row in jobs
            )
        ),
        "artifact_inventory_sha256": _sha256(
            sorted(
                (
                    int(row["id"]),
                    str(row.get("name")),
                    bool(row.get("expired")),
                    int(row.get("size_in_bytes", 0)),
                )
                for row in artifacts
            )
        ),
        "standard_runner_only": True,
        "paid_runner_minutes": 0,
        "estimated_paid_actions_cost_microusd": 0,
        "cold_end_to_end_and_warm_recipe_throughput_separate": True,
        "strategies_per_minute": None,
        "components_reused": components_reused,
        "components_computed_once": components_computed_once,
        "selective_retries": selective_retries,
        "validation_opened": False,
        "locked_opened": False,
        "audited_at": audited_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    payload["receipt_sha256"] = _sha256(payload)
    return CatalogRuntimeAuditV1.model_validate(payload)


__all__ = ["CatalogRuntimeAuditV1", "build_catalog_runtime_audit", "allowed_skips_from_verified_outputs"]
