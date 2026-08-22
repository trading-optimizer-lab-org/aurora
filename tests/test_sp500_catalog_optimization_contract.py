from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _controller_binding_values() -> dict[str, object]:
    return {
        "request_sha256": "0" * 64,
        "prompt_sha256": "1" * 64,
        "source_prompt_sha256": "2" * 64,
        "prompt_migration_sha256": "3" * 64,
        "prompt_policy_sha256": "4" * 64,
        "campaign_registry_sha256": "5" * 64,
        "campaign_definition_manifest_sha256": "6" * 64,
        "campaign_definition_sha256": "7" * 64,
        "campaign_definition_rehash_receipt_sha256": "8" * 64,
        "campaign_id": "9" * 64,
        "authority_id": "018f47a2-6e91-7c34-8000-000000000001",
        "execution_plan_sha256": "a" * 64,
        "execution_protocol_sha256": "b" * 64,
        "protected_commit_sha": "c" * 40,
        "github_controls_sha256": "d" * 64,
        "capacity_snapshot_sha256": "e" * 64,
        "request_queue_snapshot_sha256": "f" * 64,
        "authority_anchor_evidence_sha256": "0" * 64,
    }


def _valid_payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "optimization_mode": "required",
        "allow_unoptimized_run": False,
        "infrastructure_sha256": "f" * 64,
        "science": {
            "evaluator_sha256": "a" * 64,
            "data_snapshot_sha256": "b" * 64,
            "catalog_manifest_sha256": "c" * 64,
            "train_end": "2010-12-31",
            "validation_opened": False,
            "locked_opened": False,
            "numeric_profile": "cpu-f64-v1",
        },
        "workload": {
            "requested_recipes": 37_258,
            "canonical_recipes": 37_258,
            "unique_components": 7_274,
            "expected_new_recipes": 37_258,
            "expected_prior_cache_hits": 0,
            "estimated_position_equivalences": 4_020,
        },
        "execution": {
            "scheduler_version": "weighted-lpt-v1",
            "workers": 360,
            "component_workers": 60,
            "component_processes_per_worker": 1,
            "processes_per_worker": 4,
            "block_size": 256,
            "component_replication_budget": 0,
            "retry_only_unfinished": True,
            "checkpoint_interval_seconds": 120,
        },
        "limits": {
            "max_result_bytes_per_recipe": 512,
            "max_expected_tail_ratio_p99_p50": 2.0,
            "max_redundant_component_build_ratio": 0.01,
            "max_memory_fraction": 0.70,
        },
        "acceptance": {
            "require_reference_equivalence": True,
            "require_cold_and_hot_benchmarks": True,
            "require_verified_manifest": True,
            "max_performance_regression_ratio": 0.05,
        },
        "runtime_preparation": {
            "build_once_per_runtime_identity": True,
            "reuse_verified_runtime_store_required": True,
            "dependency_lock_required": True,
            "worker_network_install_allowed": False,
            "wheelhouse_sha256_required": True,
            "runtime_mode": "offline_wheelhouse",
        },
        "component_store_execution": {
            "build_before_recipe_evaluation": True,
            "global_deduplication": True,
            "recipe_worker_build_allowed": False,
            "exact_component_bundles": True,
            "conflicting_successes_block": True,
            "consumer_hypergraph_partition_required": True,
            "component_download_amplification_receipt_required": True,
            "qualified_bundle_count_required": True,
        },
        "payload_execution": {
            "exact_assignment_member_only": True,
            "exact_data_partitions_only": True,
            "exact_component_bundles_only": True,
            "download_all_attempts_allowed": False,
            "download_all_checkpoints_allowed": False,
        },
        "prepared_input_execution": {
            "prepare_once_per_input_identity": True,
            "reuse_verified_partitions_required": True,
            "partial_store_build_missing_only": True,
            "approximate_substitution_allowed": False,
        },
        "rebuildable_store_execution": {
            "actions_cache_preferred": True,
            "cache_authoritative_evidence_allowed": False,
            "repository_cache_limit_gb": 10,
            "repository_cache_retention_days": 90,
            "paid_cache_storage_allowed": False,
            "component_cache_bundle_count_options": [8, 16, 32, 64, 96, 128],
            "maximum_new_cache_entries_per_campaign": 160,
            "maximum_component_cache_bundles_per_campaign": 128,
            "maximum_cache_upload_requests_per_minute": 160,
            "maximum_cache_download_requests_per_minute": 1200,
            "persistent_duplicate_payload_artifact_allowed": False,
            "same_run_transport_artifact_max_retention_days": 1,
        },
        "recovery_execution": {
            "checkpoint_required": True,
            "checkpoint_slot_options": [1, 2, 4, 8],
            "maximum_unpersisted_seconds_p99": 600,
            "maximum_checkpoint_overhead_fraction_p95": 0.05,
            "valid_work_reuse_required": True,
            "global_rerun_allowed": False,
            "max_same_failure_occurrences": 3,
        },
    }


def test_optimization_contract_is_frozen_and_hash_stable() -> None:
    """Changing JSON key order must not change the admitted scientific plan."""

    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    payload = _valid_payload()
    first = RunOptimizationContractV1.model_validate(payload)
    second = RunOptimizationContractV1.model_validate(dict(reversed(payload.items())))

    assert first.contract_sha256 == second.contract_sha256
    assert first.science.train_end == "2010-12-31"
    assert first.science.validation_opened is False
    assert first.science.locked_opened is False
    with pytest.raises(Exception):
        first.workload.requested_recipes = 1


def test_planner_applies_only_three_sample_science_compatible_autotune(
    tmp_path: Path,
) -> None:
    from aurora.infra.github_performance.contracts import canonical_sha256
    from aurora.infra.sp500_megarun.catalog_autotune import (
        CatalogBenchmarkObservationV1,
        CatalogPerformanceHistoryV1,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )
    from scripts.plan_sp500_optimized_catalog_run import (
        apply_compatible_autotune_history,
    )

    contract = RunOptimizationContractV1.model_validate(_valid_payload())
    science = canonical_sha256(contract.science)
    history = CatalogPerformanceHistoryV1.create()
    for run_id, wall in ((1, 280.0), (2, 276.0), (3, 278.0)):
        history = history.append(
            CatalogBenchmarkObservationV1(
                run_id=run_id,
                head_sha="d" * 40,
                science_identity_sha256=science,
                thermal_state="cold",
                workers=60,
                component_workers=120,
                component_processes_per_worker=4,
                processes_per_worker=1,
                block_size=1,
                wall_seconds=wall,
                peak_memory_fraction=0.05,
                equivalent=True,
            )
        )
    path = tmp_path / "history.json"
    history.write(path)

    tuned, decision = apply_compatible_autotune_history(
        contract,
        history_path=path,
        thermal_state="cold",
    )
    assert decision is not None
    assert tuned.execution.workers == 60
    assert tuned.execution.component_workers == 120
    assert tuned.execution.component_processes_per_worker == 4
    assert tuned.execution.processes_per_worker == 1
    assert tuned.execution.block_size == 1

    untouched, missing = apply_compatible_autotune_history(
        contract,
        history_path=path,
        thermal_state="component_warm",
    )
    assert missing is None
    assert untouched == contract


def test_planner_rolls_back_to_the_fastest_verified_configuration(
    tmp_path: Path,
) -> None:
    """A slower later candidate must never replace the verified winner."""

    from aurora.infra.github_performance.contracts import canonical_sha256
    from aurora.infra.sp500_megarun.catalog_autotune import (
        CatalogBenchmarkObservationV1,
        CatalogPerformanceHistoryV1,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )
    from scripts.plan_sp500_optimized_catalog_run import (
        apply_compatible_autotune_history,
    )

    contract = RunOptimizationContractV1.model_validate(_valid_payload())
    science = canonical_sha256(contract.science)
    history = CatalogPerformanceHistoryV1.create()
    observations = (
        (1, 140.0, 1, 4),
        (2, 142.0, 1, 4),
        (3, 141.0, 1, 4),
        (4, 190.0, 2, 1),
        (5, 188.0, 2, 1),
        (6, 191.0, 2, 1),
    )
    for run_id, wall, processes, component_processes in observations:
        history = history.append(
            CatalogBenchmarkObservationV1(
                run_id=run_id,
                head_sha="e" * 40,
                science_identity_sha256=science,
                thermal_state="cold",
                workers=60,
                component_workers=120,
                component_processes_per_worker=component_processes,
                processes_per_worker=processes,
                block_size=1,
                wall_seconds=wall,
                peak_memory_fraction=0.05,
                equivalent=True,
            )
        )
    path = tmp_path / "history.json"
    history.write(path)

    restored, decision = apply_compatible_autotune_history(
        contract,
        history_path=path,
        thermal_state="cold",
    )

    assert decision is not None
    assert decision.promoted is True
    assert decision.median_wall_seconds == 141.0
    assert restored.execution.processes_per_worker == 1
    assert restored.execution.component_processes_per_worker == 4


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("science", "train_end", "2011-01-01"),
        ("science", "validation_opened", True),
        ("science", "locked_opened", True),
        (None, "allow_unoptimized_run", True),
    ],
)
def test_optimization_contract_rejects_boundary_or_bypass(
    section: str | None,
    field: str,
    value: object,
) -> None:
    """Protected periods and the optimization gate must fail closed."""

    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    payload = _valid_payload()
    target = payload if section is None else payload[section]
    assert isinstance(target, dict)
    target[field] = value

    with pytest.raises(ValueError):
        RunOptimizationContractV1.model_validate(payload)


def test_reduction_consumes_only_the_sealed_plan_and_checkpoint_deltas() -> None:
    workflow = (
        ROOT / ".github/workflows/catalog-optimized-run.yml"
    ).read_text("utf-8")

    assert "Verify and reduce this bounded group" in workflow
    assert "python -m scripts.reduce_sp500_optimized_catalog_group" in workflow
    assert "uses: ./.github/actions/aurora-merge-level" in workflow
    assert "catalog-inputs-root: ${{ runner.temp }}/checkpoint-group" in workflow
    assert "pattern: ${{ matrix.checkpoint_artifact_pattern }}" in workflow
    assert "Merge the sealed bounded reduction groups" in workflow
    assert "python scripts/reduce_sp500_optimized_catalog_run.py" in workflow
    assert "--input-root \"$RUNNER_TEMP/reduction-groups\"" in workflow
    assert "pattern: ${{ needs.engine_verify_sealed_plan.outputs.reduction_artifact_pattern }}" in workflow
    assert "pattern: catalog-checkpoint-*" not in workflow


def test_admission_issues_token_only_for_a_fully_optimized_run() -> None:
    """A plan with unresolved regression or excess memory must not start."""

    from aurora.infra.sp500_megarun.catalog_admission import (
        CatalogAdmissionEvidenceV1,
        admit_catalog_run,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    contract = RunOptimizationContractV1.model_validate(_valid_payload())
    valid_evidence = CatalogAdmissionEvidenceV1(
        estimated_tail_ratio_p99_p50=1.4,
        estimated_result_bytes_per_recipe=400,
        estimated_peak_memory_bytes=7_000_000_000,
        available_memory_bytes=16_000_000_000,
        cache_compatible=True,
        manifest_verified=True,
        previous_regression_unresolved=False,
        workflow_uses_optimized_entrypoint=True,
        **_controller_binding_values(),
    )

    accepted = admit_catalog_run(contract, valid_evidence)
    assert accepted.accepted is True
    assert accepted.violations == ()
    assert accepted.admission_token_sha256 is not None
    assert accepted.expected_physical_component_builds == 7_274
    assert accepted.request_sha256 == valid_evidence.request_sha256
    assert accepted.authority_id == valid_evidence.authority_id

    rejected = admit_catalog_run(
        contract,
        valid_evidence.model_copy(
            update={
                "estimated_peak_memory_bytes": 12_000_000_000,
                "previous_regression_unresolved": True,
            }
        ),
    )
    assert rejected.accepted is False
    assert rejected.admission_token_sha256 is None
    assert rejected.violations == (
        "MEMORY_BUDGET_EXCEEDED",
        "PREVIOUS_REGRESSION_UNRESOLVED",
    )


def test_production_admission_requires_complete_controller_binding() -> None:
    from aurora.infra.sp500_megarun.catalog_admission import (
        CatalogAdmissionEvidenceV1,
    )

    with pytest.raises(ValueError, match="CATALOG_CONTROLLER_BINDING_REQUIRED"):
        CatalogAdmissionEvidenceV1(
            estimated_tail_ratio_p99_p50=1.4,
            estimated_result_bytes_per_recipe=400,
            estimated_peak_memory_bytes=7_000_000_000,
            available_memory_bytes=16_000_000_000,
            cache_compatible=True,
            manifest_verified=True,
            previous_regression_unresolved=False,
            workflow_uses_optimized_entrypoint=True,
        )


def test_legacy_catalog_workflow_must_delegate_to_optimized_entrypoint(
    tmp_path: Path,
) -> None:
    """A public workflow must not retain a direct unguarded evaluate job."""

    from aurora.infra.sp500_megarun.catalog_admission import (
        validate_catalog_entrypoint,
    )

    guarded = tmp_path / "guarded.yml"
    guarded.write_text(
        """
name: guarded
on:
  workflow_dispatch:
jobs:
  optimized:
    uses: ./.github/workflows/catalog-optimized-run.yml
    with:
      commit_sha: ${{ github.sha }}
      runtime_input_run_id: "31418682679"
""".lstrip(),
        "utf-8",
    )
    direct = tmp_path / "direct.yml"
    direct.write_text(
        """
name: direct
on:
  workflow_dispatch:
jobs:
  evaluate:
    runs-on: ubuntu-24.04
    steps:
      - run: python scripts/run_sp500_strategy_catalog_shard.py
""".lstrip(),
        "utf-8",
    )

    assert validate_catalog_entrypoint(guarded) == ()
    assert validate_catalog_entrypoint(direct) == (
        "CATALOG_OPTIMIZED_ENTRYPOINT_REQUIRED",
    )


def test_admitted_plan_covers_every_worker_once() -> None:
    """The immutable plan must not lose or duplicate a GitHub matrix shard."""

    from aurora.infra.sp500_megarun.catalog_admission import (
        CatalogAdmissionEvidenceV1,
        build_catalog_run_plan,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    contract = RunOptimizationContractV1.model_validate(_valid_payload())
    evidence = CatalogAdmissionEvidenceV1(
        estimated_tail_ratio_p99_p50=1.5,
        estimated_result_bytes_per_recipe=500,
        estimated_peak_memory_bytes=8_000_000_000,
        available_memory_bytes=16_000_000_000,
        cache_compatible=True,
        manifest_verified=True,
        previous_regression_unresolved=False,
        workflow_uses_optimized_entrypoint=True,
        **_controller_binding_values(),
    )

    plan = build_catalog_run_plan(contract, evidence)
    flattened = [shard for matrix in plan.matrices for shard in matrix]
    assert flattened == list(range(360))
    assert [len(matrix) for matrix in plan.matrices] == [120, 120, 120]
    assert plan.admission_token_sha256
    assert plan.validation_opened is False
    assert plan.locked_opened is False


def test_admitted_resume_plan_uses_only_active_pending_workers() -> None:
    from aurora.infra.sp500_megarun.catalog_admission import (
        CatalogAdmissionEvidenceV1,
        build_catalog_run_plan,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    contract = RunOptimizationContractV1.model_validate(_valid_payload())
    evidence = CatalogAdmissionEvidenceV1(
        estimated_tail_ratio_p99_p50=1.5,
        estimated_result_bytes_per_recipe=500,
        estimated_peak_memory_bytes=8_000_000_000,
        available_memory_bytes=16_000_000_000,
        cache_compatible=True,
        manifest_verified=True,
        previous_regression_unresolved=False,
        workflow_uses_optimized_entrypoint=True,
        **_controller_binding_values(),
    )
    plan = build_catalog_run_plan(
        contract,
        evidence,
        work_manifest_sha256="f" * 64,
        pending_recipe_count=3,
        cached_recipe_count=37_255,
    )

    assert plan.active_workers == 3
    assert plan.pending_recipe_count == 3
    assert plan.cached_recipe_count == 37_255
    assert [shard for matrix in plan.matrices for shard in matrix] == [0, 1, 2]
    assert plan.work_manifest_sha256 == "f" * 64


def test_plan_script_writes_immutable_plan_and_github_matrices(
    tmp_path: Path,
) -> None:
    """The workflow planner must publish only a successfully admitted plan."""

    from scripts.plan_sp500_optimized_catalog_run import write_catalog_run_plan

    contract_path = tmp_path / "contract.json"
    evidence_path = tmp_path / "evidence.json"
    output_dir = tmp_path / "output"
    github_output = tmp_path / "github-output.txt"
    contract_path.write_text(json.dumps(_valid_payload()), "utf-8")
    evidence_path.write_text(
        json.dumps(
            {
                "estimated_tail_ratio_p99_p50": 1.5,
                "estimated_result_bytes_per_recipe": 500,
                "estimated_peak_memory_bytes": 8_000_000_000,
                "available_memory_bytes": 16_000_000_000,
                "cache_compatible": True,
                "manifest_verified": True,
                "previous_regression_unresolved": False,
                "workflow_uses_optimized_entrypoint": True,
                **_controller_binding_values(),
            }
        ),
        "utf-8",
    )

    plan = write_catalog_run_plan(
        contract_path,
        evidence_path,
        output_dir,
        github_output=github_output,
    )

    written = json.loads((output_dir / "run_plan.json").read_text("utf-8"))
    assert written["admission_token_sha256"] == plan.admission_token_sha256
    assert written["validation_opened"] is False
    assert written["locked_opened"] is False
    github_lines = github_output.read_text("utf-8").splitlines()
    assert github_lines[0].startswith('matrix_a={"shard":[0,1,2')
    assert github_lines[1].startswith('matrix_b={"shard":[120,121')
    assert github_lines[2].startswith('matrix_c={"shard":[240,241')
    assert github_lines[3] == f"admission_token_sha256={plan.admission_token_sha256}"


def test_repository_contract_is_derived_from_authoritative_artifacts() -> None:
    """A caller must not be able to invent catalog or snapshot identities."""

    from scripts.plan_sp500_optimized_catalog_run import (
        build_repository_contract,
    )

    contract = build_repository_contract(
        repo_root=ROOT,
        policy_path=ROOT / "config/sp500_catalog_optimization_policy_v1.json",
        campaign_path=ROOT / "config/sp500_megarun_dehb_campaign_v1.json",
        catalog_dir=ROOT / "config/sp500_megarun_strategy_catalog_v1",
    )

    assert contract.workload.requested_recipes == 37_258
    assert contract.workload.canonical_recipes == 37_258
    assert contract.workload.unique_components == 7_281
    assert contract.science.train_end == "2010-12-31"
    assert contract.science.validation_opened is False
    assert contract.science.locked_opened is False
    assert len(contract.science.evaluator_sha256) == 64
    assert len(contract.infrastructure_sha256) == 64
    assert len(contract.science.data_snapshot_sha256) == 64
    assert len(contract.science.catalog_manifest_sha256) == 64
    from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
        numeric_runtime_profile_sha256,
    )

    assert contract.science.numeric_profile == numeric_runtime_profile_sha256()


def test_catalog_scientific_workers_enforce_frozen_numeric_runtime() -> None:
    from aurora.infra.github_performance.preflight import load_github_yaml
    from aurora.infra.sp500_megarun.dehb_numeric_runtime import DEHB_NUMERIC_ENV

    workflows = (
        ROOT / ".github/workflows/catalog-component-worker.yml",
        ROOT / ".github/workflows/catalog-optimized-worker.yml",
        ROOT / ".github/workflows/catalog-reference-worker.yml",
    )
    for path in workflows:
        payload = load_github_yaml(path)
        job = next(iter(payload["jobs"].values()))
        assert all(job["env"].get(key) == value for key, value in DEHB_NUMERIC_ENV.items())
    assert "verify_numeric_runtime_environment" in (
        ROOT / "scripts/build_sp500_component_store.py"
    ).read_text("utf-8")
    assert "verify_numeric_runtime_environment" in (
        ROOT / "scripts/run_sp500_optimized_recipe_worker.py"
    ).read_text("utf-8")
    assert "verify_numeric_runtime_environment" in (
        ROOT / "scripts/run_sp500_strategy_catalog_shard.py"
    ).read_text("utf-8")


def test_repository_workflows_have_one_guarded_public_entrypoint() -> None:
    """Legacy launchers stay closed and the engine is workflow-call only."""

    from aurora.infra.github_performance.preflight import load_github_yaml
    from aurora.infra.sp500_megarun.catalog_admission import (
        validate_catalog_entrypoint,
    )

    legacy = ROOT / ".github/workflows/sp500-strategy-catalog-overnight.yml"
    optimized = ROOT / ".github/workflows/catalog-optimized-run.yml"

    assert validate_catalog_entrypoint(legacy) == (
        "CATALOG_OPTIMIZED_ENTRYPOINT_REQUIRED",
    )
    payload = load_github_yaml(optimized)
    assert set(payload["on"]) == {"workflow_call"}
    jobs = payload["jobs"]
    assert isinstance(jobs, dict)
    assert "engine_verify_sealed_plan" in jobs
    assert "verify_component_store" in jobs
    evaluate_jobs = [name for name in jobs if str(name).startswith("evaluate_")]
    assert evaluate_jobs == ["evaluate_a", "evaluate_b", "evaluate_c"]
    for name in evaluate_jobs:
        job = jobs[name]
        assert set(job["needs"]) == {
            "engine_verify_sealed_plan",
            "verify_component_store",
        }
        serialized = json.dumps(job, sort_keys=True)
        assert "admission_token_sha256" in serialized
    assert set(jobs["reduce_groups"]["needs"]) == {
        "engine_verify_sealed_plan",
        "ready_to_merge",
    }
    assert set(jobs["reduce"]["needs"]) == {
        "engine_verify_sealed_plan",
        "verify_component_store",
        "reduce_groups",
    }


def test_dynamic_workers_receive_only_compact_typed_matrix_routes() -> None:
    """Worker counts are sealed in descriptors instead of mutable call inputs."""

    from aurora.infra.github_performance.preflight import load_github_yaml

    workflow = load_github_yaml(
        ROOT / ".github/workflows/catalog-optimized-run.yml"
    )
    for name in ("evaluate_a", "evaluate_b", "evaluate_c"):
        job = workflow["jobs"][name]
        assert job["strategy"]["matrix"].startswith("${{ fromJSON(")
        assert job["with"]["worker_id"] == "${{ matrix.worker_id }}"
        assert "active_workers" not in job["with"]
        assert {
            "descriptor_bundle_artifact",
            "descriptor_member",
            "descriptor_sha256",
        } <= set(job["with"])


def test_worker_benchmark_override_is_allowed_only_for_qualification() -> None:
    """A measured worker candidate must never become a production bypass."""

    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )
    from scripts.plan_sp500_optimized_catalog_run import (
        apply_qualification_process_override,
        apply_qualification_component_process_override,
        apply_qualification_component_worker_override,
        apply_qualification_worker_override,
    )

    contract = RunOptimizationContractV1.model_validate(_valid_payload())
    selected = apply_qualification_worker_override(
        contract,
        workers=60,
        qualification_only=True,
    )
    assert selected.execution.workers == 60
    assert (
        selected.execution.processes_per_worker
        == contract.execution.processes_per_worker
    )
    with pytest.raises(ValueError, match="WORKER_OVERRIDE_REQUIRES_QUALIFICATION"):
        apply_qualification_worker_override(
            contract,
            workers=60,
            qualification_only=False,
        )
    with pytest.raises(ValueError, match="WORKER_OVERRIDE_INVALID"):
        apply_qualification_worker_override(
            contract,
            workers=0,
            qualification_only=True,
        )

    process_selected = apply_qualification_process_override(
        contract,
        processes_per_worker=4,
        qualification_only=True,
    )
    assert process_selected.execution.processes_per_worker == 4
    assert process_selected.execution.workers == contract.execution.workers
    assert (
        process_selected.execution.component_processes_per_worker
        == contract.execution.component_processes_per_worker
    )
    with pytest.raises(ValueError, match="PROCESS_OVERRIDE_REQUIRES_QUALIFICATION"):
        apply_qualification_process_override(
            contract,
            processes_per_worker=2,
            qualification_only=False,
        )
    with pytest.raises(ValueError, match="PROCESS_OVERRIDE_INVALID"):
        apply_qualification_process_override(
            contract,
            processes_per_worker=3,
            qualification_only=True,
        )

    component_selected = apply_qualification_component_process_override(
        contract,
        component_processes_per_worker=4,
        qualification_only=True,
    )
    assert component_selected.execution.component_processes_per_worker == 4
    assert (
        component_selected.execution.processes_per_worker
        == contract.execution.processes_per_worker
    )
    with pytest.raises(
        ValueError,
        match="COMPONENT_PROCESS_OVERRIDE_REQUIRES_QUALIFICATION",
    ):
        apply_qualification_component_process_override(
            contract,
            component_processes_per_worker=2,
            qualification_only=False,
        )
    with pytest.raises(ValueError, match="COMPONENT_PROCESS_OVERRIDE_INVALID"):
        apply_qualification_component_process_override(
            contract,
            component_processes_per_worker=3,
            qualification_only=True,
        )

    component_worker_selected = apply_qualification_component_worker_override(
        contract,
        component_workers=120,
        qualification_only=True,
    )
    assert component_worker_selected.execution.component_workers == 120
    assert component_worker_selected.execution.workers == contract.execution.workers
    with pytest.raises(
        ValueError,
        match="COMPONENT_WORKER_OVERRIDE_REQUIRES_QUALIFICATION",
    ):
        apply_qualification_component_worker_override(
            contract,
            component_workers=120,
            qualification_only=False,
        )
    with pytest.raises(ValueError, match="COMPONENT_WORKER_OVERRIDE_INVALID"):
        apply_qualification_component_worker_override(
            contract,
            component_workers=121,
            qualification_only=True,
        )

    workflow = (
        ROOT / ".github/workflows/catalog-optimized-run.yml"
    ).read_text("utf-8")
    for forbidden in (
        "benchmark_workers:",
        "--benchmark-workers",
        "benchmark_processes:",
        "--benchmark-processes",
        "benchmark_component_processes:",
        "--benchmark-component-processes",
        "benchmark_component_workers:",
        "--benchmark-component-workers",
    ):
        assert forbidden not in workflow


def test_worker_admission_rejects_wrong_token_or_partition(tmp_path: Path) -> None:
    """Every worker must prove it belongs to the frozen admitted plan."""

    from aurora.infra.sp500_megarun.catalog_admission import (
        CatalogAdmissionEvidenceV1,
        build_catalog_run_plan,
        verify_catalog_worker_admission,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    contract = RunOptimizationContractV1.model_validate(_valid_payload())
    evidence = CatalogAdmissionEvidenceV1(
        estimated_tail_ratio_p99_p50=1.5,
        estimated_result_bytes_per_recipe=500,
        estimated_peak_memory_bytes=8_000_000_000,
        available_memory_bytes=16_000_000_000,
        cache_compatible=True,
        manifest_verified=True,
        previous_regression_unresolved=False,
        workflow_uses_optimized_entrypoint=True,
        **_controller_binding_values(),
    )
    plan = build_catalog_run_plan(contract, evidence)
    plan_path = tmp_path / "run_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), "utf-8")

    verified = verify_catalog_worker_admission(
        plan_path,
        admission_token_sha256=plan.admission_token_sha256,
        shard_index=359,
        total_shards=360,
    )
    assert verified.contract_sha256 == contract.contract_sha256
    with pytest.raises(ValueError, match="CATALOG_ADMISSION_TOKEN_INVALID"):
        verify_catalog_worker_admission(
            plan_path,
            admission_token_sha256="0" * 64,
            shard_index=359,
            total_shards=360,
        )
    with pytest.raises(ValueError, match="CATALOG_PLAN_PARTITION_INVALID"):
        verify_catalog_worker_admission(
            plan_path,
            admission_token_sha256=plan.admission_token_sha256,
            shard_index=360,
            total_shards=360,
        )


def test_qualification_is_explicit_and_cannot_be_mistaken_for_production() -> None:
    """A first full equivalence run may measure gates but remains unpromoted."""

    from aurora.infra.sp500_megarun.catalog_admission import (
        CatalogAdmissionEvidenceV1,
        admit_catalog_run,
        build_catalog_run_plan,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    contract = RunOptimizationContractV1.model_validate(_valid_payload())
    evidence = CatalogAdmissionEvidenceV1(
        estimated_tail_ratio_p99_p50=3.5,
        estimated_result_bytes_per_recipe=4000,
        estimated_peak_memory_bytes=8_000_000_000,
        available_memory_bytes=16_000_000_000,
        cache_compatible=False,
        manifest_verified=True,
        previous_regression_unresolved=False,
        workflow_uses_optimized_entrypoint=True,
        qualification_only=True,
    )

    report = admit_catalog_run(contract, evidence)
    plan = build_catalog_run_plan(contract, evidence)
    assert report.accepted is True
    assert report.qualification_only is True
    assert plan.qualification_only is True


def _task10_contract_payload() -> dict[str, object]:
    payload = _valid_payload()
    payload.update(
        {
            "runtime_preparation": {
                "build_once_per_runtime_identity": True,
                "reuse_verified_runtime_store_required": True,
                "dependency_lock_required": True,
                "worker_network_install_allowed": False,
                "wheelhouse_sha256_required": True,
                "runtime_mode": "offline_wheelhouse",
            },
            "component_store_execution": {
                "build_before_recipe_evaluation": True,
                "global_deduplication": True,
                "recipe_worker_build_allowed": False,
                "exact_component_bundles": True,
                "conflicting_successes_block": True,
                "consumer_hypergraph_partition_required": True,
                "component_download_amplification_receipt_required": True,
                "qualified_bundle_count_required": True,
            },
            "payload_execution": {
                "exact_assignment_member_only": True,
                "exact_data_partitions_only": True,
                "exact_component_bundles_only": True,
                "download_all_attempts_allowed": False,
                "download_all_checkpoints_allowed": False,
            },
            "prepared_input_execution": {
                "prepare_once_per_input_identity": True,
                "reuse_verified_partitions_required": True,
                "partial_store_build_missing_only": True,
                "approximate_substitution_allowed": False,
            },
            "rebuildable_store_execution": {
                "actions_cache_preferred": True,
                "cache_authoritative_evidence_allowed": False,
                "repository_cache_limit_gb": 10,
                "repository_cache_retention_days": 90,
                "paid_cache_storage_allowed": False,
                "component_cache_bundle_count_options": [8, 16, 32, 64, 96, 128],
                "maximum_new_cache_entries_per_campaign": 160,
                "maximum_component_cache_bundles_per_campaign": 128,
                "maximum_cache_upload_requests_per_minute": 160,
                "maximum_cache_download_requests_per_minute": 1200,
                "persistent_duplicate_payload_artifact_allowed": False,
                "same_run_transport_artifact_max_retention_days": 1,
            },
            "recovery_execution": {
                "checkpoint_required": True,
                "checkpoint_slot_options": [1, 2, 4, 8],
                "maximum_unpersisted_seconds_p99": 600,
                "maximum_checkpoint_overhead_fraction_p95": 0.05,
                "valid_work_reuse_required": True,
                "global_rerun_allowed": False,
                "max_same_failure_occurrences": 3,
            },
        }
    )
    return payload


def test_task10_contract_is_closed_and_rejects_weakened_store_options() -> None:
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )

    contract = RunOptimizationContractV1.model_validate(_task10_contract_payload())
    assert contract.runtime_preparation.worker_network_install_allowed is False
    assert contract.component_store_execution.recipe_worker_build_allowed is False
    assert contract.payload_execution.exact_component_bundles_only is True
    assert contract.prepared_input_execution.partial_store_build_missing_only is True
    assert contract.rebuildable_store_execution.component_cache_bundle_count_options == (
        8,
        16,
        32,
        64,
        96,
        128,
    )
    assert contract.recovery_execution.checkpoint_slot_options == (1, 2, 4, 8)

    weakened = _task10_contract_payload()
    weakened["rebuildable_store_execution"] = {
        **weakened["rebuildable_store_execution"],
        "component_cache_bundle_count_options": [8, 16, 32, 64, 128],
    }
    with pytest.raises(ValueError):
        RunOptimizationContractV1.model_validate(weakened)

    weakened = _task10_contract_payload()
    weakened["recovery_execution"] = {
        **weakened["recovery_execution"],
        "checkpoint_slot_options": [1, 2, 8],
    }
    with pytest.raises(ValueError):
        RunOptimizationContractV1.model_validate(weakened)


def _task10_plan_fixture(
    *,
    warm_component_ordinals: set[int],
    warm_bundle_groups: tuple[tuple[int, ...], ...] = (),
    central_reduction_safe: bool = False,
):
    from aurora.infra.github_performance.merge_planner import (
        MergeResourceProjectionV1,
    )
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        CatalogComponentIdentityV1,
        RunOptimizationContractV1,
    )
    from scripts.plan_sp500_optimized_catalog_run import (
        BundleLayoutQualificationV1,
        CatalogComponentRequirementV1,
        CatalogRecipeRequirementV1,
        RebuildableStoreCandidateV1,
        RebuildableStoreInventoryV1,
        build_global_reuse_execution_plan,
    )

    contract = RunOptimizationContractV1.model_validate(_task10_contract_payload())
    requirements = []
    for ordinal in range(12):
        identity = CatalogComponentIdentityV1(
            evaluator_sha256="1" * 64,
            data_snapshot_sha256="2" * 64,
            numeric_profile_sha256="3" * 64,
            feature_definition_sha256=f"{ordinal + 10:064x}",
            parameters_sha256=f"{ordinal + 100:064x}",
            dtype_sha256="4" * 64,
            output_schema_sha256="5" * 64,
        )
        requirements.append(
            CatalogComponentRequirementV1(
                component_id=identity.component_key_sha256,
                identity=identity,
                estimated_bytes=1024 + ordinal,
            )
        )
    recipes = tuple(
        CatalogRecipeRequirementV1(
            strategy_id=f"strategy-{ordinal:03d}",
            component_ids=tuple(
                sorted(
                    (
                        requirements[ordinal % 12].component_id,
                        requirements[(ordinal + 1) % 12].component_id,
                    )
                )
            ),
            estimated_seconds_p99=840.0,
        )
        for ordinal in range(24)
    )
    candidates = []
    grouped_ordinals = {item for group in warm_bundle_groups for item in group}
    for group_index, group in enumerate(warm_bundle_groups):
        bundle_identity = f"{group_index + 700:064x}"
        content_manifest = f"{group_index + 800:064x}"
        logical_ids = tuple(
            sorted(requirements[ordinal].component_id for ordinal in group)
        )
        candidates.append(
            RebuildableStoreCandidateV1(
                object_family="component",
                logical_id=f"bundle-{group_index:03d}",
                identity_sha256=bundle_identity,
                content_manifest_sha256=content_manifest,
                content_sha256=f"{group_index + 900:064x}",
                storage_kind="actions_cache",
                status="verified",
                source_branch="main",
                contained_logical_ids=logical_ids,
                logical_identity_bindings=tuple(
                    (
                        component_id,
                        requirements[ordinal].identity.component_key_sha256,
                    )
                    for component_id, ordinal in sorted(
                        (
                            (requirements[ordinal].component_id, ordinal)
                            for ordinal in group
                        )
                    )
                ),
                cache_key=(
                    f"aurora-catalog-v1-{bundle_identity}-"
                    f"{content_manifest}-main"
                ),
                file_hashes=(("component_bundle_manifest.json", "f" * 64),),
                manifest_verified=True,
                content_verified=True,
                scope_verified=True,
            )
        )
    for ordinal in sorted(warm_component_ordinals - grouped_ordinals):
        requirement = requirements[ordinal]
        content_manifest = f"{ordinal + 300:064x}"
        candidates.append(
            RebuildableStoreCandidateV1(
                object_family="component",
                logical_id=requirement.component_id,
                identity_sha256=requirement.identity.component_key_sha256,
                content_manifest_sha256=content_manifest,
                content_sha256=f"{ordinal + 400:064x}",
                storage_kind="actions_cache",
                status="verified",
                source_branch="main",
                cache_key=(
                    "aurora-catalog-v1-"
                    f"{requirement.identity.component_key_sha256}-"
                    f"{content_manifest}-main"
                ),
                file_hashes=(("signals.npy", f"{ordinal + 500:064x}"),),
                manifest_verified=True,
                content_verified=True,
                scope_verified=True,
            )
        )
    inventory = RebuildableStoreInventoryV1(
        listing_complete=True,
        source_branch="main",
        candidates=tuple(candidates),
    )
    qualifications = tuple(
        BundleLayoutQualificationV1(
            bundle_count=count,
            equivalent=True,
            sample_count=3,
            memory_safe=True,
            disk_safe=True,
            runner_timeout_safe=True,
            projected_end_to_end_p50_seconds=1000.0 + count,
            projected_end_to_end_p95_seconds=1100.0 + count,
            projected_component_download_bytes=1_000_000 + count,
            projected_cache_uploads_per_minute=10,
            projected_cache_downloads_per_minute=100,
            checkpoint_upload_seconds_p95=5.0,
        )
        for count in (8, 16, 32, 64, 96, 128)
    )
    return build_global_reuse_execution_plan(
        contract=contract,
        campaign_id="6" * 64,
        authority_id="018f47a2-6e91-7c34-8000-000000000001",
        science_sha256="7" * 64,
        execution_plan_sha256="8" * 64,
        component_requirements=tuple(requirements),
        recipes=recipes,
        store_inventory=inventory,
        runtime_identity_sha256="9" * 64,
        prepared_input_partition_ids=("partition-a", "partition-b"),
        qualifications=qualifications,
        reduction_projection=MergeResourceProjectionV1(
            timeout_fraction_p99=0.60 if central_reduction_safe else 0.71,
            memory_fraction_p99=0.60,
            disk_fraction_p99=0.60,
            artifact_fraction_p99=0.60,
            download_fraction_p99=0.60,
            input_count_fraction_p99=0.60,
        ),
        hierarchical_reduction_projection=MergeResourceProjectionV1(
            timeout_fraction_p99=0.40,
            memory_fraction_p99=0.40,
            disk_fraction_p99=0.40,
            artifact_fraction_p99=0.40,
            download_fraction_p99=0.40,
            input_count_fraction_p99=0.40,
        ),
    )


def test_cold_campaign_builds_each_unique_component_once_before_recipes() -> None:
    plan = _task10_plan_fixture(warm_component_ordinals=set())
    assert set(plan.pending_component_ids) == set(plan.required_component_ids)
    assert plan.cached_component_ids == ()
    assert plan.recipe_jobs_depend_on_component_store is True
    assigned = [
        component_id
        for assignment in plan.component_assignments
        for component_id in assignment.component_ids
    ]
    assert sorted(assigned) == sorted(plan.required_component_ids)
    assert len(assigned) == len(set(assigned))


def test_warm_campaign_schedules_zero_component_compute() -> None:
    plan = _task10_plan_fixture(warm_component_ordinals=set(range(12)))
    assert plan.pending_component_ids == ()
    assert set(plan.cached_component_ids) == set(plan.required_component_ids)
    assert plan.component_matrix_a == ()
    assert plan.component_matrix_b == ()
    assert plan.component_assignments == ()
    assert plan.recipe_jobs_depend_on_component_store is True


def test_warm_component_bundles_are_restored_once_per_exact_group() -> None:
    plan = _task10_plan_fixture(
        warm_component_ordinals=set(range(12)),
        warm_bundle_groups=(tuple(range(6)), tuple(range(6, 12))),
    )
    assert plan.pending_component_ids == ()
    assert len(plan.cached_component_assignments) == 2
    assert sorted(
        component_id
        for assignment in plan.cached_component_assignments
        for component_id in assignment.component_ids
    ) == sorted(plan.required_component_ids)
    assert plan.component_cache_bundle_count == 2


def test_partial_store_builds_only_verified_missing_components() -> None:
    plan = _task10_plan_fixture(warm_component_ordinals={0, 2, 4, 6, 8, 10})
    assert set(plan.pending_component_ids).isdisjoint(plan.cached_component_ids)
    assert set(plan.pending_component_ids) | set(plan.cached_component_ids) == set(
        plan.required_component_ids
    )
    assigned = [
        component_id
        for assignment in plan.component_assignments
        for component_id in assignment.component_ids
    ]
    assert set(assigned) == set(plan.pending_component_ids)
    assert len(assigned) == len(set(assigned))
    recipe_ids = [
        strategy_id
        for assignment in plan.recipe_assignments
        for strategy_id in assignment.strategy_ids
    ]
    assert len(recipe_ids) == len(set(recipe_ids)) == 24
    assert plan.matrix_output_utf16_bytes <= 512 * 1024
    assert plan.component_cache_bundle_count <= 128
    assert plan.new_cache_entry_count <= 160


def test_catalog_reduction_selects_central_only_with_complete_margin() -> None:
    hierarchical = _task10_plan_fixture(
        warm_component_ordinals=set(),
        central_reduction_safe=False,
    )
    central = _task10_plan_fixture(
        warm_component_ordinals=set(),
        central_reduction_safe=True,
    )

    assert hierarchical.reduction_selection.mode == "hierarchical"
    assert central.reduction_selection.mode == "central"


def test_sealed_global_plan_is_complete_deterministic_and_byte_verified(
    tmp_path: Path,
) -> None:
    from aurora.infra.github_performance.contracts import canonical_sha256
    from aurora.infra.sp500_megarun.catalog_optimization_contract import (
        RunOptimizationContractV1,
    )
    from scripts.plan_sp500_optimized_catalog_run import (
        verify_sealed_global_reuse_execution_plan,
        write_sealed_global_reuse_execution_plan,
    )

    plan = _task10_plan_fixture(warm_component_ordinals={0, 2, 4})
    contract = RunOptimizationContractV1.model_validate(_task10_contract_payload())
    bindings = {
        "request_sha256": "a" * 64,
        "execution_protocol_sha256": "b" * 64,
        "protected_commit_sha": "c" * 40,
        "decision_sha256": "d" * 64,
        "admission_token_sha256": "e" * 64,
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
    common = {
        "contract": contract,
        "plan": plan,
        **bindings,
        "controller_binding": {
            "schema_version": "1",
            "request_sha256": bindings["request_sha256"],
            "authority_id": plan.authority_id,
            "campaign_id": plan.campaign_id,
        },
        "run_plan": {
            "schema_version": "1",
            "admission_token_sha256": bindings["admission_token_sha256"],
        },
        "resume_work_manifest": {
            "schema_version": "1",
            "pending_strategy_ids": [
                item.strategy_id for item in plan.recipe_requirements
            ],
        },
        "recipe_dag_bytes": b"PAR1synthetic-recipe-dag",
        "recipe_dag_manifest": {
            "schema_version": "1",
            "recipe_count": len(plan.recipe_requirements),
            "validation_opened": False,
            "locked_opened": False,
        },
        "source_artifacts": source_artifacts,
    }
    first = tmp_path / "first"
    second = tmp_path / "second"
    receipt = write_sealed_global_reuse_execution_plan(
        output_dir=first,
        **common,
    )
    write_sealed_global_reuse_execution_plan(output_dir=second, **common)

    first_tree = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    second_tree = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert first_tree == second_tree
    assert {
        "resolved_contract.json",
        "controller_binding.json",
        "rebuildable_store_plan.json",
        "logical_recipe_manifest.json",
        "component_requirement_manifest.json",
        "component_store_input_manifest.json",
        "pending_component_manifest.json",
        "cached_component_manifest.json",
        "component_matrix_a.json",
        "component_matrix_b.json",
        "cached_component_matrix_a.json",
        "cached_component_matrix_b.json",
        "recipe_assignment_bundle.zip",
        "recipe_matrix_a.json",
        "recipe_matrix_b.json",
        "recipe_matrix_c.json",
        "payload_bundle_manifest.json",
        "checkpoint_policy.json",
        "reduction_plan.json",
        "artifact_plan.json",
        "source_artifacts.json",
        "execution_plan_receipt.json",
    } <= set(first_tree)
    assert receipt["content_manifest"]
    verified = verify_sealed_global_reuse_execution_plan(
        first,
        expected_bindings={
            **bindings,
            "authority_id": plan.authority_id,
            "campaign_id": plan.campaign_id,
            "science_sha256": plan.science_sha256,
            "execution_plan_sha256": plan.execution_plan_sha256,
        },
    )
    assert verified["receipt_sha256"] == receipt["receipt_sha256"]

    reduction = json.loads((first / "reduction_plan.json").read_text("utf-8"))
    assert reduction["selected_mode"] == "hierarchical"
    assert reduction["nodes"]
    assert all(
        max(node["resource_projection_p99"].values()) <= 0.70
        for node in reduction["nodes"]
    )
    groups = reduction["groups"]
    worker_ids = [
        worker_id
        for group in groups
        for worker_id in group["worker_ids"]
    ]
    assert worker_ids == [item.worker_id for item in plan.recipe_assignments]
    assert len(worker_ids) == len(set(worker_ids))
    assert all(1 <= len(group["worker_ids"]) <= 24 for group in groups)
    assert all(
        group["checkpoint_artifact_pattern"].startswith("catalog-checkpoint-")
        and group["reduction_artifact"].startswith("catalog-reduction-group-")
        for group in groups
    )
    assert reduction["matrix"] == {
        "include": [
            {
                "group_id": group["group_id"],
                "checkpoint_artifact_pattern": group[
                    "checkpoint_artifact_pattern"
                ],
                "reduction_artifact": group["reduction_artifact"],
            }
            for group in groups
        ]
    }

    central_plan = _task10_plan_fixture(
        warm_component_ordinals={0, 2, 4},
        central_reduction_safe=True,
    )
    central_dir = tmp_path / "central"
    write_sealed_global_reuse_execution_plan(
        output_dir=central_dir,
        **{**common, "plan": central_plan},
    )
    central_reduction = json.loads(
        (central_dir / "reduction_plan.json").read_text("utf-8")
    )
    assert central_reduction["selected_mode"] == "central"
    assert len(central_reduction["groups"]) == 1
    assert central_reduction["groups"][0]["worker_ids"] == [
        item.worker_id for item in central_plan.recipe_assignments
    ]

    target = next((first / "payload_artifacts").rglob("worker-000.json"))
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="CATALOG_SEALED_PLAN_CONTENT_INVALID"):
        verify_sealed_global_reuse_execution_plan(first)
