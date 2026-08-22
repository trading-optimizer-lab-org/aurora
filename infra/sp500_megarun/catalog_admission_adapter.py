"""Pure adapters between bounded controller artifacts and admission evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from aurora.infra.github_performance.contracts import (
    CapacityProfile,
    FrozenModel,
    Sha256,
    canonical_sha256,
)
from aurora.infra.github_performance.merge_planner import MergeResourceProjectionV1
from aurora.infra.sp500_megarun.catalog_capacity_qualification import (
    BundleLayoutQualificationV1,
)
from aurora.infra.sp500_megarun.catalog_controller import (
    CatalogCapacityAdmissionEvidenceV1,
    CatalogGithubControlsEvidenceV1,
)
from aurora.infra.sp500_megarun.catalog_github_controls import (
    AuditorCatalogGithubControlsReceiptV1,
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_CANDIDATE_FILES = 10_000
_MAX_CANDIDATE_BYTES = 1_000_000_000
_MAX_QUALIFICATION_AGE = timedelta(days=7)
_MAX_FUTURE_SKEW = timedelta(seconds=30)
_EXPECTED_LAYOUT_COUNTS = (8, 16, 32, 64, 96, 128)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_ADMISSION_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_ADMISSION_NONFINITE_JSON:{value}")


def _strict_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )


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


class CatalogOperationalQualificationV1(FrozenModel):
    """Promoted operational evidence; blocked until real receipts are checked in."""

    schema_version: Literal["1"] = "1"
    status: Literal["ready", "blocked"]
    reason_codes: tuple[str, ...]
    qualified_at: datetime | None
    qualification_receipt_sha256: Sha256 | None
    qualification_run_ids: tuple[str, ...]
    bundle_layout_qualifications: tuple[BundleLayoutQualificationV1, ...]
    reduction_projection: MergeResourceProjectionV1 | None
    hierarchical_reduction_projection: MergeResourceProjectionV1 | None
    topology_sample_count: Annotated[int, Field(ge=0)]
    memory_fraction_p50: float | None = Field(default=None, ge=0)
    memory_fraction_p95: float | None = Field(default=None, ge=0)
    memory_fraction_p99: float | None = Field(default=None, ge=0)
    disk_fraction_p50: float | None = Field(default=None, ge=0)
    disk_fraction_p95: float | None = Field(default=None, ge=0)
    disk_fraction_p99: float | None = Field(default=None, ge=0)
    runner_start_seconds_p50: float | None = Field(default=None, ge=0)
    runner_start_seconds_p95: float | None = Field(default=None, ge=0)
    runner_start_seconds_p99: float | None = Field(default=None, ge=0)
    unit_seconds_p50: float | None = Field(default=None, ge=0)
    unit_seconds_p95: float | None = Field(default=None, ge=0)
    unit_seconds_p99: float | None = Field(default=None, ge=0)
    projected_artifact_storage_bytes: int | None = Field(default=None, ge=0)
    projected_cache_storage_bytes: int | None = Field(default=None, ge=0)
    planned_new_cache_entry_count: int | None = Field(default=None, ge=0)
    selected_component_bundle_count: int | None = Field(default=None, ge=0, le=128)
    planned_cache_upload_requests_per_minute_peak: int | None = Field(
        default=None, ge=0
    )
    planned_cache_download_requests_per_minute_peak: int | None = Field(
        default=None, ge=0
    )
    artifact_transport_retention_days: Literal[1] | None

    @field_validator("qualified_at")
    @classmethod
    def _normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_TIME_INVALID")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_closed_shape(self) -> "CatalogOperationalQualificationV1":
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_REASON_DUPLICATE")
        if len(set(self.qualification_run_ids)) != len(self.qualification_run_ids):
            raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_RUN_DUPLICATE")
        optional_values = (
            self.qualified_at,
            self.qualification_receipt_sha256,
            self.reduction_projection,
            self.hierarchical_reduction_projection,
            self.memory_fraction_p50,
            self.memory_fraction_p95,
            self.memory_fraction_p99,
            self.disk_fraction_p50,
            self.disk_fraction_p95,
            self.disk_fraction_p99,
            self.runner_start_seconds_p50,
            self.runner_start_seconds_p95,
            self.runner_start_seconds_p99,
            self.unit_seconds_p50,
            self.unit_seconds_p95,
            self.unit_seconds_p99,
            self.projected_artifact_storage_bytes,
            self.projected_cache_storage_bytes,
            self.planned_new_cache_entry_count,
            self.selected_component_bundle_count,
            self.planned_cache_upload_requests_per_minute_peak,
            self.planned_cache_download_requests_per_minute_peak,
            self.artifact_transport_retention_days,
        )
        if self.status == "blocked":
            if not self.reason_codes:
                raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_REASON_REQUIRED")
            if (
                any(value is not None for value in optional_values)
                or self.qualification_run_ids
                or self.bundle_layout_qualifications
                or self.topology_sample_count != 0
            ):
                raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_BLOCKED_SHAPE")
            return self
        if self.reason_codes or any(value is None for value in optional_values):
            raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_READY_SHAPE")
        if len(self.qualification_run_ids) < 3 or self.topology_sample_count < 3:
            raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_SAMPLES_MISSING")
        counts = tuple(item.bundle_count for item in self.bundle_layout_qualifications)
        if counts != _EXPECTED_LAYOUT_COUNTS or any(
            item.sample_count < 3
            or not item.equivalent
            or not item.memory_safe
            or not item.disk_safe
            or not item.runner_timeout_safe
            for item in self.bundle_layout_qualifications
        ):
            raise ValueError("CATALOG_OPERATIONAL_LAYOUT_QUALIFICATION_INVALID")
        triples = (
            (self.memory_fraction_p50, self.memory_fraction_p95, self.memory_fraction_p99),
            (self.disk_fraction_p50, self.disk_fraction_p95, self.disk_fraction_p99),
            (
                self.runner_start_seconds_p50,
                self.runner_start_seconds_p95,
                self.runner_start_seconds_p99,
            ),
            (self.unit_seconds_p50, self.unit_seconds_p95, self.unit_seconds_p99),
        )
        if any(tuple(sorted(triple)) != triple for triple in triples):
            raise ValueError("CATALOG_OPERATIONAL_DISTRIBUTION_INVALID")
        return self


def load_catalog_operational_qualification(
    path: Path,
) -> CatalogOperationalQualificationV1:
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_PATH_INVALID")
        return CatalogOperationalQualificationV1.model_validate(_strict_json(path))
    except Exception as exc:
        raise ValueError(f"CATALOG_OPERATIONAL_QUALIFICATION_INVALID:{exc}") from None


def verify_admission_candidate_bundle(
    root: Path,
    *,
    expected_sha256: str,
) -> Mapping[str, Any]:
    """Verify exact candidate bytes and reject extra, missing, or linked files."""

    if not _SHA256.fullmatch(expected_sha256) or root.is_symlink():
        raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
    manifest_path = resolved / "candidate-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
    manifest = _strict_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
    required = {
        "schema_version",
        "document_type",
        "request_sha256",
        "campaign_id",
        "applicable_commit_sha",
        "execution_protocol_sha256",
        "content_manifest",
        "candidate_manifest_sha256",
    }
    if set(manifest) != required:
        raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
    identity = {key: value for key, value in manifest.items() if key != "candidate_manifest_sha256"}
    if (
        manifest.get("schema_version") != "1"
        or manifest.get("document_type")
        != "catalog_admission_candidate_manifest_v1"
        or manifest.get("candidate_manifest_sha256") != expected_sha256
        or canonical_sha256(identity) != expected_sha256
    ):
        raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
    rows = manifest.get("content_manifest")
    if not isinstance(rows, list | tuple) or not rows or len(rows) > _MAX_CANDIDATE_FILES:
        raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
    expected_paths: set[str] = set()
    total = 0
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) != {"path", "sha256", "size_bytes"}:
            raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
        relative_value = raw.get("path")
        digest = raw.get("sha256")
        size = raw.get("size_bytes")
        if not isinstance(relative_value, str):
            raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
        relative = PurePosixPath(relative_value)
        if (
            relative.is_absolute()
            or relative.as_posix() != relative_value
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative_value in expected_paths
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise ValueError("CATALOG_CANDIDATE_MANIFEST_INVALID")
        target = resolved.joinpath(*relative.parts)
        if (
            target.is_symlink()
            or not target.is_file()
            or not target.resolve(strict=True).is_relative_to(resolved)
            or target.stat().st_size != size
            or hashlib.sha256(target.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("CATALOG_CANDIDATE_CONTENT_INVALID")
        expected_paths.add(relative_value)
        total += size
        if total > _MAX_CANDIDATE_BYTES:
            raise ValueError("CATALOG_CANDIDATE_BUNDLE_TOO_LARGE")
    actual_paths: set[str] = set()
    for path in resolved.rglob("*"):
        if path.is_symlink():
            raise ValueError("CATALOG_CANDIDATE_SYMLINK_FORBIDDEN")
        if path.is_file() and path != manifest_path:
            actual_paths.add(path.relative_to(resolved).as_posix())
    if actual_paths != expected_paths:
        raise ValueError("CATALOG_CANDIDATE_MANIFEST_COVERAGE_INVALID")
    return dict(manifest)


def github_controls_evidence_from_auditor_receipt(
    receipt: AuditorCatalogGithubControlsReceiptV1,
    *,
    expected_audit_context_sha256: str,
    expected_protected_commit_sha: str,
) -> CatalogGithubControlsEvidenceV1:
    receipt = AuditorCatalogGithubControlsReceiptV1.model_validate(
        receipt.model_dump(mode="json")
    )
    if receipt.audit_context_sha256 != expected_audit_context_sha256:
        raise ValueError("CATALOG_AUDIT_CONTEXT_MISMATCH")
    if (
        receipt.protected_commit_sha != expected_protected_commit_sha
        or receipt.observed_default_branch_sha != expected_protected_commit_sha
    ):
        raise ValueError("CATALOG_AUDIT_PROTECTED_COMMIT_MISMATCH")
    if (
        receipt.audit_use_context != "controller_admission"
        or receipt.caller_workflow != ".github/workflows/catalog-run-controller.yml"
        or receipt.caller_job != "live_controls_audit_before_reserve"
    ):
        raise ValueError("CATALOG_AUDIT_CALLER_MISMATCH")
    if receipt.status != "ready":
        raise ValueError("CATALOG_GITHUB_CONTROLS_BLOCKED")
    budget_skus = {
        row.get("budget_product_sku")
        for row in receipt.actions_zero_spend_budgets
        if row.get("budget_amount") == 0
    }
    expected_budgets = {"actions", "actions_storage", "actions_cache_storage"}
    billing = receipt.actions_billing_usage_snapshot
    zero_paid = (
        billing.get("paid_runner_minutes") == 0
        and billing.get("estimated_paid_actions_cost") == 0
    )
    content = {
        "receipt_sha256": receipt.receipt_sha256,
        "audit_context_sha256": receipt.audit_context_sha256,
        "protected_commit_sha": receipt.protected_commit_sha,
        "budget_skus": tuple(sorted(budget_skus)),
    }
    return CatalogGithubControlsEvidenceV1(
        status="ready",
        observed_at=receipt.github_api_observed_at,
        source_sha256=receipt.source_snapshot_sha256,
        content_sha256=_sha256(content),
        receipt_sha256=receipt.receipt_sha256,
        controls_verified=True,
        production_environment_verified=True,
        admin_credential_exposed=False,
        requester_credential_exposed=False,
        auditor_credential_exposed=False,
        standard_free_runner_only=zero_paid,
        paid_runner_minutes=int(billing.get("paid_runner_minutes", 1)),
        estimated_paid_actions_cost=int(
            billing.get("estimated_paid_actions_cost", 1)
        ),
        zero_actions_spend_budget_verified=budget_skus == expected_budgets,
        zero_actions_storage_budget_verified=budget_skus == expected_budgets,
        zero_cache_storage_budget_verified=budget_skus == expected_budgets,
        cache_limit_gb=receipt.repository_cache_storage_limit_gb or 0,
        cache_retention_days=receipt.repository_cache_retention_days or 0,
        validation_opened=False,
        locked_opened=False,
    )


def _blocked_capacity(
    *,
    profile: CapacityProfile,
    observed_at: datetime,
) -> CatalogCapacityAdmissionEvidenceV1:
    content = {
        "profile": profile.model_dump(mode="json"),
        "reason": "CATALOG_CAPACITY_UNPROVEN",
    }
    receipt_sha256 = _sha256(content)
    return CatalogCapacityAdmissionEvidenceV1(
        status="blocked",
        observed_at=observed_at,
        source_sha256=canonical_sha256(profile),
        content_sha256=receipt_sha256,
        receipt_sha256=receipt_sha256,
        reason_codes=("CATALOG_CAPACITY_UNPROVEN",),
        capacity_known=False,
        temporarily_unavailable=False,
        compatible_qualified_ceiling=profile.standard_concurrency_ceiling,
        current_safe_free_capacity=0,
        selected_workers=0,
        standard_runner_only=True,
        paid_runner_minutes=0,
        estimated_paid_actions_cost=0,
        artifact_storage_headroom_proven=False,
        cache_storage_headroom_proven=False,
        resource_margin_verified=False,
        compatible_safe_floor_used=False,
        retry_not_before=None,
        capacity_receipt_sha256=receipt_sha256,
    )


def select_catalog_capacity_evidence(
    *,
    profile: CapacityProfile,
    qualification: CatalogOperationalQualificationV1,
    controls_receipt: AuditorCatalogGithubControlsReceiptV1,
    registered_maximum_workers: int,
    observed_at: datetime,
) -> CatalogCapacityAdmissionEvidenceV1:
    """Use a promoted safe floor; never infer live account capacity."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("CATALOG_CAPACITY_TIME_INVALID")
    now = observed_at.astimezone(UTC)
    if (
        not profile.production_admission_enabled
        or profile.proven_uncontended_floor is None
        or profile.qualification_receipt_sha256 is None
        or qualification.status != "ready"
    ):
        return _blocked_capacity(profile=profile, observed_at=now)
    if (
        qualification.qualified_at is None
        or qualification.qualification_receipt_sha256
        != profile.qualification_receipt_sha256
        or qualification.qualification_run_ids != profile.qualification_run_ids
        or now - qualification.qualified_at > _MAX_QUALIFICATION_AGE
        or now - qualification.qualified_at < -_MAX_FUTURE_SKEW
    ):
        return _blocked_capacity(profile=profile, observed_at=now)
    controls_receipt = AuditorCatalogGithubControlsReceiptV1.model_validate(
        controls_receipt.model_dump(mode="json")
    )
    projected_artifact = qualification.projected_artifact_storage_bytes
    projected_cache = qualification.projected_cache_storage_bytes
    if (
        controls_receipt.status != "ready"
        or projected_artifact is None
        or projected_cache is None
        or controls_receipt.projected_campaign_artifact_bytes is None
        or controls_receipt.projected_campaign_cache_bytes is None
        or projected_artifact > controls_receipt.projected_campaign_artifact_bytes
        or projected_cache > controls_receipt.projected_campaign_cache_bytes
        or controls_receipt.free_artifact_storage_headroom is None
        or controls_receipt.free_cache_storage_headroom is None
    ):
        return _blocked_capacity(profile=profile, observed_at=now)
    values = (
        qualification.memory_fraction_p99,
        qualification.disk_fraction_p99,
    )
    resource_margin = all(value is not None and value <= 0.70 for value in values)
    if not resource_margin:
        return _blocked_capacity(profile=profile, observed_at=now)
    ceiling = profile.standard_concurrency_ceiling
    safe_floor = profile.proven_uncontended_floor
    selected = min(registered_maximum_workers, ceiling, safe_floor)
    temporarily_unavailable = bool(controls_receipt.active_heavy_run_inventory)
    content = {
        "profile": profile.model_dump(mode="json"),
        "qualification": qualification.model_dump(mode="json"),
        "controls_receipt_sha256": controls_receipt.receipt_sha256,
        "registered_maximum_workers": registered_maximum_workers,
        "selected_workers": 0 if temporarily_unavailable else selected,
    }
    receipt_sha256 = _sha256(content)
    return CatalogCapacityAdmissionEvidenceV1(
        status="ready",
        observed_at=controls_receipt.github_api_observed_at,
        source_sha256=qualification.qualification_receipt_sha256 or "0" * 64,
        content_sha256=receipt_sha256,
        receipt_sha256=receipt_sha256,
        capacity_known=True,
        temporarily_unavailable=temporarily_unavailable,
        compatible_qualified_ceiling=ceiling,
        current_safe_free_capacity=safe_floor,
        selected_workers=0 if temporarily_unavailable else selected,
        standard_runner_only=True,
        paid_runner_minutes=0,
        estimated_paid_actions_cost=0,
        artifact_storage_headroom_proven=True,
        cache_storage_headroom_proven=True,
        resource_margin_verified=True,
        compatible_safe_floor_used=True,
        retry_not_before=(now + timedelta(minutes=5) if temporarily_unavailable else None),
        capacity_receipt_sha256=receipt_sha256,
    )


__all__ = [
    "CatalogOperationalQualificationV1",
    "github_controls_evidence_from_auditor_receipt",
    "load_catalog_operational_qualification",
    "select_catalog_capacity_evidence",
    "verify_admission_candidate_bundle",
]
