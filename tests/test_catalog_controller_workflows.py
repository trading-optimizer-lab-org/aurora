from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from aurora.infra.github_performance.preflight import (
    load_github_yaml,
    validate_catalog_workflow_topology,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
)
from aurora.infra.sp500_megarun.catalog_github_controls import (
    AUDITOR_CALLER_TOPOLOGY,
    AUDITOR_SECRET_CONSUMER,
    inventory_heavy_workflows,
    jobs_with_issues_write,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
POLICY = WORKFLOWS / "catalog-controller-policy-check.yml"
LIVE_AUDIT = WORKFLOWS / "catalog-live-controls-audit.yml"
LIVE_QUALIFICATION = WORKFLOWS / "catalog-live-controls-qualification.yml"
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
    ".github/workflows/catalog-component-worker.yml",
    ".github/workflows/catalog-optimized-worker.yml",
}
LEGACY_CATALOG_WORKFLOWS = {
    ".github/workflows/sp500-atlas-calibration.yml",
    ".github/workflows/sp500-atlas-controller.yml",
    ".github/workflows/sp500-atlas-pilot.yml",
    ".github/workflows/sp500-atlas-postrun.yml",
    ".github/workflows/sp500-atlas-run.yml",
    ".github/workflows/sp500-atlas-segment.yml",
    ".github/workflows/sp500-catalog-optimization-qualification.yml",
    ".github/workflows/sp500-strategy-catalog-overnight.yml",
}


def _workflow(path: Path) -> dict[str, object]:
    return dict(load_github_yaml(path))


def _all_workflows() -> dict[str, dict[str, object]]:
    return {
        path.relative_to(ROOT).as_posix(): _workflow(path)
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
    }


def _external_action_uses(workflow: dict[str, object]) -> list[str]:
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


def test_policy_workflow_is_lightweight_read_only_and_exactly_named() -> None:
    workflow = _workflow(POLICY)
    assert workflow["on"] == {
        "pull_request": {},
        "push": {"branches": ["main"]},
    }
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"catalog-controller-policy"}
    job = jobs["catalog-controller-policy"]
    assert job["name"] == "catalog-controller-policy"
    assert job["runs-on"] == "ubuntu-24.04"
    rendered = json.dumps(job, sort_keys=True)
    assert "requirements/catalog-controller-test-linux-py311.lock" in rendered
    assert "--only-binary=:all:" in rendered
    assert "--no-deps" in rendered
    assert "--require-hashes" in rendered
    for required_test in (
        "tests/test_catalog_run_prompt_policy.py",
        "tests/test_catalog_run_request.py",
        "tests/test_catalog_campaign_definition.py",
        "tests/test_catalog_campaign_registry.py",
        "tests/test_catalog_authority_ledger.py",
        "tests/test_catalog_controller.py",
        "tests/test_catalog_github_controls.py",
        "tests/test_catalog_controller_reporting.py",
        "tests/test_github_performance_preflight.py",
        "tests/test_github_performance_workflows.py",
        "tests/test_catalog_controller_workflows.py",
    ):
        assert required_test in rendered
    assert not any(
        marker in rendered.casefold()
        for marker in (
            "catalog-optimized-worker",
            "build_sp500_component_store",
            "run_sp500_optimized_recipe_worker",
            "reduce_sp500_optimized_catalog_run",
            "catalog_recovery",
        )
    )
    assert all(FULL_ACTION_SHA.fullmatch(value) for value in _external_action_uses(workflow))


def test_live_audit_is_one_read_only_protected_reusable_job() -> None:
    workflow = _workflow(LIVE_AUDIT)
    assert set(workflow["on"]) == {"workflow_call"}
    call = workflow["on"]["workflow_call"]
    assert set(call) == {"inputs", "outputs"}
    assert set(call["inputs"]) == {
        "purpose",
        "caller_workflow",
        "caller_job",
        "protected_commit_sha",
        "audit_context_sha256",
    }
    assert set(call["outputs"]) == {
        "receipt_artifact_name",
        "receipt_sha256",
        "receipt_status",
    }
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"audit"}
    job = jobs["audit"]
    assert job["environment"] == "catalog-production"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == 5
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    assert "strategy" not in json.dumps(workflow).casefold()
    rendered = json.dumps(workflow, sort_keys=True)
    for forbidden in (
        "catalog-optimized-worker",
        "build_sp500_component_store",
        "run_sp500_optimized_recipe_worker",
        "reduce_sp500_optimized_catalog_run",
        "recover",
        "matrix",
    ):
        assert forbidden not in rendered.casefold()
    steps = job["steps"]
    secret_steps = [
        step
        for step in steps
        if "AURORA_CATALOG_AUDITOR_PRIVATE_KEY" in json.dumps(step)
    ]
    assert len(secret_steps) == 1
    assert "--workflow-auditor" in json.dumps(secret_steps[0])
    assert "--github-output" in json.dumps(secret_steps[0])
    assert all(FULL_ACTION_SHA.fullmatch(value) for value in _external_action_uses(workflow))
    assert any(
        step.get("uses", "").startswith("actions/upload-artifact@")
        for step in job["steps"]
    )


def test_auditor_secret_has_exactly_one_workflow_consumer() -> None:
    consumers = {
        path.relative_to(ROOT).as_posix()
        for path in WORKFLOWS.glob("*.y*ml")
        if "AURORA_CATALOG_AUDITOR_PRIVATE_KEY" in path.read_text("utf-8")
    }
    assert consumers == {AUDITOR_SECRET_CONSUMER}


def test_live_qualification_has_two_pure_calls_and_one_tiny_finalizer() -> None:
    workflow = _workflow(LIVE_QUALIFICATION)
    assert workflow["on"] == {"workflow_dispatch": {}}
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert "environment" not in json.dumps(workflow)
    assert "AURORA_CATALOG_AUDITOR" not in json.dumps(workflow)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {
        "qualify_live_admission_controls",
        "qualify_live_terminal_controls",
        "verify_qualification_receipt",
    }
    admission = jobs["qualify_live_admission_controls"]
    terminal = jobs["qualify_live_terminal_controls"]
    assert admission["uses"] == "./.github/workflows/catalog-live-controls-audit.yml"
    assert terminal["uses"] == "./.github/workflows/catalog-live-controls-audit.yml"
    assert admission["with"]["purpose"] == "admission"
    assert terminal["with"]["purpose"] == "terminal"
    assert terminal["needs"] == "qualify_live_admission_controls"
    assert "secrets" not in admission
    assert "secrets" not in terminal
    final = jobs["verify_qualification_receipt"]
    assert final["runs-on"] == "ubuntu-24.04"
    assert final["timeout-minutes"] == 5
    rendered = json.dumps(workflow, sort_keys=True)
    assert "matrix" not in rendered.casefold()
    assert "issues\": \"write" not in rendered
    assert all(FULL_ACTION_SHA.fullmatch(value) for value in _external_action_uses(workflow))


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


def test_controller_has_only_request_lifecycle_and_reconciler_triggers() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-run-controller.yml")
    assert workflow["on"]["issues"] == {
        "types": [
            "opened",
            "edited",
            "deleted",
            "transferred",
            "closed",
            "reopened",
            "locked",
            "unlocked",
            "labeled",
            "unlabeled",
        ]
    }
    assert set(workflow["on"]) == {"issues", "workflow_call"}
    assert set(workflow["on"]["workflow_call"]["inputs"]) == {"issue_number"}
    assert workflow["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "read",
    }
    assert "concurrency" not in workflow

    expected_writers = {
        "issue_tamper_guard",
        "reserve",
        "report_nonexecuting_decision",
        "record_running",
        "record_nonterminal_wait",
        "finalize",
    }
    writers = {
        job
        for path, job in jobs_with_issues_write(
            {".github/workflows/catalog-run-controller.yml": workflow}
        )
        if path == ".github/workflows/catalog-run-controller.yml"
    }
    assert writers == expected_writers
    for job_id in expected_writers:
        assert workflow["jobs"][job_id]["permissions"] == {
            "actions": "read",
            "contents": "read",
            "issues": "write",
        }

    for job_id in (
        "issue_tamper_guard",
        "reserve",
        "record_running",
        "record_nonterminal_wait",
        "finalize",
    ):
        assert workflow["jobs"][job_id]["concurrency"] == {
            "group": "catalog-authority-admission-v1",
            "cancel-in-progress": False,
            "queue": "max",
        }
    assert workflow["jobs"]["report_nonexecuting_decision"]["concurrency"] == {
        "group": (
            "catalog-request-receipt-v1-"
            "${{ needs.filter.outputs.issue_number }}"
        ),
        "cancel-in-progress": False,
        "queue": "max",
    }


def test_controller_job_order_and_authority_gates_are_explicit() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-run-controller.yml")
    jobs = workflow["jobs"]
    assert list(jobs) == [
        "issue_tamper_guard",
        "filter",
        "routing_snapshot",
        "route_without_privileged_audit",
        "prepare_admission_candidates",
        "live_controls_audit_before_reserve",
        "admission",
        "reserve",
        "report_nonexecuting_decision",
        "record_running",
        "engine_optimized_catalog_v1",
        "record_nonterminal_wait",
        "prepare_terminal_evidence",
        "live_controls_audit_before_terminal",
        "prepare_terminal_decision",
        "finalize",
    ]
    assert jobs["prepare_admission_candidates"]["needs"] == (
        "route_without_privileged_audit"
    )
    assert jobs["live_controls_audit_before_reserve"]["needs"] == (
        "prepare_admission_candidates"
    )
    assert jobs["admission"]["needs"] == [
        "prepare_admission_candidates",
        "live_controls_audit_before_reserve",
    ]
    assert jobs["reserve"]["needs"] == ["routing_snapshot", "admission"]
    engine = jobs["engine_optimized_catalog_v1"]
    assert engine["needs"] == ["admission", "reserve", "record_running"]
    assert engine["uses"] == "./.github/workflows/catalog-optimized-run.yml"
    assert "needs.reserve.outputs.authority_committed == 'true'" in engine["if"]
    assert (
        "needs.record_running.outputs.authority_execution_state_committed == 'true'"
        in engine["if"]
    )
    assert set(engine["with"]) == SEALED_IDENTIFIERS
    assert "secrets" not in engine
    assert "concurrency" not in engine


@pytest.mark.parametrize(
    "forbidden",
    [
        "github.event.issue.body }}",
        "github.event.issue.title }}",
        "pull_request_target",
        "secrets: inherit",
        "issues/comments/{comment_id}",
        "--method PATCH",
        "--method DELETE",
        "gh workflow run",
        "repository_dispatch",
        "/dispatches",
    ],
)
def test_controller_has_no_untrusted_or_mutable_escape(forbidden: str) -> None:
    text = (WORKFLOWS / "catalog-run-controller.yml").read_text("utf-8")
    assert forbidden not in text


def test_controller_privileged_audits_are_two_exact_pure_local_calls() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-run-controller.yml")
    jobs = workflow["jobs"]
    expected = {
        "live_controls_audit_before_reserve": "admission",
        "live_controls_audit_before_terminal": "terminal",
    }
    for job_id, purpose in expected.items():
        job = jobs[job_id]
        assert job["uses"] == "./.github/workflows/catalog-live-controls-audit.yml"
        assert job["with"]["purpose"] == purpose
        assert job["with"]["caller_workflow"] == (
            ".github/workflows/catalog-run-controller.yml"
        )
        assert job["with"]["caller_job"] == job_id
        assert "steps" not in job
        assert "secrets" not in job
        assert "concurrency" not in job


def test_terminal_evidence_is_prepared_before_fresh_terminal_audit() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-run-controller.yml")
    jobs = workflow["jobs"]
    evidence = jobs["prepare_terminal_evidence"]
    terminal_audit = jobs["live_controls_audit_before_terminal"]
    decision = jobs["prepare_terminal_decision"]
    finalizer = jobs["finalize"]
    assert "concurrency" not in evidence
    assert evidence["permissions"] == {"actions": "read", "contents": "read"}
    assert terminal_audit["needs"] == "prepare_terminal_evidence"
    assert decision["needs"] == [
        "prepare_terminal_evidence",
        "live_controls_audit_before_terminal",
    ]
    assert "concurrency" not in decision
    assert "download-artifact" not in json.dumps(finalizer)


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


def test_request_reconciler_replays_only_existing_requests() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-request-reconciler.yml")
    assert set(workflow["on"]) == {"schedule"}
    assert workflow["on"]["schedule"] == [{"cron": "*/15 * * * *"}]
    assert workflow["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "read",
    }
    text = (WORKFLOWS / "catalog-request-reconciler.yml").read_text("utf-8")
    for forbidden in (
        "workflow_dispatch",
        "--method POST",
        "create_catalog_run_request",
        "catalog-optimized-run.yml",
        "gh workflow run",
    ):
        assert forbidden not in text
    call = workflow["jobs"]["call_controller"]
    assert "steps" not in call
    assert call["uses"] == "./.github/workflows/catalog-run-controller.yml"
    assert call["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "write",
    }
    assert call["strategy"]["max-parallel"] == 4
    assert set(call["strategy"]["matrix"]) == {"include"}
    assert call["with"] == {"issue_number": "${{ matrix.issue_number }}"}
    assert "concurrency" not in call


def test_ledger_guard_can_record_tamper_but_never_compute_or_repair() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-ledger-guard.yml")
    assert workflow["on"] == {"issue_comment": {"types": ["edited", "deleted"]}}
    assert workflow["permissions"] == {"contents": "read", "issues": "read"}
    assert jobs_with_issues_write(
        {".github/workflows/catalog-ledger-guard.yml": workflow}
    ) == ((".github/workflows/catalog-ledger-guard.yml", "record_tamper_incident"),)
    writer = workflow["jobs"]["record_tamper_incident"]
    assert writer["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "write",
    }
    assert writer["concurrency"] == {
        "group": "catalog-authority-admission-v1",
        "cancel-in-progress": False,
        "queue": "max",
    }
    text = (WORKFLOWS / "catalog-ledger-guard.yml").read_text("utf-8")
    assert "AURORA_CATALOG_LEDGER_TAMPER_V1" in text
    assert "AURORA_CATALOG_REQUEST_COMMENT_TAMPER_V1" in text
    for forbidden in (
        "workflow_dispatch",
        "catalog-optimized",
        "gh workflow run",
        "--method PATCH",
        "--method DELETE",
    ):
        assert forbidden not in text


def test_issues_write_is_job_scoped_to_the_exact_governance_jobs() -> None:
    workflows = _all_workflows()
    assert all(
        not (
            isinstance(workflow.get("permissions"), dict)
            and workflow["permissions"].get("issues") == "write"
        )
        for workflow in workflows.values()
    )
    assert set(jobs_with_issues_write(workflows)) == {
        (".github/workflows/catalog-run-controller.yml", "issue_tamper_guard"),
        (".github/workflows/catalog-run-controller.yml", "reserve"),
        (
            ".github/workflows/catalog-run-controller.yml",
            "report_nonexecuting_decision",
        ),
        (".github/workflows/catalog-run-controller.yml", "record_running"),
        (
            ".github/workflows/catalog-run-controller.yml",
            "record_nonterminal_wait",
        ),
        (".github/workflows/catalog-run-controller.yml", "finalize"),
        (".github/workflows/catalog-request-reconciler.yml", "call_controller"),
        (".github/workflows/catalog-ledger-guard.yml", "record_tamper_incident"),
        (".github/workflows/catalog-run-watchdog.yml", "call_controller"),
    }


def test_request_receipt_is_mirrored_before_its_only_post() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-run-controller.yml")
    steps = workflow["jobs"]["report_nonexecuting_decision"]["steps"]
    upload_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    post_index = next(
        index
        for index, step in enumerate(steps)
        if "--method POST" in str(step.get("run", ""))
    )
    assert upload_index < post_index
    assert "actions/artifacts/$artifact_id/zip" in steps[post_index]["run"]
    assert "cmp --silent" in steps[post_index]["run"]


def test_repository_catalog_topology_is_closed_and_content_hashed() -> None:
    registry = load_catalog_campaign_registry(
        ROOT / "config/catalog_campaign_registry_v1.json"
    )
    receipt = validate_catalog_workflow_topology(repo_root=ROOT, registry=registry)
    assert receipt.status == "ready"
    assert receipt.violations == ()
    assert len(receipt.inventory) == len(tuple(WORKFLOWS.glob("*.y*ml")))
    assert re.fullmatch(r"[0-9a-f]{64}", receipt.receipt_sha256)


def test_recovery_wave_is_closed_bounded_and_reuses_the_worker() -> None:
    path = WORKFLOWS / "catalog-recovery-wave.yml"
    workflow = _workflow(path)
    assert workflow["on"].keys() == {"workflow_call"}
    inputs = workflow["on"]["workflow_call"]["inputs"]
    assert set(inputs) == SEALED_IDENTIFIERS | {
        "campaign_state_artifact",
        "attempt_manifest_artifacts",
        "checkpoint_manifest_artifacts",
        "current_wave",
    }
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "catalog-recovery-${{ inputs.authority_id }}",
        "cancel-in-progress": False,
        "queue": "max",
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
    assert "expected_checkpoint_count" in text


def test_engine_unrolls_exactly_six_selective_recovery_slots() -> None:
    workflow = _workflow(WORKFLOWS / "catalog-optimized-run.yml")
    jobs = workflow["jobs"]
    assert "reconcile_wave_0" in jobs
    for wave in range(1, 7):
        job = jobs[f"recovery_wave_{wave}"]
        assert job["uses"] == "./.github/workflows/catalog-recovery-wave.yml"
        serialized = json.dumps(job, sort_keys=True)
        assert f"current_wave\": {wave}" in serialized
        assert "retry" in serialized and "replan" in serialized
    assert "recovery_wave_7" not in jobs
    final_gate = jobs["ready_to_merge"]
    assert "recovery_wave_6" in final_gate["needs"]
    text = (WORKFLOWS / "catalog-optimized-run.yml").read_text("utf-8")
    assert "rerun all jobs" not in text.casefold()
    assert "catalog-recovery-wave.yml" in text


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


def test_watchdog_can_only_reenter_controller_for_existing_authority() -> None:
    path = WORKFLOWS / "catalog-run-watchdog.yml"
    workflow = _workflow(path)
    assert workflow["on"] == {"schedule": [{"cron": "*/15 * * * *"}]}
    assert workflow["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "read",
    }
    jobs = workflow["jobs"]
    assert set(jobs) == {"discover", "call_controller"}
    call = jobs["call_controller"]
    assert call["uses"] == "./.github/workflows/catalog-run-controller.yml"
    assert "steps" not in call
    assert call["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "write",
    }
    text = path.read_text("utf-8")
    for forbidden in (
        "workflow_dispatch",
        "repository_dispatch",
        "RESERVED",
        "create_catalog_run_request",
        "catalog-recovery-wave.yml",
        "catalog-optimized-run.yml",
        "build_sp500_component_store",
        "run_sp500_optimized_recipe_worker",
    ):
        assert forbidden not in text
    assert "ref: main" in text
    assert "issue_number: ${{ matrix.issue_number }}" in text


def test_catalog_reusable_workflow_graph_stays_below_github_limits() -> None:
    documents = _all_workflows()
    root = ".github/workflows/catalog-run-controller.yml"
    visited: set[str] = set()

    def walk(path: str, depth: int) -> int:
        assert depth <= 10
        if path in visited:
            return depth
        visited.add(path)
        workflow = documents[path]
        maximum = depth
        for job in workflow.get("jobs", {}).values():
            if not isinstance(job, dict):
                continue
            uses = job.get("uses")
            if isinstance(uses, str) and uses.startswith("./.github/workflows/"):
                target = uses.removeprefix("./")
                maximum = max(maximum, walk(target, depth + 1))
        return maximum

    assert walk(root, 1) <= 10
    assert len(visited) <= 50
