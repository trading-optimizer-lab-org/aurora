from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypedDict, cast

import pytest
from typing_extensions import NotRequired, Unpack

if TYPE_CHECKING:
    from aurora.infra.github_performance.merge_planner import MergeResourceProjectionV1
    from aurora.infra.sp500_megarun.catalog_capacity_qualification import (
        BundleLayoutQualificationV1,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )
    from aurora.infra.sp500_megarun.catalog_rebuildable_store import (
        RebuildableStoreInventoryV1,
    )
    from scripts.plan_sp500_optimized_catalog_run import (
        CatalogComponentRequirementV1,
        CatalogGlobalReuseExecutionPlanV1,
        CatalogRecipeRequirementV1,
    )


class _PlanKwargs(TypedDict):
    contract: RunOptimizationContractV1
    campaign_id: str
    authority_id: str
    science_sha256: str
    execution_plan_sha256: str
    component_requirements: tuple[CatalogComponentRequirementV1, ...]
    recipes: tuple[CatalogRecipeRequirementV1, ...]
    store_inventory: RebuildableStoreInventoryV1
    runtime_identity_sha256: str
    prepared_input_partition_ids: tuple[str, ...]
    qualifications: tuple[BundleLayoutQualificationV1, ...]
    reduction_projection: MergeResourceProjectionV1
    hierarchical_reduction_projection: MergeResourceProjectionV1
    preparation_only: bool
    hot_checkpoint_upload_seconds_p95: NotRequired[float]
    cached_strategy_ids: NotRequired[tuple[str, ...]]


class _PlanOverrides(TypedDict, total=False):
    contract: RunOptimizationContractV1
    cached_strategy_ids: tuple[str, ...]
    preparation_only: bool
    hot_checkpoint_upload_seconds_p95: float


def _plan_kwargs(*, warm_components: bool = False) -> _PlanKwargs:
    from aurora.infra.github_performance.merge_planner import (
        MergeResourceProjectionV1,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        CatalogComponentIdentityV1,
        RunOptimizationContractV1,
    )
    from aurora.infra.sp500_megarun.catalog_rebuildable_store import (
        RebuildableStoreCandidateV1,
        RebuildableStoreInventoryV1,
    )
    from aurora.tests.test_sp500_catalog_optimization_contract import (
        _task10_contract_payload,
    )
    from scripts.plan_sp500_optimized_catalog_run import (
        CatalogComponentRequirementV1,
        CatalogRecipeRequirementV1,
    )

    contract_payload = _task10_contract_payload()
    execution = contract_payload["execution"]
    assert isinstance(execution, dict)
    contract_payload["execution"] = {**execution, "workers": 4}
    contract = RunOptimizationContractV1.model_validate(contract_payload)

    requirements = tuple(
        CatalogComponentRequirementV1(
            component_id=(
                identity := CatalogComponentIdentityV1(
                    evaluator_sha256="1" * 64,
                    data_snapshot_sha256="2" * 64,
                    numeric_profile_sha256="3" * 64,
                    feature_definition_sha256=f"{ordinal + 10:064x}",
                    parameters_sha256=f"{ordinal + 100:064x}",
                    dtype_sha256="4" * 64,
                    output_schema_sha256="5" * 64,
                )
            ).component_key_sha256,
            identity=identity,
            estimated_bytes=1024 + ordinal,
        )
        for ordinal in range(4)
    )
    recipes = tuple(
        CatalogRecipeRequirementV1(
            strategy_id=f"strategy-{ordinal:03d}",
            component_ids=tuple(
                sorted(
                    (
                        requirements[ordinal % 4].component_id,
                        requirements[(ordinal + 1) % 4].component_id,
                    )
                )
            ),
            estimated_seconds_p99=100.0 + ordinal,
        )
        for ordinal in range(5)
    )
    return {
        "contract": contract,
        "campaign_id": "6" * 64,
        "authority_id": "018f47a2-6e91-7c34-8000-000000000001",
        "science_sha256": "7" * 64,
        "execution_plan_sha256": "8" * 64,
        "component_requirements": requirements,
        "recipes": recipes,
        "store_inventory": RebuildableStoreInventoryV1(
            listing_complete=True,
            source_branch="main",
            candidates=tuple(
                RebuildableStoreCandidateV1(
                    object_family="component",
                    logical_id=item.component_id,
                    identity_sha256=item.identity.component_key_sha256,
                    content_manifest_sha256="a" * 64,
                    content_sha256="b" * 64,
                    storage_kind="actions_cache",
                    status="verified",
                    source_branch="main",
                    cache_key=f"aurora-catalog-v1-{item.component_id}-{'a' * 64}-main",
                    file_hashes=(("signals.npy", "c" * 64),),
                    manifest_verified=True,
                    content_verified=True,
                    scope_verified=True,
                )
                for item in requirements
            ) if warm_components else (),
        ),
        "runtime_identity_sha256": "9" * 64,
        "prepared_input_partition_ids": ("partition-a", "partition-b"),
        "qualifications": (),
        "reduction_projection": MergeResourceProjectionV1(
            timeout_fraction_p99=0.71,
            memory_fraction_p99=0.60,
            disk_fraction_p99=0.60,
            artifact_fraction_p99=0.60,
            download_fraction_p99=0.60,
            input_count_fraction_p99=0.60,
        ),
        "hierarchical_reduction_projection": MergeResourceProjectionV1(
            timeout_fraction_p99=0.40,
            memory_fraction_p99=0.40,
            disk_fraction_p99=0.40,
            artifact_fraction_p99=0.40,
            download_fraction_p99=0.40,
            input_count_fraction_p99=0.40,
        ),
        "preparation_only": True,
    }


def _build_plan(*, warm_components: bool = False,
                **overrides: Unpack[_PlanOverrides]) -> CatalogGlobalReuseExecutionPlanV1:
    from scripts.plan_sp500_optimized_catalog_run import (
        build_global_reuse_execution_plan,
    )

    kwargs = _plan_kwargs(warm_components=warm_components)
    kwargs.update(overrides)
    return build_global_reuse_execution_plan(**kwargs)


def test_cached_recipe_ids_only_remove_pending_assignments() -> None:
    cached = ("strategy-000", "strategy-002")
    plan = _build_plan(cached_strategy_ids=cached)

    assigned = tuple(
        strategy_id
        for assignment in plan.recipe_assignments
        for strategy_id in assignment.strategy_ids
    )
    all_ids = tuple(item.strategy_id for item in plan.recipe_requirements)

    assert tuple(sorted(all_ids)) == tuple(
        f"strategy-{ordinal:03d}" for ordinal in range(5)
    )
    assert set(assigned) == set(all_ids) - set(cached)
    assert len(assigned) == len(set(assigned))
    assert set(assigned).isdisjoint(cached)


@pytest.mark.parametrize("warm_components,preparation_only", [(False, True), (True, True), (True, False)])
def test_all_cached_recipes_emit_no_recipe_workers_or_recipe_bundles(
    warm_components: bool, preparation_only: bool,
) -> None:
    all_ids = tuple(f"strategy-{ordinal:03d}" for ordinal in range(5))
    plan = _build_plan(cached_strategy_ids=all_ids, warm_components=warm_components,
                       preparation_only=preparation_only, hot_checkpoint_upload_seconds_p95=0.1)

    assert tuple(item.strategy_id for item in plan.recipe_requirements) == all_ids
    assert plan.recipe_assignments == ()
    assert plan.recipe_matrix_a == ()
    assert plan.recipe_matrix_b == ()
    assert plan.recipe_matrix_c == ()
    assert plan.component_bundles_per_worker_p50 == 0.0
    assert plan.component_bundles_per_worker_p95 == 0.0
    if warm_components:
        assert plan.projected_worker_component_download_bytes == 0
        assert plan.pending_component_ids == ()
        assert plan.component_download_amplification_p50 == 0.0
        assert plan.component_download_amplification_p95 == 0.0


def test_empty_cached_recipe_ids_preserve_default_plan() -> None:
    default = _build_plan()
    explicit_empty = _build_plan(cached_strategy_ids=())

    assert explicit_empty.model_dump(mode="python") == default.model_dump(mode="python")


@pytest.mark.parametrize("warm_components", [False, True])
@pytest.mark.parametrize("projection", [-1, 0])
def test_active_recipe_workers_reject_nonpositive_download_projection(
    warm_components: bool, projection: int,
) -> None:
    plan = _build_plan(warm_components=warm_components)
    assert plan.recipe_assignments
    payload = plan.model_dump(mode="python")
    payload["projected_worker_component_download_bytes"] = projection
    with pytest.raises(ValueError):
        type(plan).model_validate(payload)


def test_pending_component_workers_reject_zero_download_projection() -> None:
    plan = _build_plan(cached_strategy_ids=tuple(f"strategy-{ordinal:03d}" for ordinal in range(5)))
    assert plan.component_assignments and not plan.recipe_assignments
    payload = plan.model_dump(mode="python")
    payload["projected_worker_component_download_bytes"] = 0
    with pytest.raises(ValueError, match="CATALOG_WORKER_DOWNLOAD_PROJECTION_INVALID"):
        type(plan).model_validate(payload)


@pytest.mark.parametrize("warm_components", [False, True])
@pytest.mark.parametrize("fully_cached", [False, True])
def test_partial_recipe_plan_seals_and_verifies_coherent_work_inputs(
    tmp_path, warm_components: bool, fully_cached: bool,
) -> None:
    from aurora.infra.github_performance.contracts import canonical_sha256
    from aurora.infra.sp500_megarun.catalog_admission import (
        CatalogAdmissionEvidenceV1,
        build_catalog_run_plan,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )
    from aurora.infra.sp500_megarun.catalog_resume import build_resume_work_manifest
    from aurora.tests.test_sp500_catalog_optimization_contract import (
        _controller_binding_values,
        _task10_contract_payload,
    )
    from scripts.plan_sp500_optimized_catalog_run import (
        verify_sealed_global_reuse_execution_plan,
        write_sealed_global_reuse_execution_plan,
    )

    contract_payload = _task10_contract_payload()
    workload = contract_payload["workload"]
    execution = contract_payload["execution"]
    assert isinstance(workload, dict)
    assert isinstance(execution, dict)
    contract_payload["workload"] = {
        **workload,
        "requested_recipes": 5,
        "canonical_recipes": 5,
        "unique_components": 4,
        "expected_new_recipes": 0 if fully_cached else 3,
        "expected_prior_cache_hits": 5 if fully_cached else 2,
        "estimated_position_equivalences": 0,
    }
    contract_payload["execution"] = {**execution, "workers": 4}
    contract = RunOptimizationContractV1.model_validate(contract_payload)
    cached = (tuple(f"strategy-{ordinal:03d}" for ordinal in range(5))
              if fully_cached else ("strategy-000", "strategy-002"))
    plan = _build_plan(contract=contract, cached_strategy_ids=cached,
                       warm_components=warm_components, preparation_only=not warm_components,
                       hot_checkpoint_upload_seconds_p95=0.1)
    all_ids = tuple(item.strategy_id for item in plan.recipe_requirements)
    pending = tuple(item for item in all_ids if item not in cached)

    work_manifest = build_resume_work_manifest(
        all_ids,
        cached_strategy_ids=cached,
        maximum_workers=contract.execution.workers,
    )
    binding_values = _controller_binding_values()
    binding_values.update(
        campaign_id=plan.campaign_id,
        authority_id=plan.authority_id,
        execution_plan_sha256=plan.execution_plan_sha256,
    )
    evidence = CatalogAdmissionEvidenceV1(
        estimated_tail_ratio_p99_p50=1.5,
        estimated_result_bytes_per_recipe=500,
        estimated_peak_memory_bytes=8_000_000_000,
        available_memory_bytes=16_000_000_000,
        cache_compatible=True,
        manifest_verified=True,
        previous_regression_unresolved=False,
        workflow_uses_optimized_entrypoint=True,
        **binding_values,
    )
    run_plan_model = build_catalog_run_plan(
        contract,
        evidence,
        work_manifest_sha256=work_manifest.manifest_sha256,
        pending_recipe_count=len(work_manifest.pending_strategy_ids),
        cached_recipe_count=len(work_manifest.cached_strategy_ids),
    )
    run_plan = run_plan_model.model_dump(mode="json")
    resume_manifest = work_manifest.model_dump(mode="json")
    bindings = {
        "request_sha256": "a" * 64,
        "execution_protocol_sha256": "b" * 64,
        "protected_commit_sha": "c" * 40,
        "decision_sha256": "d" * 64,
        "admission_token_sha256": run_plan_model.admission_token_sha256,
    }
    source_identity = {
        "schema_version": "1",
        "document_type": "catalog_source_artifacts_v1",
        "payload": {
            "artifacts": [
                {
                    "contract_name": "reference_oracle_v1",
                    "run_id": 31948898747,
                    "artifact_id": 9264302413,
                    "artifact_name": "sp500-strategy-catalog-final-results",
                    "artifact_digest": "sha256:" + "f" * 64,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            ]
        },
    }
    source_artifacts = {
        **source_identity,
        "content_sha256": canonical_sha256(source_identity),
    }
    sealed = tmp_path / "sealed"
    receipt = write_sealed_global_reuse_execution_plan(
        output_dir=sealed,
        contract=contract,
        plan=plan,
        **bindings,
        controller_binding={
            "schema_version": "1",
            "request_sha256": bindings["request_sha256"],
            "authority_id": plan.authority_id,
            "campaign_id": plan.campaign_id,
        },
        run_plan=run_plan,
        resume_work_manifest=resume_manifest,
        recipe_dag_bytes=b"PAR1synthetic-recipe-dag",
        recipe_dag_manifest={
            "schema_version": "1",
            "recipe_count": len(all_ids),
            "validation_opened": False,
            "locked_opened": False,
        },
        source_artifacts=source_artifacts,
    )
    verified = verify_sealed_global_reuse_execution_plan(
        sealed,
        expected_bindings={
            **bindings,
            "authority_id": plan.authority_id,
            "campaign_id": plan.campaign_id,
            "science_sha256": plan.science_sha256,
            "execution_plan_sha256": plan.execution_plan_sha256,
        },
    )

    sealed_run_plan = json.loads((sealed / "run_plan.json").read_text("utf-8"))
    sealed_resume = json.loads(
        (sealed / "resume_work_manifest.json").read_text("utf-8")
    )
    logical_manifest = json.loads(
        (sealed / "logical_recipe_manifest.json").read_text("utf-8")
    )
    assert sealed_run_plan["pending_recipe_count"] == len(pending)
    assert sealed_run_plan["cached_recipe_count"] == len(cached)
    assert sealed_run_plan["active_workers"] == len(plan.recipe_assignments)
    assert sealed_run_plan["work_manifest_sha256"] == work_manifest.manifest_sha256
    assert tuple(sealed_resume["all_strategy_ids"]) == all_ids
    assert tuple(sealed_resume["cached_strategy_ids"]) == cached
    assert tuple(sealed_resume["pending_strategy_ids"]) == pending
    assert sealed_resume["active_workers"] == len(plan.recipe_assignments)
    assert logical_manifest["strategy_count"] == len(all_ids)
    assert tuple(row["strategy_id"] for row in logical_manifest["recipes"]) == all_ids
    assert set(cached).isdisjoint(pending)
    assert set(cached) | set(pending) == set(all_ids)
    assert receipt["pending_recipe_count"] == len(pending)
    assert receipt["active_recipe_workers"] == len(plan.recipe_assignments)
    assert verified["receipt_sha256"] == receipt["receipt_sha256"]


@pytest.mark.parametrize(
    ("cached_strategy_ids", "error"),
    [
        (("strategy-missing",), "CATALOG_CACHED_STRATEGY_ID_UNKNOWN"),
        (("strategy-000", "strategy-000"), "CATALOG_CACHED_STRATEGY_ID_DUPLICATE"),
        (["strategy-000"], "CATALOG_CACHED_STRATEGY_IDS_TYPE_INVALID"),
        (("strategy-000", 1), "CATALOG_CACHED_STRATEGY_IDS_TYPE_INVALID"),
    ],
)
def test_cached_recipe_ids_validate_unknown_duplicates_and_types(
    cached_strategy_ids: object,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        # Deliberately bypass static typing to exercise runtime input rejection.
        _build_plan(cached_strategy_ids=cast(tuple[str, ...], cached_strategy_ids))
