from __future__ import annotations

import json
from pathlib import Path
import re

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_github_controls import (
    AUDITOR_CALLER_TOPOLOGY,
    AUDITOR_SECRET_CONSUMER,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
POLICY = WORKFLOWS / "catalog-controller-policy-check.yml"
LIVE_AUDIT = WORKFLOWS / "catalog-live-controls-audit.yml"
LIVE_QUALIFICATION = WORKFLOWS / "catalog-live-controls-qualification.yml"
FULL_ACTION_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _workflow(path: Path) -> dict[str, object]:
    return dict(load_github_yaml(path))


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
        "tests/test_github_performance_preflight.py",
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
    assert set(call["outputs"]) == {"receipt_sha256", "receipt_status"}
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
