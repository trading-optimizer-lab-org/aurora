from __future__ import annotations

import json
from pathlib import Path
import re
import textwrap
from typing import TypedDict, cast

import pytest

from aurora.infra.github_performance.preflight import (
    load_github_yaml,
)
from aurora.infra.sp500_megarun.catalog_github_controls import (
    AUDITOR_CALLER_TOPOLOGY,
    inventory_heavy_workflows,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
POLICY = WORKFLOWS / "catalog-controller-policy-check.yml"
LIVE_AUDIT = ROOT / ".github/actions/catalog-live-controls-audit/action.yml"
BROKEN_LIVE_AUDIT_WORKFLOW = ".github/workflows/catalog-live-controls-audit.yml"
LOCAL_LIVE_AUDIT_ACTION = "./.github/actions/catalog-live-controls-audit"
LIVE_QUALIFICATION = WORKFLOWS / "catalog-live-controls-qualification.yml"
CONTROLLER_QUALIFICATION = WORKFLOWS / "catalog-controller-qualification.yml"
AUDIT_CREDENTIAL_NAMES = {
    "AURORA_CATALOG_AUDITOR_APP_ID",
    "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
    "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
    "AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN",
    "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN",
}
AUDIT_CALLER_WORKFLOWS = {
    ".github/workflows/catalog-live-controls-qualification.yml": {
        "qualify_live_admission_controls": {
            "purpose": "admission",
            "caller-workflow": ".github/workflows/catalog-live-controls-qualification.yml",
            "caller-job": "qualify_live_admission_controls",
            "protected-commit-sha": "${{ github.sha }}",
            "audit-context-sha256": "188a007b5b956430175492a1016026214d71c4ba4af0f7afc2f5dea6d8aecbe4",
        },
        "qualify_live_terminal_controls": {
            "purpose": "terminal",
            "caller-workflow": ".github/workflows/catalog-live-controls-qualification.yml",
            "caller-job": "qualify_live_terminal_controls",
            "protected-commit-sha": "${{ github.sha }}",
            "audit-context-sha256": "c32c0915943952c27734fcb52279556e3cc814a2fd6ef3d500335ceca7c0bcb3",
            "qualification-replay-directory": "admission-controls",
        },
    },
    ".github/workflows/catalog-run-controller.yml": {
        "live_controls_audit_before_reserve": {
            "purpose": "admission",
            "caller-workflow": ".github/workflows/catalog-run-controller.yml",
            "caller-job": "live_controls_audit_before_reserve",
            "protected-commit-sha": "${{ needs.prepare_admission_candidates.outputs.controls_commit_sha }}",
            "audit-context-sha256": "${{ needs.prepare_admission_candidates.outputs.audit_context_sha256 }}",
        },
        "live_controls_audit_before_terminal": {
            "purpose": "terminal",
            "caller-workflow": ".github/workflows/catalog-run-controller.yml",
            "caller-job": "live_controls_audit_before_terminal",
            "protected-commit-sha": "${{ needs.prepare_terminal_evidence.outputs.controls_commit_sha }}",
            "audit-context-sha256": "${{ needs.prepare_terminal_evidence.outputs.audit_context_sha256 }}",
        },
    },
    ".github/workflows/catalog-artifact-keeper.yml": {
          "live_controls_audit_before_maintenance": {
              "purpose": "maintenance",
              "caller-workflow": ".github/workflows/catalog-artifact-keeper.yml",
              "caller-job": "live_controls_audit_before_maintenance",
              "protected-commit-sha": "${{ github.sha }}",
              "audit-context-sha256": "0b90c2b50f081b48eb3b173b907eab0015973e536db2e8e195ff8f95b69bec42",
          },
    },
}
AUDIT_ACTION_INPUT_NAMES = {
    "purpose",
    "caller-workflow",
    "caller-job",
    "protected-commit-sha",
    "audit-context-sha256",
    "qualification-replay-directory",
    "auditor-app-id",
    "auditor-private-key",
    "enterprise-billing-token",
    "enterprise-cache-verifier-token",
    "package-inventory-token",
}
AUDIT_ACTION_CREDENTIAL_WITH = {
    "auditor-app-id": "${{ vars.AURORA_CATALOG_AUDITOR_APP_ID }}",
    "auditor-private-key": "${{ secrets.AURORA_CATALOG_AUDITOR_PRIVATE_KEY }}",
    "enterprise-billing-token": (
        "${{ secrets.AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN }}"
    ),
    "enterprise-cache-verifier-token": (
        "${{ secrets.AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN }}"
    ),
    "package-inventory-token": (
        "${{ secrets.AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN }}"
    ),
}
AUDIT_JOB_NEEDS: dict[tuple[str, str], str | list[str] | None] = {
    (".github/workflows/catalog-live-controls-qualification.yml", "qualify_live_admission_controls"): None,
    (".github/workflows/catalog-live-controls-qualification.yml", "qualify_live_terminal_controls"): "qualify_live_admission_controls",
    (".github/workflows/catalog-run-controller.yml", "live_controls_audit_before_reserve"): "prepare_admission_candidates",
    (".github/workflows/catalog-run-controller.yml", "live_controls_audit_before_terminal"): "prepare_terminal_evidence",
    (".github/workflows/catalog-artifact-keeper.yml", "live_controls_audit_before_maintenance"): None,
}
AUDIT_JOB_IF = {
    (".github/workflows/catalog-run-controller.yml", "live_controls_audit_before_reserve"): "${{ needs.prepare_admission_candidates.result == 'success' }}",
    (".github/workflows/catalog-run-controller.yml", "live_controls_audit_before_terminal"): "${{ needs.prepare_terminal_evidence.result == 'success' }}",
}
AUDIT_JOB_OUTPUTS = {
    "receipt_artifact_name": "${{ steps.controls.outputs.receipt_artifact_name }}",
    "receipt_sha256": "${{ steps.controls.outputs.receipt_sha256 }}",
    "receipt_status": "${{ steps.controls.outputs.receipt_status }}",
}
FULL_ACTION_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
SEALED_IDENTIFIERS = {
    "request_sha256",
    "authority_id",
    "campaign_id",
    "science_sha256",
    "execution_plan_sha256",
    "execution_protocol_sha256",
    "protected_commit_sha",
    "decision_sha256",
}
PRODUCTION_HEAVY_WORKFLOWS = {
    ".github/workflows/catalog-optimized-run.yml",
    ".github/workflows/sp500-atlas-run.yml",
    ".github/workflows/catalog-component-worker.yml",
    ".github/workflows/catalog-optimized-worker.yml",
}
LEGACY_CATALOG_WORKFLOWS = {
    ".github/workflows/sp500-atlas-calibration.yml",
    ".github/workflows/sp500-atlas-controller.yml",
    ".github/workflows/sp500-atlas-pilot.yml",
    ".github/workflows/sp500-atlas-postrun.yml",
    ".github/workflows/sp500-atlas-segment.yml",
    ".github/workflows/sp500-catalog-optimization-qualification.yml",
    ".github/workflows/sp500-strategy-catalog-overnight.yml",
}


_WorkflowStep = TypedDict(
    "_WorkflowStep",
    {
        "id": str,
        "name": str,
        "uses": str,
        "run": str,
        "with": dict[str, object],
        "env": dict[str, object],
        "if": str,
        "shell": str,
        "working-directory": str,
        "continue-on-error": bool,
    },
    total=False,
)
_WorkflowJob = TypedDict(
    "_WorkflowJob",
    {
        "name": str,
        "runs-on": str,
        "timeout-minutes": int,
        "environment": str,
        "permissions": dict[str, object],
        "concurrency": dict[str, object],
        "outputs": dict[str, object],
        "needs": str | list[str],
        "uses": str,
        "with": dict[str, object],
        "if": str,
        "env": dict[str, object],
        "steps": list[_WorkflowStep],
        "strategy": dict[str, object],
    },
    total=False,
)
_WorkflowCall = TypedDict(
    "_WorkflowCall",
    {"inputs": dict[str, object], "outputs": dict[str, object], "secrets": dict[str, object]},
    total=False,
)
_WorkflowOn = TypedDict(
    "_WorkflowOn",
    {
        "workflow_call": _WorkflowCall,
        "workflow_dispatch": dict[str, object],
        "issues": dict[str, object],
        "issue_comment": dict[str, object],
        "schedule": list[dict[str, object]],
        "push": dict[str, object],
        "pull_request": dict[str, object],
        "merge_group": dict[str, object],
        "workflow_run": dict[str, object],
    },
    total=False,
)
_Workflow = TypedDict(
    "_Workflow",
    {
        "name": str,
        "on": _WorkflowOn,
        "inputs": dict[str, dict[str, object]],
        "outputs": dict[str, dict[str, object]],
        "runs": dict[str, object],
        "permissions": dict[str, object],
        "jobs": dict[str, _WorkflowJob],
        "concurrency": dict[str, object],
        "env": dict[str, object],
    },
    total=False,
)


def _workflow(path: Path) -> _Workflow:
    return cast(_Workflow, dict(load_github_yaml(path)))


def _all_workflows() -> dict[str, _Workflow]:
    return {
        path.relative_to(ROOT).as_posix(): _workflow(path)
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
    }


def _external_action_uses(workflow: _Workflow) -> list[str]:
    found: list[str] = []
    jobs = workflow.get("jobs", {})
    assert isinstance(jobs, dict)
    for job in jobs.values():
        assert isinstance(job, dict)
        job_uses = job.get("uses")
        if isinstance(job_uses, str) and not job_uses.startswith("./"):
            found.append(job_uses)
        steps = job.get("steps", [])
        assert isinstance(steps, list)
        for step in steps:
            assert isinstance(step, dict)
            uses = step.get("uses")
            if isinstance(uses, str) and not uses.startswith("./"):
                found.append(uses)
    return found


def test_all_concurrency_blocks_use_only_supported_github_actions_keys() -> None:
    allowed = {"group", "queue", "cancel-in-progress"}
    for path, workflow in _all_workflows().items():
        blocks: list[tuple[str, object]] = [("workflow", workflow.get("concurrency"))]
        jobs = workflow.get("jobs", {})
        assert isinstance(jobs, dict)
        blocks.extend(
            (f"job {job_id}", job.get("concurrency"))
            for job_id, job in jobs.items()
            if isinstance(job, dict)
        )
        for location, block in blocks:
            if block is None:
                continue
            assert isinstance(block, dict)
            assert set(block) <= allowed, f"{path} {location}: {set(block) - allowed}"
            if "queue" in block:
                assert block["queue"] == "max"
                assert block.get("cancel-in-progress") is not True


def test_step_ids_are_unique_case_insensitively_within_each_job() -> None:
    for path, workflow in _all_workflows().items():
        jobs = workflow.get("jobs", {})
        assert isinstance(jobs, dict)
        for job_id, job in jobs.items():
            assert isinstance(job, dict)
            steps = job.get("steps", [])
            assert isinstance(steps, list)
            step_ids = [
                str(step["id"]).casefold()
                for step in steps
                if isinstance(step, dict) and "id" in step
            ]
            assert len(step_ids) == len(set(step_ids)), f"{path} job {job_id}"


def test_task_seven_embeds_all_five_future_auditor_callers() -> None:
    assert AUDITOR_CALLER_TOPOLOGY == (
        (
            ".github/workflows/catalog-run-controller.yml",
            "live_controls_audit_before_reserve",
            "admission",
            "controller_admission",
        ),
        (
            ".github/workflows/catalog-run-controller.yml",
            "live_controls_audit_before_terminal",
            "terminal",
            "controller_terminal",
        ),
        (
            ".github/workflows/catalog-artifact-keeper.yml",
            "live_controls_audit_before_maintenance",
            "maintenance",
            "keeper_maintenance",
        ),
        (
            ".github/workflows/catalog-live-controls-qualification.yml",
            "qualify_live_admission_controls",
            "admission",
            "live_qualification_admission",
        ),
        (
            ".github/workflows/catalog-live-controls-qualification.yml",
            "qualify_live_terminal_controls",
            "terminal",
            "live_qualification_terminal",
        ),
    )


def test_codeowners_covers_every_catalog_controller_sensitive_path() -> None:
    text = (ROOT / ".github/CODEOWNERS").read_text("utf-8")
    for line in (
        "/docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md @gomez5757",
        "/config/catalog_run_prompt_policy_v1.json @gomez5757",
        "/config/catalog_campaign_registry_v1.json @gomez5757",
        "/config/catalog_campaign_definitions/ @gomez5757",
        "/config/catalog_controller_actors_v1.json @gomez5757",
        "/config/catalog_authority_anchor_v1.json @gomez5757",
        "/config/catalog_github_controls_v1.json @gomez5757",
        "/config/catalog_github_auditor_v1.json @gomez5757",
        "/config/catalog_requester_* @gomez5757",
        "/schemas/catalog_run_* @gomez5757",
        "/schemas/catalog_campaign_definition_manifest_v1.schema.json @gomez5757",
        "/schemas/catalog_github_auditor_v1.schema.json @gomez5757",
        "/schemas/catalog_authority_anchor_v1.schema.json @gomez5757",
        "/infra/sp500_megarun/catalog_* @gomez5757",
        "/scripts/*catalog* @gomez5757",
        "/.github/workflows/catalog-* @gomez5757",
        "/.github/actions/aurora-* @gomez5757",
    ):
        assert line in text


def test_every_active_catalog_engine_is_workflow_call_only_and_sealed() -> None:
    workflows = _all_workflows()
    inventory = inventory_heavy_workflows(workflows)
    by_path = {item["path"]: item for item in inventory}
    for path in PRODUCTION_HEAVY_WORKFLOWS:
        workflow = workflows[path]
        assert set(workflow["on"]) == {"workflow_call"}
        assert SEALED_IDENTIFIERS <= set(workflow["on"]["workflow_call"]["inputs"])
        assert by_path[path]["heavy"] is True
        assert by_path[path]["direct_heavy_triggers"] == ()
        assert workflow["permissions"] == {"actions": "read", "contents": "read"}


def test_all_catalog_compute_jobs_use_free_linux_and_protected_environment() -> None:
    workflows = _all_workflows()
    for path in PRODUCTION_HEAVY_WORKFLOWS:
        for job in workflows[path]["jobs"].values():
            if "runs-on" not in job:
                continue
            assert job["runs-on"] == "ubuntu-24.04"
            assert job["environment"] == "catalog-production"
            assert job.get("permissions", workflows[path]["permissions"]).get(
                "issues"
            ) != "write"


def test_production_inputs_cannot_select_paths_commands_or_runners() -> None:
    workflows = _all_workflows()
    for path in PRODUCTION_HEAVY_WORKFLOWS:
        names = set(workflows[path]["on"]["workflow_call"]["inputs"])
        assert all(
            marker not in name
            for name in names
            for marker in (
                "path",
                "workflow",
                "command",
                "runner",
                "artifact_name",
                "data_boundary",
            )
        )


def test_all_catalog_external_actions_are_full_sha_pinned() -> None:
    for path, workflow in _all_workflows().items():
        if "catalog" in path or "atlas" in path:
            assert all(
                FULL_ACTION_SHA.fullmatch(value)
                for value in _external_action_uses(workflow)
            ), path


def test_legacy_catalog_launchers_have_no_public_trigger() -> None:
    workflows = _all_workflows()
    violations = {
        path: tuple(workflows[path]["on"])
        for path in LEGACY_CATALOG_WORKFLOWS
        if set(workflows[path]["on"]) != {"workflow_call"}
    }
    assert violations == {}


def test_recovery_wave_is_closed_bounded_and_reuses_the_worker() -> None:
    path = WORKFLOWS / "catalog-recovery-wave.yml"
    workflow = _workflow(path)
    assert workflow["on"].keys() == {"workflow_call"}
    inputs = workflow["on"]["workflow_call"]["inputs"]
    assert set(inputs) == SEALED_IDENTIFIERS | {
        "campaign_state_artifact",
        "attempt_manifest_artifacts",
        "failure_manifest_artifacts",
        "checkpoint_manifest_artifacts",
        "current_wave",
    }
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "catalog-recovery-${{ inputs.authority_id }}",
        "cancel-in-progress": False,
    }
    jobs = workflow["jobs"]
    assert set(jobs) == {
        "reconcile",
        "retry_a",
        "retry_b",
        "finalize_wave",
    }
    assert jobs["retry_a"]["uses"] == (
        "./.github/workflows/catalog-optimized-worker.yml"
    )
    assert jobs["retry_b"]["uses"] == (
        "./.github/workflows/catalog-optimized-worker.yml"
    )
    text = path.read_text("utf-8").casefold()
    assert "workflow_dispatch" not in text
    assert "gh run rerun" not in text
    assert "gh workflow run" not in text
    assert "continue-on-error" not in text
    assert "expected_attempt_count" in text
    assert "expected_failure_count" in text
    assert "expected_checkpoint_count" in text
    assert "catalog-failure-attempt-" in text
    assert "failure_reason_code" in text


def test_catalog_recovery_inline_python_is_syntactically_valid() -> None:
    paths = (
        ROOT / ".github/actions/aurora-recovery-plan/action.yml",
        WORKFLOWS / "catalog-recovery-wave.yml",
        WORKFLOWS / "catalog-optimized-worker.yml",
        WORKFLOWS / "catalog-optimized-run.yml",
    )
    found = 0
    for path in paths:
        source = path.read_text("utf-8")
        for index, match in enumerate(
            re.finditer(r"python - <<'PY'\n(.*?)\n\s+PY", source, re.DOTALL),
            start=1,
        ):
            compile(
                textwrap.dedent(match.group(1)),
                f"{path}:inline-python-{index}",
                "exec",
            )
            found += 1
    assert found >= 8


@pytest.mark.parametrize("job_id", (
    "verify_component_store", "evaluate_a", "evaluate_b", "evaluate_c",
    "reconcile_wave_0", "recovery_wave_1", "recovery_wave_2", "recovery_wave_3",
    "ready_to_merge", "reduce_groups", "reduce",
))
def test_engine_dispatch_contract_blocks_new_work_after_cancellation(job_id: str) -> None:
    # Validate the boundary sent to GitHub, not a substitute scheduler.
    # Actual cancellation propagation is still an integrated acceptance case.
    job = _workflow(WORKFLOWS / "catalog-optimized-run.yml")["jobs"][job_id]
    condition = str(job["if"])
    assert re.match(r"\$\{\{\s*!cancelled\(\)\s*&&", condition), job_id


def test_final_reduction_requires_verified_readiness_even_without_group_jobs() -> None:
    job = _workflow(WORKFLOWS / "catalog-optimized-run.yml")["jobs"]["reduce"]
    assert "ready_to_merge" in job["needs"]
    condition = str(job["if"])
    assert "needs.ready_to_merge.result == 'success' &&" in condition


def test_cancellation_keeps_terminal_diagnostics_available() -> None:
    jobs = _workflow(WORKFLOWS / "catalog-optimized-run.yml")["jobs"]
    assert "always()" in str(jobs["campaign_outcome"]["if"])
    recovery = _workflow(WORKFLOWS / "catalog-recovery-wave.yml")["jobs"]
    assert "always()" in str(recovery["finalize_wave"]["if"])


def test_engine_unrolls_two_retry_waves_and_one_final_observation() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-optimized-run.yml")
    jobs = workflow["jobs"]
    assert "reconcile_wave_0" in jobs
    for wave in range(1, 4):
        job = jobs[f"recovery_wave_{wave}"]
        assert job["uses"] == "./.github/workflows/catalog-recovery-wave.yml"
        serialized = json.dumps(job, sort_keys=True)
        assert f"current_wave\": {wave}" in serialized
        assert "retry" in serialized and "replan" in serialized
        assert "always()" in str(job["if"])
    assert "recovery_wave_4" not in jobs
    final_gate = jobs["ready_to_merge"]
    assert "recovery_wave_3" in final_gate["needs"]
    text = (WORKFLOWS / "catalog-optimized-run.yml").read_text("utf-8")
    assert "rerun all jobs" not in text.casefold()
    assert "catalog-recovery-wave.yml" in text


def test_engine_preparation_mode_builds_store_but_never_evaluates_recipes() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-optimized-run.yml")
    inputs = workflow["on"]["workflow_call"]["inputs"]
    assert inputs["execution_mode"] == {
        "required": False,
        "type": "string",
        "default": "run",
    }
    jobs = workflow["jobs"]
    for job_id in (
        "evaluate_a",
        "evaluate_b",
        "evaluate_c",
        "reconcile_wave_0",
        "recovery_wave_1",
        "recovery_wave_2",
        "ready_to_merge",
        "reduce_groups",
        "reduce",
        "verify_terminal_science",
        "audit_runtime",
    ):
        assert "inputs.execution_mode == 'run'" in str(jobs[job_id].get("if", ""))
    assert "inputs.execution_mode == 'prepare'" in json.dumps(
        jobs["campaign_outcome"], sort_keys=True
    )


def test_reusable_catalog_engine_uses_variable_commit_only_as_a_guard() -> None:
    for relative in (
        "catalog-optimized-run.yml",
        "catalog-component-worker.yml",
        "catalog-optimized-worker.yml",
        "catalog-recovery-wave.yml",
    ):
        text = (WORKFLOWS / relative).read_text(encoding="utf-8")
        assert text.count("${{ inputs.protected_commit_sha }}") == 1
        assert (
            "REQUESTED_PROTECTED_COMMIT_SHA: "
            "${{ inputs.protected_commit_sha }}"
        ) in text
        assert (
            "ref: ${{ github.sha }}" in text
            or 'ref: "${{ github.sha }}"' in text
        )

    runtime = (
        ROOT / ".github/actions/aurora-runtime-setup/action.yml"
    ).read_text(encoding="utf-8")
    assert runtime.count("${{ inputs.expected-source-sha }}") == 1
    assert (
        "REQUESTED_SOURCE_SHA: ${{ inputs.expected-source-sha }}"
    ) in runtime
    assert "EXPECTED_SOURCE_SHA: ${{ github.sha }}" in runtime


def test_requested_run_never_builds_runtime_or_prepared_inputs() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-optimized-run.yml")
    steps = workflow["jobs"]["prepare_runtime_and_inputs"]["steps"]
    by_name = {step["name"]: step for step in steps}
    assert "inputs.execution_mode == 'run'" in by_name[
        "Refuse runtime construction in a requested run"
    ]["if"]
    assert "inputs.execution_mode == 'prepare'" in by_name[
        "Build the one locked runtime store"
    ]["if"]
    assert "inputs.execution_mode == 'run'" in by_name[
        "Refuse input preparation in a requested run"
    ]["if"]
    assert "inputs.execution_mode == 'prepare'" in by_name[
        "Download and verify the frozen train-only source once"
    ]["if"]
    for step in steps:
        if str(step.get("uses", "")).startswith("actions/cache/save@"):
            assert "inputs.execution_mode == 'prepare'" in str(step.get("if", ""))


def test_preparation_activates_one_offline_runtime_before_python_helpers() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-optimized-run.yml")
    steps = workflow["jobs"]["prepare_runtime_and_inputs"]["steps"]
    setup_indices = [
        index
        for index, step in enumerate(steps)
        if step.get("uses") == "./.github/actions/aurora-runtime-setup"
    ]
    download_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name")
        == "Download and verify the frozen train-only source once"
    )

    assert len(setup_indices) == 1
    assert setup_indices[0] < download_index


def test_engine_publishes_one_content_bound_global_reuse_index() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-optimized-run.yml")
    steps = workflow["jobs"]["verify_component_store"]["steps"]
    serialized = json.dumps(steps, sort_keys=True)
    preparation = next(
        step
        for step in workflow["jobs"]["prepare_runtime_and_inputs"]["steps"]
        if step.get("name")
        == "Verify every prepared partition and derive immutable save keys"
    )
    preparation_script = preparation["run"]
    canonical_sort = (
        'verified_partitions.sort(key=lambda item: item["logical_id"])'
    )
    assert canonical_sort in preparation_script
    assert preparation_script.index(canonical_sort) < preparation_script.index(
        "identity = {"
    )
    uploads = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        and step.get("with", {}).get("path")
        == "${{ runner.temp }}/catalog-rebuildable-store-index-v1.json"
    ]
    assert len(uploads) == 1
    assert uploads[0]["with"]["name"] == (
        "${{ inputs.execution_mode == 'prepare' && "
        "format('catalog-rebuildable-store-index-prepared-{0}', inputs.authority_id) || "
        "'catalog-rebuildable-store-index-v1' }}"
    )
    assert uploads[0]["with"]["retention-days"] == 90
    assert "build_catalog_rebuildable_store_index.py" in serialized
    assert "actions/caches?ref=refs/heads/main&per_page=100" in serialized
    assert "catalog-runtime-prepared-seal" in serialized
    assert "catalog-main-caches-1.json" in serialized
    candidate_source = (
        ROOT / "scripts/prepare_catalog_admission_candidates.py"
    ).read_text("utf-8")
    assert "actions/artifacts?name={_STORE_INDEX_ARTIFACT_NAME}" in candidate_source
    assert 'f"/repos/{repository}/actions/artifacts",' not in candidate_source

    prepare = _workflow(WORKFLOWS / "catalog-prepare-one.yml")
    finalize_steps = prepare["jobs"]["finalize"]["steps"]
    download = next(
        step
        for step in finalize_steps
        if step.get("name") == "Download the verified global component-store index"
    )
    assert download["with"]["name"] == (
        "catalog-rebuildable-store-index-prepared-"
        "${{ needs.seed.outputs.authority_id }}"
    )


def test_engine_republishes_sealed_payloads_before_component_workers() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-optimized-run.yml")
    verifier = workflow["jobs"]["engine_verify_sealed_plan"]
    assert verifier["outputs"]["payload_artifact_matrix"] == (
        "${{ steps.verify.outputs.payload_artifact_matrix }}"
    )
    assert verifier["outputs"]["payload_artifact_count"] == (
        "${{ steps.verify.outputs.payload_artifact_count }}"
    )

    publisher = workflow["jobs"]["publish_sealed_payload_artifacts"]
    assert publisher["needs"] == ["engine_verify_sealed_plan"]
    assert publisher["strategy"]["matrix"] == (
        "${{ fromJSON(needs.engine_verify_sealed_plan.outputs.payload_artifact_matrix) }}"
    )
    rendered = json.dumps(publisher, sort_keys=True)
    assert "catalog-sealed-execution-plan-${{ inputs.authority_id }}" in rendered
    assert "payload_artifacts/${{ matrix.artifact }}" in rendered
    assert '\"name\": \"${{ matrix.artifact }}\"' in rendered

    for job_id in (
        "build_components_a",
        "build_components_b",
        "materialize_cached_components_a",
        "materialize_cached_components_b",
    ):
        assert "publish_sealed_payload_artifacts" in workflow["jobs"][job_id][
            "needs"
        ]


def test_checkpoint_upload_must_finish_before_the_next_segment() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-optimized-worker.yml")
    steps = workflow["jobs"]["evaluate"]["steps"]
    by_id = {
        step.get("id"): step
        for step in steps
        if isinstance(step, dict) and step.get("id")
    }
    for slot in range(2, 9):
        condition = str(by_id[f"compute_{slot}"]["if"])
        assert f"steps.upload_{slot - 1}.outputs['artifact-id'] != ''" in condition
        assert f"steps.upload_{slot - 1}.outputs['artifact-digest'] != ''" in condition


def test_recovery_action_accepts_zero_checkpoint_prefix_but_validates_any_chain() -> None:
    text = (
        ROOT / ".github/actions/aurora-recovery-plan/action.yml"
    ).read_text("utf-8")
    assert "validate_checkpoint_slot_chain" in text
    assert "CheckpointSlotEvidence" in text
    assert 'descriptor["prior_checkpoint_chain_artifact"] = (' in text
    assert 'checkpoint.artifact_name if checkpoint is not None else ""' in text
    assert "RECOVERY_AUTHORITATIVE_CHECKPOINT_MISSING" not in text
