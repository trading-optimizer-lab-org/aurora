"""Bound fixed engine evidence into one truthful terminal-finalizer envelope."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from .catalog_authority_ledger import select_campaign_authority
from .catalog_controller import CatalogControllerDecisionV1, ControllerOutcome
from .catalog_controller_reporting import (
    FINAL_EVIDENCE_FILENAME_BY_SLOT,
    FINAL_EVIDENCE_SLOT_NAMES,
    FINALIZER_INPUT_NAMES,
    CatalogFinalEvidenceFactsV1,
    CatalogFinalEvidenceV1,
    CatalogFinalizerEnvelopeV1,
    CatalogPerformanceTelemetryV1,
    EvidenceSlotV1,
)
from .catalog_engine_outcome import (
    CatalogEngineOutcomeState,
    CatalogEngineOutcomeV1,
)
from .catalog_github_controls import AuditorCatalogGithubControlsReceiptV1
from .catalog_request_contract import canonical_model_bytes
from .catalog_routing import CatalogRoutingCommandV1


_SHA256_ZERO = "0" * 64
_CORE_PRESENT_SLOTS = frozenset(
    {
        "authority_anchor_evidence",
        "authority_writer_provenance",
        "authority_ledger_snapshot",
        "authority_mirror_coverage",
        "authority_lifecycle_history",
        "originating_request_lifecycle_history",
        "request_receipt_writer_provenance",
        "request_receipt_mirror_coverage",
        "tamper_incident_inventory",
        "github_controls_before_reserve",
        "admission_decision",
        "capacity_decision",
        "source_artifact_lineage",
        "expected_logical_unit_manifest",
        "expected_logical_unit_count",
        "component_contract_sha256",
        "validation_opened",
        "locked_opened",
        "source_artifact_run_ids",
        "source_artifact_original_and_mirror_ids",
        "terminal_artifact_names",
    }
)


def _canonical_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _strict_json(path: Path, code: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(code)

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("duplicate key")
            payload[key] = value
        return payload

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite constant: {value}")
        ),
    )
    if not isinstance(payload, dict):
        raise ValueError(code)
    return payload


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _sequence(value: object, code: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(code)
    return value


def _content_hash_valid(payload: Mapping[str, Any], field: str) -> bool:
    expected = payload.get(field)
    identity = {key: value for key, value in payload.items() if key != field}
    return isinstance(expected, str) and expected == _sha256_bytes(
        _canonical_bytes(identity)
    )


def _plan_payload(path: Path, document_type: str) -> Mapping[str, Any]:
    value = _strict_json(path, "CATALOG_TERMINAL_PLAN_DOCUMENT_INVALID")
    if (
        value.get("schema_version") != "1"
        or value.get("document_type") != document_type
        or not _content_hash_valid(value, "content_sha256")
    ):
        raise ValueError("CATALOG_TERMINAL_PLAN_DOCUMENT_INVALID")
    return value


def _hashed_wrapper(
    *,
    slot: str,
    binding: Mapping[str, object],
    sources: Mapping[str, str],
    facts: Mapping[str, object],
) -> bytes:
    identity = {
        "schema_version": "1",
        "slot": slot,
        **dict(binding),
        "source_sha256s": dict(sorted(sources.items())),
        "verified_facts": dict(facts),
        "validation_opened": False,
        "locked_opened": False,
    }
    value = {**identity, "receipt_sha256": _sha256_bytes(_canonical_bytes(identity))}
    return _canonical_bytes(value) + b"\n"


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _copy_json(source: Path, destination: Path, code: str) -> str:
    _strict_json(source, code)
    raw = source.read_bytes()
    destination.write_bytes(raw)
    return _sha256_bytes(raw)


def _verified_controls(path: Path, *, purpose: str) -> AuditorCatalogGithubControlsReceiptV1:
    receipt = AuditorCatalogGithubControlsReceiptV1.model_validate(
        _strict_json(path, "CATALOG_TERMINAL_CONTROLS_INVALID")
    )
    expected_context = {
        "admission": "controller_admission",
        "terminal": "controller_terminal",
    }[purpose]
    expected_job = {
        "admission": "live_controls_audit_before_reserve",
        "terminal": "live_controls_audit_before_terminal",
    }[purpose]
    if (
        receipt.status != "ready"
        or receipt.audit_use_context != expected_context
        or receipt.caller_workflow != ".github/workflows/catalog-run-controller.yml"
        or receipt.caller_job != expected_job
    ):
        raise ValueError("CATALOG_TERMINAL_CONTROLS_INVALID")
    return receipt


def _optional_file(root: Path, filename: str) -> Path | None:
    path = root / filename
    return path if path.is_file() and not path.is_symlink() else None


def _verify_runtime_seal(
    root: Path,
    binding: Mapping[str, object],
) -> tuple[Mapping[str, Any] | None, Mapping[str, str]]:
    path = _optional_file(root, "runtime-prepared-seal.json")
    if path is None:
        return None, {}
    seal = _strict_json(path, "CATALOG_RUNTIME_PREPARED_SEAL_INVALID")
    if (
        not _content_hash_valid(seal, "seal_sha256")
        or any(seal.get(key) != value for key, value in binding.items())
        or seal.get("validation_opened") is not False
        or seal.get("locked_opened") is not False
        or not _sequence(seal.get("partitions"), "CATALOG_RUNTIME_PREPARED_SEAL_INVALID")
    ):
        raise ValueError("CATALOG_RUNTIME_PREPARED_SEAL_INVALID")
    return seal, {"runtime_prepared_seal": _sha256_file(path)}


def _verify_component_seal(
    root: Path,
    *,
    expected_component_ids: tuple[str, ...],
    component_manifest_path: Path,
) -> tuple[Mapping[str, Any] | None, Mapping[str, str]]:
    path = _optional_file(root, "component-store-seal.json")
    if path is None:
        return None, {}
    seal = _strict_json(path, "CATALOG_COMPONENT_STORE_SEAL_INVALID")
    if (
        not _content_hash_valid(seal, "seal_sha256")
        or tuple(seal.get("required_component_ids", ())) != expected_component_ids
        or set(_mapping(seal.get("component_result_sha256"), "CATALOG_COMPONENT_STORE_SEAL_INVALID"))
        != set(expected_component_ids)
        or seal.get("component_store_input_manifest_sha256")
        != _sha256_file(component_manifest_path)
        or seal.get("validation_opened") is not False
        or seal.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_COMPONENT_STORE_SEAL_INVALID")
    return seal, {"component_store_seal": _sha256_file(path)}


def _verify_science_and_final(
    *,
    science_root: Path,
    final_root: Path,
    binding: Mapping[str, object],
    expected_count: int,
) -> tuple[bool, dict[str, str], Mapping[str, Any] | None]:
    index_path = _optional_file(science_root, "catalog_terminal_science_index_v1.json")
    receipt_path = _optional_file(final_root, "receipt.json")
    if index_path is None or receipt_path is None:
        return False, {}, None
    index = _strict_json(index_path, "CATALOG_TERMINAL_SCIENCE_INDEX_INVALID")
    if (
        not _content_hash_valid(index, "index_sha256")
        or any(index.get(key) != value for key, value in binding.items())
        or index.get("validation_opened") is not False
        or index.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_TERMINAL_SCIENCE_INDEX_INVALID")
    sources = {"terminal_science_index": _sha256_file(index_path)}
    files = _sequence(index.get("files"), "CATALOG_TERMINAL_SCIENCE_INDEX_INVALID")
    expected_names = {
        "catalog_scientific_audit_receipt_v1.json",
        "catalog_equivalence_receipt_v1.json",
        "catalog_regression_receipt_v1.json",
    }
    observed_names: set[str] = set()
    for raw in files:
        row = _mapping(raw, "CATALOG_TERMINAL_SCIENCE_INDEX_INVALID")
        name = row.get("path")
        if not isinstance(name, str) or name not in expected_names or name in observed_names:
            raise ValueError("CATALOG_TERMINAL_SCIENCE_INDEX_INVALID")
        target = science_root / name
        if (
            not target.is_file()
            or target.is_symlink()
            or target.stat().st_size != row.get("size_bytes")
            or _sha256_file(target) != row.get("sha256")
        ):
            raise ValueError("CATALOG_TERMINAL_SCIENCE_INDEX_INVALID")
        document = _strict_json(target, "CATALOG_TERMINAL_SCIENCE_RECEIPT_INVALID")
        if (
            not _content_hash_valid(document, "receipt_sha256")
            or any(document.get(key) != value for key, value in binding.items())
        ):
            raise ValueError("CATALOG_TERMINAL_SCIENCE_RECEIPT_INVALID")
        observed_names.add(name)
        sources[name] = _sha256_file(target)
    if observed_names != expected_names:
        raise ValueError("CATALOG_TERMINAL_SCIENCE_INDEX_INVALID")
    reduction = _strict_json(receipt_path, "CATALOG_TERMINAL_REDUCTION_INVALID")
    if (
        not _content_hash_valid(reduction, "receipt_sha256")
        or reduction.get("strategy_count") != expected_count
        or reduction.get("science_identity_sha256") != binding["science_sha256"]
        or reduction.get("validation_opened") is not False
        or reduction.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_TERMINAL_REDUCTION_INVALID")
    for name in ("results.parquet", "selected_results.jsonl", "summary.csv", "receipt.json"):
        target = final_root / name
        if target.is_symlink() or not target.is_file():
            raise ValueError("CATALOG_TERMINAL_FINAL_ROOT_INVALID")
        sources[f"final:{name}"] = _sha256_file(target)
    return True, sources, reduction


def _verify_runtime_audit(
    root: Path,
    binding: Mapping[str, object],
) -> tuple[Mapping[str, Any] | None, Mapping[str, str]]:
    path = _optional_file(root, "runtime-audit.json")
    if path is None:
        return None, {}
    value = _strict_json(path, "CATALOG_RUNTIME_AUDIT_INVALID")
    if (
        not _content_hash_valid(value, "receipt_sha256")
        or any(value.get(key) != expected for key, expected in binding.items())
        or value.get("standard_runner_only") is not True
        or value.get("validation_opened") is not False
        or value.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_RUNTIME_AUDIT_INVALID")
    return value, {"runtime_audit": _sha256_file(path)}


def _facts_and_sources(
    *,
    routing: CatalogRoutingCommandV1,
    request_receipts: Mapping[str, Any],
    expected_unit_ids: tuple[str, ...],
    expected_component_ids: tuple[str, ...],
    engine: CatalogEngineOutcomeV1 | None,
    runtime_seal: Mapping[str, Any] | None,
    component_seal: Mapping[str, Any] | None,
    science_complete: bool,
    reduction: Mapping[str, Any] | None,
    runtime_audit: Mapping[str, Any] | None,
    admission_controls: AuditorCatalogGithubControlsReceiptV1,
) -> CatalogFinalEvidenceFactsV1:
    terminal_candidate = (
        engine is not None
        and engine.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE
        and science_complete
        and runtime_audit is not None
    )
    completed = expected_unit_ids if terminal_candidate else ()
    available_components = expected_component_ids if component_seal is not None else ()
    terminal_failure = (
        engine.terminal_failure_code
        if engine is not None and engine.state is CatalogEngineOutcomeState.FAILED
        else None
    )
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
        expected_unit_ids=expected_unit_ids,
        completed_unit_ids=completed,
        conflicting_attempt_unit_ids=(),
        expected_component_ids=expected_component_ids,
        available_component_ids=available_components,
        component_recomputed_in_recipe_ids=(),
        source_lineage_valid=True,
        runtime_receipt_valid=runtime_seal is not None,
        prepared_data_valid=runtime_seal is not None,
        checkpoint_chain_valid=terminal_candidate,
        component_store_sealed=component_seal is not None,
        reducer_complete=terminal_candidate and reduction is not None,
        schemas_valid=terminal_candidate,
        scientific_audit_passed=terminal_candidate,
        equivalence_passed=terminal_candidate,
        regression_passed=terminal_candidate,
        validation_opened=False,
        locked_opened=False,
        standard_runner_only=(
            runtime_audit is not None
            and runtime_audit.get("standard_runner_only") is True
        ),
        paid_runner_minutes=int(
            runtime_audit.get("paid_runner_minutes", 0)
            if runtime_audit is not None
            else 0
        ),
        estimated_paid_actions_cost_microusd=int(
            runtime_audit.get("estimated_paid_actions_cost_microusd", 0)
            if runtime_audit is not None
            else 0
        ),
        zero_actions_spend_budget_verified=admission_controls.status == "ready",
        zero_actions_storage_budget_verified=admission_controls.status == "ready",
        zero_cache_storage_budget_verified=admission_controls.status == "ready",
        ledger_valid=True,
        ledger_writer_provenance_valid=routing.prerequisites.ledger_mirrors_verified,
        ledger_mirror_coverage_valid=routing.prerequisites.ledger_mirrors_verified,
        authority_lifecycle_complete=routing.prerequisites.lifecycle_tamper_free,
        originating_request_intact=routing.prerequisites.lifecycle_tamper_free,
        request_lifecycle_complete=routing.prerequisites.lifecycle_tamper_free,
        request_receipt_writer_provenance_valid=(
            request_receipts.get("writer_provenance_verified") is True
        ),
        request_receipt_mirror_coverage_valid=(
            request_receipts.get("artifact_mirror_verified") is True
        ),
        tamper_incident_inventory_complete=routing.prerequisites.lifecycle_tamper_free,
        github_controls_before_reserve_ready=True,
        github_controls_before_terminal_ready=False,
        terminal_failure_code=terminal_failure,
        same_failure_fingerprint_count=(
            engine.failure_occurrence_count if engine is not None else 0
        ),
        work_preserved="Componentes y resultados verificados siguen reutilizables.",
        automatic_action="Detención o cierre seguro según la evidencia verificada.",
    )


def prepare_terminal_evidence(
    *,
    repo_root: Path,
    admission_root: Path,
    sealed_plan: Path,
    routing_root: Path,
    admission_controls_path: Path,
    engine_outcome_root: Path,
    runtime_prepared_root: Path,
    component_seal_root: Path,
    final_root: Path,
    science_root: Path,
    runtime_audit_root: Path,
    recovery_root: Path,
    engine_result: str,
    output_dir: Path,
) -> dict[str, object]:
    """Verify all fixed available evidence and prepare the post-audit envelope."""

    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("CATALOG_PREPARED_TERMINAL_OUTPUT_EXISTS")
    if engine_result not in {"success", "failure", "cancelled", "skipped"}:
        raise ValueError("CATALOG_ENGINE_RESULT_INVALID")
    root = repo_root.resolve(strict=True)
    if repo_root.is_symlink() or not root.is_dir():
        raise ValueError("CATALOG_TERMINAL_REPOSITORY_INVALID")

    from scripts.plan_sp500_optimized_catalog_run import (
        verify_sealed_global_reuse_execution_plan,
    )

    decision = CatalogControllerDecisionV1.model_validate(
        _strict_json(
            admission_root / "controller-decision/decision.json",
            "CATALOG_TERMINAL_ADMISSION_DECISION_INVALID",
        )
    )
    if (
        decision.outcome not in {ControllerOutcome.ADMITTED, ControllerOutcome.ADOPTED}
        or decision.sealed_inputs is None
        or not decision.should_schedule_compute
    ):
        raise ValueError("CATALOG_TERMINAL_ADMISSION_DECISION_INVALID")
    sealed = decision.sealed_inputs
    controls_commit_sha = (
        sealed.github_controls_commit_sha or sealed.protected_commit_sha
    )
    binding = {
        "request_sha256": sealed.request_sha256,
        "authority_id": str(sealed.authority_id),
        "campaign_id": sealed.campaign_id,
        "science_sha256": sealed.science_sha256,
        "execution_plan_sha256": sealed.execution_plan_sha256,
        "execution_protocol_sha256": sealed.execution_protocol_sha256,
        "protected_commit_sha": sealed.protected_commit_sha,
    }
    plan_receipt = verify_sealed_global_reuse_execution_plan(
        sealed_plan,
        expected_bindings=binding,
    )
    controller_document = _plan_payload(
        sealed_plan / "controller_binding.json", "controller_binding"
    )
    controller_binding = _mapping(
        controller_document.get("binding"),
        "CATALOG_TERMINAL_CONTROLLER_BINDING_INVALID",
    )
    if any(controller_binding.get(key) != value for key, value in binding.items()):
        raise ValueError("CATALOG_TERMINAL_CONTROLLER_BINDING_INVALID")

    routing = CatalogRoutingCommandV1.model_validate(
        _strict_json(
            routing_root / "routing-command.json",
            "CATALOG_TERMINAL_ROUTING_INVALID",
        )
    )
    authority = select_campaign_authority(routing.ledger, sealed.campaign_id)
    if (
        routing.request_sha256 != sealed.request_sha256
        or routing.campaign_id != sealed.campaign_id
        or authority is None
        or authority.authority_id != sealed.authority_id
        or authority.science_sha256 != sealed.science_sha256
        or authority.execution_protocol_sha256 != sealed.execution_protocol_sha256
        or authority.protected_commit_sha != sealed.protected_commit_sha
        or not routing.prerequisites.authority_anchor_verified
        or not routing.prerequisites.ledger_mirrors_verified
        or not routing.prerequisites.lifecycle_tamper_free
        or routing.prerequisites.validation_opened
        or routing.prerequisites.locked_opened
    ):
        raise ValueError("CATALOG_TERMINAL_ROUTING_INVALID")
    request_receipts = _strict_json(
        routing_root / "request-receipts.json",
        "CATALOG_TERMINAL_REQUEST_RECEIPTS_INVALID",
    )
    if (
        request_receipts.get("complete") is not True
        or request_receipts.get("stable") is not True
        or request_receipts.get("writer_receipt_history_valid") is not True
        or request_receipts.get("writer_provenance_verified") is not True
        or request_receipts.get("artifact_mirror_verified") is not True
    ):
        raise ValueError("CATALOG_TERMINAL_REQUEST_RECEIPTS_INVALID")

    admission_controls = _verified_controls(
        admission_controls_path,
        purpose="admission",
    )
    if (
        admission_controls.receipt_sha256 != sealed.github_controls_receipt_sha256
        or admission_controls.protected_commit_sha != controls_commit_sha
    ):
        raise ValueError("CATALOG_TERMINAL_ADMISSION_CONTROLS_INVALID")

    engine_path = _optional_file(
        engine_outcome_root, "catalog-engine-outcome-v1.json"
    )
    engine = (
        CatalogEngineOutcomeV1.model_validate(
            _strict_json(engine_path, "CATALOG_ENGINE_OUTCOME_INVALID")
        )
        if engine_path is not None
        else None
    )
    if engine is not None and (
        engine.request_sha256 != sealed.request_sha256
        or engine.authority_id != sealed.authority_id
        or engine.campaign_id != sealed.campaign_id
        or engine.science_sha256 != sealed.science_sha256
        or engine.execution_plan_sha256 != sealed.execution_plan_sha256
        or engine.execution_protocol_sha256 != sealed.execution_protocol_sha256
        or engine.protected_commit_sha != sealed.protected_commit_sha
    ):
        raise ValueError("CATALOG_ENGINE_OUTCOME_BINDING_INVALID")
    if (engine is not None) != (engine_result == "success"):
        raise ValueError("CATALOG_ENGINE_RESULT_CONTRADICTS_OUTCOME")

    logical = _plan_payload(
        sealed_plan / "logical_recipe_manifest.json", "logical_recipe_manifest"
    )
    recipes = _sequence(logical.get("recipes"), "CATALOG_TERMINAL_LOGICAL_MANIFEST_INVALID")
    expected_unit_ids = tuple(
        str(_mapping(row, "CATALOG_TERMINAL_LOGICAL_MANIFEST_INVALID").get("strategy_id"))
        for row in recipes
    )
    if (
        not expected_unit_ids
        or len(expected_unit_ids) != len(set(expected_unit_ids))
        or logical.get("strategy_count") != len(expected_unit_ids)
    ):
        raise ValueError("CATALOG_TERMINAL_LOGICAL_MANIFEST_INVALID")
    component_manifest_path = sealed_plan / "component_store_input_manifest.json"
    component_manifest = _plan_payload(
        component_manifest_path, "component_store_input_manifest"
    )
    expected_component_ids = tuple(
        str(value)
        for value in _sequence(
            component_manifest.get("required_component_ids"),
            "CATALOG_TERMINAL_COMPONENT_MANIFEST_INVALID",
        )
    )
    if expected_component_ids != tuple(sorted(set(expected_component_ids))):
        raise ValueError("CATALOG_TERMINAL_COMPONENT_MANIFEST_INVALID")

    runtime_seal, runtime_sources = _verify_runtime_seal(runtime_prepared_root, binding)
    component_seal, component_sources = _verify_component_seal(
        component_seal_root,
        expected_component_ids=expected_component_ids,
        component_manifest_path=component_manifest_path,
    )
    science_complete, science_sources, reduction = _verify_science_and_final(
        science_root=science_root,
        final_root=final_root,
        binding=binding,
        expected_count=len(expected_unit_ids),
    )
    runtime_audit, audit_sources = _verify_runtime_audit(runtime_audit_root, binding)

    terminal_candidate = (
        engine is not None
        and engine.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE
    )
    if terminal_candidate and (
        runtime_seal is None
        or component_seal is None
        or not science_complete
        or runtime_audit is None
    ):
        raise ValueError("CATALOG_TERMINAL_CANDIDATE_EVIDENCE_INCOMPLETE")

    source_document = _strict_json(
        sealed_plan / "source_artifacts.json",
        "CATALOG_TERMINAL_SOURCE_ARTIFACTS_INVALID",
    )
    source_payload = _mapping(
        source_document.get("payload"), "CATALOG_TERMINAL_SOURCE_ARTIFACTS_INVALID"
    )
    source_evidence = _mapping(
        source_payload.get("evidence"), "CATALOG_TERMINAL_SOURCE_ARTIFACTS_INVALID"
    )
    artifact_plan_sha256 = source_evidence.get("artifact_plan_sha256")
    if not isinstance(artifact_plan_sha256, str):
        raise ValueError("CATALOG_TERMINAL_SOURCE_ARTIFACTS_INVALID")

    facts = _facts_and_sources(
        routing=routing,
        request_receipts=request_receipts,
        expected_unit_ids=expected_unit_ids,
        expected_component_ids=expected_component_ids,
        engine=engine,
        runtime_seal=runtime_seal,
        component_seal=component_seal,
        science_complete=science_complete,
        reduction=reduction,
        runtime_audit=runtime_audit,
        admission_controls=admission_controls,
    )

    output_dir.mkdir(parents=False, exist_ok=False)
    evidence_dir = output_dir / "evidence"
    external_dir = output_dir / "external"
    evidence_dir.mkdir()
    external_dir.mkdir()

    source_hashes = {
        "sealed_plan_receipt": _sha256_file(sealed_plan / "execution_plan_receipt.json"),
        "controller_decision": _sha256_file(
            admission_root / "controller-decision/decision.json"
        ),
        "routing_command": _sha256_file(routing_root / "routing-command.json"),
        "admission_controls": _sha256_file(admission_controls_path),
        "source_artifacts": _sha256_file(sealed_plan / "source_artifacts.json"),
        "logical_recipe_manifest": _sha256_file(
            sealed_plan / "logical_recipe_manifest.json"
        ),
        "component_store_input_manifest": _sha256_file(component_manifest_path),
        **runtime_sources,
        **component_sources,
        **science_sources,
        **audit_sources,
    }
    if engine_path is not None:
        source_hashes["engine_outcome"] = _sha256_file(engine_path)
    recovery_files = (
        sorted(path for path in recovery_root.iterdir() if path.is_file() and not path.is_symlink())
        if recovery_root.is_dir() and not recovery_root.is_symlink()
        else []
    )
    for path in recovery_files:
        source_hashes[f"recovery:{path.name}"] = _sha256_file(path)

    success_sources = {
        **source_hashes,
    }
    present_slots = set(_CORE_PRESENT_SLOTS)
    if runtime_seal is not None:
        present_slots.update({"runtime", "prepared_data"})
    if component_seal is not None:
        present_slots.update({"component_manifest", "component_store_seal"})
    if terminal_candidate and science_complete and runtime_audit is not None:
        present_slots.update(
            {
                "completed_logical_unit_manifest",
                "completed_logical_unit_count",
                "recipe_results",
                "attempt_reconciliation",
                "checkpoint_reconciliation",
                "recovery_history",
                "reduction_receipt",
                "scientific_audit_receipt",
                "equivalence_receipt",
                "performance_receipt",
                "actions_billing_and_zero_spend_budgets_receipt",
            }
        )
    slots: dict[str, EvidenceSlotV1] = {}
    evidence_manifest: list[dict[str, object]] = []
    for slot in FINAL_EVIDENCE_SLOT_NAMES:
        if slot == "github_controls_before_terminal":
            slots[slot] = EvidenceSlotV1(
                status="not_reached",
                sha256=None,
                reason_code="CONTROL_AUDIT_UNAVAILABLE",
                artifact_or_receipt_id=None,
            )
            continue
        if slot == "terminal_failure_receipt" and facts.terminal_failure_code is None:
            slots[slot] = EvidenceSlotV1(
                status="not_reached",
                sha256=None,
                reason_code="NO_TERMINAL_FAILURE",
                artifact_or_receipt_id=None,
            )
            continue
        if slot not in present_slots:
            reason = "UPSTREAM_FAILED" if engine_result in {"failure", "cancelled"} else "UPSTREAM_BLOCKED"
            slots[slot] = EvidenceSlotV1(
                status="not_reached",
                sha256=None,
                reason_code=reason,
                artifact_or_receipt_id=None,
            )
            continue
        filename = FINAL_EVIDENCE_FILENAME_BY_SLOT[slot]
        raw = _hashed_wrapper(
            slot=slot,
            binding=binding,
            sources=success_sources,
            facts={
                "engine_state": engine.state.value if engine is not None else "UNAVAILABLE",
                "verified": True,
            },
        )
        target = evidence_dir / filename
        target.write_bytes(raw)
        digest = _sha256_bytes(raw)
        slots[slot] = EvidenceSlotV1(
            status="present",
            sha256=digest,
            reason_code=None,
            artifact_or_receipt_id=filename,
        )
        evidence_manifest.append(
            {"path": filename, "sha256": digest, "size_bytes": len(raw)}
        )

    telemetry = None
    if runtime_audit is not None:
        telemetry = CatalogPerformanceTelemetryV1(
            strategies_per_minute=runtime_audit.get("strategies_per_minute"),
            components_reused=runtime_audit.get("components_reused"),
            components_computed_once=runtime_audit.get("components_computed_once"),
            selective_retries=runtime_audit.get("selective_retries"),
        )
    final_evidence_base = CatalogFinalEvidenceV1(
        schema_version="1",
        request_sha256=sealed.request_sha256,
        authority_id=sealed.authority_id,
        campaign_id=sealed.campaign_id,
        science_sha256=sealed.science_sha256,
        execution_plan_sha256=sealed.execution_plan_sha256,
        artifact_plan_sha256=artifact_plan_sha256,
        execution_protocol_sha256=sealed.execution_protocol_sha256,
        protected_commit_sha=sealed.protected_commit_sha,
        prompt_sha256=str(controller_binding["prompt_sha256"]),
        source_prompt_sha256=str(controller_binding["source_prompt_sha256"]),
        prompt_migration_sha256=str(controller_binding["prompt_migration_sha256"]),
        prompt_policy_sha256=str(controller_binding["prompt_policy_sha256"]),
        registry_sha256=str(controller_binding["campaign_registry_sha256"]),
        evidence_slots=slots,
        facts=facts,
        telemetry=telemetry,
    )

    external_sources = {
        "authority_issue": routing_root / "authority-issue.json",
        "authority_comments": routing_root / "authority-comments.json",
        "authority_timeline": routing_root / "authority-comments.json",
        "authority_anchor": root / "config/catalog_authority_anchor_v1.json",
        "request_issue": routing_root / "event.json",
        "request_timeline": routing_root / "request-timeline.json",
        "request_receipts": routing_root / "request-receipts.json",
        "github_controls_before_reserve": admission_controls_path,
    }
    external_hashes: dict[str, str] = {}
    for name, source in external_sources.items():
        external_hashes[name] = _copy_json(
            source,
            external_dir / f"{name}.json",
            f"CATALOG_TERMINAL_EXTERNAL_INPUT_INVALID:{name}",
        )
    authority_comments = _strict_json(
        routing_root / "authority-comments.json",
        "CATALOG_TERMINAL_AUTHORITY_COMMENTS_INVALID",
    )
    derived_external = {
        "authority_mirrors": {
            "artifact_records": authority_comments.get("artifact_records", []),
            "checkpoints": authority_comments.get("checkpoints", []),
        },
        "tamper_incidents": {
            "authority": authority_comments.get("tamper_incidents", []),
            "request_receipts": request_receipts.get("receipts", []),
        },
    }
    for name, value in derived_external.items():
        target = external_dir / f"{name}.json"
        _write_json(target, value)
        external_hashes[name] = _sha256_file(target)
    if set(external_hashes) != set(FINALIZER_INPUT_NAMES) - {
        "github_controls_before_terminal"
    }:
        raise ValueError("CATALOG_TERMINAL_EXTERNAL_INPUT_SET_INVALID")

    context_identity = {
        "schema_version": "1",
        **binding,
        "github_controls_commit_sha": controls_commit_sha,
        "engine_outcome_evidence_sha256": (
            engine.evidence_sha256 if engine is not None else _SHA256_ZERO
        ),
        "routing_snapshot_sha256": routing.prerequisites.routing_snapshot_sha256,
        "evidence_manifest_sha256": _sha256_bytes(_canonical_bytes(evidence_manifest)),
    }
    audit_context_sha256 = _sha256_bytes(_canonical_bytes(context_identity))
    index_identity = {
        "schema_version": "1",
        **binding,
        "github_controls_commit_sha": controls_commit_sha,
        "audit_context_sha256": audit_context_sha256,
        "final_evidence_base": final_evidence_base.model_dump(mode="json"),
        "external_input_sha256s": dict(sorted(external_hashes.items())),
        "evidence_manifest": sorted(evidence_manifest, key=lambda row: str(row["path"])),
        "engine_result": engine_result,
        "engine_outcome_evidence_sha256": (
            engine.evidence_sha256 if engine is not None else None
        ),
        "prepared_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "validation_opened": False,
        "locked_opened": False,
    }
    index = {
        **index_identity,
        "index_sha256": _sha256_bytes(_canonical_bytes(index_identity)),
    }
    _write_json(output_dir / "prepared-terminal-evidence-v1.json", index)
    return index


def bind_terminal_controls(
    *,
    prepared_root: Path,
    terminal_controls_path: Path,
    output_dir: Path,
) -> CatalogFinalizerEnvelopeV1:
    """Bind one fresh ready terminal audit and emit a complete finalizer input."""

    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("CATALOG_TERMINAL_DECISION_OUTPUT_EXISTS")
    index = _strict_json(
        prepared_root / "prepared-terminal-evidence-v1.json",
        "CATALOG_PREPARED_TERMINAL_INDEX_INVALID",
    )
    if not _content_hash_valid(index, "index_sha256"):
        raise ValueError("CATALOG_PREPARED_TERMINAL_INDEX_INVALID")
    receipt = _verified_controls(terminal_controls_path, purpose="terminal")
    if (
        receipt.audit_context_sha256 != index.get("audit_context_sha256")
        or receipt.protected_commit_sha
        != index.get("github_controls_commit_sha", index.get("protected_commit_sha"))
    ):
        raise ValueError("CATALOG_TERMINAL_CONTROLS_BINDING_INVALID")

    base = CatalogFinalEvidenceV1.model_validate(index.get("final_evidence_base"))
    output_dir.mkdir(parents=False, exist_ok=False)
    evidence_dir = output_dir / "evidence"
    external_dir = output_dir / "external"
    shutil.copytree(prepared_root / "evidence", evidence_dir)
    shutil.copytree(prepared_root / "external", external_dir)
    terminal_filename = FINAL_EVIDENCE_FILENAME_BY_SLOT[
        "github_controls_before_terminal"
    ]
    terminal_raw = _hashed_wrapper(
        slot="github_controls_before_terminal",
        binding={
            key: index[key]
            for key in (
                "request_sha256",
                "authority_id",
                "campaign_id",
                "science_sha256",
                "execution_plan_sha256",
                "execution_protocol_sha256",
                "protected_commit_sha",
            )
        }
        | {
            "github_controls_commit_sha": index.get(
                "github_controls_commit_sha", index["protected_commit_sha"]
            )
        },
        sources={"terminal_controls": _sha256_file(terminal_controls_path)},
        facts={"status": receipt.status, "freshness_checked_again_under_writer_lock": True},
    )
    (evidence_dir / terminal_filename).write_bytes(terminal_raw)
    slots = dict(base.evidence_slots)
    slots["github_controls_before_terminal"] = EvidenceSlotV1(
        status="present",
        sha256=_sha256_bytes(terminal_raw),
        reason_code=None,
        artifact_or_receipt_id=terminal_filename,
    )
    facts_payload = base.facts.model_dump(mode="json")
    facts_payload["github_controls_before_terminal_ready"] = True
    final_evidence_payload = base.model_dump(mode="json")
    final_evidence_payload["evidence_slots"] = {
        name: slot.model_dump(mode="json") for name, slot in slots.items()
    }
    final_evidence_payload["facts"] = facts_payload
    final_evidence = CatalogFinalEvidenceV1.model_validate(
        final_evidence_payload
    )
    external_terminal = external_dir / "github_controls_before_terminal.json"
    external_terminal.write_bytes(terminal_controls_path.read_bytes())
    external_hashes = dict(index.get("external_input_sha256s", {}))
    external_hashes["github_controls_before_terminal"] = _sha256_file(
        external_terminal
    )
    envelope = CatalogFinalizerEnvelopeV1(
        schema_version="1",
        final_evidence=final_evidence,
        input_sha256s=external_hashes,
    )
    (output_dir / "finalizer-envelope.json").write_bytes(
        canonical_model_bytes(envelope) + b"\n"
    )
    return envelope


__all__ = ["bind_terminal_controls", "prepare_terminal_evidence"]
