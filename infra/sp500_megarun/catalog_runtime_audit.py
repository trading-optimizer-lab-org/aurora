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
    for job in jobs:
        labels = job.get("labels")
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


__all__ = ["CatalogRuntimeAuditV1", "build_catalog_runtime_audit"]
