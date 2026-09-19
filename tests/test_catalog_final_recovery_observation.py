from __future__ import annotations

import json
from pathlib import Path
import re
import textwrap

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun import catalog_engine_outcome
from scripts import prepare_catalog_engine_outcome


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/catalog-optimized-run.yml"
AUTHORITY_ID = "018f47a2-6e91-7c34-8000-000000000101"


def _workflow_outcome_builder() -> str:
    workflow = load_github_yaml(WORKFLOW)
    step = next(
        step
        for step in workflow["jobs"]["campaign_outcome"]["steps"]
        if step.get("name") == "Build one closed engine-outcome input"
    )
    matches = re.findall(
        r"python - <<'PY'\n(.*?)\n\s*PY",
        step["run"],
        flags=re.DOTALL,
    )
    assert len(matches) == 1
    source = textwrap.dedent(matches[0])
    values = {
        "request_sha256": "1" * 64,
        "authority_id": AUTHORITY_ID,
        "campaign_id": "2" * 64,
        "science_sha256": "3" * 64,
        "execution_plan_sha256": "4" * 64,
        "execution_protocol_sha256": "5" * 64,
        "protected_commit_sha": "6" * 40,
    }
    for key, value in values.items():
        source = source.replace(f"${{{{ inputs.{key} }}}}", value)
    return source.replace("${{ github.sha }}", values["protected_commit_sha"])


def _set_stage_environment(
    monkeypatch: pytest.MonkeyPatch,
    stages: dict[str, str],
) -> None:
    result_names = {
        "engine_verify_sealed_plan": "RESULT_ENGINE_VERIFY",
        "prepare_runtime_and_inputs": "RESULT_PREPARE",
        "build_components_a": "RESULT_BUILD_A",
        "build_components_b": "RESULT_BUILD_B",
        "materialize_cached_components_a": "RESULT_CACHED_A",
        "materialize_cached_components_b": "RESULT_CACHED_B",
        "verify_component_store": "RESULT_COMPONENT_SEAL",
        "evaluate_a": "RESULT_EVALUATE_A",
        "evaluate_b": "RESULT_EVALUATE_B",
        "evaluate_c": "RESULT_EVALUATE_C",
        "ready_to_merge": "RESULT_READY",
        "reduce_groups": "RESULT_REDUCE_GROUPS",
        "reduce": "RESULT_REDUCE",
        "verify_terminal_science": "RESULT_SCIENCE",
        "audit_runtime": "RESULT_AUDIT",
    }
    for stage, variable in result_names.items():
        monkeypatch.setenv(variable, stages[stage])


def _run_workflow_consumer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    recovery_statuses: tuple[str, ...],
    stages: dict[str, str],
    failure_count: int = 0,
    failure_reason: str = "",
    failure_fingerprint: str = "",
) -> tuple[dict[str, object], dict[str, object]]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    _set_stage_environment(monkeypatch, stages)
    for wave in range(4):
        status = recovery_statuses[wave] if wave < len(recovery_statuses) else ""
        monkeypatch.setenv(f"RECOVERY_{wave}", status)
    for wave in range(1, 4):
        monkeypatch.setenv(f"FAILURE_FP_{wave}", failure_fingerprint)
        monkeypatch.setenv(f"FAILURE_COUNT_{wave}", str(failure_count))
        monkeypatch.setenv(f"FAILURE_REASON_{wave}", failure_reason)
        monkeypatch.setenv(f"RETRY_NOT_BEFORE_{wave}", "")
    monkeypatch.setenv("FINAL_EVIDENCE_ARTIFACT", "catalog-final-root-018f47a2")

    exec(compile(_workflow_outcome_builder(), str(WORKFLOW), "exec"), {})
    input_path = tmp_path / "engine-outcome-input.json"
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    module_path = Path(catalog_engine_outcome.__file__).resolve()
    assert module_path.is_relative_to(ROOT)
    output_path = tmp_path / "catalog-engine-outcome-v1.json"
    github_output = tmp_path / "github-output.txt"
    result = prepare_catalog_engine_outcome.main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--github-output",
            str(github_output),
        ]
    )
    assert result == 0
    return payload, json.loads(output_path.read_text(encoding="utf-8"))


def test_wave_three_is_observed_by_the_real_engine_outcome_consumer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    jobs = load_github_yaml(WORKFLOW)["jobs"]
    wave_3 = jobs["recovery_wave_3"]
    assert wave_3["uses"] == "./.github/workflows/catalog-recovery-wave.yml"
    assert wave_3["with"]["current_wave"] == 3
    assert "needs.recovery_wave_2.outputs.status == 'retry'" in wave_3["if"]
    assert "needs.recovery_wave_2.outputs.status == 'replan'" in wave_3["if"]
    assert "recovery_wave_4" not in jobs
    ready_to_merge = jobs["ready_to_merge"]
    assert "recovery_wave_3" in ready_to_merge["needs"]
    assert "needs.recovery_wave_3.outputs.status == 'complete'" in ready_to_merge["if"]
    audit_runtime = jobs["audit_runtime"]
    assert "recovery_wave_3" in audit_runtime["needs"]
    audit_step = next(
        step
        for step in audit_runtime["steps"]
        if step.get("name") == "Collect complete current-run metadata"
    )
    assert "VERIFIED_WAVE_3_STATUS" in audit_step["env"]
    assert "for wave in (1, 2, 3)" in audit_step["run"]
    campaign_outcome = jobs["campaign_outcome"]
    assert "recovery_wave_3" in campaign_outcome["needs"]
    outcome_step = next(
        step
        for step in campaign_outcome["steps"]
        if step.get("name") == "Build one closed engine-outcome input"
    )
    for field in (
        "RECOVERY_3",
        "FAILURE_FP_3",
        "FAILURE_COUNT_3",
        "FAILURE_REASON_3",
        "RETRY_NOT_BEFORE_3",
    ):
        assert field in outcome_step["env"]

    stages = {
        "engine_verify_sealed_plan": "success",
        "prepare_runtime_and_inputs": "success",
        "build_components_a": "success",
        "build_components_b": "success",
        "materialize_cached_components_a": "skipped",
        "materialize_cached_components_b": "skipped",
        "verify_component_store": "success",
        "evaluate_a": "success",
        "evaluate_b": "success",
        "evaluate_c": "success",
        "ready_to_merge": "success",
        "reduce_groups": "success",
        "reduce": "success",
        "verify_terminal_science": "success",
        "audit_runtime": "success",
    }
    payload, outcome = _run_workflow_consumer(
        monkeypatch,
        tmp_path,
        recovery_statuses=("retry", "retry", "retry", "complete"),
        stages=stages,
    )

    assert payload["recovery_statuses"] == ["retry", "retry", "retry", "complete"]
    recovery_artifact = payload["recovery_evidence_artifact"]
    assert isinstance(recovery_artifact, str)
    assert recovery_artifact.endswith("-3-4242-1")
    assert outcome["state"] == "TERMINAL_CANDIDATE"


def test_wave_three_limit_is_consumed_as_blocked_with_its_failure_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stages = {
        "engine_verify_sealed_plan": "success",
        "prepare_runtime_and_inputs": "success",
        "build_components_a": "success",
        "build_components_b": "success",
        "materialize_cached_components_a": "skipped",
        "materialize_cached_components_b": "skipped",
        "verify_component_store": "success",
        "evaluate_a": "success",
        "evaluate_b": "success",
        "evaluate_c": "success",
        "ready_to_merge": "skipped",
        "reduce_groups": "skipped",
        "reduce": "skipped",
        "verify_terminal_science": "skipped",
        "audit_runtime": "skipped",
    }
    failure_fingerprint = "d" * 64
    payload, outcome = _run_workflow_consumer(
        monkeypatch,
        tmp_path,
        recovery_statuses=("retry", "retry", "retry", "blocked"),
        stages=stages,
        failure_count=2,
        failure_reason="RECOVERY_WAVE_BUDGET_EXHAUSTED",
        failure_fingerprint=failure_fingerprint,
    )

    recovery_statuses = payload["recovery_statuses"]
    assert isinstance(recovery_statuses, list)
    assert recovery_statuses[-1] == "blocked"
    assert payload["failure_fingerprint"] == failure_fingerprint
    assert payload["failure_occurrence_count"] == 2
    assert payload["failure_reason_code"] == "RECOVERY_WAVE_BUDGET_EXHAUSTED"
    assert outcome["state"] == "BLOCKED"
    assert outcome["reason_code"] == "RECOVERY_WAVE_BUDGET_EXHAUSTED"
    assert outcome["failure_fingerprint"] == failure_fingerprint
    assert outcome["failure_occurrence_count"] == 2
