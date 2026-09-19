from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/catalog-optimized-run.yml"


def _step(job: str, step_id: str) -> dict[str, Any]:
    workflow = load_github_yaml(WORKFLOW)
    return next(
        step
        for step in workflow["jobs"][job]["steps"]
        if step.get("id") == step_id
    )


def _inline_python(run: str) -> str:
    for marker in ("python -S - <<'PY'\n", "python - <<'PY'\n"):
        if marker in run:
            return textwrap.dedent(run.split(marker, 1)[1].split("\nPY", 1)[0])
    raise AssertionError("inline Python block not found")


def _sha(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sealed_profile_fixture(tmp_path: Path, *, include_profile: bool, generation: int = 8, duplicate: bool = False) -> Path:
    root = tmp_path / "runner-temp" / "sealed-plan"
    root.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    controller: dict[str, object] = {
        "schema_version": "1",
        "binding": {"request_sha256": "a" * 64},
    }
    profiles = [
        {"schema_version": "1", "campaign_key": "catalog-fast-canary-v1",
         "target_generation": target, "source_request_sha256": "b" * 64}
        for target in (8, 9, 11)
    ]
    profile = next(row for row in profiles if row["target_generation"] == generation)
    if include_profile:
        profile_path = root / "reduction_recovery.json"
        profile_path.write_text(
            json.dumps(profile, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        controller["binding"]["reduction_recovery_sha256"] = _sha(profile)  # type: ignore[index]
    (workspace / "config/catalog_reduction_recovery_profiles_v1.json").write_text(
        json.dumps(
            {"schema_version": "1", "profiles": [profiles[0], profiles[1], profiles[1]] if duplicate else profiles},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    controller["content_sha256"] = _sha(
        {key: value for key, value in controller.items() if key != "content_sha256"}
    )
    controller_path = root / "controller_binding.json"
    controller_path.write_text(
        json.dumps(controller, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    for path in (controller_path, root / "reduction_recovery.json"):
        if path.is_file():
            manifest.append(
                {
                    "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size_bytes": path.stat().st_size,
                }
            )
    receipt_identity = {
        "schema_version": "1",
        "content_manifest": manifest,
        "content_manifest_sha256": _sha(manifest),
        "validation_opened": False,
        "locked_opened": False,
    }
    receipt = {
        **receipt_identity,
        "receipt_sha256": _sha(receipt_identity),
    }
    (root / "execution_plan_receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return root.parent


def _run_recovery_verifier(tmp_path: Path, *, include_profile: bool, generation: int = 8, duplicate: bool = False) -> subprocess.CompletedProcess[str]:
    step = _step("engine_verify_sealed_plan", "recovery")
    script = _inline_python(step["run"])
    runner_temp = _sealed_profile_fixture(tmp_path, include_profile=include_profile, generation=generation, duplicate=duplicate)
    output = tmp_path / "github-output.txt"
    output.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_WORKSPACE": str(tmp_path / "workspace"),
        }
    )
    return subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _outputs(tmp_path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in (tmp_path / "github-output.txt").read_text(encoding="utf-8").splitlines()
        if line
    )


@pytest.mark.parametrize("generation", [8, 9, 11])
def test_engine_verify_derives_reduction_only_from_sealed_profile_and_manifest(tmp_path: Path, generation: int) -> None:
    result = _run_recovery_verifier(tmp_path, include_profile=True, generation=generation)
    assert result.returncode == 0, result.stderr
    values = _outputs(tmp_path)
    assert values["reduction_only"] == "true"
    assert values["recovery_verified"] == "true"


def test_engine_verify_rejects_duplicate_protected_profile_targets(tmp_path: Path) -> None:
    result = _run_recovery_verifier(tmp_path, include_profile=True, duplicate=True)
    assert result.returncode != 0
    assert "CATALOG_REDUCTION_RECOVERY_PROFILE_MISMATCH" in result.stderr


def test_engine_verify_without_profile_is_normal_and_does_not_accept_free_input(tmp_path: Path) -> None:
    result = _run_recovery_verifier(tmp_path, include_profile=False)
    assert result.returncode == 0, result.stderr
    values = _outputs(tmp_path)
    assert values["reduction_only"] == "false"
    assert values["recovery_verified"] == "false"


def test_reduction_only_route_skips_producers_but_keeps_runtime_and_current_science() -> None:
    workflow = load_github_yaml(WORKFLOW)
    jobs = workflow["jobs"]
    for job in (
        "publish_sealed_payload_artifacts",
        "build_components_a",
        "build_components_b",
        "materialize_cached_components_a",
        "materialize_cached_components_b",
        "verify_component_store",
        "evaluate_a",
        "evaluate_b",
        "evaluate_c",
        "reconcile_wave_0",
        "recovery_wave_1",
        "recovery_wave_2",
        "recovery_wave_3",
        "ready_to_merge",
        "reduce_groups",
    ):
        condition = str(jobs[job].get("if", ""))
        assert "reduction_only" in condition or job.startswith("recovery_wave_")
        assert "!= 'true'" in condition or job.startswith("recovery_wave_")

    reduce_condition = str(jobs["reduce"]["if"])
    assert "prepare_runtime_and_inputs.result == 'success'" in reduce_condition
    assert "recovery_verified" in reduce_condition
    assert "ready_to_merge.result == 'success'" in reduce_condition
    assert "reduce_groups.result == 'success'" in reduce_condition
    assert "reduction_only != 'true'" in reduce_condition

    restore = next(
        step
        for step in jobs["reduce"]["steps"]
        if step.get("name") == "Restore sealed reduction-only source"
    )
    assert "scripts/restore_catalog_reduction_recovery.py" in restore["run"]
    assert "--sealed-plan" in restore["run"]
    assert "--output-dir" in restore["run"]
    assert restore["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert restore["env"]["CATALOG_PROTECTED_COMMIT_SHA"] == "${{ github.sha }}"

    reducer = next(
        step
        for step in jobs["reduce"]["steps"]
        if step.get("name") == "Merge the sealed bounded reduction groups"
    )
    assert "--sealed-plan" in reducer["run"]
    assert "--recovery-source-root" in reducer["run"]
    assert "$RUNNER_TEMP/reduction-recovery/groups" in reducer["run"]


def test_recovery_route_disables_fault_activation_and_does_not_use_old_token() -> None:
    workflow = load_github_yaml(WORKFLOW)
    canary = _step("engine_verify_sealed_plan", "canary")
    assert "reduction_recovery.json" in canary["run"]
    reducer = next(
        step
        for step in workflow["jobs"]["reduce"]["steps"]
        if step.get("name") == "Merge the sealed bounded reduction groups"
    )
    assert "admission-token" in reducer["run"]
    assert "old" not in reducer["run"].lower()


def test_run_outcome_extracts_all_recovery_stage_results_from_workflow(tmp_path: Path) -> None:
    workflow = load_github_yaml(WORKFLOW)
    assert "publish_sealed_payload_artifacts" in workflow["jobs"]["campaign_outcome"]["needs"]
    outcome_step = next(
        step
        for step in workflow["jobs"]["campaign_outcome"]["steps"]
        if step.get("name") == "Build one closed engine-outcome input"
    )
    script = _inline_python(outcome_step["run"])
    environment = os.environ.copy()
    environment.update(
        {
            "RESULT_ENGINE_VERIFY": "success",
            "RESULT_PREPARE": "success",
            "RESULT_PUBLISH": "skipped",
            "RESULT_BUILD_A": "skipped",
            "RESULT_BUILD_B": "skipped",
            "RESULT_CACHED_A": "skipped",
            "RESULT_CACHED_B": "skipped",
            "RESULT_COMPONENT_SEAL": "skipped",
            "RESULT_EVALUATE_A": "skipped",
            "RESULT_EVALUATE_B": "skipped",
            "RESULT_EVALUATE_C": "skipped",
            "RESULT_RECONCILE": "skipped",
            "RESULT_RECOVERY_1": "skipped",
            "RESULT_RECOVERY_2": "skipped",
            "RESULT_RECOVERY_3": "skipped",
            "RESULT_READY": "skipped",
            "RESULT_REDUCE_GROUPS": "skipped",
            "RESULT_REDUCE": "success",
            "RESULT_SCIENCE": "success",
            "RESULT_AUDIT": "success",
            "VERIFIED_REDUCTION_ONLY": "true",
            "VERIFIED_RECOVERY": "true",
            "RECOVERY_0": "",
            "RECOVERY_1": "",
            "RECOVERY_2": "",
            "RECOVERY_3": "",
            "GITHUB_RUN_ID": "1234",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(tmp_path / "github-output.txt"),
            "FINAL_EVIDENCE_ARTIFACT": "catalog-final-root",
        }
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", script],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads((tmp_path / "engine-outcome-input.json").read_text(encoding="utf-8"))
    recovery_stages = {
        "publish_sealed_payload_artifacts",
        "build_components_a",
        "build_components_b",
        "materialize_cached_components_a",
        "materialize_cached_components_b",
        "verify_component_store",
        "evaluate_a",
        "evaluate_b",
        "evaluate_c",
        "reconcile_wave_0",
        "recovery_wave_1",
        "recovery_wave_2",
        "recovery_wave_3",
        "ready_to_merge",
        "reduce_groups",
    }
    stages = payload["stage_results"]
    assert {name for name in recovery_stages if stages.get(name) != "skipped"} == set()


def test_historical_request_read_is_scoped_to_reducer_and_call_chain() -> None:
    workflow = load_github_yaml(WORKFLOW)
    assert workflow["permissions"].get("issues", "none") == "none"
    assert workflow["jobs"]["reduce"]["permissions"] == {
        "actions": "read", "contents": "read", "issues": "read",
    }
    for filename, job in (
        ("catalog-fast-controller.yml", "engine"),
        ("catalog-run-controller.yml", "engine_optimized_catalog_v1"),
        ("catalog-prepare-one.yml", "prepare_engine"),
        ("catalog-prepare.yml", "prepare"),
    ):
        caller = load_github_yaml(ROOT / ".github/workflows" / filename)
        assert caller["jobs"][job]["permissions"] == {
            "actions": "read", "contents": "read", "issues": "read",
        }
