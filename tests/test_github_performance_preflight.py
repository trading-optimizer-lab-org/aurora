from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import RunSpec
from aurora.infra.github_performance.preflight import (
    DuplicateYamlKey,
    PreflightError,
    freeze_resolved_contract,
    load_github_yaml,
    resolve_run_spec,
    validate_future_workflow,
    validate_run_spec,
    write_preflight_report,
)
from github_performance_helpers import (
    complete_runtime_evidence,
    manual_heavy_workflow,
    minimal_valid_spec,
    push_triggered_heavy_workflow,
    workflow_with_step,
    write_yaml,
)


def test_rejects_local_execution(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["execution"]["local_runs_allowed"] = True
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "LOCAL_EXECUTION_ALLOWED" in report.violation_codes


def test_rejects_larger_runner(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["performance"]["larger_runners_allowed"] = True
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "LARGER_RUNNER_FORBIDDEN" in report.violation_codes


def test_rejects_planner_ceiling_above_360(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["performance"]["planner_max_jobs"] = 361
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "CONCURRENCY_CEILING_EXCEEDED" in report.violation_codes


def test_rejects_empty_user_owned_fields(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["identity"]["campaign_id"] = ""
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "REQUIRED_VALUE_EMPTY" in report.violation_codes


def test_rejects_zero_length_or_overlapping_periods(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["policy"]["train_end"] = spec["policy"]["train_start"]
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "PERIOD_ORDER_INVALID" in report.violation_codes


def test_rejects_data_after_validation(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["data"]["max_date"] = "2021-01-01"
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "DATA_AFTER_VALIDATION" in report.violation_codes


def test_runtime_evidence_freezes_blank_derived_hashes() -> None:
    requested = RunSpec.model_validate(minimal_valid_spec())
    resolved = resolve_run_spec(requested, complete_runtime_evidence())
    assert resolved.identity["code_sha"] == "a" * 40
    assert resolved.policy["policy_hash"] == "b" * 64
    assert resolved.data["snapshot_hash"] == "c" * 64
    assert resolved.execution["environment_sha256"] == "3" * 64
    assert resolved.performance["capacity_profile_sha256"] == "f" * 64


def test_supplied_runtime_hash_must_match_observed_evidence() -> None:
    payload = minimal_valid_spec()
    payload["identity"]["code_sha"] = "0" * 40
    requested = RunSpec.model_validate(payload)
    with pytest.raises(PreflightError, match="CODE_SHA_MISMATCH"):
        resolve_run_spec(requested, complete_runtime_evidence())


def test_freeze_writes_resolved_spec_and_performance_contract(
    tmp_path: Path,
) -> None:
    requested = RunSpec.model_validate(minimal_valid_spec())
    paths = freeze_resolved_contract(
        requested,
        complete_runtime_evidence(),
        tmp_path,
    )
    assert {path.name for path in paths} == {
        "resolved_run_spec.json",
        "performance_contract.json",
    }
    contract = json.loads((tmp_path / "performance_contract.json").read_text())
    assert contract["locked_opened"] is False
    assert contract["standard_runner_only"] is True
    assert contract["capacity_profile_sha256"] == "f" * 64


def test_preflight_report_is_machine_readable(tmp_path: Path) -> None:
    path = write_yaml(tmp_path / "spec.yaml", minimal_valid_spec())
    report = validate_run_spec(path)
    output = write_preflight_report(report, tmp_path / "output")
    payload = json.loads(output.read_text())
    assert payload["valid"] is False
    assert isinstance(payload["violations"], list)


def test_rejects_missing_local_reusable_workflow(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        manual_heavy_workflow("./.github/workflows/missing.yml"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "LOCAL_REFERENCE_MISSING" in {item.code for item in violations}


def test_rejects_unpinned_external_action(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        workflow_with_step("actions/checkout@v6"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "ACTION_NOT_PINNED" in {item.code for item in violations}


def test_rejects_unapproved_sha_for_official_action(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        workflow_with_step(f"actions/checkout@{'0' * 40}"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "ACTION_SHA_NOT_APPROVED" in {item.code for item in violations}


def test_rejects_local_reference_outside_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-action"
    outside.write_text("name: outside\n", encoding="utf-8")
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        manual_heavy_workflow("./../outside-action"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "LOCAL_REFERENCE_OUTSIDE_REPO" in {
        item.code for item in violations
    }


def test_rejects_heavy_push_trigger(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        push_triggered_heavy_workflow(),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "HEAVY_AUTOMATIC_TRIGGER" in {item.code for item in violations}


def test_accepts_manual_framework_caller(tmp_path: Path) -> None:
    reusable = tmp_path / ".github/workflows/_aurora-future-run-v3.yml"
    reusable.parent.mkdir(parents=True)
    reusable.write_text("name: reusable\n", encoding="utf-8")
    caller = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        manual_heavy_workflow(
            "./.github/workflows/_aurora-future-run-v3.yml"
        ),
    )
    assert validate_future_workflow(caller, tmp_path) == []


def test_github_loader_preserves_on_as_a_string(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")
    assert "on" in load_github_yaml(path)


def test_github_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("name: first\nname: second\n", encoding="utf-8")
    with pytest.raises(DuplicateYamlKey, match="name"):
        load_github_yaml(path)
