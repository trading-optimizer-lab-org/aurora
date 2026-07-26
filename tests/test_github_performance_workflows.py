from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from aurora.infra.github_performance.preflight import load_github_yaml


ROOT = Path(__file__).parents[1]
ACTION_PATH = (
    ROOT / ".github" / "actions" / "aurora-runtime-setup" / "action.yml"
)
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "_aurora-future-run-v3.yml"
)
POLICY_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "github-performance-policy.yml"
)
RECOVERY_WAVE_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "_aurora-recovery-plan-v3.yml"
)
RETRY_SHARD_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "_aurora-retry-shard-v3.yml"
)
MERGE_LEVEL_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "_aurora-merge-level-v3.yml"
)
MERGE_ONLY_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "github-performance-merge-only.yml"
)
REPLAN_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "github-performance-replan.yml"
)
REFERENCE_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "github-performance-reference.yml"
)


def _load_action() -> dict[str, Any]:
    return yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))


def _locked_action(name: str) -> str:
    lock = json.loads(
        (ROOT / "config" / "official_actions_lock.json").read_text(
            encoding="utf-8"
        )
    )
    return f"{name}@{lock[name]}"


def test_runtime_setup_is_composite_and_pinned() -> None:
    action = _load_action()
    assert action["runs"]["using"] == "composite"
    uses = [
        step["uses"]
        for step in action["runs"]["steps"]
        if "uses" in step
    ]
    assert _locked_action("actions/setup-python") in uses
    assert all(
        value.rsplit("@", 1)[-1].isalnum() and
        len(value.rsplit("@", 1)[-1]) == 40
        for value in uses
    )


def test_runtime_setup_requires_exact_wheelhouse_and_lock() -> None:
    action = _load_action()
    assert action["inputs"]["wheelhouse-path"]["required"] is True
    assert action["inputs"]["dependency-lock-path"]["required"] is True


def test_runtime_setup_installs_offline_without_resolution_or_building() -> None:
    text = ACTION_PATH.read_text(encoding="utf-8")
    assert "--no-index" in text
    assert "--require-hashes" in text
    assert "--no-deps" in text
    assert "pip wheel" not in text
    assert "--upgrade pip" not in text
    assert "https://" not in text
    assert "http://" not in text
    assert "wheelhouse_manifest.json" in text
    assert "dependency_lock_manifest.json" in text


def test_runtime_setup_pins_numeric_threads_to_detected_cpus() -> None:
    action_text = ACTION_PATH.read_text(encoding="utf-8")
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        assert f'echo "{variable}=$cpu_count"' in action_text
    assert "getconf _NPROCESSORS_ONLN" in action_text


def test_runtime_setup_has_no_credential_or_larger_runner_escape() -> None:
    action_text = ACTION_PATH.read_text(encoding="utf-8").lower()
    assert "persist-credentials" not in action_text
    assert "larger" not in action_text
    assert "gpu" not in action_text
    assert "self-hosted" not in action_text


def _workflow() -> dict[str, Any]:
    return dict(load_github_yaml(WORKFLOW_PATH))


def _needs(job: dict[str, Any]) -> set[str]:
    value = job.get("needs", ())
    if isinstance(value, str):
        return {value}
    return set(value)


def test_reusable_workflow_has_complete_dependency_spine() -> None:
    jobs = _workflow()["jobs"]
    assert _needs(jobs["prepare_environment"]) == set()
    assert _needs(jobs["validate"]) == {"prepare_environment"}
    assert _needs(jobs["prepare_data"]) == {"validate"}
    assert _needs(jobs["freeze_contract"]) == {
        "validate",
        "prepare_environment",
        "prepare_data",
    }
    assert _needs(jobs["smoke"]) == {"freeze_contract"}
    assert _needs(jobs["pilot"]) == {"smoke"}
    assert _needs(jobs["plan"]) == {"pilot"}
    assert _needs(jobs["fanout_a"]) == {"plan"}
    assert _needs(jobs["fanout_b"]) == {"plan"}
    assert _needs(jobs["campaign_initialize"]) == {
        "plan",
        "freeze_contract",
    }
    assert _needs(jobs["recovery_plan"]) == {
        "plan",
        "fanout_a",
        "fanout_b",
        "campaign_initialize",
    }
    assert _needs(jobs["retry_a"]) == {"plan", "recovery_plan"}
    assert _needs(jobs["retry_b"]) == {"plan", "recovery_plan"}
    previous_a = "retry_a"
    previous_b = "retry_b"
    previous_recovery = "recovery_plan"
    for wave in range(1, 6):
        recovery = f"recovery_plan_{wave}"
        assert _needs(jobs[recovery]) == {
            "plan",
            previous_recovery,
            previous_a,
            previous_b,
        }
        previous_recovery = recovery
        if wave < 5:
            next_a = f"retry_{wave + 1}_a"
            next_b = f"retry_{wave + 1}_b"
            assert _needs(jobs[next_a]) == {"plan", recovery}
            assert _needs(jobs[next_b]) == {"plan", recovery}
            previous_a = next_a
            previous_b = next_b
    assert _needs(jobs["merge_partials"]) == {
        "plan",
        "fanout_a",
        "fanout_b",
        "recovery_plan",
        "retry_a",
        "retry_b",
        "recovery_plan_1",
        "retry_2_a",
        "retry_2_b",
        "recovery_plan_2",
        "retry_3_a",
        "retry_3_b",
        "recovery_plan_3",
        "retry_4_a",
        "retry_4_b",
        "recovery_plan_4",
        "retry_5_a",
        "retry_5_b",
        "recovery_plan_5",
    }
    assert _needs(jobs["final_merge"]) == {
        "plan",
        "freeze_contract",
        "merge_partials",
    }
    assert _needs(jobs["verify"]) == {"final_merge"}
    assert _needs(jobs["collect_timeline"]) == {"verify"}
    assert _needs(jobs["publish"]) == {"verify", "collect_timeline"}


def test_reusable_workflow_respects_standard_runner_limits() -> None:
    jobs = _workflow()["jobs"]
    for job in jobs.values():
        if "uses" in job:
            assert str(job["uses"]).startswith("./.github/workflows/")
        else:
            assert job["runs-on"] == "ubuntu-24.04"
    matrix_limits = {
        "fanout_a": 256,
        "fanout_b": 104,
        "retry_a": 256,
        "retry_b": 104,
    }
    for wave in range(2, 6):
        matrix_limits[f"retry_{wave}_a"] = 256
        matrix_limits[f"retry_{wave}_b"] = 104
    for name, limit in matrix_limits.items():
        strategy = jobs[name]["strategy"]
        assert strategy["fail-fast"] is False
        assert strategy["max-parallel"] == limit
        assert limit <= 256
    assert (
        jobs["fanout_a"]["strategy"]["max-parallel"]
        + jobs["fanout_b"]["strategy"]["max-parallel"]
        == 360
    )
    for wave in range(1, 6):
        a = "retry_a" if wave == 1 else f"retry_{wave}_a"
        b = "retry_b" if wave == 1 else f"retry_{wave}_b"
        assert (
            jobs[a]["strategy"]["max-parallel"]
            + jobs[b]["strategy"]["max-parallel"]
            == 360
        )


def test_recovery_is_durable_and_iterates_to_maximum_retry_budget() -> None:
    jobs = _workflow()["jobs"]
    recovery_jobs = (
        "recovery_plan",
        "recovery_plan_1",
        "recovery_plan_2",
        "recovery_plan_3",
        "recovery_plan_4",
        "recovery_plan_5",
    )
    for wave, name in enumerate(recovery_jobs):
        job = jobs[name]
        assert job["uses"] == (
            "./.github/workflows/_aurora-recovery-plan-v3.yml"
        )
        assert job["with"]["current_wave"] == wave
        assert job["with"]["max_waves"] == 6
    assert "campaign-update" in WORKFLOW_PATH.read_text(encoding="utf-8")
    recovery_text = RECOVERY_WAVE_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "aurora github recovery-loop" in recovery_text
    assert "campaign_state_latest.json" in recovery_text
    retry_text = RETRY_SHARD_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "aurora github run-shard" in retry_text
    assert "matrix" not in retry_text


def test_universal_merge_only_workflow_reuses_verified_artifacts_only() -> None:
    workflow = dict(load_github_yaml(MERGE_ONLY_WORKFLOW_PATH))
    assert "workflow_call" in workflow["on"]
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert {
        "source_run_id",
        "source_state_artifact_name",
        "run_label",
        "workload",
        "retention_days",
    } <= set(inputs)
    text = MERGE_ONLY_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "aurora github merge-only" in text
    assert "aurora github final-merge" in text
    assert "aurora github verify" in text
    assert "campaign_state_latest.json" in text
    assert "verified_source_artifacts" in text
    assert "gh run download" in text
    assert "aurora github run-shard" not in text
    assert '["scientific_output"]' in text
    assert "reference_results.parquet" not in text
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"


def test_universal_replan_workflow_changes_only_operational_plan() -> None:
    workflow = dict(load_github_yaml(REPLAN_WORKFLOW_PATH))
    assert "workflow_call" in workflow["on"]
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert {
        "source_run_id",
        "source_state_artifact_name",
        "run_label",
        "requested_jobs",
        "operational_overrides",
        "retention_days",
    } <= set(inputs)
    text = REPLAN_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "aurora github replan-pending" in text
    assert "campaign_state_latest.json" in text
    assert "work_unit_manifest.json" in text
    assert "unit_attempts.parquet" in text
    assert "operational_overrides" in text
    assert "aurora github run-shard" not in text
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"


def test_registered_reference_workflow_routes_recovery_operations() -> None:
    workflow = dict(load_github_yaml(REFERENCE_WORKFLOW_PATH))
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["operation"]["options"] == [
        "full",
        "merge_only",
        "replan",
        "replan_fixture",
    ]
    jobs = workflow["jobs"]
    assert jobs["reference"]["uses"] == (
        "./.github/workflows/_aurora-future-run-v3.yml"
    )
    assert jobs["merge_only"]["uses"] == (
        "./.github/workflows/github-performance-merge-only.yml"
    )
    assert jobs["replan"]["uses"] == (
        "./.github/workflows/github-performance-replan.yml"
    )
    requested_jobs = jobs["replan"]["with"]["requested_jobs"]
    assert "fromJSON" in requested_jobs
    assert "format('{0}', inputs.requested_jobs)" in requested_jobs
    assert jobs["replan_fixture_source"]["uses"] == (
        "./.github/workflows/_aurora-future-run-v3.yml"
    )
    fixture = jobs["build_replan_fixture"]
    assert fixture["runs-on"] == "ubuntu-24.04"
    fixture_text = REFERENCE_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "OUT_OF_MEMORY" not in fixture_text
    assert "build_github_performance_replan_fixture.py" in fixture_text


def test_replan_restores_verified_source_runtime_across_orchestration_fixes() -> None:
    text = REPLAN_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "SOURCE_SCIENTIFIC_RUNTIME_MISMATCH" in text
    assert "source_runtime_verified" in text
    assert 'wheelhouse["code_sha"]' in text
    assert 'contract["identity"]["code_sha"]' in text
    assert "orchestration_code_sha" in text
    assert "SOURCE_CODE_SHA_MISMATCH" not in text


def test_reusable_workflow_preserves_salvage_and_bounded_merge() -> None:
    jobs = _workflow()["jobs"]
    for name in ("recovery_plan", "merge_partials", "final_merge", "verify"):
        assert "always()" in jobs[name]["if"]
    for name in ("fanout_a", "fanout_b", "retry_a", "retry_b"):
        upload_steps = [
            step
            for step in jobs[name]["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact@")
        ]
        assert upload_steps
        assert all("always()" in step["if"] for step in upload_steps)
    final_download = next(
        step
        for step in jobs["final_merge"]["steps"]
        if step["name"] == "Download partial merges only"
    )
    assert "partial-*" in final_download["with"]["pattern"]
    assert "shard-*" not in final_download["with"]["pattern"]


def test_reusable_workflow_executes_every_bounded_merge_plan_level() -> None:
    jobs = _workflow()["jobs"]
    levels = [f"merge_level_{level}" for level in range(4)]
    assert all(level in jobs for level in levels)
    assert jobs["merge_level_0"]["uses"] == (
        "./.github/workflows/_aurora-merge-level-v3.yml"
    )
    for level in range(1, 4):
        assert _needs(jobs[f"merge_level_{level}"]) == {
            "plan",
            f"merge_level_{level - 1}",
        }
    assert _needs(jobs["final_merge"]) == {
        "plan",
        "freeze_contract",
        *levels,
    }
    merge_workflow = dict(load_github_yaml(MERGE_LEVEL_WORKFLOW_PATH))
    merge_jobs = merge_workflow["jobs"]
    assert set(merge_jobs) == {"merge"}
    merge_job = merge_jobs["merge"]
    assert merge_job["runs-on"] == "ubuntu-24.04"
    assert merge_job["strategy"]["fail-fast"] is False
    assert merge_job["strategy"]["max-parallel"] <= 256
    merge_text = MERGE_LEVEL_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "aurora github merge-plan-group" in merge_text
    assert "matrix.output_artifact" in merge_text
    final_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "needs.plan.outputs.merge_root_artifact" in final_text
    assert "Download merge root only" in final_text


def test_reusable_workflow_uses_compact_unique_attempt_artifacts() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "plan_outputs.json" in text
    assert "matrix.attempt_id" in text
    assert (
        "shard-${{ matrix.merge_group }}-${{ matrix.shard_id }}"
        "-${{ matrix.attempt_id }}"
    ) in text
    assert "compression-level: 0" in text
    assert "if-no-files-found: error" in text
    assert text.count('--assignment-root "$RUNNER_TEMP/plan"') == 4
    assert text.count('--prepared-root "$RUNNER_TEMP/prepared"') == 4


def test_reusable_workflow_inputs_and_permissions_are_minimal() -> None:
    workflow = _workflow()
    inputs = workflow["on"]["workflow_call"]["inputs"]
    assert set(inputs) == {
        "execution_mode",
        "forced_job_count",
        "prepared_artifact_name",
        "wheelhouse_artifact_name",
        "spec_path",
        "workload",
        "run_label",
        "retention_days",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert "push" not in workflow["on"]
    assert "pull_request" not in workflow["on"]


def test_reusable_workflow_builds_aurora_and_wheelhouse_exactly_once() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    prepare_text = str(jobs["prepare_environment"])
    assert "build_github_performance_wheelhouse.py" in prepare_text
    assert text.count("build_github_performance_wheelhouse.py") == 1
    assert text.count("pip wheel") <= 1
    assert "requirements/github-performance.lock" in prepare_text
    upload = next(
        step
        for step in jobs["prepare_environment"]["steps"]
        if step["name"] == "Upload immutable wheelhouse"
    )
    assert "wheelhouse" in str(upload["with"]["path"])
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["compression-level"] == 0


def test_reusable_workflow_can_reuse_exact_wheelhouse_artifact() -> None:
    workflow = _workflow()
    prepare = workflow["jobs"]["prepare_environment"]
    shared_download = next(
        step
        for step in prepare["steps"]
        if step["name"] == "Download shared immutable wheelhouse"
    )
    build = next(
        step
        for step in prepare["steps"]
        if step["name"] == "Build immutable wheelhouse once"
    )
    upload = next(
        step
        for step in prepare["steps"]
        if step["name"] == "Upload immutable wheelhouse"
    )
    assert shared_download["if"] == "inputs.wheelhouse_artifact_name != ''"
    assert build["if"] == "inputs.wheelhouse_artifact_name == ''"
    assert upload["if"] == "inputs.wheelhouse_artifact_name == ''"
    assert (
        shared_download["with"]["name"]
        == "${{ env.AURORA_WHEELHOUSE_ARTIFACT_NAME }}"
    )


def test_every_runtime_consumer_downloads_the_same_wheelhouse_first() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    runtime_jobs = {
        name
        for name, job in jobs.items()
        if any(
            step.get("uses")
            == "./.github/actions/aurora-runtime-setup"
            for step in job.get("steps", ())
        )
    }
    assert runtime_jobs
    for name in runtime_jobs:
        steps = jobs[name]["steps"]
        setup_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("uses")
            == "./.github/actions/aurora-runtime-setup"
        )
        download_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("name") == "Download immutable wheelhouse"
        )
        assert download_index < setup_index, name
        setup = steps[setup_index]
        assert (
            setup["with"]["wheelhouse-path"]
            == "${{ runner.temp }}/wheelhouse"
        )
        assert (
            setup["with"]["dependency-lock-path"]
            == "requirements/github-performance.lock"
        )


def test_reusable_workflow_can_reuse_exact_prepared_artifact() -> None:
    workflow = _workflow()
    prepared = workflow["jobs"]["prepare_data"]
    shared_download = next(
        step
        for step in prepared["steps"]
        if step["name"] == "Download shared immutable inputs"
    )
    prepare = next(
        step
        for step in prepared["steps"]
        if step["name"] == "Prepare immutable data once"
    )
    upload = next(
        step
        for step in prepared["steps"]
        if step["name"] == "Upload prepared inputs"
    )
    assert shared_download["if"] == "inputs.prepared_artifact_name != ''"
    assert prepare["if"] == "inputs.prepared_artifact_name == ''"
    assert upload["if"] == "inputs.prepared_artifact_name == ''"
    assert (
        shared_download["with"]["name"]
        == "${{ env.AURORA_PREPARED_ARTIFACT_NAME }}"
    )
    assert "inputs.prepared_artifact_name" in str(
        workflow["env"]["AURORA_PREPARED_ARTIFACT_NAME"]
    )


def test_timeline_collection_is_read_only_and_cannot_block_science() -> None:
    jobs = _workflow()["jobs"]
    collector = jobs["collect_timeline"]
    assert collector["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    step = next(
        item
        for item in collector["steps"]
        if item["name"] == "Collect read-only GitHub timing"
    )
    assert step["continue-on-error"] is True
    publisher = jobs["publish"]
    assert "always()" in publisher["if"]
    assert any(
        item["name"]
        == "Record incomplete timing without touching scientific files"
        for item in publisher["steps"]
    )


def test_policy_workflow_is_lightweight_static_pr_enforcement() -> None:
    workflow = load_github_yaml(POLICY_WORKFLOW_PATH)
    assert "pull_request" in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert set(jobs) == {"workflow_policy"}
    job = jobs["workflow_policy"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert "strategy" not in job
    text = POLICY_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "validate_github_workflow_policy.py" in text
    assert "workflow_dispatch" in workflow["on"]
