from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance.benchmark import (
    ScientificOutputMismatch,
    compare_runs,
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
                    "selected_jobs": 4,
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
    assert workflow["permissions"] == {
        "contents": "read",
        "actions": "read",
    }
    jobs = workflow["jobs"]
    assert jobs["optimized"]["needs"] == "prime_runtime"
    assert jobs["optimized"]["with"]["execution_mode"] == "optimized"
    assert jobs["baseline"]["needs"] == "optimized"
    assert jobs["baseline"]["with"]["execution_mode"] == "baseline"
    forced = jobs["baseline"]["with"]["forced_job_count"]
    assert "needs.optimized.outputs.selected_jobs" in str(forced)
    assert jobs["compare"]["needs"] == ["optimized", "baseline"]
    upload = jobs["compare"]["steps"][-1]
    assert upload["if"] == "always()"
    assert str(upload["with"]["path"]).endswith(
        "/benchmark/comparison"
    )
    assert validate_workflow_policy(WORKFLOW, ROOT) == []
