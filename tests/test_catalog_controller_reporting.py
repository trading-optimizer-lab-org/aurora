from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest

from aurora.infra.sp500_megarun.catalog_controller_reporting import (
    FINAL_EVIDENCE_FILENAME_BY_SLOT,
    FINAL_EVIDENCE_SLOT_NAMES,
    CatalogFinalEvidenceFactsV1,
    CatalogFinalEvidenceV1,
    CatalogPerformanceTelemetryV1,
    CatalogTerminalState,
    EvidenceSlotV1,
    finalize_catalog_run,
)


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_ID = UUID("018f47a2-6e91-7c34-8000-000000000101")
SHA = {
    name: hashlib.sha256(name.encode("utf-8")).hexdigest()
    for name in (
        "request",
        "campaign",
        "science",
        "execution-plan",
        "artifact-plan",
        "execution-protocol",
        "prompt",
        "source-prompt",
        "prompt-migration",
        "prompt-policy",
        "registry",
    )
}


def _present_slot(name: str) -> EvidenceSlotV1:
    return EvidenceSlotV1(
        status="present",
        sha256=hashlib.sha256(f"slot:{name}".encode()).hexdigest(),
        reason_code=None,
        artifact_or_receipt_id=FINAL_EVIDENCE_FILENAME_BY_SLOT[name],
    )


def _success_slots() -> dict[str, EvidenceSlotV1]:
    slots = {name: _present_slot(name) for name in FINAL_EVIDENCE_SLOT_NAMES}
    slots["terminal_failure_receipt"] = EvidenceSlotV1(
        status="not_reached",
        sha256=None,
        reason_code="NO_TERMINAL_FAILURE",
        artifact_or_receipt_id=None,
    )
    return slots


def _valid_facts() -> CatalogFinalEvidenceFactsV1:
    return CatalogFinalEvidenceFactsV1(
        authority_matches=True,
        campaign_matches=True,
        science_matches=True,
        execution_plan_matches=True,
        artifact_plan_matches=True,
        execution_protocol_matches=True,
        protected_commit_matches=True,
        prompt_chain_matches=True,
        registry_matches=True,
        expected_unit_ids=("recipe-0001", "recipe-0002", "recipe-0003"),
        completed_unit_ids=("recipe-0001", "recipe-0002", "recipe-0003"),
        conflicting_attempt_unit_ids=(),
        expected_component_ids=("component-a", "component-b"),
        available_component_ids=("component-a", "component-b"),
        component_recomputed_in_recipe_ids=(),
        source_lineage_valid=True,
        runtime_receipt_valid=True,
        prepared_data_valid=True,
        checkpoint_chain_valid=True,
        component_store_sealed=True,
        reducer_complete=True,
        schemas_valid=True,
        scientific_audit_passed=True,
        equivalence_passed=True,
        regression_passed=True,
        validation_opened=False,
        locked_opened=False,
        standard_runner_only=True,
        paid_runner_minutes=0,
        estimated_paid_actions_cost_microusd=0,
        zero_actions_spend_budget_verified=True,
        zero_actions_storage_budget_verified=True,
        zero_cache_storage_budget_verified=True,
        ledger_valid=True,
        ledger_writer_provenance_valid=True,
        ledger_mirror_coverage_valid=True,
        authority_lifecycle_complete=True,
        originating_request_intact=True,
        request_lifecycle_complete=True,
        request_receipt_writer_provenance_valid=True,
        request_receipt_mirror_coverage_valid=True,
        tamper_incident_inventory_complete=True,
        github_controls_before_reserve_ready=True,
        github_controls_before_terminal_ready=True,
        terminal_failure_code=None,
        same_failure_fingerprint_count=0,
        work_preserved="Componentes y resultados verificados siguen reutilizables.",
        automatic_action="Detención o cierre seguro según la evidencia verificada.",
    )


def _valid_evidence(
    *,
    telemetry: CatalogPerformanceTelemetryV1 | None = ...,
) -> CatalogFinalEvidenceV1:
    if telemetry is ...:
        telemetry = CatalogPerformanceTelemetryV1(
            strategies_per_minute=14_250.5,
            components_reused=2,
            components_computed_once=0,
            selective_retries=1,
        )
    return CatalogFinalEvidenceV1(
        schema_version="1",
        request_sha256=SHA["request"],
        authority_id=AUTHORITY_ID,
        campaign_id=SHA["campaign"],
        science_sha256=SHA["science"],
        execution_plan_sha256=SHA["execution-plan"],
        artifact_plan_sha256=SHA["artifact-plan"],
        execution_protocol_sha256=SHA["execution-protocol"],
        protected_commit_sha="a" * 40,
        prompt_sha256=SHA["prompt"],
        source_prompt_sha256=SHA["source-prompt"],
        prompt_migration_sha256=SHA["prompt-migration"],
        prompt_policy_sha256=SHA["prompt-policy"],
        registry_sha256=SHA["registry"],
        evidence_slots=_success_slots(),
        facts=_valid_facts(),
        telemetry=telemetry,
    )


def valid_final_evidence(
    *, telemetry: CatalogPerformanceTelemetryV1 | None = ...
) -> dict[str, object]:
    return {"final_evidence": _valid_evidence(telemetry=telemetry)}


def mutated_final_evidence(mutation: str) -> dict[str, object]:
    evidence = _valid_evidence()
    payload = evidence.model_dump(mode="python")
    facts = payload["facts"]
    slots = payload["evidence_slots"]
    if mutation == "wrong_authority":
        facts["authority_matches"] = False
    elif mutation == "wrong_campaign":
        facts["campaign_matches"] = False
    elif mutation == "wrong_science":
        facts["science_matches"] = False
    elif mutation == "wrong_plan":
        facts["execution_plan_matches"] = False
    elif mutation == "missing_unit":
        facts["completed_unit_ids"] = ("recipe-0001", "recipe-0003")
    elif mutation == "duplicate_unit":
        facts["completed_unit_ids"] = (
            "recipe-0001",
            "recipe-0002",
            "recipe-0002",
            "recipe-0003",
        )
    elif mutation == "conflicting_attempts":
        facts["conflicting_attempt_unit_ids"] = ("recipe-0002",)
    elif mutation == "component_missing":
        facts["available_component_ids"] = ("component-a",)
    elif mutation == "component_recomputed_in_recipe":
        facts["component_recomputed_in_recipe_ids"] = ("component-b",)
    elif mutation == "source_lineage_invalid":
        facts["source_lineage_valid"] = False
    elif mutation == "runtime_receipt_invalid":
        facts["runtime_receipt_valid"] = False
    elif mutation == "prepared_data_invalid":
        facts["prepared_data_valid"] = False
    elif mutation == "checkpoint_chain_gap":
        facts["checkpoint_chain_valid"] = False
    elif mutation == "component_store_unsealed":
        facts["component_store_sealed"] = False
    elif mutation == "reducer_incomplete":
        facts["reducer_complete"] = False
    elif mutation == "schema_invalid":
        facts["schemas_valid"] = False
    elif mutation == "audit_failed":
        facts["scientific_audit_passed"] = False
    elif mutation == "equivalence_failed":
        facts["equivalence_passed"] = False
    elif mutation == "regression_failed":
        facts["regression_passed"] = False
    elif mutation == "validation_open":
        facts["validation_opened"] = True
    elif mutation == "locked_open":
        facts["locked_opened"] = True
    elif mutation == "paid_runner":
        facts["paid_runner_minutes"] = 1
    elif mutation == "paid_actions_storage":
        facts["estimated_paid_actions_cost_microusd"] = 1
    elif mutation == "zero_spend_budget_drift":
        facts["zero_actions_storage_budget_verified"] = False
    elif mutation == "ledger_invalid":
        facts["ledger_valid"] = False
    elif mutation == "ledger_writer_provenance_invalid":
        facts["ledger_writer_provenance_valid"] = False
    elif mutation == "ledger_mirror_coverage_invalid":
        facts["ledger_mirror_coverage_valid"] = False
    elif mutation == "authority_lifecycle_incomplete":
        facts["authority_lifecycle_complete"] = False
    elif mutation == "request_lifecycle_incomplete":
        facts["request_lifecycle_complete"] = False
    elif mutation == "request_receipt_writer_provenance_invalid":
        facts["request_receipt_writer_provenance_valid"] = False
    elif mutation == "tamper_incident_inventory_incomplete":
        facts["tamper_incident_inventory_complete"] = False
    elif mutation == "controls_drift":
        facts["github_controls_before_terminal_ready"] = False
    else:
        raise AssertionError(mutation)
    payload["facts"] = facts
    payload["evidence_slots"] = slots
    return {"final_evidence": CatalogFinalEvidenceV1.model_validate(payload)}


def test_complete_bound_evidence_is_success() -> None:
    result = finalize_catalog_run(**valid_final_evidence())
    assert result.state is CatalogTerminalState.SUCCESS
    assert result.reason_code == "CATALOG_SUCCESS"
    assert result.completed_unit_count == result.expected_unit_count
    assert result.missing_unit_ids == ()
    assert result.duplicate_unit_ids == ()


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("wrong_authority", "FINAL_AUTHORITY_MISMATCH"),
        ("wrong_campaign", "FINAL_CAMPAIGN_MISMATCH"),
        ("wrong_science", "FINAL_SCIENCE_MISMATCH"),
        ("wrong_plan", "FINAL_EXECUTION_PLAN_MISMATCH"),
        ("missing_unit", "FINAL_LOGICAL_UNIT_MISSING"),
        ("duplicate_unit", "FINAL_LOGICAL_UNIT_DUPLICATE"),
        ("conflicting_attempts", "FINAL_ATTEMPT_CONFLICT"),
        ("component_missing", "FINAL_COMPONENT_MISSING"),
        ("component_recomputed_in_recipe", "FINAL_COMPONENT_RECOMPUTED"),
        ("source_lineage_invalid", "FINAL_SOURCE_LINEAGE_INVALID"),
        ("runtime_receipt_invalid", "FINAL_RUNTIME_INVALID"),
        ("prepared_data_invalid", "FINAL_PREPARED_DATA_INVALID"),
        ("checkpoint_chain_gap", "FINAL_CHECKPOINT_CHAIN_INVALID"),
        ("component_store_unsealed", "FINAL_COMPONENT_STORE_UNSEALED"),
        ("reducer_incomplete", "FINAL_REDUCTION_INCOMPLETE"),
        ("schema_invalid", "FINAL_SCHEMA_INVALID"),
        ("audit_failed", "FINAL_SCIENTIFIC_AUDIT_FAILED"),
        ("equivalence_failed", "FINAL_EQUIVALENCE_FAILED"),
        ("regression_failed", "FINAL_REGRESSION_FAILED"),
        ("validation_open", "FINAL_VALIDATION_OPENED"),
        ("locked_open", "FINAL_LOCKED_OPENED"),
        ("paid_runner", "FINAL_PAID_RUNNER_USED"),
        ("paid_actions_storage", "FINAL_PAID_ACTIONS_USAGE_FORBIDDEN"),
        ("zero_spend_budget_drift", "FINAL_ZERO_SPEND_BUDGET_DRIFT"),
        ("ledger_invalid", "FINAL_LEDGER_INVALID"),
        ("ledger_writer_provenance_invalid", "FINAL_LEDGER_WRITER_INVALID"),
        ("ledger_mirror_coverage_invalid", "FINAL_LEDGER_MIRROR_COVERAGE_INVALID"),
        ("authority_lifecycle_incomplete", "FINAL_AUTHORITY_LIFECYCLE_INVALID"),
        ("request_lifecycle_incomplete", "FINAL_REQUEST_LIFECYCLE_INVALID"),
        (
            "request_receipt_writer_provenance_invalid",
            "FINAL_REQUEST_RECEIPT_WRITER_INVALID",
        ),
        ("tamper_incident_inventory_incomplete", "FINAL_TAMPER_HISTORY_INVALID"),
        ("controls_drift", "FINAL_GITHUB_CONTROLS_DRIFT"),
    ],
)
def test_no_incomplete_or_unbound_result_can_be_success(
    mutation: str, reason: str
) -> None:
    result = finalize_catalog_run(**mutated_final_evidence(mutation))
    assert result.state is not CatalogTerminalState.SUCCESS
    assert result.reason_code == reason


def test_report_never_invents_throughput() -> None:
    result = finalize_catalog_run(**valid_final_evidence(telemetry=None))
    assert "no medido" in result.human_summary.lower()
    assert "15.000" not in result.human_summary


def final_evidence_after_pre_audit_failure() -> dict[str, object]:
    payload = _valid_evidence(telemetry=None).model_dump(mode="python")
    for name in (
        "actions_billing_and_zero_spend_budgets_receipt",
        "validation_opened",
        "locked_opened",
    ):
        payload["evidence_slots"][name] = {
            "status": "missing",
            "sha256": None,
            "reason_code": "PRE_AUDIT_FAILED",
            "artifact_or_receipt_id": None,
        }
    return {"final_evidence": CatalogFinalEvidenceV1.model_validate(payload)}


def test_report_never_invents_zero_cost_or_closed_data_boundaries() -> None:
    result = finalize_catalog_run(**final_evidence_after_pre_audit_failure())
    assert "no verificable" in result.human_summary.lower()
    assert "0 verificado" not in result.human_summary.lower()


def final_evidence_after_runtime_preparation_failure() -> dict[str, object]:
    payload = _valid_evidence(telemetry=None).model_dump(mode="python")
    phase_reached = False
    for name in FINAL_EVIDENCE_SLOT_NAMES:
        if name == "runtime":
            phase_reached = True
            payload["evidence_slots"][name] = {
                "status": "missing",
                "sha256": None,
                "reason_code": "RUNTIME_PREPARATION_FAILED",
                "artifact_or_receipt_id": None,
            }
        elif phase_reached and name != "terminal_failure_receipt":
            payload["evidence_slots"][name] = {
                "status": "not_reached",
                "sha256": None,
                "reason_code": "NOT_REACHED_AFTER_RUNTIME_FAILURE",
                "artifact_or_receipt_id": None,
            }
    payload["facts"]["runtime_receipt_valid"] = False
    payload["facts"]["prepared_data_valid"] = False
    return {"final_evidence": CatalogFinalEvidenceV1.model_validate(payload)}


def test_admitted_early_failure_can_emit_truthful_blocked_with_absent_slots() -> None:
    result = finalize_catalog_run(**final_evidence_after_runtime_preparation_failure())
    assert result.state is CatalogTerminalState.BLOCKED
    assert result.evidence_slots["runtime"].status == "missing"
    assert result.evidence_slots["recipe_results"].status == "not_reached"
    assert result.missing_evidence_reason_codes == (
        "RUNTIME_PREPARATION_FAILED",
    )


def test_invalid_ledger_blocks_without_appending_to_damaged_chain() -> None:
    result = finalize_catalog_run(**mutated_final_evidence("ledger_invalid"))
    assert result.state is CatalogTerminalState.BLOCKED
    assert result.authority_append_allowed is False
    assert result.authority_terminal_record_created is False
    assert result.standalone_incident_artifact_required is True


def test_fully_evidenced_closed_engine_failure_is_failed() -> None:
    payload = _valid_evidence(telemetry=None).model_dump(mode="python")
    payload["facts"]["terminal_failure_code"] = (
        "SCIENTIFIC_ENGINE_DETERMINISTIC_FAILURE"
    )
    payload["evidence_slots"]["terminal_failure_receipt"] = _present_slot(
        "terminal_failure_receipt"
    ).model_dump(mode="python")
    result = finalize_catalog_run(
        final_evidence=CatalogFinalEvidenceV1.model_validate(payload)
    )
    assert result.state is CatalogTerminalState.FAILED
    assert result.reason_code == "SCIENTIFIC_ENGINE_DETERMINISTIC_FAILURE"


def test_unknown_engine_failure_is_blocked_not_failed() -> None:
    payload = _valid_evidence(telemetry=None).model_dump(mode="python")
    payload["facts"]["terminal_failure_code"] = "MYSTERY_FAILURE"
    payload["evidence_slots"]["terminal_failure_receipt"] = _present_slot(
        "terminal_failure_receipt"
    ).model_dump(mode="python")
    result = finalize_catalog_run(
        final_evidence=CatalogFinalEvidenceV1.model_validate(payload)
    )
    assert result.state is CatalogTerminalState.BLOCKED
    assert result.reason_code == "FINAL_UNKNOWN_FAILURE_CODE"


def test_slot_contract_is_closed_and_cannot_omit_a_slot() -> None:
    payload = _valid_evidence().model_dump(mode="python")
    del payload["evidence_slots"]["prepared_data"]
    with pytest.raises(ValueError, match="FINAL_EVIDENCE_SLOT_SET_INVALID"):
        CatalogFinalEvidenceV1.model_validate(payload)


def test_present_and_absent_slot_shapes_are_strict() -> None:
    with pytest.raises(ValueError):
        EvidenceSlotV1(
            status="present",
            sha256=None,
            reason_code=None,
            artifact_or_receipt_id="runtime_v1.json",
        )
    with pytest.raises(ValueError):
        EvidenceSlotV1(
            status="missing",
            sha256="0" * 64,
            reason_code="RUNTIME_PREPARATION_FAILED",
            artifact_or_receipt_id=None,
        )
    with pytest.raises(ValueError):
        EvidenceSlotV1(
            status="missing",
            sha256=None,
            reason_code="UNBOUNDED_FREE_TEXT",
            artifact_or_receipt_id=None,
        )


def test_rendered_comments_never_contain_untrusted_payloads() -> None:
    result = finalize_catalog_run(**mutated_final_evidence("controls_drift"))
    lowered = result.human_summary.casefold()
    for forbidden in (
        "ghp_",
        "github_pat_",
        "bearer ",
        "traceback",
        "c:\\",
        "/home/runner",
        "issue_body",
        "raw github event",
    ):
        assert forbidden not in lowered


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_cli_inputs(base: Path, mutation: str) -> tuple[list[str], Path]:
    external_names = (
        "authority_issue",
        "authority_comments",
        "authority_mirrors",
        "authority_timeline",
        "authority_anchor",
        "request_issue",
        "request_timeline",
        "request_receipts",
        "tamper_incidents",
        "github_controls_before_reserve",
        "github_controls_before_terminal",
    )
    input_hashes: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for name in external_names:
        path = base / f"{name}.json"
        content = _canonical_bytes({"schema_version": "1", "kind": name})
        path.write_bytes(content)
        paths[name] = path
        input_hashes[name] = hashlib.sha256(content).hexdigest()

    final_dir = base / "final-evidence"
    final_dir.mkdir()
    evidence = mutated_final_evidence(mutation)["final_evidence"]
    assert isinstance(evidence, CatalogFinalEvidenceV1)
    payload = evidence.model_dump(mode="python")
    for name, slot in payload["evidence_slots"].items():
        if slot["status"] != "present":
            continue
        filename = FINAL_EVIDENCE_FILENAME_BY_SLOT[name]
        content = _canonical_bytes({"schema_version": "1", "slot": name})
        (final_dir / filename).write_bytes(content)
        slot["sha256"] = hashlib.sha256(content).hexdigest()
        slot["artifact_or_receipt_id"] = filename
    evidence = CatalogFinalEvidenceV1.model_validate(payload)
    decision = base / "decision.json"
    decision.write_bytes(
        _canonical_bytes(
            {
                "schema_version": "1",
                "final_evidence": evidence.model_dump(mode="json"),
                "input_sha256s": input_hashes,
            }
        )
    )
    output = base / "output"
    arguments = [
        "--decision",
        str(decision),
        "--authority-issue",
        str(paths["authority_issue"]),
        "--authority-comments",
        str(paths["authority_comments"]),
        "--authority-mirrors",
        str(paths["authority_mirrors"]),
        "--authority-timeline",
        str(paths["authority_timeline"]),
        "--authority-anchor",
        str(paths["authority_anchor"]),
        "--request-issue",
        str(paths["request_issue"]),
        "--request-timeline",
        str(paths["request_timeline"]),
        "--request-receipts",
        str(paths["request_receipts"]),
        "--tamper-incidents",
        str(paths["tamper_incidents"]),
        "--final-evidence-directory",
        str(final_dir),
        "--github-controls-before-reserve",
        str(paths["github_controls_before_reserve"]),
        "--github-controls-before-terminal",
        str(paths["github_controls_before_terminal"]),
        "--output-dir",
        str(output),
    ]
    return arguments, output


def run_finalizer_cli(tmp_path: Path, mutation: str) -> Path:
    arguments, output = _write_cli_inputs(tmp_path, mutation)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/finalize_catalog_controller_run.py"),
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return output


def test_cli_emits_only_outputs_permitted_by_the_decision(tmp_path: Path) -> None:
    output = run_finalizer_cli(tmp_path, mutation="ledger_invalid")
    assert (output / "catalog_terminal_decision.json").is_file()
    assert (output / "catalog_run_summary.md").is_file()
    assert (output / "catalog_final_evidence_manifest.json").is_file()
    assert not (output / "catalog_terminal_authority_comment.md").exists()
    assert (output / "catalog_standalone_incident.json").is_file()


def test_cli_refuses_existing_output_directory(tmp_path: Path) -> None:
    arguments, output = _write_cli_inputs(tmp_path, "ledger_invalid")
    output.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/finalize_catalog_controller_run.py"),
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "CATALOG_FINAL_OUTPUT_EXISTS" in result.stderr


def test_cli_rejects_unexpected_evidence_file(tmp_path: Path) -> None:
    arguments, output = _write_cli_inputs(tmp_path, "ledger_invalid")
    final_dir = Path(arguments[arguments.index("--final-evidence-directory") + 1])
    (final_dir / "surprise.json").write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/finalize_catalog_controller_run.py"),
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "CATALOG_FINAL_EVIDENCE_FILE_UNEXPECTED" in result.stderr
    assert not output.exists()
