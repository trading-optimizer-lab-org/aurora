from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    VerifiedAuthorityLedgerV1,
    append_authority_record,
)
from aurora.infra.sp500_megarun.catalog_controller import (
    CatalogRequestQueueEvidenceV1,
    CatalogSealedInputsV1,
    ControllerOutcome,
    _decision,
)
from aurora.infra.sp500_megarun.catalog_controller_reporting import (
    CatalogTerminalState,
    finalize_catalog_run,
)
from aurora.infra.sp500_megarun.catalog_engine_outcome import (
    select_catalog_engine_outcome,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_routing import (
    CatalogRoutingCommandV1,
    CatalogRoutingPrerequisitesV1,
)
from aurora.infra.sp500_megarun.catalog_runtime_audit import (
    build_catalog_runtime_audit,
)
from aurora.infra.sp500_megarun.catalog_terminal_adapter import (
    bind_terminal_controls,
    prepare_terminal_evidence,
)
from scripts.plan_sp500_optimized_catalog_run import (
    write_sealed_global_reuse_execution_plan,
)
from test_catalog_admission_adapter import _auditor_receipt
from test_sp500_catalog_optimization_contract import (
    _task10_contract_payload,
    _task10_plan_fixture,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
REQUEST = "a" * 64
PROTOCOL = "b" * 64
COMMIT = "c" * 40
DECISION_HASH = "d" * 64
ADMISSION_TOKEN = "e" * 64
ARTIFACT_PLAN = "f" * 64


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        path.write_bytes(canonical_model_bytes(value) + b"\n")
    else:
        path.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


def _hashed(identity: dict[str, object], field: str) -> dict[str, object]:
    return {**identity, field: canonical_sha256(identity)}


def _sealed_plan(root: Path):
    plan = _task10_plan_fixture(warm_component_ordinals=set())
    contract = RunOptimizationContractV1.model_validate(_task10_contract_payload())
    source_identity = {
        "schema_version": "1",
        "document_type": "catalog_source_artifacts_v1",
        "payload": {
            "artifacts": [
                {
                    "contract_name": "reference_oracle_v1",
                    "run_id": 10,
                    "artifact_id": 11,
                    "artifact_name": "reference",
                    "artifact_digest": "sha256:" + "1" * 64,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            ],
            "evidence": {"artifact_plan_sha256": ARTIFACT_PLAN},
        },
    }
    source = _hashed(source_identity, "content_sha256")
    controller_binding = {
        "request_sha256": REQUEST,
        "authority_id": str(plan.authority_id),
        "campaign_id": plan.campaign_id,
        "science_sha256": plan.science_sha256,
        "execution_plan_sha256": plan.execution_plan_sha256,
        "execution_protocol_sha256": PROTOCOL,
        "protected_commit_sha": COMMIT,
        "prompt_sha256": "2" * 64,
        "source_prompt_sha256": "3" * 64,
        "prompt_migration_sha256": "4" * 64,
        "prompt_policy_sha256": "5" * 64,
        "campaign_registry_sha256": "6" * 64,
    }
    write_sealed_global_reuse_execution_plan(
        output_dir=root,
        contract=contract,
        plan=plan,
        request_sha256=REQUEST,
        execution_protocol_sha256=PROTOCOL,
        protected_commit_sha=COMMIT,
        decision_sha256=DECISION_HASH,
        admission_token_sha256=ADMISSION_TOKEN,
        controller_binding=controller_binding,
        run_plan={"schema_version": "1", "admission_token_sha256": ADMISSION_TOKEN},
        resume_work_manifest={
            "schema_version": "1",
            "pending_strategy_ids": [row.strategy_id for row in plan.recipe_requirements],
        },
        recipe_dag_bytes=b"PAR1terminal-adapter",
        recipe_dag_manifest={
            "schema_version": "1",
            "recipe_count": len(plan.recipe_requirements),
            "validation_opened": False,
            "locked_opened": False,
        },
        source_artifacts=source,
    )
    return plan, controller_binding


def _decision_and_controls(plan, *, controls_commit_sha: str = COMMIT):
    controls = _auditor_receipt(
        audit_use_context="controller_admission",
        audit_context_sha256="7" * 64,
        protected_commit_sha=controls_commit_sha,
        observed_default_branch_sha=controls_commit_sha,
        caller_job="live_controls_audit_before_reserve",
    )
    sealed = CatalogSealedInputsV1(
        engine_id="optimized_catalog_v1",
        request_sha256=REQUEST,
        campaign_id=plan.campaign_id,
        science_sha256=plan.science_sha256,
        execution_plan_sha256=plan.execution_plan_sha256,
        execution_protocol_sha256=PROTOCOL,
        protected_commit_sha=COMMIT,
        github_controls_commit_sha=controls_commit_sha,
        prompt_sha256="2" * 64,
        prompt_policy_sha256="5" * 64,
        campaign_registry_sha256="6" * 64,
        campaign_definition_manifest_sha256="8" * 64,
        campaign_definition_sha256="9" * 64,
        campaign_definition_rehash_receipt_sha256="0" * 64,
        authority_id=plan.authority_id,
        authority_anchor_evidence_sha256="1" * 64,
        github_controls_receipt_sha256=controls.receipt_sha256,
        capacity_receipt_sha256="2" * 64,
        source_artifact_manifest_sha256="3" * 64,
        artifact_plan_sha256=ARTIFACT_PLAN,
    )
    decision = _decision(
        outcome=ControllerOutcome.ADMITTED,
        reason_code="CATALOG_ADMITTED",
        request_sha256=REQUEST,
        campaign_id=plan.campaign_id,
        science_sha256=plan.science_sha256,
        execution_plan_sha256=plan.execution_plan_sha256,
        execution_protocol_sha256=PROTOCOL,
        authority_id=plan.authority_id,
        should_create_authority=True,
        should_schedule_compute=True,
        sealed_inputs=sealed,
    )
    return decision, controls


def _routing(root: Path, plan, decision) -> None:
    reserved = append_authority_record(
        previous=None,
        authority_id=plan.authority_id,
        request_issue_number=101,
        campaign_id=plan.campaign_id,
        request_sha256=REQUEST,
        science_sha256=plan.science_sha256,
        execution_plan_sha256=plan.execution_plan_sha256,
        execution_protocol_sha256=PROTOCOL,
        state=AuthorityState.RESERVED,
        run_id=900,
        run_attempt=1,
        writer_job_id="reserve",
        writer_job_database_id=901,
        protected_commit_sha=COMMIT,
        created_at=NOW,
    )
    running = append_authority_record(
        previous=reserved,
        state=AuthorityState.RUNNING,
        writer_job_id="record_running",
        writer_job_database_id=902,
        created_at=NOW,
    )
    queue = CatalogRequestQueueEvidenceV1(
        status="ready",
        observed_at=NOW,
        source_sha256="1" * 64,
        content_sha256="2" * 64,
        receipt_sha256="3" * 64,
        reason_codes=(),
        complete=True,
        stable=True,
        current_issue_number=101,
        eligible_open_issue_numbers=(101,),
        request_queue_snapshot_sha256="4" * 64,
    )
    command = CatalogRoutingCommandV1(
        request_sha256=REQUEST,
        request_issue_number=101,
        campaign_id=plan.campaign_id,
        queue=queue,
        ledger=VerifiedAuthorityLedgerV1.from_records(
            (reserved, running), verified_writer_run_ids=(900,)
        ),
        prerequisites=CatalogRoutingPrerequisitesV1(
            observed_at=NOW,
            request_verified=True,
            campaign_registered=True,
            protected_head_verified=True,
            authority_anchor_verified=True,
            ledger_mirrors_verified=True,
            lifecycle_tamper_free=True,
            snapshot_complete=True,
            snapshot_stable=True,
            validation_opened=False,
            locked_opened=False,
            active_owner_authority_ids=(plan.authority_id,),
            routing_snapshot_sha256="5" * 64,
        ),
        verified_github_now=NOW,
    )
    _write(root / "routing-command.json", command)
    _write(root / "request-receipts.json", {
        "schema_version": "1",
        "request_issue_number": 101,
        "receipts": [],
        "complete": True,
        "stable": True,
        "writer_receipt_history_valid": True,
        "writer_provenance_verified": True,
        "artifact_mirror_verified": True,
    })
    _write(root / "authority-issue.json", {"issue": 999})
    _write(root / "authority-comments.json", {
        "comments": [],
        "artifact_records": [reserved.model_dump(mode="json"), running.model_dump(mode="json")],
        "checkpoints": [],
        "tamper_incidents": [],
        "complete_timeline": {"complete": True},
    })
    _write(root / "event.json", {"issue": {"number": 101}})
    _write(root / "request-timeline.json", {"complete": True, "stable": True})


def _runtime_and_science(base: Path, plan) -> dict[str, Path]:
    roots = {name: base / name for name in ("runtime", "component", "final", "science", "audit", "recovery", "engine")}
    for root in roots.values():
        root.mkdir()
    binding = {
        "request_sha256": REQUEST,
        "authority_id": str(plan.authority_id),
        "campaign_id": plan.campaign_id,
        "science_sha256": plan.science_sha256,
        "execution_plan_sha256": plan.execution_plan_sha256,
        "execution_protocol_sha256": PROTOCOL,
        "protected_commit_sha": COMMIT,
    }
    runtime_identity = {
        "schema_version": "1",
        **binding,
        "runtime_identity_sha256": "6" * 64,
        "runtime_manifest_sha256": "7" * 64,
        "prepared_input_identity_sha256": "8" * 64,
        "source_artifacts_sha256": "9" * 64,
        "source_fetch_receipt_sha256": "0" * 64,
        "partitions": [
            {
                "logical_id": "partition-a",
                "cache_key": "catalog-prepared-partition-a",
                "manifest_sha256": "1" * 64,
                "file_count": 1,
                "size_bytes": 12,
                "cache_hit": False,
            }
        ],
        "validation_opened": False,
        "locked_opened": False,
    }
    _write(roots["runtime"] / "runtime-prepared-seal.json", _hashed(runtime_identity, "seal_sha256"))
    component_manifest = base / "sealed" / "component_store_input_manifest.json"
    component_payload = json.loads(component_manifest.read_text("utf-8"))
    component_ids = component_payload["required_component_ids"]
    component_identity = {
        "schema_version": "1",
        "required_component_ids": component_ids,
        "component_result_sha256": {key: "a" * 64 for key in component_ids},
        "component_store_input_manifest_sha256": hashlib.sha256(component_manifest.read_bytes()).hexdigest(),
        "validation_opened": False,
        "locked_opened": False,
    }
    _write(roots["component"] / "component-store-seal.json", _hashed(component_identity, "seal_sha256"))
    for name, raw in (
        ("results.parquet", b"PAR1synthetic"),
        ("selected_results.jsonl", b""),
        ("summary.csv", b"strategy_id\n"),
    ):
        (roots["final"] / name).write_bytes(raw)
    reduction_identity = {
        "schema_version": 1,
        "strategy_count": len(plan.recipe_requirements),
        "result_sha256": "b" * 64,
        "science_identity_sha256": plan.science_sha256,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write(roots["final"] / "receipt.json", _hashed(reduction_identity, "receipt_sha256"))
    science_files = []
    for name in (
        "catalog_scientific_audit_receipt_v1.json",
        "catalog_equivalence_receipt_v1.json",
        "catalog_regression_receipt_v1.json",
    ):
        identity = {"schema_version": "1", **binding, "passed": True}
        target = roots["science"] / name
        _write(target, _hashed(identity, "receipt_sha256"))
        science_files.append({
            "path": name,
            "size_bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        })
    science_index = {
        "schema_version": "1",
        **binding,
        "files": science_files,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write(roots["science"] / "catalog_terminal_science_index_v1.json", _hashed(science_index, "index_sha256"))
    jobs = [{"jobs": [{"id": 1, "name": "reduce", "labels": ["ubuntu-24.04"], "runner_group_name": "GitHub Actions"}]}]
    artifacts = [{"artifacts": [{"id": 2, "name": "final", "expired": False, "size_in_bytes": 12}]}]
    audit = build_catalog_runtime_audit(
        binding=binding,
        run={
            "id": 900,
            "run_attempt": 1,
            "head_sha": COMMIT,
            "path": ".github/workflows/catalog-run-controller.yml",
            "repository": {"full_name": "trading-optimizer-lab-org/aurora"},
        },
        repository={"full_name": "trading-optimizer-lab-org/aurora", "visibility": "public", "private": False},
        jobs_pages=jobs,
        jobs_confirmation_pages=jobs,
        artifacts_pages=artifacts,
        artifacts_confirmation_pages=artifacts,
        run_id=900,
        run_attempt=1,
        audited_at=NOW,
        components_reused=0,
        components_computed_once=len(component_ids),
        selective_retries=0,
    )
    _write(roots["audit"] / "runtime-audit.json", audit)
    outcome = select_catalog_engine_outcome(
        **binding,
        engine_run_id=900,
        engine_run_attempt=1,
        stage_results={"reduce": "success", "verify_terminal_science": "success", "audit_runtime": "success"},
        recovery_statuses=(),
        final_evidence_artifact="catalog-final",
        runtime_audit_artifact="catalog-runtime-audit",
        science_evidence_artifact="catalog-science",
        recovery_evidence_artifact=None,
        failure_fingerprint=None,
        failure_occurrence_count=0,
        failure_reason_code=None,
        retry_not_before=None,
        terminal_failure_code=None,
        created_at=NOW,
    )
    _write(roots["engine"] / "catalog-engine-outcome-v1.json", outcome)
    return roots


def _fixture(
    tmp_path: Path,
    *,
    complete: bool,
    controls_commit_sha: str = COMMIT,
):
    sealed = tmp_path / "sealed"
    plan, _ = _sealed_plan(sealed)
    decision, admission_controls = _decision_and_controls(
        plan, controls_commit_sha=controls_commit_sha
    )
    admission = tmp_path / "admission"
    _write(admission / "controller-decision" / "decision.json", decision)
    routing = tmp_path / "routing"
    _routing(routing, plan, decision)
    controls_path = tmp_path / "admission-controls.json"
    _write(controls_path, admission_controls)
    if complete:
        roots = _runtime_and_science(tmp_path, plan)
        engine_result = "success"
    else:
        roots = {name: tmp_path / name for name in ("runtime", "component", "final", "science", "audit", "recovery", "engine")}
        for root in roots.values():
            root.mkdir()
        engine_result = "failure"
    output = tmp_path / "prepared"
    index = prepare_terminal_evidence(
        repo_root=Path(__file__).resolve().parents[1],
        admission_root=admission,
        sealed_plan=sealed,
        routing_root=routing,
        admission_controls_path=controls_path,
        engine_outcome_root=roots["engine"],
        runtime_prepared_root=roots["runtime"],
        component_seal_root=roots["component"],
        final_root=roots["final"],
        science_root=roots["science"],
        runtime_audit_root=roots["audit"],
        recovery_root=roots["recovery"],
        engine_result=engine_result,
        output_dir=output,
    )
    return plan, index, output


def _terminal_controls(index: dict[str, object]):
    controls_commit_sha = str(
        index.get("github_controls_commit_sha", index["protected_commit_sha"])
    )
    return _auditor_receipt(
        audit_use_context="controller_terminal",
        audit_context_sha256=index["audit_context_sha256"],
        protected_commit_sha=controls_commit_sha,
        observed_default_branch_sha=controls_commit_sha,
        caller_job="live_controls_audit_before_terminal",
    )


def test_complete_bound_evidence_reaches_one_truthful_success(tmp_path: Path) -> None:
    _plan, index, prepared = _fixture(tmp_path, complete=True)
    controls = tmp_path / "terminal-controls.json"
    _write(controls, _terminal_controls(index))
    envelope = bind_terminal_controls(
        prepared_root=prepared,
        terminal_controls_path=controls,
        output_dir=tmp_path / "decision-input",
    )
    decision = finalize_catalog_run(final_evidence=envelope.final_evidence)
    assert decision.state is CatalogTerminalState.SUCCESS
    assert decision.reason_code == "CATALOG_SUCCESS"


def test_runtime_preparation_failure_is_blocked_without_invented_hashes(tmp_path: Path) -> None:
    _plan, index, prepared = _fixture(tmp_path, complete=False)
    controls = tmp_path / "terminal-controls.json"
    _write(controls, _terminal_controls(index))
    envelope = bind_terminal_controls(
        prepared_root=prepared,
        terminal_controls_path=controls,
        output_dir=tmp_path / "decision-input",
    )
    decision = finalize_catalog_run(final_evidence=envelope.final_evidence)
    assert decision.state is CatalogTerminalState.BLOCKED
    runtime = envelope.final_evidence.evidence_slots["runtime"]
    assert runtime.status == "not_reached"
    assert runtime.sha256 is None


def test_terminal_controls_must_match_exact_context_and_commit(tmp_path: Path) -> None:
    _plan, index, prepared = _fixture(tmp_path, complete=False)
    controls = tmp_path / "terminal-controls.json"
    wrong = _auditor_receipt(
        audit_use_context="controller_terminal",
        audit_context_sha256="0" * 64,
        protected_commit_sha=COMMIT,
        observed_default_branch_sha=COMMIT,
        caller_job="live_controls_audit_before_terminal",
    )
    _write(controls, wrong)
    with pytest.raises(ValueError, match="CATALOG_TERMINAL_CONTROLS_BINDING_INVALID"):
        bind_terminal_controls(
            prepared_root=prepared,
            terminal_controls_path=controls,
            output_dir=tmp_path / "decision-input",
        )


def test_recovery_keeps_execution_commit_but_audits_current_controls_commit(
    tmp_path: Path,
) -> None:
    current_controls_commit = "d" * 40
    _plan, index, prepared = _fixture(
        tmp_path,
        complete=False,
        controls_commit_sha=current_controls_commit,
    )
    assert index["protected_commit_sha"] == COMMIT
    assert index["github_controls_commit_sha"] == current_controls_commit
    controls = tmp_path / "terminal-controls.json"
    _write(controls, _terminal_controls(index))
    envelope = bind_terminal_controls(
        prepared_root=prepared,
        terminal_controls_path=controls,
        output_dir=tmp_path / "decision-input",
    )
    assert envelope.final_evidence.protected_commit_sha == COMMIT


def test_recovery_rejects_controls_receipt_for_old_execution_commit(
    tmp_path: Path,
) -> None:
    _plan, index, prepared = _fixture(
        tmp_path,
        complete=False,
        controls_commit_sha="d" * 40,
    )
    stale = _auditor_receipt(
        audit_use_context="controller_terminal",
        audit_context_sha256=index["audit_context_sha256"],
        protected_commit_sha=COMMIT,
        observed_default_branch_sha=COMMIT,
        caller_job="live_controls_audit_before_terminal",
    )
    controls = tmp_path / "terminal-controls.json"
    _write(controls, stale)
    with pytest.raises(ValueError, match="CATALOG_TERMINAL_CONTROLS_BINDING_INVALID"):
        bind_terminal_controls(
            prepared_root=prepared,
            terminal_controls_path=controls,
            output_dir=tmp_path / "decision-input",
        )


def test_terminal_adapter_never_overwrites_existing_output(tmp_path: Path) -> None:
    _plan, _index, prepared = _fixture(tmp_path, complete=False)
    output = tmp_path / "decision-input"
    output.mkdir()
    controls = tmp_path / "terminal-controls.json"
    _write(controls, _terminal_controls(_index))
    with pytest.raises(ValueError, match="CATALOG_TERMINAL_DECISION_OUTPUT_EXISTS"):
        bind_terminal_controls(
            prepared_root=prepared,
            terminal_controls_path=controls,
            output_dir=output,
        )
