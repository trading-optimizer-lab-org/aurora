#!/usr/bin/env python3
"""Build one request-independent catalog preparation seed.

This command performs repository, source-artifact, and cache discovery before any
user-requested catalog run exists.  Its sealed plan is consumed only in
``execution_mode=prepare`` by the optimized reusable engine.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
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


from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.merge_planner import MergeResourceProjectionV1
from aurora.infra.sp500_megarun.catalog_admission import (
    CatalogAdmissionEvidenceV1,
    build_catalog_run_plan,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
    verify_catalog_campaign_definition,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_controller import catalog_authority_id
from aurora.infra.sp500_megarun.catalog_execution_protocol import (
    execution_protocol_sha256,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogPreparationIdentityV1,
    build_catalog_preparation_identity,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_resume import build_resume_work_manifest
from scripts.compile_sp500_catalog_recipes import write_recipe_dag_artifacts
from scripts.plan_sp500_optimized_catalog_run import (
    build_global_reuse_execution_plan,
    build_repository_contract,
    write_sealed_global_reuse_execution_plan,
)
from scripts.prepare_catalog_admission_candidates import (
    derive_catalog_work_requirements,
    load_verified_rebuildable_store_inventory,
    verify_fixed_source_artifact_metadata,
)


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_STORE_INDEX_ARTIFACT_NAME = "catalog-rebuildable-store-index-v1"
PREPARED_PARTITIONS = (
    "runtime-fragment-core",
    "runtime-fragment-D_CBOE_PCR",
    "runtime-fragment-D_CFTC",
    "runtime-fragment-D_CFTC_LEGACY",
    "runtime-fragment-D_FED",
    "runtime-fragment-D_FED_H15_H10",
    "runtime-fragment-D_FRENCH_US",
    "runtime-fragment-D_MACRO_PIT",
    "runtime-fragment-D_Z1",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare one registered catalog outside the launch path."
    )
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--runtime-smoke", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_PREPARATION_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _strict_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_PREPARATION_INPUT_INVALID")
    return json.loads(
        path.read_text("utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_PREPARATION_NONFINITE_JSON:{value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _safe_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("CATALOG_PREPARATION_REPOSITORY_PATH_INVALID")
    candidate = root.joinpath(*relative.split("/"))
    if candidate.is_symlink():
        raise ValueError("CATALOG_PREPARATION_REPOSITORY_PATH_INVALID")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("CATALOG_PREPARATION_REPOSITORY_PATH_INVALID")
    return resolved


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


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _document(document_type: str, payload: object) -> dict[str, object]:
    identity = {
        "schema_version": "1",
        "document_type": document_type,
        "payload": payload,
    }
    return {**identity, "content_sha256": canonical_sha256(identity)}


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preparation_projections() -> tuple[
    MergeResourceProjectionV1,
    MergeResourceProjectionV1,
]:
    """Closed placeholders: reduction never executes in preparation mode."""

    return (
        MergeResourceProjectionV1(
            timeout_fraction_p99=0.71,
            memory_fraction_p99=0.71,
            disk_fraction_p99=0.71,
            artifact_fraction_p99=0.71,
            download_fraction_p99=0.71,
            input_count_fraction_p99=0.71,
        ),
        MergeResourceProjectionV1(
            timeout_fraction_p99=0.50,
            memory_fraction_p99=0.50,
            disk_fraction_p99=0.50,
            artifact_fraction_p99=0.50,
            download_fraction_p99=0.50,
            input_count_fraction_p99=0.50,
        ),
    )


def build_preparation_bindings(
    identity: CatalogPreparationIdentityV1,
) -> dict[str, str]:
    """Derive deterministic non-production identifiers for one preparation."""

    key = identity.preparation_key_sha256
    campaign_id = canonical_sha256(
        {
            "schema_version": "catalog-fast-campaign-v1",
            "preparation_key_sha256": key,
        }
    )
    request_sha256 = canonical_sha256(
        {
            "schema_version": "catalog-preparation-request-v1",
            "preparation_key_sha256": key,
        }
    )
    authority_id = str(
        catalog_authority_id(
            request_sha256=request_sha256,
            campaign_id=campaign_id,
        )
    )
    execution_plan_sha256 = canonical_sha256(
        {
            "schema_version": "catalog-preparation-plan-v1",
            "preparation_key_sha256": key,
            "authority_id": authority_id,
        }
    )
    decision_sha256 = canonical_sha256(
        {
            "schema_version": "catalog-preparation-decision-v1",
            "execution_plan_sha256": execution_plan_sha256,
        }
    )
    return {
        "campaign_id": campaign_id,
        "request_sha256": request_sha256,
        "authority_id": authority_id,
        "execution_plan_sha256": execution_plan_sha256,
        "decision_sha256": decision_sha256,
    }


def prepare_campaign(
    *,
    campaign_key: str,
    repo_root: Path,
    runtime_smoke_path: Path,
    output_dir: Path,
    github_output: Path | None,
) -> dict[str, object]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
    if (
        repository != _REPOSITORY
        or not token
        or not _COMMIT.fullmatch(expected_commit)
        or not runner_temp_raw
    ):
        raise ValueError("CATALOG_PREPARATION_INVOCATION_INVALID")
    root = repo_root.resolve(strict=True)
    runner_temp = Path(runner_temp_raw).resolve(strict=True)
    target = output_dir.resolve(strict=False)
    smoke_path = runtime_smoke_path.resolve(strict=True)
    if (
        repo_root.is_symlink()
        or not root.is_dir()
        or output_dir.exists()
        or output_dir.is_symlink()
        or not target.is_relative_to(runner_temp)
        or not smoke_path.is_relative_to(runner_temp)
        or (github_output is not None and github_output.is_symlink())
    ):
        raise ValueError("CATALOG_PREPARATION_PATH_INVALID")
    checked_out_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if checked_out_commit != expected_commit:
        raise ValueError("CATALOG_PREPARATION_PROTECTED_COMMIT_MISMATCH")

    runtime_smoke = _mapping(
        _strict_json(smoke_path),
        "CATALOG_PRODUCTION_RUNTIME_SMOKE_INVALID",
    )
    if (
        runtime_smoke.get("status") != "PREPARED"
        or runtime_smoke.get("production_dependency_smoke_passed") is not True
        or runtime_smoke.get("network_install_performed") is not False
    ):
        raise ValueError("CATALOG_PRODUCTION_RUNTIME_SMOKE_INVALID")

    registry = load_catalog_campaign_registry(
        _safe_file(root, "config/catalog_campaign_registry_v1.json")
    )
    entry = resolve_catalog_campaign(registry, campaign_key, root)
    identity = build_catalog_preparation_identity(
        repo_root=root,
        registry_entry=entry,
        protected_commit_sha=expected_commit,
    )
    bindings = build_preparation_bindings(identity)
    manifest_path = _safe_file(root, entry.definition_manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    verified_manifest = verify_catalog_campaign_definition(
        repo_root=root,
        registry_entry=entry,
        manifest=parse_catalog_campaign_definition_bytes(manifest_bytes),
    )
    contract = build_repository_contract(
        repo_root=root,
        policy_path=_safe_file(root, entry.optimization_policy_path),
        campaign_path=_safe_file(root, entry.campaign_contract_path),
        catalog_dir=(root / entry.catalog_dir).resolve(strict=True),
        selected_config_path=_safe_file(root, entry.selected_config_path),
    )
    science_sha256 = canonical_sha256(contract.science)
    if science_sha256 != entry.scientific_contract_sha256:
        raise ValueError("CATALOG_SCIENCE_IDENTITY_MISMATCH")

    catalog_path = _safe_file(root, f"{entry.catalog_dir}/catalog.jsonl")
    catalog_rows = tuple(
        _mapping(json.loads(line), "CATALOG_PREPARATION_CATALOG_INVALID")
        for line in catalog_path.read_text("utf-8").splitlines()
        if line
    )
    selected_raw = _strict_json(_safe_file(root, entry.selected_config_path))
    if not isinstance(selected_raw, list):
        raise ValueError("CATALOG_PREPARATION_SELECTED_CONFIG_INVALID")
    feature_path = _safe_file(root, entry.feature_contract_path)
    components, recipes = derive_catalog_work_requirements(
        contract=contract,
        catalog_rows=catalog_rows,
        selected_rows=tuple(
            _mapping(item, "CATALOG_PREPARATION_SELECTED_CONFIG_INVALID")
            for item in selected_raw
        ),
        feature_contract_sha256=_sha_file(feature_path),
    )

    client = CatalogGitHubReadOnlyClient(repository, token)
    source_contract = _mapping(
        _strict_json(_safe_file(root, "config/catalog_keeper_source_artifacts_v1.json")),
        "CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID",
    )
    source_rows = source_contract.get("artifacts")
    if not isinstance(source_rows, list):
        raise ValueError("CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
    artifact_metadata: dict[int, Mapping[str, object]] = {}
    for raw in source_rows:
        row = _mapping(raw, "CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
        artifact_id = row.get("artifact_id")
        if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
            raise ValueError("CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
        metadata, _ = client.get_json(
            f"/repos/{repository}/actions/artifacts/{artifact_id}"
        )
        artifact_metadata[artifact_id] = _mapping(
            metadata,
            "CATALOG_SOURCE_ARTIFACT_METADATA_INVALID",
        )
    if client.observed_at is None:
        raise ValueError("CATALOG_PREPARATION_GITHUB_TIME_INVALID")
    source_evidence, normalized_sources = verify_fixed_source_artifact_metadata(
        source_contract=source_contract,
        artifact_metadata=artifact_metadata,
        required_contracts=entry.source_artifact_contracts,
        observed_at=client.observed_at,
    )
    caches = client.stable_paginated(
        f"/repos/{repository}/actions/caches?ref=refs/heads/main",
        root="actions_caches",
    ).collection
    indexes = client.stable_paginated(
        f"/repos/{repository}/actions/artifacts?name={_STORE_INDEX_ARTIFACT_NAME}",
        root="artifacts",
    ).collection
    inventory = load_verified_rebuildable_store_inventory(
        artifacts=indexes.rows,
        caches=caches.rows,
        client=client,
        repository=repository,
        token=token,
        download_root=runner_temp / "catalog-preparation-indexes",
    )

    protocol_sha256 = execution_protocol_sha256(
        root=root,
        entry=entry,
        manifest_sha256=_sha_file(manifest_path),
    )
    runtime_identity_sha256 = canonical_sha256(
        {
            "schema_version": "catalog-runtime-identity-v1",
            "runner_image": "ubuntu-24.04",
            "python_abi": "cp311",
            "runtime_mode": contract.runtime_preparation.runtime_mode,
            "lock_sha256": identity.dependency_lock_sha256,
        }
    )
    central_projection, hierarchical_projection = _preparation_projections()
    plan = build_global_reuse_execution_plan(
        contract=contract,
        campaign_id=bindings["campaign_id"],
        authority_id=bindings["authority_id"],
        science_sha256=science_sha256,
        execution_plan_sha256=bindings["execution_plan_sha256"],
        component_requirements=components,
        recipes=recipes,
        store_inventory=inventory,
        runtime_identity_sha256=runtime_identity_sha256,
        prepared_input_partition_ids=PREPARED_PARTITIONS,
        qualifications=(),
        reduction_projection=central_projection,
        hierarchical_reduction_projection=hierarchical_projection,
        preparation_only=True,
    )

    output_dir.mkdir(parents=False, exist_ok=False)
    dag_dir = output_dir / "recipe-dag"
    dag_manifest = write_recipe_dag_artifacts(catalog_path, dag_dir)
    source_document = _document(
        "catalog_source_artifacts_v1",
        {
            "evidence": source_evidence,
            "artifacts": normalized_sources,
            "source_contract": source_contract,
        },
    )
    documents = {
        "resolved-contract.json": contract,
        "component-requirements.json": _document(
            "catalog_component_requirements_v1",
            {"count": len(components), "items": components},
        ),
        "recipe-requirements.json": _document(
            "catalog_recipe_requirements_v1",
            {"count": len(recipes), "items": recipes},
        ),
        "source-artifacts.json": source_document,
        "runtime-smoke.json": runtime_smoke,
    }
    for name, value in documents.items():
        _write_json(output_dir / name, value)

    work_manifest = build_resume_work_manifest(
        tuple(item.strategy_id for item in recipes),
        cached_strategy_ids=(),
        maximum_workers=contract.execution.workers,
    )
    admission_base = dict(
        _mapping(
            _strict_json(_safe_file(root, entry.admission_evidence_path)),
            "CATALOG_ADMISSION_EVIDENCE_INVALID",
        )
    )
    closed_hash = lambda label: canonical_sha256(  # noqa: E731
        {"schema_version": "catalog-preparation-binding-v1", "label": label, "key": identity.preparation_key_sha256}
    )
    evidence = CatalogAdmissionEvidenceV1(
        **admission_base,
        request_sha256=bindings["request_sha256"],
        prompt_sha256=closed_hash("prompt"),
        source_prompt_sha256=closed_hash("source-prompt"),
        prompt_migration_sha256=closed_hash("prompt-migration"),
        prompt_policy_sha256=_sha_file(_safe_file(root, "config/catalog_run_prompt_policy_v1.json")),
        campaign_registry_sha256=_sha_file(_safe_file(root, "config/catalog_campaign_registry_v1.json")),
        campaign_definition_manifest_sha256=_sha_file(manifest_path),
        campaign_definition_sha256=verified_manifest.campaign_definition_sha256,
        campaign_definition_rehash_receipt_sha256=canonical_sha256(
            verified_manifest.model_dump(mode="json")
        ),
        campaign_id=bindings["campaign_id"],
        authority_id=bindings["authority_id"],
        execution_plan_sha256=bindings["execution_plan_sha256"],
        execution_protocol_sha256=protocol_sha256,
        protected_commit_sha=expected_commit,
        github_controls_sha256=_sha_file(_safe_file(root, "config/catalog_github_controls_v1.json")),
        capacity_snapshot_sha256=closed_hash("preparation-capacity"),
        request_queue_snapshot_sha256=closed_hash("preparation-queue"),
        authority_anchor_evidence_sha256=closed_hash("preparation-authority"),
        qualification_only=False,
    )
    run_plan = build_catalog_run_plan(
        contract,
        evidence,
        work_manifest_sha256=work_manifest.manifest_sha256,
        pending_recipe_count=len(recipes),
        cached_recipe_count=0,
    )
    _write_json(output_dir / "template-admission-evidence.json", evidence)
    controller_binding = {
        key: value
        for key, value in evidence.model_dump(mode="json").items()
        if key
        in {
            "request_sha256",
            "campaign_definition_sha256",
            "campaign_id",
            "authority_id",
            "execution_plan_sha256",
            "execution_protocol_sha256",
            "protected_commit_sha",
        }
    }
    sealed_receipt = write_sealed_global_reuse_execution_plan(
        output_dir=output_dir / "sealed-plan",
        contract=contract,
        plan=plan,
        request_sha256=bindings["request_sha256"],
        execution_protocol_sha256=protocol_sha256,
        protected_commit_sha=expected_commit,
        decision_sha256=bindings["decision_sha256"],
        admission_token_sha256=run_plan.admission_token_sha256,
        controller_binding=controller_binding,
        run_plan=run_plan.model_dump(mode="json"),
        resume_work_manifest=work_manifest.model_dump(mode="json"),
        recipe_dag_bytes=(dag_dir / "recipe_dag.parquet").read_bytes(),
        recipe_dag_manifest=dag_manifest,
        source_artifacts=source_document,
    )
    context_identity = {
        "schema_version": "1",
        "document_type": "catalog_preparation_seed_v1",
        "identity": identity.model_dump(mode="json"),
        **bindings,
        "science_sha256": science_sha256,
        "execution_protocol_sha256": protocol_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
        "prepared_input_partition_ids": PREPARED_PARTITIONS,
        "logical_recipe_count": len(recipes),
        "unique_component_count": len(components),
        "runtime_smoke_sha256": _sha_file(smoke_path),
        "source_artifacts_sha256": source_document["content_sha256"],
        "recipe_dag_manifest_sha256": dag_manifest["manifest_sha256"],
        "sealed_plan_receipt_sha256": sealed_receipt["receipt_sha256"],
    }
    context = {
        **context_identity,
        "content_sha256": canonical_sha256(context_identity),
    }
    _write_json(output_dir / "preparation-seed.json", context)
    if github_output is not None:
        values = {
            **bindings,
            "preparation_key_sha256": identity.preparation_key_sha256,
            "science_sha256": science_sha256,
            "execution_protocol_sha256": protocol_sha256,
        }
        with github_output.open("a", encoding="utf-8", newline="\n") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    return context


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        prepare_campaign(
            campaign_key=args.campaign_key,
            repo_root=args.repo_root,
            runtime_smoke_path=args.runtime_smoke,
            output_dir=args.output_dir,
            github_output=args.github_output,
        )
        return 0
    except (
        CatalogGitHubSnapshotError,
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
