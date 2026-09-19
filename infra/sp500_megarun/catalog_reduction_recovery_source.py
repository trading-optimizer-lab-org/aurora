"""Fail-closed local validation for an immutable historical reduction source.

This module only validates a sealed source plan and its existing reduction
groups.  It does not authenticate GitHub, resolve external provenance, write
artifacts, evaluate science, or start workers.  The caller must authenticate
the source archive and its provenance externally (the parent recovery reader
is responsible for that) and pass the authenticated source bindings here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from pydantic import field_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    canonical_sha256,
    deep_freeze_json,
)
from aurora.infra.sp500_megarun.catalog_admission import (
    CatalogRunPlanV1,
    verify_catalog_plan_token,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_resume import (
    CatalogResumeIndexV1,
    CatalogResumeWorkManifestV1,
    load_resume_index,
)
from aurora.infra.sp500_megarun.catalog_sealed_plan import (
    verify_sealed_global_reuse_execution_plan,
)
from scripts.reduce_sp500_optimized_catalog_run import (
    _verify_group_reduction_inputs,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_BINDING_KEYS = frozenset(
    {
        "request_sha256",
        "decision_sha256",
        "protected_commit_sha",
        "authority_id",
        "campaign_id",
        "execution_plan_sha256",
    }
)


class ValidatedReductionRecoverySource(FrozenModel):
    """Immutable evidence that one historical reduction source is reusable."""

    resume_index: CatalogResumeIndexV1
    plan_receipt: Mapping[str, object]
    source_root_node_descriptor_sha256: str | None
    group_receipts: tuple[Mapping[str, object], ...]

    @field_validator("plan_receipt", mode="after")
    @classmethod
    def _freeze_plan_receipt(
        cls, value: Mapping[str, object]
    ) -> Mapping[str, object]:
        return cast(Mapping[str, object], deep_freeze_json(value))

    @field_validator("group_receipts", mode="after")
    @classmethod
    def _freeze_group_receipts(
        cls, value: tuple[Mapping[str, object], ...]
    ) -> tuple[Mapping[str, object], ...]:
        return tuple(
            cast(Mapping[str, object], deep_freeze_json(receipt))
            for receipt in value
        )

    @property
    def strategy_ids(self) -> tuple[str, ...]:
        """The exact strategy IDs covered by the validated group source."""

        return self.resume_index.strategy_ids

    @property
    def index_sha256(self) -> str:
        """Canonical hash of the validated resume index."""

        return self.resume_index.index_sha256

    @property
    def group_ids(self) -> tuple[int, ...]:
        """Reduction group IDs in the source plan's deterministic order."""

        group_ids: list[int] = []
        for receipt in self.group_receipts:
            group_id = receipt.get("reduction_group_id")
            if not isinstance(group_id, int):
                raise ValueError("CATALOG_RECOVERY_GROUP_RECEIPT_INVALID")
            group_ids.append(group_id)
        return tuple(group_ids)

    @property
    def work_manifest_sha256(self) -> str:
        """Work-manifest hash bound into the validated group receipts."""

        if not self.group_receipts:
            return ""
        return str(self.group_receipts[0]["work_manifest_sha256"])

    @property
    def plan_receipt_sha256(self) -> str:
        """Hash of the immutable source execution-plan receipt."""

        return str(self.plan_receipt["receipt_sha256"])

    @property
    def source_plan_receipt_sha256(self) -> str:
        """Compatibility name for callers describing the source receipt."""

        return self.plan_receipt_sha256

    @property
    def group_receipt_sha256s(self) -> tuple[str, ...]:
        """Hashes of the validated reduction-group receipts."""

        return tuple(str(receipt["receipt_sha256"]) for receipt in self.group_receipts)


def _read_json_object(path: Path, *, error_code: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(payload, dict):
        raise ValueError(error_code)
    return payload


def _require_sha256(value: object, *, error_code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(error_code)
    return value


def _validate_source_bindings(
    expected_bindings: Mapping[str, str],
) -> dict[str, str]:
    if not isinstance(expected_bindings, Mapping) or not expected_bindings:
        raise ValueError("CATALOG_RECOVERY_SOURCE_BINDINGS_INVALID")
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(value, str)
        or not value
        for key, value in expected_bindings.items()
    ):
        raise ValueError("CATALOG_RECOVERY_SOURCE_BINDINGS_INVALID")
    missing = _SOURCE_BINDING_KEYS.difference(expected_bindings)
    if missing:
        raise ValueError("CATALOG_RECOVERY_SOURCE_BINDINGS_INCOMPLETE")
    return {str(key): str(value) for key, value in expected_bindings.items()}


def _validate_expected_strategy_ids(
    expected_strategy_ids: Sequence[str],
) -> tuple[str, ...]:
    if isinstance(expected_strategy_ids, (str, bytes)):
        raise ValueError("CATALOG_RECOVERY_STRATEGY_SET_INVALID")
    try:
        strategy_ids = tuple(expected_strategy_ids)
    except TypeError as exc:
        raise ValueError("CATALOG_RECOVERY_STRATEGY_SET_INVALID") from exc
    if (
        not strategy_ids
        or any(not isinstance(strategy_id, str) or not strategy_id for strategy_id in strategy_ids)
        or len(set(strategy_ids)) != len(strategy_ids)
    ):
        raise ValueError("CATALOG_RECOVERY_STRATEGY_SET_INVALID")
    return strategy_ids


def _require_closed_boundary(
    payload: Mapping[str, object],
    *,
    error_code: str,
) -> None:
    if (
        payload.get("partial") is True
        or payload.get("validation_opened") is not False
        or payload.get("locked_opened") is not False
    ):
        raise ValueError(error_code)


def _validate_group_artifact_names(reduction_plan: Mapping[str, object]) -> None:
    groups = reduction_plan.get("groups")
    if not isinstance(groups, list):
        raise ValueError("CATALOG_RECOVERY_REDUCTION_PLAN_INVALID")
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("CATALOG_RECOVERY_REDUCTION_PLAN_INVALID")
        artifact = group.get("reduction_artifact")
        if not isinstance(artifact, str):
            raise ValueError("CATALOG_RECOVERY_GROUP_ARTIFACT_INVALID")
        relative = Path(artifact)
        if (
            not artifact
            or relative.is_absolute()
            or len(relative.parts) != 1
            or relative.name != artifact
            or artifact in {".", ".."}
        ):
            raise ValueError("CATALOG_RECOVERY_GROUP_ARTIFACT_INVALID")


def _validate_source_plan_bindings(
    plan_receipt: Mapping[str, object],
    reduction_plan: Mapping[str, object],
) -> None:
    for key in ("authority_id", "campaign_id", "science_sha256", "execution_plan_sha256"):
        value = plan_receipt.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError("CATALOG_RECOVERY_SOURCE_PLAN_BINDING_INVALID")
        if reduction_plan.get(key) != value:
            raise ValueError("CATALOG_RECOVERY_SOURCE_PLAN_BINDING_INVALID")
    _require_sha256(
        plan_receipt["science_sha256"],
        error_code="CATALOG_RECOVERY_SOURCE_PLAN_BINDING_INVALID",
    )
    _require_sha256(
        plan_receipt["execution_plan_sha256"],
        error_code="CATALOG_RECOVERY_SOURCE_PLAN_BINDING_INVALID",
    )


def _validate_work_manifest(
    sealed_plan: Path,
    *,
    run_plan: CatalogRunPlanV1,
    contract: RunOptimizationContractV1,
    expected_strategy_ids: tuple[str, ...],
) -> CatalogResumeWorkManifestV1:
    manifest_payload = _read_json_object(
        sealed_plan / "resume_work_manifest.json",
        error_code="CATALOG_RECOVERY_WORK_MANIFEST_INVALID",
    )
    try:
        work_manifest = CatalogResumeWorkManifestV1.model_validate(manifest_payload)
    except ValueError as exc:
        raise ValueError("CATALOG_RECOVERY_WORK_MANIFEST_INVALID") from exc
    if (
        work_manifest.schema_version != "1"
        or work_manifest.validation_opened is not False
        or work_manifest.locked_opened is not False
    ):
        raise ValueError("CATALOG_RECOVERY_WORK_MANIFEST_INVALID")
    manifest_identity = work_manifest.model_dump(
        mode="python", exclude={"manifest_sha256"}
    )
    if canonical_sha256(manifest_identity) != work_manifest.manifest_sha256:
        raise ValueError("CATALOG_RECOVERY_WORK_MANIFEST_HASH_INVALID")
    if (
        run_plan.work_manifest_sha256 != work_manifest.manifest_sha256
        or run_plan.contract_sha256 != contract.contract_sha256
        or run_plan.pending_recipe_count != len(work_manifest.pending_strategy_ids)
        or run_plan.cached_recipe_count != len(work_manifest.cached_strategy_ids)
        or run_plan.active_workers != work_manifest.active_workers
    ):
        raise ValueError("CATALOG_RECOVERY_WORK_MANIFEST_BINDING_INVALID")
    all_ids = work_manifest.all_strategy_ids
    cached_ids = work_manifest.cached_strategy_ids
    pending_ids = work_manifest.pending_strategy_ids
    if (
        not all_ids
        or len(set(all_ids)) != len(all_ids)
        or len(set(cached_ids)) != len(cached_ids)
        or len(set(pending_ids)) != len(pending_ids)
        or set(cached_ids).intersection(pending_ids)
        or set(cached_ids).union(pending_ids) != set(all_ids)
        or set(pending_ids) != set(expected_strategy_ids)
        or len(pending_ids) != len(expected_strategy_ids)
    ):
        raise ValueError("CATALOG_RECOVERY_STRATEGY_COVERAGE_INVALID")
    return work_manifest


def _validate_result_boundaries(index: CatalogResumeIndexV1) -> None:
    if (
        index.validation_opened is not False
        or index.locked_opened is not False
        or index.duplicate_result_count != 0
    ):
        raise ValueError("CATALOG_RECOVERY_RESULT_BOUNDARY_INVALID")
    for item in index.results:
        try:
            result = json.loads(item.result_json)
        except ValueError as exc:
            raise ValueError("CATALOG_RECOVERY_RESULT_INVALID") from exc
        if not isinstance(result, dict):
            raise ValueError("CATALOG_RECOVERY_RESULT_INVALID")
        if result.get("partial") is True:
            raise ValueError("CATALOG_RECOVERY_RESULT_PARTIAL")
        info = result.get("info")
        if not isinstance(info, dict):
            raise ValueError("CATALOG_RECOVERY_RESULT_INVALID")
        _require_closed_boundary(
            info,
            error_code="CATALOG_RECOVERY_RESULT_BOUNDARY_INVALID",
        )


def verify_reduction_recovery_source(
    sealed_plan: Path,
    group_root: Path,
    expected_bindings: Mapping[str, str],
    expected_science_identity_sha256: str,
    expected_catalog_manifest_sha256: str,
    expected_strategy_ids: Sequence[str],
) -> ValidatedReductionRecoverySource:
    """Validate an authenticated historical source before existing reduction.

    The caller must authenticate the source archive and GitHub provenance
    externally before passing ``expected_bindings``.  This function does not
    authenticate GitHub or any other external service; it only verifies the
    local sealed plan, its exact group inputs, and their historical results.
    It is read-only, does not evaluate science, does not start workers, and
    does not rewrite pending or cached counts.  A parent recovery workflow may
    use the returned evidence to construct a separate recovery envelope.
    ``expected_strategy_ids`` is the exact historical group coverage expected
    from this source (the sealed work manifest's pending IDs); cached IDs stay
    bound to the sealed source plan and are never rewritten here.
    """

    expected_science = _require_sha256(
        expected_science_identity_sha256,
        error_code="CATALOG_RECOVERY_SCIENCE_IDENTITY_INVALID",
    )
    expected_catalog = _require_sha256(
        expected_catalog_manifest_sha256,
        error_code="CATALOG_RECOVERY_CATALOG_MANIFEST_INVALID",
    )
    expected_ids = _validate_expected_strategy_ids(expected_strategy_ids)
    bindings = _validate_source_bindings(expected_bindings)

    source_root = Path(sealed_plan)
    groups_root = Path(group_root)
    plan_receipt_raw = verify_sealed_global_reuse_execution_plan(
        source_root,
        expected_bindings=bindings,
    )
    if not isinstance(plan_receipt_raw, dict):
        raise ValueError("CATALOG_RECOVERY_SOURCE_PLAN_RECEIPT_INVALID")
    _require_closed_boundary(
        plan_receipt_raw,
        error_code="CATALOG_RECOVERY_SOURCE_PLAN_BOUNDARY_INVALID",
    )
    plan_receipt_sha256 = plan_receipt_raw.get("receipt_sha256")
    if (
        not isinstance(plan_receipt_sha256, str)
        or _SHA256_RE.fullmatch(plan_receipt_sha256) is None
    ):
        raise ValueError("CATALOG_RECOVERY_SOURCE_PLAN_RECEIPT_INVALID")

    contract_payload = _read_json_object(
        source_root / "resolved_contract.json",
        error_code="CATALOG_RECOVERY_SOURCE_CONTRACT_INVALID",
    )
    try:
        contract = RunOptimizationContractV1.model_validate(contract_payload)
    except ValueError as exc:
        raise ValueError("CATALOG_RECOVERY_SOURCE_CONTRACT_INVALID") from exc
    if (
        canonical_sha256(contract.science) != expected_science
        or contract.science.catalog_manifest_sha256 != expected_catalog
        or contract.science.validation_opened is not False
        or contract.science.locked_opened is not False
    ):
        raise ValueError("CATALOG_RECOVERY_SOURCE_SCIENCE_BINDING_INVALID")

    admission_token = plan_receipt_raw.get("admission_token_sha256")
    if not isinstance(admission_token, str) or not admission_token:
        raise ValueError("CATALOG_RECOVERY_SOURCE_ADMISSION_TOKEN_INVALID")
    run_plan = verify_catalog_plan_token(
        source_root / "run_plan.json",
        admission_token_sha256=admission_token,
    )
    if run_plan.schema_version != "1":
        raise ValueError("CATALOG_RECOVERY_RUN_PLAN_INVALID")

    work_manifest = _validate_work_manifest(
        source_root,
        run_plan=run_plan,
        contract=contract,
        expected_strategy_ids=expected_ids,
    )

    reduction_plan = _read_json_object(
        source_root / "reduction_plan.json",
        error_code="CATALOG_RECOVERY_REDUCTION_PLAN_INVALID",
    )
    _validate_group_artifact_names(reduction_plan)
    _validate_source_plan_bindings(plan_receipt_raw, reduction_plan)

    group_receipts_raw, root_node_hash = _verify_group_reduction_inputs(
        groups_root,
        reduction_plan_path=source_root / "reduction_plan.json",
        pending_recipe_count=run_plan.pending_recipe_count,
        expected_science_identity_sha256=expected_science,
        expected_catalog_manifest_sha256=expected_catalog,
        expected_work_manifest_sha256=work_manifest.manifest_sha256,
    )
    for receipt in group_receipts_raw:
        _require_closed_boundary(
            receipt,
            error_code="CATALOG_RECOVERY_GROUP_BOUNDARY_INVALID",
        )
        if not isinstance(receipt.get("receipt_sha256"), str):
            raise ValueError("CATALOG_RECOVERY_GROUP_RECEIPT_INVALID")

    groups = reduction_plan.get("groups")
    if not isinstance(groups, list):  # pragma: no cover - checked above
        raise ValueError("CATALOG_RECOVERY_REDUCTION_PLAN_INVALID")
    for group in groups:
        assert isinstance(group, dict)  # validated by _validate_group_artifact_names
        artifact = str(group["reduction_artifact"])
        manifest = _read_json_object(
            groups_root / artifact / "reduction_group_manifest.json",
            error_code="CATALOG_RECOVERY_GROUP_MANIFEST_INVALID",
        )
        _require_closed_boundary(
            manifest,
            error_code="CATALOG_RECOVERY_GROUP_BOUNDARY_INVALID",
        )

    resume_index = load_resume_index(
        (groups_root,),
        expected_science_identity_sha256=expected_science,
        expected_catalog_manifest_sha256=expected_catalog,
    )
    if (
        resume_index.physical_result_count != len(expected_ids)
        or len(resume_index.strategy_ids) != len(expected_ids)
        or set(resume_index.strategy_ids) != set(expected_ids)
    ):
        raise ValueError("CATALOG_RECOVERY_STRATEGY_COVERAGE_INVALID")
    _validate_result_boundaries(resume_index)

    return ValidatedReductionRecoverySource(
        resume_index=resume_index,
        plan_receipt=plan_receipt_raw,
        source_root_node_descriptor_sha256=root_node_hash,
        group_receipts=tuple(group_receipts_raw),
    )


__all__ = [
    "ValidatedReductionRecoverySource",
    "verify_reduction_recovery_source",
]
