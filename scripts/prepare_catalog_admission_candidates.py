#!/usr/bin/env python3
"""Build bounded repository and metadata candidates before live admission audit."""

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
from typing import Any, Mapping, Sequence
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
    verify_catalog_campaign_definition,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignEntryV1,
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_controller import (
    CatalogProtectedHeadEvidenceV1,
    CatalogScienceAdmissionEvidenceV1,
    CatalogSourceArtifactsEvidenceV1,
)
from aurora.infra.sp500_megarun.catalog_execution_protocol import (
    PROTOCOL_COMMON_PATHS as _PROTOCOL_COMMON_PATHS,
    execution_protocol_sha256 as _protocol_sha256,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    CatalogComponentIdentityV1,
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_rebuildable_store import (
    RebuildableStoreInventoryV1,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import (
    CatalogRebuildableStoreIndexV1,
    inventory_from_verified_indexes,
)
from aurora.infra.sp500_megarun.catalog_routing import CatalogRoutingCommandV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from aurora.infra.sp500_megarun.strategy_catalog import configuration_sha256
from scripts.compile_sp500_catalog_recipes import write_recipe_dag_artifacts
from scripts.plan_sp500_optimized_catalog_run import (
    CatalogComponentRequirementV1,
    CatalogRecipeRequirementV1,
    build_repository_contract,
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_STORE_INDEX_ARTIFACT_NAME = "catalog-rebuildable-store-index-v1"
_MAX_STORE_INDEX_ARTIFACTS = 256
_MAX_STORE_INDEX_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_STORE_INDEX_FILE_BYTES = 16 * 1024 * 1024
_PREPARED_PARTITIONS = (
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
        description="Prepare one fixed catalog admission candidate bundle."
    )
    parser.add_argument("--routing-snapshot-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_CANDIDATE_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _strict_json(path: Path) -> object:
    return _strict_json_bytes(path.read_bytes())


def _strict_json_bytes(raw: bytes) -> object:
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_CANDIDATE_NONFINITE_JSON:{value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


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


def _safe_repository_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("CATALOG_CANDIDATE_REPOSITORY_PATH_INVALID")
    candidate = root.joinpath(*relative.split("/"))
    if candidate.is_symlink():
        raise ValueError("CATALOG_CANDIDATE_REPOSITORY_SYMLINK_FORBIDDEN")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("CATALOG_CANDIDATE_REPOSITORY_PATH_INVALID")
    return resolved


def _component_identity(
    *,
    contract: RunOptimizationContractV1,
    feature_contract_sha256: str,
    lane_id: str,
    configuration_sha256: str,
) -> CatalogComponentIdentityV1:
    return CatalogComponentIdentityV1(
        evaluator_sha256=contract.science.evaluator_sha256,
        data_snapshot_sha256=contract.science.data_snapshot_sha256,
        numeric_profile_sha256=canonical_sha256(
            {
                "schema_version": "catalog-numeric-profile-v1",
                "numeric_profile": contract.science.numeric_profile,
            }
        ),
        feature_definition_sha256=canonical_sha256(
            {
                "schema_version": "catalog-feature-definition-v1",
                "feature_contract_sha256": feature_contract_sha256,
                "lane_id": lane_id,
            }
        ),
        parameters_sha256=configuration_sha256,
        dtype_sha256=canonical_sha256(
            {"schema_version": "catalog-component-dtype-v1", "dtype": "int8"}
        ),
        output_schema_sha256=canonical_sha256(
            {
                "schema_version": "catalog-component-output-v1",
                "domain": (-1, 0, 1),
                "axis": "training_session",
            }
        ),
    )


def derive_catalog_work_requirements(
    *,
    contract: RunOptimizationContractV1,
    catalog_rows: Sequence[Mapping[str, object]],
    selected_rows: Sequence[Mapping[str, object]],
    feature_contract_sha256: str,
) -> tuple[
    tuple[CatalogComponentRequirementV1, ...],
    tuple[CatalogRecipeRequirementV1, ...],
]:
    """Derive identities and dependency sets without evaluating one component."""

    if not _SHA256.fullmatch(feature_contract_sha256):
        raise ValueError("CATALOG_FEATURE_CONTRACT_HASH_INVALID")
    source_components: dict[str, tuple[str, Mapping[str, object]]] = {}
    for rows, allow_selected_key in (
        (catalog_rows, False),
        (selected_rows, True),
    ):
        for raw_row in rows:
            row = _mapping(raw_row, "CATALOG_CANDIDATE_ROW_INVALID")
            raw_components = row.get("components") if "components" in row else (row,)
            if not isinstance(raw_components, Sequence) or isinstance(
                raw_components, (str, bytes)
            ):
                raise ValueError("CATALOG_CANDIDATE_COMPONENT_SET_INVALID")
            for raw_component in raw_components:
                component = _mapping(
                    raw_component,
                    "CATALOG_CANDIDATE_COMPONENT_INVALID",
                )
                lane_id = component.get("lane_id")
                source_id = component.get("configuration_sha256")
                configuration = component.get("configuration")
                if (
                    not isinstance(lane_id, str)
                    or not lane_id
                    or not isinstance(configuration, Mapping)
                ):
                    raise ValueError("CATALOG_CANDIDATE_COMPONENT_INVALID")
                if source_id is None and allow_selected_key:
                    selected_key = component.get("source_strategy_key")
                    if not isinstance(selected_key, str) or not _SHA256.fullmatch(
                        selected_key
                    ):
                        raise ValueError("CATALOG_CANDIDATE_COMPONENT_INVALID")
                    source_id = configuration_sha256(lane_id, configuration)
                if not isinstance(source_id, str) or not _SHA256.fullmatch(source_id):
                    raise ValueError("CATALOG_CANDIDATE_COMPONENT_INVALID")
                checked = (lane_id, dict(configuration))
                previous = source_components.get(source_id)
                if previous is not None and previous != checked:
                    raise ValueError("COMPONENT_DEFINITION_CONFLICT")
                source_components[source_id] = checked

    requirements: list[CatalogComponentRequirementV1] = []
    global_by_source: dict[str, str] = {}
    for source_id in sorted(source_components):
        lane_id, _configuration = source_components[source_id]
        identity = _component_identity(
            contract=contract,
            feature_contract_sha256=feature_contract_sha256,
            lane_id=lane_id,
            configuration_sha256=source_id,
        )
        global_by_source[source_id] = identity.component_key_sha256
        requirements.append(
            CatalogComponentRequirementV1(
                component_id=identity.component_key_sha256,
                identity=identity,
                estimated_bytes=8192,
                source_configuration_sha256=source_id,
            )
        )

    recipes: list[CatalogRecipeRequirementV1] = []
    seen_strategies: set[str] = set()
    for raw_row in catalog_rows:
        row = _mapping(raw_row, "CATALOG_CANDIDATE_ROW_INVALID")
        strategy_id = row.get("strategy_id")
        raw_components = row.get("components")
        feature_count = row.get("feature_count", 1)
        if (
            not isinstance(strategy_id, str)
            or not strategy_id
            or strategy_id in seen_strategies
            or not isinstance(raw_components, Sequence)
            or isinstance(raw_components, (str, bytes))
            or isinstance(feature_count, bool)
            or not isinstance(feature_count, int)
            or feature_count < 1
        ):
            raise ValueError("CATALOG_CANDIDATE_RECIPE_INVALID")
        component_ids: list[str] = []
        for raw_component in raw_components:
            component = _mapping(
                raw_component,
                "CATALOG_CANDIDATE_COMPONENT_INVALID",
            )
            source_id = component.get("configuration_sha256")
            if not isinstance(source_id, str) or source_id not in global_by_source:
                raise ValueError("CATALOG_RECIPE_COMPONENT_UNKNOWN")
            component_ids.append(global_by_source[source_id])
        seen_strategies.add(strategy_id)
        recipes.append(
            CatalogRecipeRequirementV1(
                strategy_id=strategy_id,
                component_ids=tuple(sorted(set(component_ids))),
                estimated_seconds_p99=float(feature_count),
            )
        )
    if not requirements or not recipes:
        raise ValueError("CATALOG_GLOBAL_REUSE_WORKLOAD_EMPTY")
    return tuple(requirements), tuple(sorted(recipes, key=lambda item: item.strategy_id))


def verify_fixed_source_artifact_metadata(
    *,
    source_contract: Mapping[str, object],
    artifact_metadata: Mapping[int, Mapping[str, object]],
    required_contracts: Sequence[str],
    observed_at: datetime,
) -> tuple[CatalogSourceArtifactsEvidenceV1, tuple[dict[str, object], ...]]:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("CATALOG_SOURCE_ARTIFACT_TIME_INVALID")
    rows = source_contract.get("artifacts")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
    by_name: dict[str, Mapping[str, object]] = {}
    for raw in rows:
        row = _mapping(raw, "CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
        name = row.get("contract_name")
        if not isinstance(name, str) or name in by_name:
            raise ValueError("CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
        by_name[name] = row
    if tuple(sorted(by_name)) != tuple(sorted(set(required_contracts))):
        raise ValueError("CATALOG_SOURCE_ARTIFACT_COVERAGE_INVALID")

    normalized: list[dict[str, object]] = []
    for contract_name in required_contracts:
        row = by_name[contract_name]
        artifact_id = row.get("artifact_id")
        run_id = row.get("run_id")
        expected_head = row.get("head_sha")
        if (
            isinstance(artifact_id, bool)
            or not isinstance(artifact_id, int)
            or artifact_id < 1
            or isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id < 1
            or row.get("validation_opened") is not False
            or row.get("locked_opened") is not False
            or not isinstance(expected_head, str)
            or not _COMMIT.fullmatch(expected_head)
        ):
            raise ValueError("CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
        observed = artifact_metadata.get(artifact_id)
        workflow_run = (
            observed.get("workflow_run") if isinstance(observed, Mapping) else None
        )
        if (
            not isinstance(observed, Mapping)
            or observed.get("id") != artifact_id
            or observed.get("name") != row.get("artifact_name")
            or observed.get("size_in_bytes") != row.get("artifact_size_in_bytes")
            or observed.get("digest") != row.get("artifact_digest")
            or observed.get("expired") is not False
            or not isinstance(workflow_run, Mapping)
            or workflow_run.get("id") != run_id
            or workflow_run.get("head_sha") != expected_head
        ):
            raise ValueError("CATALOG_SOURCE_ARTIFACT_METADATA_INVALID")
        normalized.append(
            {
                "contract_name": contract_name,
                "artifact_id": artifact_id,
                "run_id": run_id,
                "artifact_name": row.get("artifact_name"),
                "artifact_size_in_bytes": row.get("artifact_size_in_bytes"),
                "artifact_digest": row.get("artifact_digest"),
                "head_sha": expected_head,
                "validation_opened": False,
                "locked_opened": False,
            }
        )
    normalized_rows = tuple(normalized)
    source_sha = _sha256(source_contract)
    content_sha = _sha256(normalized_rows)
    evidence = CatalogSourceArtifactsEvidenceV1(
        status="ready",
        observed_at=observed_at.astimezone(UTC),
        source_sha256=source_sha,
        content_sha256=content_sha,
        receipt_sha256=_sha256(
            {"source_sha256": source_sha, "content_sha256": content_sha}
        ),
        artifacts_exist=True,
        hashes_bound=True,
        runtime_artifact_fresh=True,
        unexpired_or_verified_mirror=True,
        immutable=True,
        source_artifact_manifest_sha256=source_sha,
        artifact_plan_sha256=content_sha,
    )
    return evidence, normalized_rows


def _download_store_index_archive(
    *,
    repository: str,
    token: str,
    artifact_id: int,
    destination: Path,
) -> bytes:
    if destination.exists() or destination.is_symlink():
        raise ValueError("CATALOG_STORE_INDEX_DOWNLOAD_TARGET_EXISTS")
    environment = dict(os.environ)
    environment["GH_TOKEN"] = token
    with destination.open("xb") as stream:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repository}/actions/artifacts/{artifact_id}/zip",
            ],
            stdout=stream,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
            timeout=120,
        )
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        raise ValueError("CATALOG_STORE_INDEX_DOWNLOAD_FAILED")
    raw = destination.read_bytes()
    if not raw or len(raw) > _MAX_STORE_INDEX_FILE_BYTES:
        raise ValueError("CATALOG_STORE_INDEX_ARCHIVE_SIZE_INVALID")
    return raw


def _store_index_payload_from_archive(path: Path) -> bytes:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise ValueError("CATALOG_STORE_INDEX_ARCHIVE_SHAPE_INVALID")
            member = members[0]
            unix_type = (member.external_attr >> 16) & 0o170000
            if (
                member.is_dir()
                or member.filename != f"{_STORE_INDEX_ARTIFACT_NAME}.json"
                or "\\" in member.filename
                or Path(member.filename).is_absolute()
                or ".." in Path(member.filename).parts
                or unix_type == 0o120000
                or member.file_size < 1
                or member.file_size > _MAX_STORE_INDEX_FILE_BYTES
            ):
                raise ValueError("CATALOG_STORE_INDEX_ARCHIVE_SHAPE_INVALID")
            payload = archive.read(member)
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("CATALOG_STORE_INDEX_ARCHIVE_INVALID") from exc
    if len(payload) > _MAX_STORE_INDEX_FILE_BYTES:
        raise ValueError("CATALOG_STORE_INDEX_FILE_SIZE_INVALID")
    return payload


def load_verified_rebuildable_store_inventory(
    *,
    artifacts: Sequence[Mapping[str, Any]],
    caches: Sequence[Mapping[str, Any]],
    client: CatalogGitHubReadOnlyClient,
    repository: str,
    token: str,
    download_root: Path,
) -> RebuildableStoreInventoryV1:
    """Verify every exact-name index and keep only cache keys still live."""

    if len(artifacts) > _MAX_STORE_INDEX_ARTIFACTS:
        raise ValueError("CATALOG_STORE_INDEX_COUNT_LIMIT_EXCEEDED")
    sizes = tuple(row.get("size_in_bytes") for row in artifacts)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in sizes
    ) or sum(int(value) for value in sizes) > _MAX_STORE_INDEX_TOTAL_BYTES:
        raise ValueError("CATALOG_STORE_INDEX_BYTES_LIMIT_EXCEEDED")
    cache_ids = tuple(row.get("id") for row in caches)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in cache_ids
    ) or len(cache_ids) != len(set(cache_ids)):
        raise ValueError("CATALOG_STORE_CACHE_INVENTORY_INVALID")
    cache_keys = tuple(
        str(row.get("key"))
        for row in caches
        if row.get("ref") == "refs/heads/main"
    )
    if any(not key or key == "None" for key in cache_keys) or len(cache_keys) != len(
        set(cache_keys)
    ):
        raise ValueError("CATALOG_STORE_CACHE_INVENTORY_INVALID")

    if download_root.exists() or download_root.is_symlink():
        raise ValueError("CATALOG_STORE_INDEX_DOWNLOAD_ROOT_EXISTS")
    download_root.mkdir(parents=False)
    indexes: list[CatalogRebuildableStoreIndexV1] = []
    runs: dict[int, Mapping[str, Any]] = {}
    artifact_ids: set[int] = set()
    for metadata in sorted(artifacts, key=lambda row: int(row.get("id", 0))):
        artifact_id = metadata.get("id")
        workflow_run = metadata.get("workflow_run")
        digest = metadata.get("digest")
        if (
            isinstance(artifact_id, bool)
            or not isinstance(artifact_id, int)
            or artifact_id < 1
            or artifact_id in artifact_ids
            or metadata.get("name") != _STORE_INDEX_ARTIFACT_NAME
            or metadata.get("expired") is not False
            or not isinstance(workflow_run, Mapping)
            or not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or not _SHA256.fullmatch(digest.removeprefix("sha256:"))
        ):
            raise ValueError("CATALOG_STORE_INDEX_ARTIFACT_METADATA_INVALID")
        artifact_ids.add(artifact_id)
        archive_path = download_root / f"{artifact_id}.zip"
        archive_bytes = _download_store_index_archive(
            repository=repository,
            token=token,
            artifact_id=artifact_id,
            destination=archive_path,
        )
        if hashlib.sha256(archive_bytes).hexdigest() != digest.removeprefix(
            "sha256:"
        ):
            raise ValueError("CATALOG_STORE_INDEX_ARTIFACT_DIGEST_INVALID")
        index = CatalogRebuildableStoreIndexV1.model_validate(
            _strict_json_bytes(_store_index_payload_from_archive(archive_path))
        )
        run_id = index.writer_run_id
        if run_id not in runs:
            run_raw, _ = client.get_json(
                f"/repos/{repository}/actions/runs/{run_id}"
            )
            runs[run_id] = _mapping(
                run_raw,
                "CATALOG_STORE_INDEX_WRITER_RUN_INVALID",
            )
        run = runs[run_id]
        run_repository = run.get("repository")
        run_repository_name = (
            run_repository.get("full_name")
            if isinstance(run_repository, Mapping)
            else None
        )
        if (
            index.repository != repository
            or workflow_run.get("id") != run_id
            or workflow_run.get("head_branch") != "main"
            or workflow_run.get("head_sha") != index.protected_commit_sha
            or run.get("id") != run_id
            or run.get("run_attempt") != index.writer_run_attempt
            or run.get("path") != index.writer_workflow
            or run.get("head_branch") != "main"
            or run.get("head_sha") != index.protected_commit_sha
            or run.get("status") != "completed"
            or run_repository_name != repository
        ):
            raise ValueError("CATALOG_STORE_INDEX_WRITER_RUN_INVALID")
        indexes.append(index)
    return inventory_from_verified_indexes(
        tuple(indexes),
        live_cache_keys=frozenset(cache_keys),
    )


def _document(document_type: str, payload: object) -> dict[str, object]:
    identity = {
        "schema_version": "1",
        "document_type": document_type,
        "payload": payload,
    }
    return {**identity, "content_sha256": canonical_sha256(identity)}


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical_bytes(value) + b"\n")


def prepare(
    *,
    routing_snapshot_dir: Path,
    repo_root: Path,
    output_dir: Path,
    github_output: Path | None,
) -> dict[str, object]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    runner_temp_value = os.environ.get("RUNNER_TEMP", "")
    if (
        not _REPOSITORY.fullmatch(repository)
        or not _COMMIT.fullmatch(expected_commit)
        or not runner_temp_value
    ):
        raise ValueError("CATALOG_CANDIDATE_INVOCATION_INVALID")
    runner_temp = Path(runner_temp_value).resolve(strict=True)
    root = repo_root.resolve(strict=True)
    snapshot = routing_snapshot_dir.resolve(strict=True)
    resolved_output = output_dir.resolve(strict=False)
    if (
        repo_root.is_symlink()
        or not root.is_dir()
        or routing_snapshot_dir.is_symlink()
        or not snapshot.is_dir()
        or not snapshot.is_relative_to(runner_temp)
        or output_dir.exists()
        or output_dir.is_symlink()
        or not resolved_output.is_relative_to(runner_temp)
    ):
        raise ValueError("CATALOG_CANDIDATE_PATH_INVALID")

    command = CatalogRoutingCommandV1.model_validate(
        _strict_json(snapshot / "routing-command.json")
    )
    protected_head = CatalogProtectedHeadEvidenceV1.model_validate(
        _strict_json(snapshot / "protected-head.json")
    )
    checked_out_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if (
        protected_head.applicable_commit_sha != expected_commit
        or checked_out_commit != expected_commit
    ):
        raise ValueError("CATALOG_CANDIDATE_PROTECTED_COMMIT_MISMATCH")
    event = _mapping(_strict_json(snapshot / "event.json"), "CATALOG_REQUEST_INVALID")
    issue = _mapping(event.get("issue"), "CATALOG_REQUEST_INVALID")
    title = issue.get("title")
    body = issue.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("CATALOG_REQUEST_INVALID")

    registry_path = _safe_repository_file(root, "config/catalog_campaign_registry_v1.json")
    registry = load_catalog_campaign_registry(registry_path)
    actors = _mapping(
        _strict_json(_safe_repository_file(root, "config/catalog_controller_actors_v1.json")),
        "CATALOG_REQUEST_ACTOR_INVALID",
    )
    key_relative = actors.get("requester_public_key_path")
    if not isinstance(key_relative, str):
        raise ValueError("CATALOG_REQUESTER_KEY_UNAVAILABLE")
    request = parse_catalog_run_request(
        title,
        body,
        _safe_repository_file(root, key_relative).read_bytes(),
    )
    if request.request_sha256 != command.request_sha256:
        raise ValueError("CATALOG_CANDIDATE_REQUEST_MISMATCH")
    entry = resolve_catalog_campaign(registry, request.campaign_key, root)
    manifest_path = _safe_repository_file(root, entry.definition_manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = parse_catalog_campaign_definition_bytes(manifest_bytes)
    verified_manifest = verify_catalog_campaign_definition(
        repo_root=root,
        registry_entry=entry,
        manifest=manifest,
    )
    if verified_manifest.campaign_definition_sha256 != request.campaign_definition_sha256:
        raise ValueError("CATALOG_CAMPAIGN_DEFINITION_MISMATCH")

    contract = build_repository_contract(
        repo_root=root,
        policy_path=_safe_repository_file(root, entry.optimization_policy_path),
        campaign_path=_safe_repository_file(root, entry.campaign_contract_path),
        catalog_dir=(root / entry.catalog_dir).resolve(strict=True),
        selected_config_path=_safe_repository_file(root, entry.selected_config_path),
    )
    science_sha256 = canonical_sha256(contract.science)
    if science_sha256 != entry.scientific_contract_sha256:
        raise ValueError("CATALOG_SCIENCE_IDENTITY_MISMATCH")

    catalog_path = _safe_repository_file(root, f"{entry.catalog_dir}/catalog.jsonl")
    catalog_rows = tuple(
        _mapping(json.loads(line), "CATALOG_CANDIDATE_ROW_INVALID")
        for line in catalog_path.read_text("utf-8").splitlines()
        if line
    )
    selected = _strict_json(_safe_repository_file(root, entry.selected_config_path))
    if not isinstance(selected, list):
        raise ValueError("CATALOG_SELECTED_CONFIG_INVALID")
    feature_path = _safe_repository_file(root, entry.feature_contract_path)
    components, recipes = derive_catalog_work_requirements(
        contract=contract,
        catalog_rows=catalog_rows,
        selected_rows=tuple(
            _mapping(row, "CATALOG_SELECTED_CONFIG_INVALID") for row in selected
        ),
        feature_contract_sha256=hashlib.sha256(feature_path.read_bytes()).hexdigest(),
    )

    client = CatalogGitHubReadOnlyClient(repository, token)
    source_contract = _mapping(
        _strict_json(_safe_repository_file(root, "config/catalog_keeper_source_artifacts_v1.json")),
        "CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID",
    )
    raw_source_rows = source_contract.get("artifacts")
    if not isinstance(raw_source_rows, list):
        raise ValueError("CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
    artifact_metadata: dict[int, Mapping[str, object]] = {}
    for raw in raw_source_rows:
        row = _mapping(raw, "CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
        artifact_id = row.get("artifact_id")
        if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
            raise ValueError("CATALOG_SOURCE_ARTIFACT_CONTRACT_INVALID")
        metadata, _response = client.get_json(
            f"/repos/{repository}/actions/artifacts/{artifact_id}"
        )
        artifact_metadata[artifact_id] = _mapping(
            metadata,
            "CATALOG_SOURCE_ARTIFACT_METADATA_INVALID",
        )
    if client.observed_at is None:
        raise ValueError("CATALOG_CANDIDATE_GITHUB_TIME_INVALID")
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
    store_indexes = client.stable_paginated(
        f"/repos/{repository}/actions/artifacts?name={_STORE_INDEX_ARTIFACT_NAME}",
        root="artifacts",
    ).collection
    store_inventory = load_verified_rebuildable_store_inventory(
        artifacts=store_indexes.rows,
        caches=caches.rows,
        client=client,
        repository=repository,
        token=token,
        download_root=runner_temp / "catalog-store-index-downloads",
    )
    store_metadata = {
        "cache_inventory_sha256": caches.collection_sha256,
        "cache_count": len(caches.rows),
        "store_index_inventory_sha256": store_indexes.collection_sha256,
        "store_index_artifact_count": len(store_indexes.rows),
        "authoritative_verified_candidates": len(store_inventory.candidates),
        "cache_is_not_authoritative_evidence": True,
        "cache_keys_require_content_bound_index": True,
    }

    admission_base = _mapping(
        _strict_json(_safe_repository_file(root, entry.admission_evidence_path)),
        "CATALOG_ADMISSION_EVIDENCE_INVALID",
    )
    optimization_ok = (
        float(admission_base.get("estimated_tail_ratio_p99_p50", float("inf")))
        <= contract.limits.max_expected_tail_ratio_p99_p50
        and int(admission_base.get("estimated_result_bytes_per_recipe", 0))
        <= contract.limits.max_result_bytes_per_recipe
        and int(admission_base.get("estimated_peak_memory_bytes", 1))
        / int(admission_base.get("available_memory_bytes", 1))
        <= contract.limits.max_memory_fraction
        and admission_base.get("cache_compatible") is True
        and admission_base.get("manifest_verified") is True
        and admission_base.get("previous_regression_unresolved") is False
        and admission_base.get("workflow_uses_optimized_entrypoint") is True
    )
    science_content = {
        "scientific_contract_sha256": science_sha256,
        "campaign_definition_sha256": verified_manifest.campaign_definition_sha256,
        "contract_sha256": contract.contract_sha256,
        "optimization_admission_verified": optimization_ok,
    }
    science_evidence = CatalogScienceAdmissionEvidenceV1(
        status="ready" if optimization_ok else "blocked",
        observed_at=client.observed_at,
        source_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        content_sha256=_sha256(science_content),
        receipt_sha256=_sha256({"science": science_content}),
        reason_codes=() if optimization_ok else ("CATALOG_OPTIMIZATION_ADMISSION_FAILED",),
        scientific_contract_sha256=science_sha256,
        optimization_admission_verified=optimization_ok,
        science_identity_verified=True,
        data_contract_verified=True,
        feature_contract_verified=True,
        metric_contract_verified=True,
        cache_contract_verified=True,
        component_contract_verified=True,
    )
    protocol_sha256 = _protocol_sha256(
        root=root,
        entry=entry,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
    runtime_identity_sha256 = canonical_sha256(
        {
            "schema_version": "catalog-runtime-identity-v1",
            "runner_image": "ubuntu-24.04",
            "python_abi": "cp311",
            "runtime_mode": contract.runtime_preparation.runtime_mode,
            "lock_sha256": hashlib.sha256(
                _safe_repository_file(root, "requirements/catalog-optimized.lock").read_bytes()
            ).hexdigest(),
        }
    )

    output_dir.mkdir(parents=False, exist_ok=False)
    dag_dir = output_dir / "recipe-dag"
    dag_manifest = write_recipe_dag_artifacts(catalog_path, dag_dir)
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
        "store-inventory.json": _document(
            "catalog_rebuildable_store_inventory_v1",
            {
                "inventory": store_inventory,
                "metadata": store_metadata,
            },
        ),
        "source-artifacts.json": _document(
            "catalog_source_artifacts_v1",
            {
                "evidence": source_evidence,
                "artifacts": normalized_sources,
                "source_contract": source_contract,
            },
        ),
        "science-evidence.json": science_evidence,
        "operational-qualification.json": _strict_json(
            _safe_repository_file(
                root,
                "config/catalog_operational_qualification_v1.json",
            )
        ),
    }
    context = {
        "schema_version": "1",
        "document_type": "catalog_admission_candidates_v1",
        "request_sha256": command.request_sha256,
        "campaign_id": command.campaign_id,
        "campaign_key": entry.campaign_key,
        "applicable_commit_sha": expected_commit,
        "campaign_definition_sha256": verified_manifest.campaign_definition_sha256,
        "campaign_definition_rehash_receipt_sha256": canonical_sha256(
            verified_manifest.model_dump(mode="json")
        ),
        "scientific_contract_sha256": science_sha256,
        "execution_protocol_sha256": protocol_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
        "prepared_input_partition_ids": _PREPARED_PARTITIONS,
        "admission_base": dict(admission_base),
        "logical_recipe_count": len(recipes),
        "unique_component_count": len(components),
        "source_artifact_plan_sha256": source_evidence.artifact_plan_sha256,
        "store_metadata_sha256": _sha256(store_metadata),
        "operational_qualification_sha256": hashlib.sha256(
            _safe_repository_file(
                root,
                "config/catalog_operational_qualification_v1.json",
            ).read_bytes()
        ).hexdigest(),
        "recipe_dag_manifest_sha256": dag_manifest["manifest_sha256"],
        "validation_opened": False,
        "locked_opened": False,
    }
    documents["candidate-context.json"] = {
        **context,
        "content_sha256": canonical_sha256(context),
    }
    for name, value in documents.items():
        _write_json(output_dir / name, value)

    content_manifest = tuple(
        {
            "path": path.relative_to(output_dir).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(
            output_dir.rglob("*"),
            key=lambda item: item.relative_to(output_dir).as_posix(),
        )
        if path.is_file()
    )
    manifest_identity = {
        "schema_version": "1",
        "document_type": "catalog_admission_candidate_manifest_v1",
        "request_sha256": command.request_sha256,
        "campaign_id": command.campaign_id,
        "applicable_commit_sha": expected_commit,
        "execution_protocol_sha256": protocol_sha256,
        "content_manifest": content_manifest,
    }
    candidate_manifest = {
        **manifest_identity,
        "candidate_manifest_sha256": canonical_sha256(manifest_identity),
    }
    _write_json(output_dir / "candidate-manifest.json", candidate_manifest)
    audit_context_sha256 = canonical_sha256(
        {
            "candidate_manifest_sha256": candidate_manifest[
                "candidate_manifest_sha256"
            ],
            "routing_snapshot_sha256": (
                command.prerequisites.routing_snapshot_sha256
            ),
            "execution_commit_sha": expected_commit,
            "controls_commit_sha": protected_head.current_protected_head_sha,
        }
    )
    if github_output is not None:
        if github_output.is_symlink():
            raise ValueError("CATALOG_CANDIDATE_GITHUB_OUTPUT_INVALID")
        values = {
            "audit_context_sha256": audit_context_sha256,
            "candidate_manifest_sha256": candidate_manifest[
                "candidate_manifest_sha256"
            ],
            "execution_protocol_sha256": protocol_sha256,
            "protected_commit_sha": expected_commit,
            "controls_commit_sha": protected_head.current_protected_head_sha,
        }
        with github_output.open("a", encoding="utf-8", newline="\n") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    return candidate_manifest


def main() -> int:
    args = _parser().parse_args()
    try:
        prepare(
            routing_snapshot_dir=args.routing_snapshot_dir,
            repo_root=args.repo_root,
            output_dir=args.output_dir,
            github_output=args.github_output,
        )
        return 0
    except (
        CatalogGitHubSnapshotError,
        ValueError,
        TypeError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
