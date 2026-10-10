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
RECOVERY_PLAN_ACTION_PATH = (
    ROOT / ".github" / "actions" / "aurora-shard-recovery-plan" / "action.yml"
)
RETRY_SHARD_ACTION_PATH = (
    ROOT / ".github" / "actions" / "aurora-retry-shard" / "action.yml"
)
MERGE_LEVEL_ACTION_PATH = (
    ROOT / ".github" / "actions" / "aurora-merge-level" / "action.yml"
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
VALIDATION_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "github-performance-validation.yml"
)
CAPACITY_CALIBRATION_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "catalog-capacity-calibration.yml"
)
CATALOG_OPTIMIZED_WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "catalog-optimized-run.yml"
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


def test_runtime_setup_requires_one_exact_runtime_object_and_lock() -> None:
    action = _load_action()
    required = {
        "python-version",
        "runtime-mode",
        "runtime-object-path",
        "runtime-manifest-path",
        "dependency-lock-path",
        "expected-runtime-identity-sha256",
        "expected-source-sha",
        "expected-numeric-profile-sha256",
    }
    assert set(action["inputs"]) == required
    assert all(action["inputs"][name]["required"] is True for name in required)


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
    assert "RUNTIME_DEPENDENCY_LOCK_HASH_INVALID" in text
    assert "RUNTIME_FILE_HASH_INVALID" in text
    assert "RUNTIME_OBJECT_HASH_INVALID" in text


def test_catalog_workers_pin_numeric_threads_without_oversubscription() -> None:
    worker_texts = [
        (ROOT / ".github/workflows/catalog-optimized-worker.yml").read_text(
            "utf-8"
        ),
        (ROOT / ".github/workflows/catalog-component-worker.yml").read_text(
            "utf-8"
        ),
    ]
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        assert all(f'{variable}: "1"' in text for text in worker_texts)


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


def test_catalog_reduction_uses_bound_merge_action_and_root_only() -> None:
    workflow = load_github_yaml(CATALOG_OPTIMIZED_WORKFLOW_PATH)
    jobs = workflow["jobs"]
    grouped = jobs["reduce_groups"]
    merge_step = next(
        step
        for step in grouped["steps"]
        if step.get("uses") == "./.github/actions/aurora-merge-level"
    )
    assert merge_step["with"]["mode"] == "catalog"
    assert merge_step["with"]["expected-level"] == "0"
    assert merge_step["with"]["expected-authority-id"] == (
        "${{ inputs.authority_id }}"
    )
    assert merge_step["with"]["expected-campaign-id"] == (
        "${{ inputs.campaign_id }}"
    )
    assert merge_step["with"]["expected-science-sha256"] == (
        "${{ inputs.science_sha256 }}"
    )
    assert merge_step["with"]["expected-execution-plan-sha256"] == (
        "${{ inputs.execution_plan_sha256 }}"
    )
    final_download = next(
        step
        for step in jobs["reduce"]["steps"]
        if step["name"] == "Download only bounded reduction groups"
    )
    assert "reduction_artifact_pattern" in final_download["with"]["pattern"]
    assert "checkpoint" not in final_download["with"]["pattern"]

    workflow_text = CATALOG_OPTIMIZED_WORKFLOW_PATH.read_text("utf-8")
    assert 'selected_mode == "central"' in workflow_text
    assert "expected_maximum_groups = 1" in workflow_text
    assert "expected_maximum_fan_in = 360" in workflow_text

    action_text = MERGE_LEVEL_ACTION_PATH.read_text("utf-8")
    for marker in (
        "Validate immutable reducer mode",
        "CATALOG_MERGE_MODE_INVALID",
        "CATALOG_MERGE_DIRECT_CHILD_SET_INVALID",
        "CATALOG_MERGE_PLAN_BINDING_INVALID",
        "CATALOG_MERGE_RESOURCE_MARGIN_UNPROVEN",
        "node_descriptor_sha256",
        "float(projection[field]) > 0.70",
        "float(projection[field]) < 0",
    ):
        assert marker in action_text
