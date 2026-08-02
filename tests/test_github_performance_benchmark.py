from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance.benchmark import (
    ScientificOutputMismatch,
    compare_runs,
    scientific_content_identity_from_output,
    write_benchmark_outputs,
)
from aurora.infra.github_performance.preflight import (
    load_github_yaml,
    validate_workflow_policy,
)


ROOT = Path(__file__).parents[1]
WORKFLOW = (
    ROOT / ".github/workflows/github-performance-benchmark.yml"
)


def _artifact(
    root: Path,
    *,
    mode: str,
    wall_seconds: float,
    unit_hash: str = "a" * 64,
    selected_jobs: int = 4,
) -> Path:
    root.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "unit_key": ["u001"],
                "unit_output_sha256": [unit_hash],
            }
        ),
        root / "reference_results.parquet",
    )
    (root / "final_merge_summary.json").write_text(
        json.dumps(
            {
                "partial": False,
                "scientific_output": "reference_results.parquet",
                "locked_opened": False,
                "validation_used_for_selection": False,
            }
        ),
        encoding="utf-8",
    )
    (root / "performance_contract.json").write_text(
        json.dumps(
            {
                "code_sha": "b" * 40,
                "policy_hash": "c" * 64,
                "snapshot_hash": "d" * 64,
                "environment_sha256": "e" * 64,
                "standard_runner_only": True,
                "larger_runners_allowed": False,
                "matrix_job_ceiling": 256,
                "standard_concurrency_ceiling": 360,
            }
        ),
        encoding="utf-8",
    )
    (root / "environment_manifest.json").write_text(
        json.dumps({"cache": {"hit": True}}),
        encoding="utf-8",
    )
    (root / "execution_plan.json").write_text(
        json.dumps(
            {
                "assignment_strategy": mode,
                "job_count": {
                    "selected_jobs": selected_jobs,
                    "predicted_seconds": 120.0,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "timeline_summary.json").write_text(
        json.dumps(
            {
                "complete": True,
                "requested_parallelism": 360,
                "observed_peak_parallelism": 4,
                "workflow_wall_seconds": wall_seconds,
                "execution_wall_seconds": wall_seconds - 10.0,
                "estimated_billable_minutes": wall_seconds / 60.0,
                "queue_seconds_total": 20.0,
                "setup_seconds_total": 30.0,
                "canonical_setup_seconds_total": 10.0,
                "restore_setup_seconds_total": 20.0,
                "transfer_seconds_total": 10.0,
                "compute_seconds_total": 200.0,
                "retry_seconds_total": 0.0,
                "merge_seconds_total": 12.0,
                "job_seconds_total": 252.0,
                "straggler_ratio": 1.2,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_compare_requires_identical_scientific_outputs(
    tmp_path: Path,
) -> None:
    baseline = _artifact(
        tmp_path / "baseline",
        mode="equal_count_flat",
        wall_seconds=240.0,
    )
    optimized = _artifact(
        tmp_path / "optimized",
        mode="weighted_lpt_hierarchical",
        wall_seconds=120.0,
        unit_hash="f" * 64,
    )
    with pytest.raises(ScientificOutputMismatch):
        compare_runs(baseline, optimized)


def test_scientific_content_identity_ignores_operational_provenance(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    changed = tmp_path / "changed.parquet"
    for path, attempt_id, unit_hash in (
        (first, "attempt-a", "a" * 64),
        (second, "attempt-b", "a" * 64),
        (changed, "attempt-a", "b" * 64),
    ):
        pq.write_table(
            pa.table(
                {
                    "unit_key": ["u001"],
                    "unit_output_sha256": [unit_hash],
                    "source_attempt_id": [attempt_id],
                }
            ),
            path,
        )

    first_identity = scientific_content_identity_from_output(first)
    second_identity = scientific_content_identity_from_output(second)
    changed_identity = scientific_content_identity_from_output(changed)

    assert first.read_bytes() != second.read_bytes()
    assert first_identity == second_identity
    assert (
        first_identity["scientific_content_sha256"]
        != changed_identity["scientific_content_sha256"]
    )


def test_compare_reports_speed_only_after_equivalence(
    tmp_path: Path,
) -> None:
    baseline = _artifact(
        tmp_path / "baseline",
        mode="equal_count_flat",
        wall_seconds=240.0,
    )
    optimized = _artifact(
        tmp_path / "optimized",
        mode="weighted_lpt_hierarchical",
        wall_seconds=120.0,
    )
    report = compare_runs(baseline, optimized)
    assert report.scientific_outputs_equal is True
    assert report.timing_comparable is True
    assert report.speedup == 2.0
    assert report.material_speedup_achieved is True
    assert report.optimization_selected is True
    assert report.selected_execution_mode == "optimized"
    assert report.optimization_disposition == "selected"
    assert report.speedup_uncertainty["lower_bound"] > 1.05
    assert report.same_code_sha is True
    assert report.same_snapshot_hash is True
    assert report.same_cache_state is True
    assert report.same_performance_contract is True
    assert report.matrix_job_ceiling_respected is True
    assert report.larger_runner_used is False
    outputs = write_benchmark_outputs(report, tmp_path / "comparison")
    assert {path.name for path in outputs} == {
        "bottleneck_report.json",
        "performance_final.json",
        "github_performance_phase1_closure.json",
    }
    closure = json.loads(
        (
            tmp_path
            / "comparison"
            / "github_performance_phase1_closure.json"
        ).read_text()
    )
    assert closure["status"] == "success"
    assert closure["comparison_dimension"] == "assignment_strategy"
    assert closure["optimization_selected"] is True
    assert closure["selected_execution_mode"] == "optimized"


def test_compare_rejects_slower_optimization_automatically(
    tmp_path: Path,
) -> None:
    baseline = _artifact(
        tmp_path / "baseline",
        mode="equal_count_flat",
        wall_seconds=120.0,
    )
    optimized = _artifact(
        tmp_path / "optimized",
        mode="weighted_lpt_hierarchical",
        wall_seconds=140.0,
    )

    report = compare_runs(baseline, optimized)

    assert report.status == "success"
    assert report.speedup < 1.0
    assert report.material_speedup_achieved is False
    assert report.optimization_selected is False
    assert report.selected_execution_mode == "baseline"
    assert report.optimization_disposition == "rejected_slower"
    assert report.optimization_selection_reason_codes == (
        "OPTIMIZED_SLOWER_THAN_BASELINE",
    )


def test_compare_rejects_non_material_speedup(
    tmp_path: Path,
) -> None:
    baseline = _artifact(
        tmp_path / "baseline",
        mode="equal_count_flat",
        wall_seconds=101.0,
    )
    optimized = _artifact(
        tmp_path / "optimized",
        mode="weighted_lpt_hierarchical",
        wall_seconds=100.0,
    )

    report = compare_runs(baseline, optimized)

    assert report.speedup == 1.01
    assert report.optimization_selected is False
    assert report.selected_execution_mode == "baseline"
    assert report.optimization_disposition == "rejected_not_material"
    assert report.optimization_selection_reason_codes == (
        "SPEEDUP_NOT_MATERIAL_AFTER_RESOLUTION_BOUND",
    )


def test_compare_adaptive_topology_allows_different_job_counts(
    tmp_path: Path,
) -> None:
    baseline = _artifact(
        tmp_path / "baseline",
        mode="equal_count_flat",
        wall_seconds=240.0,
        selected_jobs=1,
    )
    optimized = _artifact(
        tmp_path / "optimized",
        mode="weighted_lpt_hierarchical",
        wall_seconds=120.0,
        selected_jobs=16,
    )

    report = compare_runs(
        baseline,
        optimized,
        comparison_dimension="adaptive_topology",
    )

    assert report.status == "success"
    assert report.comparison_dimension == "adaptive_topology"
    assert report.same_selected_jobs is False
    assert report.scientific_outputs_equal is True
    assert report.timing_comparable is True
    assert report.material_speedup_achieved is True


def test_compare_adaptive_topology_requires_different_job_counts(
    tmp_path: Path,
) -> None:
    baseline = _artifact(
        tmp_path / "baseline",
        mode="equal_count_flat",
        wall_seconds=240.0,
    )
    optimized = _artifact(
        tmp_path / "optimized",
        mode="weighted_lpt_hierarchical",
        wall_seconds=120.0,
    )

    report = compare_runs(
        baseline,
        optimized,
        comparison_dimension="adaptive_topology",
    )

    assert report.status == "failed"
    assert report.timing_comparable is False
    assert "TOPOLOGY_NOT_DIFFERENT" in report.failure_codes


def test_compare_does_not_claim_speed_for_different_environment(
    tmp_path: Path,
) -> None:
    baseline = _artifact(
        tmp_path / "baseline",
        mode="equal_count_flat",
        wall_seconds=240.0,
    )
    optimized = _artifact(
        tmp_path / "optimized",
        mode="weighted_lpt_hierarchical",
        wall_seconds=120.0,
    )
    contract_path = optimized / "performance_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["environment_sha256"] = "f" * 64
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    report = compare_runs(baseline, optimized)
    assert report.scientific_outputs_equal is True
    assert report.timing_comparable is False
    assert report.speedup == 0.0
    assert "ENVIRONMENT_HASH_MISMATCH" in report.failure_codes


def test_manual_benchmark_runs_optimized_then_equivalent_baseline() -> None:
    workflow = load_github_yaml(WORKFLOW)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["workload_family"]["options"] == [
        "candidate_sweep",
        "event_study",
        "robustness",
    ]
    assert inputs["forced_job_count"]["default"] == 0
    assert inputs["baseline_forced_job_count"]["default"] == 0
    assert inputs["comparison_dimension"]["default"] == (
        "assignment_strategy"
    )
    assert inputs["comparison_dimension"]["options"] == [
        "assignment_strategy",
        "adaptive_topology",
    ]
    assert inputs["performance_profile_run_id"]["default"] == ""
    assert inputs["performance_profile_artifact_name"]["default"] == ""
    assert inputs["fault_injection_shard_id"]["default"] == ""
    assert inputs["fault_injection_after_units"]["default"] == 0
    assert workflow["permissions"] == {
        "contents": "read",
        "actions": "read",
    }
    jobs = workflow["jobs"]
    assert "setup_benchmark" in jobs
    assert jobs["setup_benchmark"]["needs"] == "prime_runtime"
    assert jobs["optimized"]["needs"] == "prime_runtime"
    assert jobs["optimized"]["with"]["execution_mode"] == "optimized"
    optimized_text = str(jobs["optimized"]["with"])
    for family in ("candidate_sweep", "event_study", "robustness"):
        assert family in optimized_text
    assert "inputs.forced_job_count" in str(
        jobs["optimized"]["with"]["forced_job_count"]
    )
    shared_wheelhouse = jobs["optimized"]["with"][
        "wheelhouse_artifact_name"
    ]
    assert "shared-wheelhouse" in str(shared_wheelhouse)
    shared_snapshot = jobs["optimized"]["with"]["prepared_artifact_name"]
    assert "shared-prepared" in str(shared_snapshot)
    assert jobs["baseline"]["needs"] == "optimized"
    assert jobs["baseline"]["with"]["execution_mode"] == "baseline"
    assert (
        jobs["baseline"]["with"]["prepared_artifact_name"]
        == shared_snapshot
    )
    assert (
        jobs["baseline"]["with"]["wheelhouse_artifact_name"]
        == shared_wheelhouse
    )
    forced = jobs["baseline"]["with"]["forced_job_count"]
    assert "needs.optimized.outputs.selected_jobs" in str(forced)
    assert "inputs.forced_job_count" in str(forced)
    assert "inputs.baseline_forced_job_count" in str(forced)
    assert jobs["compare"]["needs"] == [
        "optimized",
        "baseline",
        "setup_benchmark",
    ]
    compare_text = str(jobs["compare"])
    assert "environment_setup_benchmark.json" in compare_text
    assert "--comparison-dimension" in compare_text
    assert "--cold-repetitions 3" in str(jobs["setup_benchmark"])
    assert "aurora github build-performance-profile" in compare_text
    assert "performance_profile.json" in compare_text
    assert (
        jobs["optimized"]["with"]["performance_profile_run_id"]
        == "${{ inputs.performance_profile_run_id }}"
    )
    assert (
        jobs["baseline"]["with"]["performance_profile_artifact_name"]
        == "${{ inputs.performance_profile_artifact_name }}"
    )
    for name in ("optimized", "baseline"):
        assert jobs[name]["with"]["fault_injection_shard_id"] == (
            "${{ inputs.fault_injection_shard_id }}"
        )
    upload = jobs["compare"]["steps"][-1]
    assert upload["if"] == "always()"
    assert str(upload["with"]["path"]).endswith(
        "/benchmark/comparison"
    )
    assert validate_workflow_policy(WORKFLOW, ROOT) == []
