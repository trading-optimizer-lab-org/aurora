#!/usr/bin/env python3
"""Turn one verified component-store build into a reusable PREPARED bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from math import ceil
import os
from pathlib import Path
import re
import shutil
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
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogPreparedReceiptV1,
    CatalogPreparationIdentityV1,
    build_catalog_preparation_identity,
)
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    write_prepared_catalog_bundle_manifest,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import (
    CatalogRebuildableStoreIndexV1,
    inventory_from_verified_indexes,
)
from aurora.infra.sp500_megarun.catalog_resume import build_resume_work_manifest
from scripts.compile_sp500_catalog_recipes import verify_recipe_dag_artifacts
from scripts.plan_sp500_optimized_catalog_run import (
    CatalogComponentRequirementV1,
    CatalogRecipeRequirementV1,
    build_global_reuse_execution_plan,
    verify_sealed_global_reuse_execution_plan,
    write_sealed_global_reuse_execution_plan,
)


_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Finalize a content-bound hot catalog bundle."
    )
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--seed-dir", required=True, type=Path)
    parser.add_argument("--store-index", required=True, type=Path)
    parser.add_argument("--checkpoint-upload-seconds-p95", required=True, type=float)
    parser.add_argument("--qualified-workers", required=True, type=int)
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


def _payload(path: Path, document_type: str) -> Mapping[str, Any]:
    document = _mapping(_strict_json(path), "CATALOG_PREPARATION_DOCUMENT_INVALID")
    identity = {key: value for key, value in document.items() if key != "content_sha256"}
    payload = document.get("payload")
    if (
        document.get("schema_version") != "1"
        or document.get("document_type") != document_type
        or document.get("content_sha256") != canonical_sha256(identity)
        or not isinstance(payload, Mapping)
    ):
        raise ValueError("CATALOG_PREPARATION_DOCUMENT_INVALID")
    return payload


def _write_json(path: Path, value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    path.write_text(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _effective_contract(contract: object, workers: int):
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    parsed = RunOptimizationContractV1.model_validate(contract)
    if isinstance(workers, bool) or not 1 <= workers <= 360:
        raise ValueError("CATALOG_WORKER_CEILING_INVALID")
    payload = parsed.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "workers": workers,
        "component_workers": min(
            int(payload["execution"]["component_workers"]),
            workers,
            120,
        ),
    }
    return RunOptimizationContractV1.model_validate(payload)


def conservative_reduction_projections(
    *,
    recipe_count: int,
    workers: int,
    result_bytes_per_recipe: int,
) -> tuple[MergeResourceProjectionV1, MergeResourceProjectionV1]:
    """Use computed size/fan-in ceilings and force the bounded tree by default."""

    if recipe_count < 1 or workers < 1 or result_bytes_per_recipe < 1:
        raise ValueError("CATALOG_REDUCTION_PROJECTION_INVALID")
    recipes_per_worker = ceil(recipe_count / workers)
    group_recipes = min(recipe_count, recipes_per_worker * 24)
    expanded_group_bytes = group_recipes * result_bytes_per_recipe * 8
    hierarchical = MergeResourceProjectionV1(
        timeout_fraction_p99=min(0.69, 600.0 / (30.0 * 60.0)),
        memory_fraction_p99=min(0.69, expanded_group_bytes / (7 * 1024**3)),
        disk_fraction_p99=min(0.69, expanded_group_bytes / (14 * 1024**3)),
        artifact_fraction_p99=min(0.69, expanded_group_bytes / (2 * 1024**3)),
        download_fraction_p99=min(0.69, expanded_group_bytes / (2 * 1024**3)),
        input_count_fraction_p99=min(0.69, min(workers, 24) / 500.0),
    )
    central = MergeResourceProjectionV1(
        timeout_fraction_p99=None,
        memory_fraction_p99=None,
        disk_fraction_p99=None,
        artifact_fraction_p99=None,
        download_fraction_p99=None,
        input_count_fraction_p99=None,
    )
    return central, hierarchical


def _template_bindings(seed: Mapping[str, Any], workers: int) -> dict[str, str]:
    # preparation_key_sha256 is a computed property and therefore is not serialized.
    identity = CatalogPreparationIdentityV1.model_validate(seed.get("identity"))
    preparation_key = identity.preparation_key_sha256
    execution_plan_sha256 = canonical_sha256(
        {
            "schema_version": "catalog-fast-plan-template-v1",
            "preparation_key_sha256": preparation_key,
            "workers": workers,
        }
    )
    decision_sha256 = canonical_sha256(
        {
            "schema_version": "catalog-fast-template-decision-v1",
            "execution_plan_sha256": execution_plan_sha256,
        }
    )
    return {
        "request_sha256": str(seed["request_sha256"]),
        "campaign_id": str(seed["campaign_id"]),
        "authority_id": str(seed["authority_id"]),
        "execution_plan_sha256": execution_plan_sha256,
        "decision_sha256": decision_sha256,
    }


def required_prepared_cache_keys(
    index: CatalogRebuildableStoreIndexV1,
    execution_receipt: Mapping[str, object],
) -> tuple[str, ...]:
    """Bind PREPARED to every runtime, input, and component cache it needs."""

    expected_families = {"runtime", "prepared_input", "component"}
    families = {candidate.object_family for candidate in index.candidates}
    if families != expected_families or any(
        candidate.cache_key is None for candidate in index.candidates
    ):
        raise ValueError("CATALOG_PREPARATION_CACHE_COVERAGE_INVALID")
    indexed_by_family = {
        family: {
            str(candidate.cache_key)
            for candidate in index.candidates
            if candidate.object_family == family
        }
        for family in expected_families
    }
    raw_runtime_key = execution_receipt.get("runtime_cache_key")
    raw_prepared_keys = execution_receipt.get("prepared_input_cache_keys")
    if not isinstance(raw_runtime_key, str) or not raw_runtime_key:
        raise ValueError("CATALOG_PREPARATION_CACHE_COVERAGE_INVALID")
    if not isinstance(raw_prepared_keys, tuple | list) or not raw_prepared_keys:
        raise ValueError("CATALOG_PREPARATION_CACHE_COVERAGE_INVALID")
    prepared_keys: set[str] = set()
    for row in raw_prepared_keys:
        if (
            not isinstance(row, tuple | list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or not row[0]
            or not isinstance(row[1], str)
            or not row[1]
        ):
            raise ValueError("CATALOG_PREPARATION_CACHE_COVERAGE_INVALID")
        prepared_keys.add(row[1])
    if (
        indexed_by_family["runtime"] != {raw_runtime_key}
        or indexed_by_family["prepared_input"] != prepared_keys
        or not indexed_by_family["component"]
    ):
        raise ValueError("CATALOG_PREPARATION_CACHE_COVERAGE_INVALID")
    return tuple(
        sorted(
            indexed_by_family["runtime"]
            | indexed_by_family["prepared_input"]
            | indexed_by_family["component"]
        )
    )


def finalize_preparation(
    *,
    campaign_key: str,
    repo_root: Path,
    seed_dir: Path,
    store_index_path: Path,
    checkpoint_upload_seconds_p95: float,
    qualified_workers: int,
    output_dir: Path,
    github_output: Path | None,
) -> CatalogPreparedReceiptV1:
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
    if (
        not _COMMIT.fullmatch(expected_commit)
        or not runner_temp_raw
        or checkpoint_upload_seconds_p95 < 0
    ):
        raise ValueError("CATALOG_PREPARATION_FINALIZE_INVOCATION_INVALID")
    runner_temp = Path(runner_temp_raw).resolve(strict=True)
    root = repo_root.resolve(strict=True)
    seed = seed_dir.resolve(strict=True)
    index_path = store_index_path.resolve(strict=True)
    target = output_dir.resolve(strict=False)
    if (
        repo_root.is_symlink()
        or seed_dir.is_symlink()
        or not seed.is_dir()
        or not seed.is_relative_to(runner_temp)
        or not index_path.is_relative_to(runner_temp)
        or output_dir.exists()
        or output_dir.is_symlink()
        or not target.is_relative_to(runner_temp)
        or (github_output is not None and github_output.is_symlink())
    ):
        raise ValueError("CATALOG_PREPARATION_FINALIZE_PATH_INVALID")

    seed_context = _mapping(
        _strict_json(seed / "preparation-seed.json"),
        "CATALOG_PREPARATION_SEED_INVALID",
    )
    seed_identity = {key: value for key, value in seed_context.items() if key != "content_sha256"}
    if (
        seed_context.get("schema_version") != "1"
        or seed_context.get("document_type") != "catalog_preparation_seed_v1"
        or seed_context.get("content_sha256") != canonical_sha256(seed_identity)
    ):
        raise ValueError("CATALOG_PREPARATION_SEED_INVALID")
    identity = CatalogPreparationIdentityV1.model_validate(seed_context.get("identity"))
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    entry = resolve_catalog_campaign(registry, campaign_key, root)
    expected_identity = build_catalog_preparation_identity(
        repo_root=root,
        registry_entry=entry,
        protected_commit_sha=expected_commit,
    )
    if identity != expected_identity:
        raise ValueError("CATALOG_PREPARATION_STALE")

    index = CatalogRebuildableStoreIndexV1.model_validate(_strict_json(index_path))
    for field in (
        "protected_commit_sha",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
    ):
        expected = (
            expected_commit
            if field == "protected_commit_sha"
            else seed_context.get(field)
        )
        if getattr(index, field) != expected:
            raise ValueError("CATALOG_PREPARATION_STORE_INDEX_MISMATCH")
    live_keys = frozenset(
        candidate.cache_key
        for candidate in index.candidates
        if candidate.cache_key is not None
    )
    inventory = inventory_from_verified_indexes(
        (index,), live_cache_keys=live_keys,
        runtime_source_commit_sha=expected_commit,
    )

    contract = _effective_contract(_strict_json(seed / "resolved-contract.json"), qualified_workers)
    component_payload = _payload(
        seed / "component-requirements.json",
        "catalog_component_requirements_v1",
    )
    recipe_payload = _payload(
        seed / "recipe-requirements.json",
        "catalog_recipe_requirements_v1",
    )
    components = tuple(
        CatalogComponentRequirementV1.model_validate(item)
        for item in component_payload.get("items", ())
    )
    recipes = tuple(
        CatalogRecipeRequirementV1.model_validate(item)
        for item in recipe_payload.get("items", ())
    )
    if (
        component_payload.get("count") != len(components)
        or recipe_payload.get("count") != len(recipes)
        or not components
        or not recipes
    ):
        raise ValueError("CATALOG_PREPARATION_REQUIREMENTS_INVALID")
    bindings = _template_bindings(seed_context, qualified_workers)
    central, hierarchical = conservative_reduction_projections(
        recipe_count=len(recipes),
        workers=qualified_workers,
        result_bytes_per_recipe=contract.limits.max_result_bytes_per_recipe,
    )
    plan = build_global_reuse_execution_plan(
        contract=contract,
        campaign_id=bindings["campaign_id"],
        authority_id=bindings["authority_id"],
        science_sha256=str(seed_context["science_sha256"]),
        execution_plan_sha256=bindings["execution_plan_sha256"],
        component_requirements=components,
        recipes=recipes,
        store_inventory=inventory,
        runtime_identity_sha256=str(seed_context["runtime_identity_sha256"]),
        prepared_input_partition_ids=tuple(
            str(item) for item in seed_context["prepared_input_partition_ids"]
        ),
        qualifications=(),
        reduction_projection=central,
        hierarchical_reduction_projection=hierarchical,
        preparation_only=False,
        hot_checkpoint_upload_seconds_p95=checkpoint_upload_seconds_p95,
        worker_count_override=qualified_workers,
    )
    if (
        plan.pending_component_ids
        or plan.component_assignments
        or plan.runtime.preparation_required
        or plan.prepared_inputs.preparation_required
    ):
        raise ValueError("CATALOG_PREPARATION_INCOMPLETE")

    work_manifest = build_resume_work_manifest(
        tuple(item.strategy_id for item in recipes),
        cached_strategy_ids=(),
        maximum_workers=qualified_workers,
    )
    evidence_payload = CatalogAdmissionEvidenceV1.model_validate(
        _strict_json(seed / "template-admission-evidence.json")
    ).model_dump(mode="python")
    evidence_payload.update(
        {
            "execution_plan_sha256": bindings["execution_plan_sha256"],
            "capacity_snapshot_sha256": canonical_sha256(
                {
                    "schema_version": "catalog-fast-capacity-v1",
                    "preparation_key_sha256": identity.preparation_key_sha256,
                    "workers": qualified_workers,
                }
            ),
        }
    )
    evidence = CatalogAdmissionEvidenceV1.model_validate(evidence_payload)
    run_plan = build_catalog_run_plan(
        contract,
        evidence,
        work_manifest_sha256=work_manifest.manifest_sha256,
        pending_recipe_count=len(recipes),
        cached_recipe_count=0,
    )
    dag_manifest = verify_recipe_dag_artifacts(
        seed / "recipe-dag/recipe_dag.parquet",
        seed / "recipe-dag/recipe_dag_manifest.json",
    )
    source_document = _mapping(
        _strict_json(seed / "source-artifacts.json"),
        "CATALOG_SOURCE_ARTIFACT_DOCUMENT_INVALID",
    )

    output_dir.mkdir(parents=False, exist_ok=False)
    evidence_dir = output_dir / "evidence"
    evidence_dir.mkdir()
    shutil.copy2(seed / "preparation-seed.json", evidence_dir / "preparation-seed.json")
    shutil.copy2(seed / "runtime-smoke.json", evidence_dir / "runtime-smoke.json")
    shutil.copy2(index_path, evidence_dir / "catalog-rebuildable-store-index-v1.json")
    template_dir = output_dir / f"templates/workers-{qualified_workers:03d}"
    controller_binding = {
        "request_sha256": bindings["request_sha256"],
        "campaign_definition_sha256": identity.campaign_definition_sha256,
        "campaign_id": bindings["campaign_id"],
        "authority_id": bindings["authority_id"],
        "execution_plan_sha256": bindings["execution_plan_sha256"],
        "execution_protocol_sha256": str(seed_context["execution_protocol_sha256"]),
        "protected_commit_sha": expected_commit,
        "preparation_key_sha256": identity.preparation_key_sha256,
    }
    template_receipt = write_sealed_global_reuse_execution_plan(
        output_dir=template_dir,
        contract=contract,
        plan=plan,
        request_sha256=bindings["request_sha256"],
        execution_protocol_sha256=str(seed_context["execution_protocol_sha256"]),
        protected_commit_sha=expected_commit,
        decision_sha256=bindings["decision_sha256"],
        admission_token_sha256=run_plan.admission_token_sha256,
        controller_binding=controller_binding,
        run_plan=run_plan.model_dump(mode="json"),
        resume_work_manifest=work_manifest.model_dump(mode="json"),
        recipe_dag_bytes=(seed / "recipe-dag/recipe_dag.parquet").read_bytes(),
        recipe_dag_manifest=dag_manifest,
        source_artifacts=source_document,
    )
    verify_sealed_global_reuse_execution_plan(
        template_dir,
        expected_bindings={
            "request_sha256": bindings["request_sha256"],
            "authority_id": bindings["authority_id"],
            "campaign_id": bindings["campaign_id"],
            "science_sha256": str(seed_context["science_sha256"]),
            "execution_plan_sha256": bindings["execution_plan_sha256"],
            "execution_protocol_sha256": str(seed_context["execution_protocol_sha256"]),
            "protected_commit_sha": expected_commit,
            "decision_sha256": bindings["decision_sha256"],
        },
    )
    runtime_smoke = _mapping(
        _strict_json(seed / "runtime-smoke.json"),
        "CATALOG_PRODUCTION_RUNTIME_SMOKE_INVALID",
    )
    receipt = CatalogPreparedReceiptV1.create(
        identity=identity,
        generated_at=datetime.now(timezone.utc),
        runtime_identity_sha256=plan.runtime.identity_sha256,
        prepared_input_identity_sha256=plan.prepared_inputs.identity_sha256,
        component_store_manifest_sha256=index.index_sha256,
        execution_plan_template_sha256=plan.plan_sha256,
        required_cache_keys=required_prepared_cache_keys(index, template_receipt),
        logical_recipe_count=len(recipes),
        unique_component_count=len(components),
        qualified_worker_ceiling=qualified_workers,
        production_dependency_smoke_passed=(
            runtime_smoke.get("production_dependency_smoke_passed") is True
        ),
        recipe_worker_build_allowed=False,
    )
    _write_json(output_dir / "prepared-receipt.json", receipt)
    manifest = write_prepared_catalog_bundle_manifest(
        bundle_dir=output_dir,
        prepared_receipt=receipt,
    )
    if github_output is not None:
        values = {
            "prepared_cache_key": (
                f"aurora-catalog-prepared-v1-{identity.preparation_key_sha256}-"
                f"{index.index_sha256}"
            ),
            "prepared_cache_restore_prefix": (
                f"aurora-catalog-prepared-v1-{identity.preparation_key_sha256}-"
            ),
            "prepared_receipt_sha256": receipt.receipt_sha256,
            "prepared_bundle_manifest_sha256": manifest.manifest_sha256,
            "template_request_sha256": bindings["request_sha256"],
            "template_decision_sha256": bindings["decision_sha256"],
            "authority_id": bindings["authority_id"],
            "campaign_id": bindings["campaign_id"],
            "execution_plan_sha256": bindings["execution_plan_sha256"],
        }
        with github_output.open("a", encoding="utf-8", newline="\n") as stream:
            for key, value in values.items():
                if not isinstance(value, str) or "\n" in value:
                    raise ValueError("CATALOG_PREPARATION_OUTPUT_INVALID")
                stream.write(f"{key}={value}\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        finalize_preparation(
            campaign_key=args.campaign_key,
            repo_root=args.repo_root,
            seed_dir=args.seed_dir,
            store_index_path=args.store_index,
            checkpoint_upload_seconds_p95=args.checkpoint_upload_seconds_p95,
            qualified_workers=args.qualified_workers,
            output_dir=args.output_dir,
            github_output=args.github_output,
        )
        return 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
