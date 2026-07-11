from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / ".github/workflows/global-technical-buy-indicator-external-pack-360jobs.yml"
WORKER = ROOT / ".github/workflows/gtbi-fast-strict-v6-worker.yml"
LOCK = ROOT / "requirements/gtbi-fast-strict.lock"
FINAL_MERGER = ROOT / "scripts/merge_gtbi_fast_strict_final.py"
V6_MODE = "optimized_evaluation_v6_fast_strict"


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _trigger(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def _v6_text(*job_names: str) -> str:
    jobs = _workflow(ENTRY)["jobs"]
    return yaml.safe_dump({name: jobs[name] for name in job_names}, sort_keys=True)


def test_registered_workflow_contains_complete_v6_graph() -> None:
    jobs = _workflow(ENTRY)["jobs"]
    expected = {
        "v6_build_data",
        "v6_plan",
        "v6_worker_a",
        "v6_worker_b",
        "v6_smoke_validate",
        "v6_retry_plan_1",
        "v6_retry_1_a",
        "v6_retry_1_b",
        "v6_retry_plan_2",
        "v6_retry_2_a",
        "v6_retry_2_b",
        "v6_final_inventory",
        "v6_merge_block",
        "v6_final_merge",
        "v6_cleanup",
    }
    assert expected <= set(jobs)
    assert jobs["v6_final_merge"]["needs"] == ["v6_merge_block"]


def test_v6_test_mode_runs_only_selected_workers_and_never_enters_full_reducers() -> None:
    workflow = _workflow(ENTRY)
    jobs = workflow["jobs"]
    plan = jobs["v6_plan"]
    assert "selected_worker_ids" in plan["outputs"]
    publish = plan["steps"][-2]
    assert publish["env"]["TEST_MODE"] == "${{ inputs.test_mode }}"
    assert publish["env"]["TEST_MAX_JOBS"] == "${{ inputs.test_max_jobs }}"
    assert "selected = all_workers[:limit]" in publish["run"]

    smoke = jobs["v6_smoke_validate"]
    assert smoke["needs"] == ["v6_plan", "v6_worker_a", "v6_worker_b"]
    assert "inputs.test_mode == 'true'" in smoke["if"]
    smoke_text = yaml.safe_dump(smoke, sort_keys=True)
    assert "--expected-worker-ids" in smoke_text
    assert "gtbi-v6-fast-strict-smoke-results" in smoke_text

    for name in (
        "v6_retry_plan_1",
        "v6_retry_plan_2",
        "v6_final_inventory",
        "v6_merge_block",
        "v6_final_merge",
        "v6_cleanup",
    ):
        assert "inputs.test_mode != 'true'" in jobs[name]["if"]


def test_v6_uses_live_explicit_data_pack_inputs() -> None:
    workflow = _workflow(ENTRY)
    inputs = _trigger(workflow)["workflow_dispatch"]["inputs"]
    assert inputs["data_run_id"]["default"] == "29148013009"
    assert inputs["data_artifact_name"]["default"] == "gtbi-external-pack-data"
    text = ENTRY.read_text(encoding="utf-8")
    assert "27936694743" not in text
    assert "8247340714" not in text
    build = workflow["jobs"]["v6_build_data"]
    download = next(
        step for step in build["steps"] if step.get("uses") == "actions/download-artifact@v4"
    )
    assert download["with"]["run-id"] == "${{ inputs.data_run_id }}"
    assert download["with"]["name"] == "${{ inputs.data_artifact_name }}"
    worker = _workflow(WORKER)
    worker_inputs = _trigger(worker)["workflow_call"]["inputs"]
    assert "data_artifact_run_id" in worker_inputs
    assert "data_manifest_artifact_name" in worker_inputs
    worker_downloads = [
        step
        for step in worker["jobs"]["run"]["steps"]
        if step.get("uses") == "actions/download-artifact@v4"
    ]
    assert worker_downloads[0]["with"]["run-id"] == "${{ inputs.data_artifact_run_id }}"
    assert worker_downloads[0]["with"]["name"] == "${{ inputs.data_artifact_name }}"
    assert worker_downloads[0]["with"]["path"] == "v6-data/data-pack"
    assert worker_downloads[1]["with"]["name"] == "${{ inputs.data_manifest_artifact_name }}"
    assert worker_downloads[1]["with"]["path"] == "v6-data"


def test_source_inputs_are_shared_without_exceeding_dispatch_limit() -> None:
    workflow = _workflow(ENTRY)
    inputs = _trigger(workflow)["workflow_dispatch"]["inputs"]
    assert len(inputs) <= 25
    assert "data_pack_run_id" not in inputs
    assert "data_pack_artifact_name" not in inputs
    legacy_download = next(
        step
        for step in workflow["jobs"]["build_external_pack"]["steps"]
        if step.get("uses") == "actions/download-artifact@v4"
    )
    assert legacy_download["with"]["run-id"] == "${{ inputs.data_run_id }}"
    assert legacy_download["with"]["name"] == "${{ inputs.data_artifact_name }}"


def test_v6_uses_two_180_worker_matrices_and_twenty_blocks() -> None:
    jobs = _workflow(ENTRY)["jobs"]
    worker_jobs = (
        "v6_worker_a",
        "v6_worker_b",
        "v6_retry_1_a",
        "v6_retry_1_b",
        "v6_retry_2_a",
        "v6_retry_2_b",
    )
    for name in worker_jobs:
        assert jobs[name]["strategy"]["fail-fast"] is False
        assert jobs[name]["strategy"]["max-parallel"] == 180
        assert jobs[name]["uses"] == "./.github/workflows/gtbi-fast-strict-v6-worker.yml"
    assert jobs["v6_merge_block"]["strategy"]["fail-fast"] is False
    assert jobs["v6_merge_block"]["strategy"]["max-parallel"] == 20
    assert 'test "${#workers[@]}" -eq 18' in ENTRY.read_text(encoding="utf-8")
    text = ENTRY.read_text(encoding="utf-8")
    assert "matrix_a.json" in text
    assert "matrix_b.json" in text
    assert "block_matrix.json" in text


def test_retry_rounds_and_final_selection_use_validated_inventory() -> None:
    text = _v6_text(
        "v6_retry_plan_1",
        "v6_retry_plan_2",
        "v6_final_inventory",
        "v6_merge_block",
    )
    assert text.count("python scripts/gtbi_fast_strict_inventory.py") == 3
    assert text.count("--campaign-manifest") == 3
    assert text.count("--input-root") >= 3
    assert text.count("--output-dir") >= 3
    assert "selected_workers.csv" in text
    assert "inventory_summary.json" in text
    assert "--paginate" in text
    assert "startswith" in text
    assert "gtbi-v6-worker-" in text
    assert text.count("artifact_roots=(worker-artifacts/gtbi-v6-worker-*)") == 3
    assert text.count("sort -u worker-artifacts.txt") == 3


def test_v6_worker_is_persistent_combined_sparse_and_exact() -> None:
    worker = _workflow(WORKER)
    job = worker["jobs"]["run"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == 330
    assert worker["permissions"]["actions"] == "write"
    assert "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT" not in job["env"]
    text = WORKER.read_text(encoding="utf-8")
    assert text.count("run_gtbi_fast_strict_worker.py") == 1
    assert "sparse-checkout" in text
    assert "strategy_packs" not in text
    assert "cache: pip" in text
    assert "candidate_timeout_seconds=0" not in text
    assert "--candidate-timeout-seconds" not in text
    assert "signal-first-phase signals" not in text
    assert "signal-first-phase exits" not in text
    assert job["env"]["GTBI_SYMBOL_WORKERS"] == "4"
    assert job["env"]["OMP_NUM_THREADS"] == "1"
    assert job["env"]["OPENBLAS_NUM_THREADS"] == "1"
    assert job["env"]["MKL_NUM_THREADS"] == "1"


def test_v6_final_contract_is_strict_hash_bound_and_exactly_named() -> None:
    jobs = _workflow(ENTRY)["jobs"]
    final_text = yaml.safe_dump(jobs["v6_final_merge"], sort_keys=True)
    assert final_text.count("merge_gtbi_fast_strict_final.py") == 1
    assert final_text.count("validate_gtbi_fast_strict_artifact.py") == 1
    assert "--expected-alias-count 72000" in final_text
    assert "--expected-strategy-count 72000" in final_text
    assert "--output-json" in final_text
    assert "--expected-block-count 20" in final_text
    assert "--expected-worker-count 360" in final_text
    assert "global-technical-buy-indicator-long-hold-fast-strict-v6-results" in final_text
    merger_text = FINAL_MERGER.read_text(encoding="utf-8")
    assert "strict_final_pass" in merger_text
    assert "synthetic_missing_timeout_rows" in merger_text
    assert "fill_missing_timeouts_enabled" in merger_text
    assert "_SUCCESS" in merger_text


def test_v6_dates_and_economic_scope_are_unchanged() -> None:
    text = _v6_text("v6_build_data", "v6_plan", "v6_final_merge")
    text += WORKER.read_text(encoding="utf-8")
    assert "2010-12-31" in text
    assert "2011-01-01" in text
    assert "2020-12-31" in text
    assert "2021-01-01" in text
    assert "2000000000" in ENTRY.read_text(encoding="utf-8")
    assert V6_MODE in text
    assert "optimized_evaluation_v5_event_first" in text
    assert "scripts/strategy_packs/gtbi_long_hold_fundamental_timing_v1" in text


def test_v6_pythonpath_and_data_manifest_bind_runtime_roots_and_min_cap() -> None:
    jobs = _workflow(ENTRY)["jobs"]
    expected_pythonpath = "${{ github.workspace }}:${{ github.workspace }}/.."
    script_jobs = (
        "v6_build_data",
        "v6_plan",
        "v6_retry_plan_1",
        "v6_retry_plan_2",
        "v6_final_inventory",
        "v6_merge_block",
        "v6_final_merge",
    )
    for name in script_jobs:
        assert jobs[name]["env"]["PYTHONPATH"] == expected_pythonpath
    assert _workflow(WORKER)["jobs"]["run"]["env"]["PYTHONPATH"] == expected_pythonpath
    seal_step = next(step for step in jobs["v6_build_data"]["steps"] if step.get("id") == "seal")
    assert '--min-market-cap "${{ inputs.min_market_cap }}"' in seal_step["run"]


def test_v6_has_reproducible_minimal_bootstrap_and_no_child_dispatch() -> None:
    text = _v6_text(
        "v6_build_data",
        "v6_plan",
        "v6_retry_plan_1",
        "v6_retry_plan_2",
        "v6_final_inventory",
        "v6_merge_block",
        "v6_final_merge",
    )
    text += WORKER.read_text(encoding="utf-8")
    assert "C:\\" not in text
    assert "self-hosted" not in text
    assert "query1.finance.yahoo.com" not in text
    assert "pip install --upgrade pip" not in text
    assert "[data-cloud,ml]" not in text
    assert "gh workflow run" not in text
    assert "workflow_dispatch" not in WORKER.read_text(encoding="utf-8")
    assert text.count("requirements/gtbi-fast-strict.lock") >= 2


def test_v6_artifacts_fail_closed_and_use_required_retention() -> None:
    workflow = _workflow(ENTRY)
    upload_steps = []
    for job_name, job in workflow["jobs"].items():
        if not job_name.startswith("v6_") or "steps" not in job:
            continue
        upload_steps.extend(
            step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v4"
        )
    worker_uploads = [
        step
        for step in _workflow(WORKER)["jobs"]["run"]["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
    ]
    upload_steps.extend(worker_uploads)
    assert upload_steps
    for step in upload_steps:
        config = step["with"]
        assert config["if-no-files-found"] == "error"
        expected_retention = (
            30
            if config["name"]
            == "global-technical-buy-indicator-long-hold-fast-strict-v6-results"
            else 3
        )
        assert config["retention-days"] == expected_retention
        assert config["compression-level"] == 1


def test_v6_cleanup_is_current_run_only_tolerant_and_preserves_final() -> None:
    workflow = _workflow(ENTRY)
    assert "V6" in workflow["name"]
    assert "V6" in workflow["run-name"]
    cleanup = workflow["jobs"]["v6_cleanup"]
    assert cleanup["needs"] == ["v6_final_merge"]
    assert cleanup["permissions"]["actions"] == "write"
    delete_step = next(step for step in cleanup["steps"] if "Delete current-run" in step["name"])
    assert delete_step["continue-on-error"] is True
    text = delete_step["run"]
    assert "${{ github.run_id }}" in text
    assert "--paginate" in text
    assert "DELETE" in text
    assert "global-technical-buy-indicator-long-hold-fast-strict-v6-results" in text


def test_legacy_jobs_exclude_v6_mode() -> None:
    jobs = _workflow(ENTRY)["jobs"]
    for name in ("build_external_pack", "plan_blocks", "run_block", "merge_final"):
        assert V6_MODE in str(jobs[name]["if"])


def test_worker_workflow_is_reusable_only() -> None:
    trigger = _trigger(_workflow(WORKER))
    assert "workflow_call" in trigger
    assert "workflow_dispatch" not in trigger


def test_v6_dependency_lock_is_minimal_and_pinned() -> None:
    lines = [
        line.strip()
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines
    assert all("==" in line for line in lines)
    packages = {line.split("==", 1)[0].lower() for line in lines}
    assert {"numpy", "pandas", "pyarrow", "numba", "platformdirs"} <= packages
    assert not packages & {"scikit-learn", "statsmodels", "hmmlearn", "lightgbm", "xgboost"}
