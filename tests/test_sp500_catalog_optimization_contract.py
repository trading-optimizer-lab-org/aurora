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


def test_reduction_step_is_named_for_runtime_attribution() -> None:
    workflow = (
        ROOT / ".github/workflows/catalog-optimized-run.yml"
    ).read_text("utf-8")

    assert (
        "Reduce catalog results (scripts/reduce_sp500_optimized_catalog_run.py)"
        in workflow
    )


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
    """The legacy workflow may only delegate to the admission-controlled one."""

    from aurora.infra.github_performance.preflight import load_github_yaml
    from aurora.infra.sp500_megarun.catalog_admission import (
        validate_catalog_entrypoint,
    )

    legacy = ROOT / ".github/workflows/sp500-strategy-catalog-overnight.yml"
    optimized = ROOT / ".github/workflows/catalog-optimized-run.yml"

    assert validate_catalog_entrypoint(legacy) == ()
    payload = load_github_yaml(optimized)
    jobs = payload["jobs"]
    assert isinstance(jobs, dict)
    assert "plan" in jobs
    evaluate_jobs = [name for name in jobs if str(name).startswith("evaluate_")]
    assert evaluate_jobs == ["evaluate_a", "evaluate_b", "evaluate_c"]
    for name in evaluate_jobs:
        job = jobs[name]
        assert set(job["needs"]) == {"plan", "merge_components"}
        serialized = json.dumps(job, sort_keys=True)
        assert "admission_token_sha256" in serialized
    assert set(jobs["reduce"]["needs"]) == {"plan", *evaluate_jobs}


def test_dynamic_worker_count_is_typed_for_reusable_workflow_calls() -> None:
    """GitHub job outputs are strings and number inputs require fromJSON."""

    from aurora.infra.github_performance.preflight import load_github_yaml

    workflow = load_github_yaml(
        ROOT / ".github/workflows/catalog-optimized-run.yml"
    )
    for name in ("evaluate_a", "evaluate_b", "evaluate_c"):
        assert workflow["jobs"][name]["with"]["active_workers"] == (
            "${{ fromJSON(needs.plan.outputs.active_workers) }}"
        )


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
    assert "benchmark_workers:" in workflow
    assert "--benchmark-workers" in workflow
    assert "benchmark_processes:" in workflow
    assert "--benchmark-processes" in workflow
    assert "benchmark_component_processes:" in workflow
    assert "--benchmark-component-processes" in workflow
    assert "benchmark_component_workers:" in workflow
    assert "--benchmark-component-workers" in workflow


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
