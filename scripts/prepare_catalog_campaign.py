#!/usr/bin/env python3
"""Build one request-independent catalog preparation seed.

This command performs repository, source-artifact, and cache discovery before any
user-requested catalog run exists.  Its sealed plan is consumed only in
``execution_mode=prepare`` by the optimized reusable engine.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, cast


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.merge_planner import MergeResourceProjectionV1
from aurora.infra.sp500_megarun.catalog_admission import (
    CatalogAdmissionEvidenceV1,
    build_catalog_run_plan,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_binding import (
    build_checkpoint_recovery_binding,
    verify_checkpoint_recovery_plan,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CHECKPOINT_COUNT,
    CheckpointRecoveryProfileV1,
    canonical_cached_strategy_ids_sha256,
    load_checkpoint_recovery_profile,
    validate_exact_checkpoint_profile,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_restore import (
    restore_catalog_checkpoint_recovery,
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
from scripts.verify_catalog_production_runtime import validate_production_runtime_receipt
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
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,179}$")
_STORE_INDEX_ARTIFACT_NAME = "catalog-rebuildable-store-index-v1"
PREPARED_PARTITIONS = tuple(
    sorted(
        (
            "runtime-fragment-core",
            "runtime-fragment-D_CBOE_PCR",
            "runtime-fragment-D_CFTC",
            "runtime-fragment-D_CFTC_LEGACY",
            "runtime-fragment-D_FED_H3_H6_H8_G19_CP",
            "runtime-fragment-D_FED_H15_H10",
            "runtime-fragment-D_FRENCH_US",
            "runtime-fragment-D_MACRO_PIT",
            "runtime-fragment-D_Z1",
        )
    )
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


def _jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _payload_artifact_matrix(sealed_plan_dir: Path) -> str:
    payload_root = sealed_plan_dir / "payload_artifacts"
    if (
        sealed_plan_dir.is_symlink()
        or payload_root.is_symlink()
        or not payload_root.is_dir()
    ):
        raise ValueError("CATALOG_PAYLOAD_ARTIFACT_ROOT_INVALID")
    artifacts: list[str] = []
    for bundle in sorted(payload_root.iterdir(), key=lambda item: item.name):
        if (
            bundle.is_symlink()
            or not bundle.is_dir()
            or _ARTIFACT_NAME.fullmatch(bundle.name) is None
        ):
            raise ValueError("CATALOG_PAYLOAD_ARTIFACT_INVALID")
        members = tuple(path for path in bundle.rglob("*") if path.is_file())
        if not members or any(path.is_symlink() for path in members):
            raise ValueError("CATALOG_PAYLOAD_ARTIFACT_EMPTY_OR_UNSAFE")
        artifacts.append(bundle.name)
    if not artifacts or len(artifacts) > 256:
        raise ValueError("CATALOG_PAYLOAD_ARTIFACT_MATRIX_INVALID")
    return json.dumps(
        {"artifact": artifacts},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _document(document_type: str, payload: object) -> dict[str, object]:
    checked_payload = _jsonable(payload)
    identity = {
        "schema_version": "1",
        "document_type": document_type,
        "payload": checked_payload,
    }
    return {**identity, "content_sha256": canonical_sha256(identity)}


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _download_checkpoint_recovery_artifact(
    repository: str,
    token: str,
    artifact_id: int,
) -> bytes:
    """Download one bounded recovery archive without exposing the token."""

    if (
        repository != _REPOSITORY
        or not token
        or type(artifact_id) is not int
        or artifact_id < 1
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_READER_INVALID")
    maximum_bytes = 64 * 1024 * 1024
    try:
        with tempfile.TemporaryFile() as stream:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{repository}/actions/artifacts/{artifact_id}/zip",
                ],
                stdout=stream,
                stderr=subprocess.PIPE,
                env={**os.environ, "GH_TOKEN": token},
                timeout=60,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_DOWNLOAD_FAILED")
            stream.seek(0)
            raw = stream.read(maximum_bytes + 1)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_DOWNLOAD_FAILED") from exc
    if not raw or len(raw) > maximum_bytes:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_ARCHIVE_SIZE_INVALID")
    return raw


def _owned_recovery_directory(
    restore_root: Path,
    value: object,
) -> Path:
    """Require a restored directory to remain below the one restore root."""

    if not isinstance(value, Path):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID")
    if value.is_symlink() or restore_root.is_symlink():
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID")
    try:
        resolved_root = restore_root.resolve(strict=True)
        resolved = value.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID") from exc
    if (
        not resolved_root.is_dir()
        or not resolved.is_dir()
        or not resolved.is_relative_to(resolved_root)
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID")
    current = resolved_root
    for part in value.absolute().relative_to(resolved_root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID")
    return resolved


def _recovery_files(root: Path) -> list[dict[str, object]]:
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('CATALOG_CHECKPOINT_RECOVERY_TRANSPORT_INVALID')
        if path.is_file():
            files.append({'path': path.relative_to(root).as_posix(),
                          'sha256': _sha_file(path), 'size_bytes': path.stat().st_size})
    if not files:
        raise ValueError('CATALOG_CHECKPOINT_RECOVERY_TRANSPORT_INVALID')
    return files


def _checkpoint_recovery_state(
    *,
    repo_root: Path,
    profile: CheckpointRecoveryProfileV1 | None,
    restore_root: Path,
    restore: Callable[[], object] | None,
) -> dict[str, object] | None:
    """Validate the one authenticated restore used by the SP8 preparation."""

    if profile is None:
        return None
    if restore is None:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESTORE_REQUIRED")
    try:
        result = restore()
        result_profile = getattr(result, "profile")
        proof = getattr(result, "proof")
        source_validation = getattr(result, "source_validation")
        resume_index = getattr(source_validation, "resume_index")
        source_plan_root = _owned_recovery_directory(
            restore_root,
            getattr(result, "source_plan_root"),
        )
        checkpoint_root = _owned_recovery_directory(
            restore_root,
            getattr(result, "checkpoint_root"),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("CATALOG_"):
            raise
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID") from exc
    if not isinstance(result_profile, CheckpointRecoveryProfileV1):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_INVALID")
    protected_profile = validate_exact_checkpoint_profile(repo_root, result_profile)
    if protected_profile != profile:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_MISMATCH")
    if not isinstance(proof, CheckpointRecoveryOwnerProofV1):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_OWNER_PROOF_INVALID")
    if (
        proof.profile_sha256 != protected_profile.profile_sha256
        or proof.source_request_sha256 != protected_profile.source_request_sha256
        or proof.source_run_id != protected_profile.source_run_id
        or proof.source_run_attempt != protected_profile.source_run_attempt
        or proof.source_protected_commit_sha
        != protected_profile.source_protected_commit_sha
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_OWNER_PROOF_INVALID")
    if source_plan_root == checkpoint_root:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID")
    try:
        cached_strategy_ids = tuple(resume_index.strategy_ids)
        resume_index_sha256 = resume_index.index_sha256
        source_plan_receipt_sha256 = source_validation.plan_receipt_sha256
        source_science_sha256 = source_validation.science_identity_sha256
        source_catalog_sha256 = source_validation.catalog_manifest_sha256
        checkpoint_count = source_validation.checkpoint_count
    except AttributeError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID") from exc
    if (
        any(type(item) is not str or not item for item in cached_strategy_ids)
        or len(set(cached_strategy_ids)) != len(cached_strategy_ids)
        or len(cached_strategy_ids) != protected_profile.expected_result_count
        or protected_profile.expected_total_count <= len(cached_strategy_ids)
        or canonical_cached_strategy_ids_sha256(cached_strategy_ids)
        != protected_profile.cached_strategy_ids_sha256
        or resume_index.physical_result_count != len(cached_strategy_ids)
        or resume_index.duplicate_result_count != 0
        or source_plan_receipt_sha256
        != protected_profile.source_plan_receipt_sha256
        or source_science_sha256 != protected_profile.science_sha256
        or source_catalog_sha256 != protected_profile.catalog_manifest_sha256
        or checkpoint_count != CHECKPOINT_RECOVERY_CHECKPOINT_COUNT
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_INVALID")
    return {
        "profile": protected_profile,
        "proof": proof,
        "binding": build_checkpoint_recovery_binding(protected_profile, proof),
        "cached_strategy_ids": cached_strategy_ids,
        "resume_index_sha256": resume_index_sha256,
        "source_plan_receipt_sha256": source_plan_receipt_sha256,
        "files": _recovery_files(restore_root),
        "source_plan_relative": source_plan_root.relative_to(
            restore_root.resolve(strict=True)
        ).as_posix(),
        "checkpoint_relative": checkpoint_root.relative_to(
            restore_root.resolve(strict=True)
        ).as_posix(),
    }


def _checkpoint_recovery_seed_document(
    state: Mapping[str, object],
) -> dict[str, object]:
    profile = state["profile"]
    proof = state["proof"]
    if not isinstance(profile, CheckpointRecoveryProfileV1) or not isinstance(
        proof, CheckpointRecoveryOwnerProofV1
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID")
    return {
        "schema_version": "1",
        "profile": profile.model_dump(mode="json"),
        "owner_proof": asdict(proof),
        "binding": state["binding"],
        # _checkpoint_recovery_state validates and stores a tuple of string IDs.
        "cached_strategy_ids": list(cast(tuple[str, ...], state["cached_strategy_ids"])),
        "cached_strategy_ids_sha256": profile.cached_strategy_ids_sha256,
        "resume_index_sha256": state["resume_index_sha256"],
        "source_plan_receipt_sha256": state["source_plan_receipt_sha256"],
        "source_plan_relative": state["source_plan_relative"],
        "checkpoint_relative": state["checkpoint_relative"],
        "files": state["files"],
    }


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
    checkpoint_recovery_restore: Callable[[], object] | None = None,
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
    validate_production_runtime_receipt(
        runtime_smoke,
        lock_path=_safe_file(root, "requirements/catalog-optimized.lock"),
    )

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
        expected_commit=expected_commit,
        artifacts=indexes.rows,
        caches=caches.rows,
        client=client,
        repository=repository,
        token=token,
        download_root=runner_temp / "catalog-preparation-indexes",
    )

    checkpoint_recovery_profile = load_checkpoint_recovery_profile(
        root,
        entry.campaign_key,
        8,
    )
    checkpoint_recovery_staging = target.parent / (
        f".{target.name}-checkpoint-recovery"
    )
    checkpoint_recovery_state: dict[str, object] | None = None
    if checkpoint_recovery_profile is not None:
        if checkpoint_recovery_profile.science_sha256 != science_sha256:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SCIENCE_MISMATCH")
        if checkpoint_recovery_restore is None:
            checkpoint_recovery_restore = lambda: restore_catalog_checkpoint_recovery(
                repo_root=root,
                repository=repository,
                protected_commit_sha=expected_commit,
                profile=checkpoint_recovery_profile,
                output_dir=checkpoint_recovery_staging,
                fetch_json=client,
                download_artifact=lambda artifact_id: (
                    _download_checkpoint_recovery_artifact(
                        repository,
                        token,
                        artifact_id,
                    )
                ),
            )
        checkpoint_recovery_state = _checkpoint_recovery_state(
            repo_root=root,
            profile=checkpoint_recovery_profile,
            restore_root=checkpoint_recovery_staging,
            restore=checkpoint_recovery_restore,
        )
    cached_strategy_ids = (
        tuple(cast(tuple[str, ...], checkpoint_recovery_state["cached_strategy_ids"]))
        if checkpoint_recovery_state is not None
        else ()
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
        cached_strategy_ids=cached_strategy_ids,
    )

    output_dir.mkdir(parents=False, exist_ok=False)
    if checkpoint_recovery_state is not None:
        checkpoint_recovery_output = output_dir / "checkpoint-recovery"
        if checkpoint_recovery_output.exists() or checkpoint_recovery_output.is_symlink():
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_OUTPUT_EXISTS")
        os.replace(checkpoint_recovery_staging, checkpoint_recovery_output)
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
        cached_strategy_ids=cached_strategy_ids,
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
        pending_recipe_count=len(work_manifest.pending_strategy_ids),
        cached_recipe_count=len(work_manifest.cached_strategy_ids),
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
    if checkpoint_recovery_state is not None:
        controller_binding["checkpoint_recovery"] = checkpoint_recovery_state["binding"]
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
    if checkpoint_recovery_state is not None:
        verify_checkpoint_recovery_plan(
            output_dir / "sealed-plan",
            checkpoint_recovery_state["profile"],
            checkpoint_recovery_state["proof"],
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
    if checkpoint_recovery_state is not None:
        context_identity["checkpoint_recovery"] = _checkpoint_recovery_seed_document(
            checkpoint_recovery_state
        )
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
            "payload_artifact_matrix": _payload_artifact_matrix(
                output_dir / "sealed-plan"
            ),
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
