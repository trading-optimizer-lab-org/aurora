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
    assert _locked_action("actions/cache") in uses
    assert (
        "actions/cache/restore@"
        + _locked_action("actions/cache").split("@", 1)[1]
    ) in uses
    assert all(
        value.rsplit("@", 1)[-1].isalnum() and
        len(value.rsplit("@", 1)[-1]) == 40
        for value in uses
    )


def test_runtime_setup_defaults_to_restore_only() -> None:
    action = _load_action()
    assert action["inputs"]["cache-mode"]["default"] == "restore-only"
    steps = action["runs"]["steps"]
    restore = next(step for step in steps if step.get("id") == "cache-restore")
    writer = next(step for step in steps if step.get("id") == "cache-writer")
    assert restore["if"] == "inputs.cache-mode == 'restore-only'"
    assert writer["if"] == "inputs.cache-mode == 'writer'"


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
    assert _needs(jobs["prepare_environment"]) == {"validate"}
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
    assert _needs(jobs["recovery_plan"]) == {
        "plan",
        "fanout_a",
        "fanout_b",
    }
    assert _needs(jobs["retry_a"]) == {"plan", "recovery_plan"}
    assert _needs(jobs["retry_b"]) == {"plan", "recovery_plan"}
    assert _needs(jobs["merge_partials"]) == {
        "plan",
        "fanout_a",
        "fanout_b",
        "retry_a",
        "retry_b",
    }
    assert _needs(jobs["final_merge"]) == {
        "plan",
        "freeze_contract",
        "merge_partials",
    }
    assert _needs(jobs["verify"]) == {"final_merge"}
    assert _needs(jobs["publish"]) == {"verify"}


def test_reusable_workflow_respects_standard_runner_limits() -> None:
    jobs = _workflow()["jobs"]
    for job in jobs.values():
        assert job["runs-on"] == "ubuntu-24.04"
    matrix_limits = {
        "fanout_a": 256,
        "fanout_b": 104,
        "retry_a": 256,
        "retry_b": 104,
    }
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


def test_reusable_workflow_inputs_and_permissions_are_minimal() -> None:
    workflow = _workflow()
    inputs = workflow["on"]["workflow_call"]["inputs"]
    assert set(inputs) == {
        "spec_path",
        "workload",
        "run_label",
        "retention_days",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert "push" not in workflow["on"]
    assert "pull_request" not in workflow["on"]
