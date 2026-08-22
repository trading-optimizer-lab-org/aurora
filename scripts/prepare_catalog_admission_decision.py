#!/usr/bin/env python3
"""Consume bounded candidates plus one fresh audit and seal one decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import (  # noqa: E402
    CapacityProfile,
    canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_admission import (  # noqa: E402
    CatalogAdmissionEvidenceV1,
    build_catalog_run_plan,
)
from aurora.infra.sp500_megarun.catalog_admission_adapter import (  # noqa: E402
    CatalogOperationalQualificationV1,
    github_controls_evidence_from_auditor_receipt,
    select_catalog_capacity_evidence,
    verify_admission_candidate_bundle,
)
from aurora.infra.sp500_megarun.catalog_authority_ledger import (  # noqa: E402
    select_campaign_authority,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (  # noqa: E402
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_controller import (  # noqa: E402
    CatalogCapacityAdmissionEvidenceV1,
    CatalogControllerDecisionV1,
    CatalogProtectedHeadEvidenceV1,
    CatalogScienceAdmissionEvidenceV1,
    CatalogSourceArtifactsEvidenceV1,
    ControllerOutcome,
    catalog_authority_id,
    catalog_execution_plan_sha256,
)
from aurora.infra.sp500_megarun.catalog_github_controls import (  # noqa: E402
    AuditorCatalogGithubControlsReceiptV1,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (  # noqa: E402
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (  # noqa: E402
    canonical_model_bytes,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store import (  # noqa: E402
    RebuildableStoreInventoryV1,
)
from aurora.infra.sp500_megarun.catalog_resume import (  # noqa: E402
    build_resume_work_manifest,
)
from aurora.infra.sp500_megarun.catalog_routing import (  # noqa: E402
    CatalogRoutingCommandV1,
)
from aurora.infra.sp500_megarun.catalog_run_request import (  # noqa: E402
    parse_catalog_run_request,
)
from scripts.compile_sp500_catalog_recipes import (  # noqa: E402
    verify_recipe_dag_artifacts,
)
from scripts.plan_sp500_optimized_catalog_run import (  # noqa: E402
    CatalogComponentRequirementV1,
    CatalogRecipeRequirementV1,
    build_global_reuse_execution_plan,
    write_sealed_global_reuse_execution_plan,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_OUTPUT = re.compile(
    r"^(?:true|false|[0-9a-f]{40}|[0-9a-f]{64}|"
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|"
    r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*)$"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seal one fixed catalog admission decision."
    )
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--routing-snapshot-dir", type=Path, required=True)
    parser.add_argument("--controls-receipt", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    return parser


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


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _document_payload(path: Path, expected_type: str) -> Mapping[str, Any]:
    document = _mapping(_strict_json(path), "CATALOG_CANDIDATE_DOCUMENT_INVALID")
    identity = {
        key: value for key, value in document.items() if key != "content_sha256"
    }
    if (
        document.get("schema_version") != "1"
        or document.get("document_type") != expected_type
        or document.get("content_sha256") != canonical_sha256(identity)
    ):
        raise ValueError("CATALOG_CANDIDATE_DOCUMENT_INVALID")
    return _mapping(document.get("payload"), "CATALOG_CANDIDATE_DOCUMENT_INVALID")


def _safe_repo_file(root: Path, relative: str) -> Path:
    path = root.joinpath(*relative.split("/"))
    if path.is_symlink():
        raise ValueError("CATALOG_ADMISSION_REPOSITORY_SYMLINK_FORBIDDEN")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("CATALOG_ADMISSION_REPOSITORY_PATH_INVALID")
    return resolved


def _bounded_temp_path(path: Path, runner_temp: Path, *, directory: bool) -> Path:
    if path.is_symlink():
        raise ValueError("CATALOG_ADMISSION_PATH_INVALID")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(runner_temp) or (
        directory and not resolved.is_dir()
    ) or (not directory and not resolved.is_file()):
        raise ValueError("CATALOG_ADMISSION_PATH_INVALID")
    return resolved


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_model_bytes(value) + b"\n")


def build_operational_plan(
    *,
    capacity: CatalogCapacityAdmissionEvidenceV1,
    candidate_manifest_sha256: str,
    execution_protocol_sha256: str,
    contract_sha256: str,
    runtime_identity_sha256: str,
    source_artifact_plan_sha256: str,
    store_metadata_sha256: str,
    recipe_dag_manifest_sha256: str,
    operational_qualification_sha256: str,
    logical_recipe_count: int,
    unique_component_count: int,
    component_workers: int,
) -> dict[str, object]:
    hashes = (
        candidate_manifest_sha256,
        execution_protocol_sha256,
        contract_sha256,
        runtime_identity_sha256,
        source_artifact_plan_sha256,
        store_metadata_sha256,
        recipe_dag_manifest_sha256,
        operational_qualification_sha256,
        capacity.capacity_receipt_sha256,
    )
    if any(not _SHA256.fullmatch(value) for value in hashes):
        raise ValueError("CATALOG_OPERATIONAL_PLAN_HASH_INVALID")
    if (
        logical_recipe_count < 1
        or unique_component_count < 1
        or component_workers < 0
        or component_workers > 120
    ):
        raise ValueError("CATALOG_OPERATIONAL_PLAN_COUNT_INVALID")
    return {
        "schema_version": "1",
        "planner": "catalog-global-reuse-v1",
        "workers": capacity.selected_workers,
        "component_workers": component_workers,
        "logical_recipe_count": logical_recipe_count,
        "unique_component_count": unique_component_count,
        "candidate_manifest_sha256": candidate_manifest_sha256,
        "execution_protocol_sha256": execution_protocol_sha256,
        "contract_sha256": contract_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
        "source_artifact_plan_sha256": source_artifact_plan_sha256,
        "store_metadata_sha256": store_metadata_sha256,
        "recipe_dag_manifest_sha256": recipe_dag_manifest_sha256,
        "operational_qualification_sha256": operational_qualification_sha256,
        "capacity_receipt_sha256": capacity.capacity_receipt_sha256,
        "retry_only_unfinished": True,
        "global_component_deduplication": True,
        "validation_opened": False,
        "locked_opened": False,
    }


def _load_context(candidate_dir: Path) -> Mapping[str, Any]:
    context = _mapping(
        _strict_json(candidate_dir / "candidate-context.json"),
        "CATALOG_CANDIDATE_CONTEXT_INVALID",
    )
    identity = {key: value for key, value in context.items() if key != "content_sha256"}
    if context.get("content_sha256") != canonical_sha256(identity):
        raise ValueError("CATALOG_CANDIDATE_CONTEXT_INVALID")
    return context


def _load_candidate_inputs(
    candidate_dir: Path,
) -> tuple[
    RunOptimizationContractV1,
    tuple[CatalogComponentRequirementV1, ...],
    tuple[CatalogRecipeRequirementV1, ...],
    RebuildableStoreInventoryV1,
    CatalogScienceAdmissionEvidenceV1,
    CatalogSourceArtifactsEvidenceV1,
    CatalogOperationalQualificationV1,
]:
    contract = RunOptimizationContractV1.model_validate(
        _strict_json(candidate_dir / "resolved-contract.json")
    )
    component_payload = _document_payload(
        candidate_dir / "component-requirements.json",
        "catalog_component_requirements_v1",
    )
    recipe_payload = _document_payload(
        candidate_dir / "recipe-requirements.json",
        "catalog_recipe_requirements_v1",
    )
    store_payload = _document_payload(
        candidate_dir / "store-inventory.json",
        "catalog_rebuildable_store_inventory_v1",
    )
    source_payload = _document_payload(
        candidate_dir / "source-artifacts.json",
        "catalog_source_artifacts_v1",
    )
    components_raw = component_payload.get("items")
    recipes_raw = recipe_payload.get("items")
    if not isinstance(components_raw, list) or not isinstance(recipes_raw, list):
        raise ValueError("CATALOG_CANDIDATE_WORKLOAD_INVALID")
    if component_payload.get("count") != len(components_raw) or recipe_payload.get(
        "count"
    ) != len(recipes_raw):
        raise ValueError("CATALOG_CANDIDATE_WORKLOAD_INVALID")
    components = tuple(
        CatalogComponentRequirementV1.model_validate(item)
        for item in components_raw
    )
    recipes = tuple(
        CatalogRecipeRequirementV1.model_validate(item) for item in recipes_raw
    )
    inventory = RebuildableStoreInventoryV1.model_validate(
        store_payload.get("inventory")
    )
    science = CatalogScienceAdmissionEvidenceV1.model_validate(
        _strict_json(candidate_dir / "science-evidence.json")
    )
    source = CatalogSourceArtifactsEvidenceV1.model_validate(
        source_payload.get("evidence")
    )
    qualification = CatalogOperationalQualificationV1.model_validate(
        _strict_json(candidate_dir / "operational-qualification.json")
    )
    return contract, components, recipes, inventory, science, source, qualification


def _contract_for_capacity(
    contract: RunOptimizationContractV1,
    capacity: CatalogCapacityAdmissionEvidenceV1,
) -> RunOptimizationContractV1:
    if capacity.selected_workers < 1:
        return contract
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "workers": capacity.selected_workers,
        "component_workers": min(
            int(payload["execution"]["component_workers"]),
            capacity.selected_workers,
            120,
        ),
    }
    return RunOptimizationContractV1.model_validate(payload)


def _run_controller(
    *,
    repo_root: Path,
    routing_dir: Path,
    evidence_paths: Mapping[str, Path],
    output_dir: Path,
    github_output: Path,
) -> CatalogControllerDecisionV1:
    command = [
        sys.executable,
        str(repo_root / "scripts/control_catalog_run.py"),
        "--event",
        str(routing_dir / "event.json"),
        "--authority-issue",
        str(routing_dir / "authority-issue.json"),
        "--authority-comments",
        str(routing_dir / "authority-comments.json"),
        "--request-queue",
        str(routing_dir / "request-queue.json"),
        "--protected-head",
        str(routing_dir / "protected-head.json"),
        "--github-controls",
        str(evidence_paths["github_controls"]),
        "--capacity",
        str(evidence_paths["capacity"]),
        "--admission-evidence",
        str(evidence_paths["admission"]),
        "--authority-anchor",
        "config/catalog_authority_anchor_v1.json",
        "--registry",
        "config/catalog_campaign_registry_v1.json",
        "--actors",
        "config/catalog_controller_actors_v1.json",
        "--policy",
        "config/catalog_run_prompt_policy_v1.json",
        "--repo-root",
        str(repo_root),
        "--output-dir",
        str(output_dir),
        "--github-output",
        str(github_output),
    ]
    result = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_CONTROLLER_DECISION_ADAPTER_FAILED")
    return CatalogControllerDecisionV1.model_validate(
        _strict_json(output_dir / "decision.json")
    )


def _append_outputs(
    path: Path | None,
    *,
    decision: CatalogControllerDecisionV1,
    sealed_plan_ready: bool,
    request_issue_number: int,
) -> None:
    if path is None:
        return
    values: dict[str, str] = {
        "call_engine": str(decision.should_schedule_compute).lower(),
        "sealed_plan_ready": str(sealed_plan_ready).lower(),
        "outcome": decision.outcome.value,
        "reason_code": decision.reason_code,
        "decision_sha256": decision.decision_sha256,
        "request_sha256": decision.request_sha256,
        "request_issue_number": str(request_issue_number),
    }
    if decision.retry_not_before is not None:
        values["retry_not_before"] = decision.retry_not_before.isoformat().replace(
            "+00:00", "Z"
        )
    if decision.should_schedule_compute and decision.sealed_inputs is not None:
        sealed = decision.sealed_inputs
        values.update(
            {
                "authority_id": str(sealed.authority_id),
                "campaign_id": sealed.campaign_id,
                "science_sha256": sealed.science_sha256,
                "execution_plan_sha256": sealed.execution_plan_sha256,
                "execution_protocol_sha256": sealed.execution_protocol_sha256,
                "protected_commit_sha": sealed.protected_commit_sha,
                "controls_commit_sha": (
                    sealed.github_controls_commit_sha
                    or sealed.protected_commit_sha
                ),
            }
        )
    if any(not _SAFE_OUTPUT.fullmatch(value) for value in values.values()):
        raise ValueError("CATALOG_ADMISSION_GITHUB_OUTPUT_INVALID")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in sorted(values.items()):
            stream.write(f"{key}={value}\n")


def prepare(
    *,
    candidate_dir: Path,
    routing_snapshot_dir: Path,
    controls_receipt_path: Path,
    repo_root: Path,
    output_dir: Path,
    github_output: Path | None,
) -> CatalogControllerDecisionV1:
    runner_temp_value = os.environ.get("RUNNER_TEMP", "")
    expected_candidate = os.environ.get(
        "CATALOG_EXPECTED_CANDIDATE_MANIFEST_SHA256", ""
    )
    expected_controls = os.environ.get("CATALOG_EXPECTED_CONTROLS_RECEIPT_SHA256", "")
    expected_audit_context = os.environ.get("CATALOG_EXPECTED_AUDIT_CONTEXT_SHA256", "")
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    if (
        not runner_temp_value
        or not _SHA256.fullmatch(expected_candidate)
        or not _SHA256.fullmatch(expected_controls)
        or not _SHA256.fullmatch(expected_audit_context)
        or not _COMMIT.fullmatch(expected_commit)
    ):
        raise ValueError("CATALOG_ADMISSION_INVOCATION_INVALID")
    runner_temp = Path(runner_temp_value).resolve(strict=True)
    candidates = _bounded_temp_path(candidate_dir, runner_temp, directory=True)
    routing = _bounded_temp_path(routing_snapshot_dir, runner_temp, directory=True)
    controls_path = _bounded_temp_path(
        controls_receipt_path,
        runner_temp,
        directory=False,
    )
    root = repo_root.resolve(strict=True)
    resolved_output = output_dir.resolve(strict=False)
    if (
        repo_root.is_symlink()
        or not root.is_dir()
        or output_dir.exists()
        or output_dir.is_symlink()
        or not resolved_output.is_relative_to(runner_temp)
        or (github_output is not None and github_output.is_symlink())
    ):
        raise ValueError("CATALOG_ADMISSION_PATH_INVALID")
    manifest = verify_admission_candidate_bundle(
        candidates,
        expected_sha256=expected_candidate,
    )
    context = _load_context(candidates)
    protected_head = CatalogProtectedHeadEvidenceV1.model_validate(
        _strict_json(routing / "protected-head.json")
    )
    if (
        manifest.get("applicable_commit_sha") != expected_commit
        or context.get("applicable_commit_sha") != expected_commit
        or context.get("execution_protocol_sha256")
        != manifest.get("execution_protocol_sha256")
    ):
        raise ValueError("CATALOG_ADMISSION_CANDIDATE_BINDING_INVALID")

    controls_receipt = AuditorCatalogGithubControlsReceiptV1.model_validate(
        _strict_json(controls_path)
    )
    if controls_receipt.receipt_sha256 != expected_controls:
        raise ValueError("CATALOG_CONTROLS_RECEIPT_HASH_MISMATCH")
    github_controls = github_controls_evidence_from_auditor_receipt(
        controls_receipt,
        expected_audit_context_sha256=expected_audit_context,
        expected_protected_commit_sha=protected_head.current_protected_head_sha,
    )
    (
        contract,
        components,
        recipes,
        inventory,
        science,
        source,
        qualification,
    ) = _load_candidate_inputs(candidates)
    profile = CapacityProfile.model_validate(
        _strict_json(_safe_repo_file(root, "config/github_capacity_profile.json"))
    )
    registry = load_catalog_campaign_registry(
        _safe_repo_file(root, "config/catalog_campaign_registry_v1.json")
    )
    entry = resolve_catalog_campaign(registry, str(context.get("campaign_key")), root)
    capacity = select_catalog_capacity_evidence(
        profile=profile,
        qualification=qualification,
        controls_receipt=controls_receipt,
        registered_maximum_workers=entry.max_free_workers,
        observed_at=controls_receipt.github_api_observed_at,
    )
    effective_contract = _contract_for_capacity(contract, capacity)
    component_workers = (
        effective_contract.execution.component_workers
        if capacity.selected_workers > 0
        else 0
    )
    qualification_sha256 = hashlib.sha256(
        (candidates / "operational-qualification.json").read_bytes()
    ).hexdigest()
    if qualification_sha256 != context.get("operational_qualification_sha256"):
        raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_HASH_MISMATCH")
    operational_plan = build_operational_plan(
        capacity=capacity,
        candidate_manifest_sha256=expected_candidate,
        execution_protocol_sha256=str(context.get("execution_protocol_sha256")),
        contract_sha256=effective_contract.contract_sha256,
        runtime_identity_sha256=str(context.get("runtime_identity_sha256")),
        source_artifact_plan_sha256=source.artifact_plan_sha256,
        store_metadata_sha256=str(context.get("store_metadata_sha256")),
        recipe_dag_manifest_sha256=str(context.get("recipe_dag_manifest_sha256")),
        operational_qualification_sha256=qualification_sha256,
        logical_recipe_count=len(recipes),
        unique_component_count=len(components),
        component_workers=component_workers,
    )
    campaign_id = str(context.get("campaign_id"))
    execution_plan_sha256 = catalog_execution_plan_sha256(
        campaign_id=campaign_id,
        operational_plan=operational_plan,
    )
    routing_command = CatalogRoutingCommandV1.model_validate(
        _strict_json(routing / "routing-command.json")
    )
    matching = select_campaign_authority(routing_command.ledger, campaign_id)
    authority_id = (
        matching.authority_id
        if matching is not None
        else catalog_authority_id(
            request_sha256=routing_command.request_sha256,
            campaign_id=campaign_id,
        )
    )
    global_plan = None
    if capacity.status == "ready" and capacity.selected_workers > 0:
        if (
            qualification.reduction_projection is None
            or qualification.hierarchical_reduction_projection is None
        ):
            raise ValueError("CATALOG_OPERATIONAL_QUALIFICATION_INVALID")
        global_plan = build_global_reuse_execution_plan(
            contract=effective_contract,
            campaign_id=campaign_id,
            authority_id=str(authority_id),
            science_sha256=science.scientific_contract_sha256,
            execution_plan_sha256=execution_plan_sha256,
            component_requirements=components,
            recipes=recipes,
            store_inventory=inventory,
            runtime_identity_sha256=str(context.get("runtime_identity_sha256")),
            prepared_input_partition_ids=tuple(
                str(item) for item in context.get("prepared_input_partition_ids", ())
            ),
            qualifications=qualification.bundle_layout_qualifications,
            reduction_projection=qualification.reduction_projection,
            hierarchical_reduction_projection=(
                qualification.hierarchical_reduction_projection
            ),
        )

    output_dir.mkdir(parents=False, exist_ok=False)
    evidence_dir = output_dir / "evidence"
    evidence_dir.mkdir()
    evidence_paths = {
        "github_controls": evidence_dir / "github-controls.json",
        "capacity": evidence_dir / "capacity.json",
        "admission": evidence_dir / "admission-evidence.json",
    }
    active_owner = matching is not None and matching.authority_id in set(
        routing_command.prerequisites.active_owner_authority_ids
    )
    admission_payload = {
        "verified_github_now": controls_receipt.github_api_observed_at,
        "science_evidence": science,
        "source_artifacts_evidence": source,
        "operational_plan": operational_plan,
        "execution_protocol_sha256": context.get("execution_protocol_sha256"),
        "active_owner_run": active_owner,
    }
    _write_json(evidence_paths["github_controls"], github_controls)
    _write_json(evidence_paths["capacity"], capacity)
    _write_json(evidence_paths["admission"], admission_payload)
    controller_output = output_dir / "controller-decision"
    controller_github_output = output_dir / "controller-github-output.txt"
    decision = _run_controller(
        repo_root=root,
        routing_dir=routing,
        evidence_paths=evidence_paths,
        output_dir=controller_output,
        github_output=controller_github_output,
    )
    if decision.execution_plan_sha256 != execution_plan_sha256:
        raise ValueError("CATALOG_ADMISSION_EXECUTION_PLAN_MISMATCH")

    sealed_plan_ready = False
    if decision.outcome is ControllerOutcome.ADMITTED:
        if decision.sealed_inputs is None or global_plan is None:
            raise ValueError("CATALOG_ADMISSION_SEALED_INPUTS_MISSING")
        sealed = decision.sealed_inputs
        if (
            sealed.authority_id != authority_id
            or sealed.campaign_id != campaign_id
            or sealed.execution_plan_sha256 != execution_plan_sha256
            or sealed.github_controls_receipt_sha256
            != github_controls.receipt_sha256
            or sealed.capacity_receipt_sha256 != capacity.capacity_receipt_sha256
        ):
            raise ValueError("CATALOG_ADMISSION_SEALED_INPUTS_MISMATCH")
        policy = _mapping(
            _strict_json(_safe_repo_file(root, "config/catalog_run_prompt_policy_v1.json")),
            "CATALOG_PROMPT_POLICY_INVALID",
        )
        admission_base = _mapping(
            context.get("admission_base"),
            "CATALOG_ADMISSION_EVIDENCE_INVALID",
        )
        evidence = CatalogAdmissionEvidenceV1(
            **admission_base,
            request_sha256=sealed.request_sha256,
            prompt_sha256=sealed.prompt_sha256,
            source_prompt_sha256=policy.get("source_prompt_sha256"),
            prompt_migration_sha256=policy.get("migration_sha256"),
            prompt_policy_sha256=sealed.prompt_policy_sha256,
            campaign_registry_sha256=sealed.campaign_registry_sha256,
            campaign_definition_manifest_sha256=(
                sealed.campaign_definition_manifest_sha256
            ),
            campaign_definition_sha256=sealed.campaign_definition_sha256,
            campaign_definition_rehash_receipt_sha256=(
                sealed.campaign_definition_rehash_receipt_sha256
            ),
            campaign_id=sealed.campaign_id,
            authority_id=sealed.authority_id,
            execution_plan_sha256=sealed.execution_plan_sha256,
            execution_protocol_sha256=sealed.execution_protocol_sha256,
            protected_commit_sha=sealed.protected_commit_sha,
            github_controls_sha256=sealed.github_controls_receipt_sha256,
            capacity_snapshot_sha256=sealed.capacity_receipt_sha256,
            request_queue_snapshot_sha256=(
                routing_command.queue.request_queue_snapshot_sha256
            ),
            authority_anchor_evidence_sha256=(
                sealed.authority_anchor_evidence_sha256
            ),
            qualification_only=False,
        )
        work_manifest = build_resume_work_manifest(
            tuple(item.strategy_id for item in recipes),
            cached_strategy_ids=(),
            maximum_workers=effective_contract.execution.workers,
        )
        run_plan = build_catalog_run_plan(
            effective_contract,
            evidence,
            work_manifest_sha256=work_manifest.manifest_sha256,
            pending_recipe_count=len(work_manifest.pending_strategy_ids),
            cached_recipe_count=0,
        )
        event = _mapping(
            _strict_json(routing / "event.json"),
            "CATALOG_REQUEST_INVALID",
        )
        issue = _mapping(event.get("issue"), "CATALOG_REQUEST_INVALID")
        request = parse_catalog_run_request(
            str(issue.get("title")),
            str(issue.get("body")),
            _safe_repo_file(
                root,
                "config/catalog_requester_public_key_v1.pem",
            ).read_bytes(),
        )
        if request.request_sha256 != sealed.request_sha256:
            raise ValueError("CATALOG_ADMISSION_REQUEST_MISMATCH")
        dag_path = candidates / "recipe-dag/recipe_dag.parquet"
        dag_manifest_path = candidates / "recipe-dag/recipe_dag_manifest.json"
        dag_manifest = verify_recipe_dag_artifacts(dag_path, dag_manifest_path)
        evidence_json = evidence.model_dump(mode="json")
        controller_binding = {
            field: evidence_json[field]
            for field in (
                "request_sha256",
                "prompt_sha256",
                "source_prompt_sha256",
                "prompt_migration_sha256",
                "prompt_policy_sha256",
                "campaign_registry_sha256",
                "campaign_definition_manifest_sha256",
                "campaign_definition_sha256",
                "campaign_definition_rehash_receipt_sha256",
                "campaign_id",
                "authority_id",
                "execution_plan_sha256",
                "execution_protocol_sha256",
                "protected_commit_sha",
                "github_controls_sha256",
                "capacity_snapshot_sha256",
                "request_queue_snapshot_sha256",
                "authority_anchor_evidence_sha256",
            )
        }
        write_sealed_global_reuse_execution_plan(
            output_dir=output_dir / "sealed-plan",
            contract=effective_contract,
            plan=global_plan,
            request_sha256=sealed.request_sha256,
            execution_protocol_sha256=sealed.execution_protocol_sha256,
            protected_commit_sha=sealed.protected_commit_sha,
            decision_sha256=decision.decision_sha256,
            admission_token_sha256=run_plan.admission_token_sha256,
            controller_binding=controller_binding,
            run_plan=run_plan.model_dump(mode="json"),
            resume_work_manifest=work_manifest.model_dump(mode="json"),
            recipe_dag_bytes=dag_path.read_bytes(),
            recipe_dag_manifest=dag_manifest,
            source_artifacts=_mapping(
                _strict_json(candidates / "source-artifacts.json"),
                "CATALOG_SOURCE_ARTIFACT_DOCUMENT_INVALID",
            ),
        )
        sealed_plan_ready = True
    _append_outputs(
        github_output,
        decision=decision,
        sealed_plan_ready=sealed_plan_ready,
        request_issue_number=routing_command.request_issue_number,
    )
    return decision


def main() -> int:
    args = _parser().parse_args()
    try:
        prepare(
            candidate_dir=args.candidate_dir,
            routing_snapshot_dir=args.routing_snapshot_dir,
            controls_receipt_path=args.controls_receipt,
            repo_root=args.repo_root,
            output_dir=args.output_dir,
            github_output=args.github_output,
        )
        return 0
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
