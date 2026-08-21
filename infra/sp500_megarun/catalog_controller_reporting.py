"""Truthful terminal decisions and bounded Spanish catalog-run summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from enum import Enum
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from .catalog_request_contract import FrozenModel, Sha256


SafeEvidenceId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,160}$"),
]
SafeLogicalId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,160}$"),
]

FINAL_EVIDENCE_SLOT_NAMES = (
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
    "github_controls_before_terminal",
    "admission_decision",
    "capacity_decision",
    "runtime",
    "prepared_data",
    "source_artifact_lineage",
    "expected_logical_unit_manifest",
    "expected_logical_unit_count",
    "completed_logical_unit_manifest",
    "completed_logical_unit_count",
    "recipe_results",
    "component_manifest",
    "component_contract_sha256",
    "component_store_seal",
    "attempt_reconciliation",
    "checkpoint_reconciliation",
    "recovery_history",
    "reduction_receipt",
    "scientific_audit_receipt",
    "equivalence_receipt",
    "performance_receipt",
    "actions_billing_and_zero_spend_budgets_receipt",
    "terminal_failure_receipt",
    "validation_opened",
    "locked_opened",
    "source_artifact_run_ids",
    "source_artifact_original_and_mirror_ids",
    "terminal_artifact_names",
)

FINAL_EVIDENCE_FILENAME_BY_SLOT = {
    name: f"catalog_{name}_v1.json" for name in FINAL_EVIDENCE_SLOT_NAMES
}

NON_RETRYABLE_EXECUTION_FAILURE_CODES = frozenset(
    {
        "SCIENTIFIC_ENGINE_DETERMINISTIC_FAILURE",
        "SCIENTIFIC_INPUT_DOMAIN_EXHAUSTED",
    }
)

FINALIZER_INPUT_NAMES = (
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

CLOSED_EVIDENCE_REASON_CODES = frozenset(
    {
        "NO_TERMINAL_FAILURE",
        "RUNTIME_PREPARATION_FAILED",
        "NOT_REACHED_AFTER_RUNTIME_FAILURE",
        "PRE_AUDIT_FAILED",
        "NO_TRUSTWORTHY_EVIDENCE",
        "UPSTREAM_BLOCKED",
        "UPSTREAM_FAILED",
        "SOURCE_ARTIFACT_UNAVAILABLE",
        "CONTROL_AUDIT_UNAVAILABLE",
        "CAPACITY_NOT_REACHED",
        "RESULT_NOT_REACHED",
    }
)

_REASON_EXPLANATIONS = {
    "CATALOG_SUCCESS": "Todas las pruebas obligatorias coinciden y cada estrategia aparece una sola vez.",
    "FINAL_AUTHORITY_MISMATCH": "La evidencia no pertenece a la autoridad reservada.",
    "FINAL_CAMPAIGN_MISMATCH": "La evidencia no pertenece a la campaña autorizada.",
    "FINAL_SCIENCE_MISMATCH": "La identidad científica no coincide con la autorizada.",
    "FINAL_EXECUTION_PLAN_MISMATCH": "El plan ejecutado no coincide con el plan sellado.",
    "FINAL_ARTIFACT_PLAN_MISMATCH": "El plan de artefactos no coincide con el sellado.",
    "FINAL_EXECUTION_PROTOCOL_MISMATCH": "El protocolo ejecutado no coincide con el protegido.",
    "FINAL_PROTECTED_COMMIT_MISMATCH": "La ejecución no está vinculada al commit protegido.",
    "FINAL_PROMPT_CHAIN_MISMATCH": "La cadena del prompt y su política no coincide.",
    "FINAL_REGISTRY_MISMATCH": "El registro de campaña no coincide con el protegido.",
    "FINAL_LOGICAL_UNIT_MISSING": "Falta al menos una estrategia prevista.",
    "FINAL_LOGICAL_UNIT_DUPLICATE": "Al menos una estrategia aparece más de una vez.",
    "FINAL_LOGICAL_UNIT_UNEXPECTED": "Aparece una estrategia que no estaba prevista.",
    "FINAL_ATTEMPT_CONFLICT": "Dos intentos válidos discrepan para la misma estrategia.",
    "FINAL_COMPONENT_MISSING": "Falta al menos un componente requerido.",
    "FINAL_COMPONENT_RECOMPUTED": "Un worker de estrategias recalculó un componente.",
    "FINAL_SOURCE_LINEAGE_INVALID": "No se pudo demostrar el origen exacto de los datos.",
    "FINAL_RUNTIME_INVALID": "El entorno de ejecución no quedó demostrado.",
    "FINAL_PREPARED_DATA_INVALID": "Los datos preparados no coinciden con el plan.",
    "FINAL_CHECKPOINT_CHAIN_INVALID": "La cadena de puntos de recuperación tiene un hueco o conflicto.",
    "FINAL_COMPONENT_STORE_UNSEALED": "El almacén de componentes no quedó sellado.",
    "FINAL_REDUCTION_INCOMPLETE": "La reducción final no cubre todo el trabajo previsto.",
    "FINAL_SCHEMA_INVALID": "Algún resultado no cumple su contrato cerrado.",
    "FINAL_SCIENTIFIC_AUDIT_FAILED": "La auditoría científica final no pasó.",
    "FINAL_EQUIVALENCE_FAILED": "La equivalencia con la referencia no pasó.",
    "FINAL_REGRESSION_FAILED": "La comprobación de regresiones no pasó.",
    "FINAL_VALIDATION_OPENED": "Se abrió el periodo de validación prohibido.",
    "FINAL_LOCKED_OPENED": "Se abrió el periodo bloqueado prohibido.",
    "FINAL_PAID_RUNNER_USED": "Se detectó uso de un runner no permitido.",
    "FINAL_PAID_ACTIONS_USAGE_FORBIDDEN": "Se detectó coste nuevo de GitHub Actions.",
    "FINAL_ZERO_SPEND_BUDGET_DRIFT": "Falta o cambió una protección de gasto cero.",
    "FINAL_LEDGER_INVALID": "La cadena de autoridad está dañada o no es verificable.",
    "FINAL_LEDGER_WRITER_INVALID": "No se pudo demostrar quién escribió la autoridad.",
    "FINAL_LEDGER_MIRROR_COVERAGE_INVALID": "Los espejos no cubren toda la cadena de autoridad.",
    "FINAL_AUTHORITY_LIFECYCLE_INVALID": "El historial completo de la autoridad no es fiable.",
    "FINAL_REQUEST_LIFECYCLE_INVALID": "El historial de la solicitud original no es fiable.",
    "FINAL_REQUEST_RECEIPT_WRITER_INVALID": "No se pudo demostrar quién escribió los recibos de solicitud.",
    "FINAL_REQUEST_RECEIPT_MIRROR_INVALID": "Los espejos no cubren los recibos de solicitud.",
    "FINAL_TAMPER_HISTORY_INVALID": "El inventario de incidentes o manipulaciones está incompleto.",
    "FINAL_GITHUB_CONTROLS_DRIFT": "Los controles de GitHub ya no coinciden con los protegidos.",
    "FINAL_REPEATED_FAILURE_LIMIT": "El mismo fallo alcanzó el límite de tres apariciones.",
    "FINAL_UNKNOWN_FAILURE_CODE": "El fallo no pertenece a la lista científica cerrada.",
    "RUNTIME_PREPARATION_FAILED": "La preparación del entorno falló antes de poder ejecutar estrategias.",
    "PRE_AUDIT_FAILED": "La comprobación previa no produjo evidencia fiable.",
    "NO_TRUSTWORTHY_EVIDENCE": "Falta evidencia fiable para cerrar el run.",
}


def _canonical_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class CatalogTerminalState(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class EvidenceSlotV1(FrozenModel):
    status: Literal["present", "missing", "not_reached"]
    sha256: Sha256 | None
    reason_code: str | None
    artifact_or_receipt_id: SafeEvidenceId | None

    @model_validator(mode="after")
    def _require_exact_shape(self) -> "EvidenceSlotV1":
        if self.status == "present":
            if (
                self.sha256 is None
                or self.artifact_or_receipt_id is None
                or self.reason_code is not None
            ):
                raise ValueError("FINAL_PRESENT_SLOT_INVALID")
        elif (
            self.sha256 is not None
            or self.artifact_or_receipt_id is not None
            or self.reason_code not in CLOSED_EVIDENCE_REASON_CODES
        ):
            raise ValueError("FINAL_ABSENT_SLOT_INVALID")
        return self


class CatalogPerformanceTelemetryV1(FrozenModel):
    strategies_per_minute: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
    )
    components_reused: int | None = Field(default=None, ge=0)
    components_computed_once: int | None = Field(default=None, ge=0)
    selective_retries: int | None = Field(default=None, ge=0)


class CatalogFinalEvidenceFactsV1(FrozenModel):
    authority_matches: bool
    campaign_matches: bool
    science_matches: bool
    execution_plan_matches: bool
    artifact_plan_matches: bool
    execution_protocol_matches: bool
    protected_commit_matches: bool
    prompt_chain_matches: bool
    registry_matches: bool
    expected_unit_ids: tuple[SafeLogicalId, ...]
    completed_unit_ids: tuple[SafeLogicalId, ...]
    conflicting_attempt_unit_ids: tuple[SafeLogicalId, ...]
    expected_component_ids: tuple[SafeLogicalId, ...]
    available_component_ids: tuple[SafeLogicalId, ...]
    component_recomputed_in_recipe_ids: tuple[SafeLogicalId, ...]
    source_lineage_valid: bool
    runtime_receipt_valid: bool
    prepared_data_valid: bool
    checkpoint_chain_valid: bool
    component_store_sealed: bool
    reducer_complete: bool
    schemas_valid: bool
    scientific_audit_passed: bool
    equivalence_passed: bool
    regression_passed: bool
    validation_opened: bool
    locked_opened: bool
    standard_runner_only: bool
    paid_runner_minutes: int = Field(ge=0)
    estimated_paid_actions_cost_microusd: int = Field(ge=0)
    zero_actions_spend_budget_verified: bool
    zero_actions_storage_budget_verified: bool
    zero_cache_storage_budget_verified: bool
    ledger_valid: bool
    ledger_writer_provenance_valid: bool
    ledger_mirror_coverage_valid: bool
    authority_lifecycle_complete: bool
    originating_request_intact: bool
    request_lifecycle_complete: bool
    request_receipt_writer_provenance_valid: bool
    request_receipt_mirror_coverage_valid: bool
    tamper_incident_inventory_complete: bool
    github_controls_before_reserve_ready: bool
    github_controls_before_terminal_ready: bool
    terminal_failure_code: str | None = Field(default=None, max_length=96)
    same_failure_fingerprint_count: int = Field(ge=0, le=3)
    work_preserved: Literal[
        "Componentes y resultados verificados siguen reutilizables."
    ]
    automatic_action: Literal[
        "Detención o cierre seguro según la evidencia verificada."
    ]

    @model_validator(mode="after")
    def _require_manifest_shapes(self) -> "CatalogFinalEvidenceFactsV1":
        for name, values in (
            ("expected units", self.expected_unit_ids),
            ("conflicting attempts", self.conflicting_attempt_unit_ids),
            ("expected components", self.expected_component_ids),
            ("available components", self.available_component_ids),
            (
                "recomputed components",
                self.component_recomputed_in_recipe_ids,
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name}")
        if not self.expected_unit_ids:
            raise ValueError("expected logical unit manifest is empty")
        return self


class CatalogFinalEvidenceV1(FrozenModel):
    schema_version: Literal["1"]
    request_sha256: Sha256
    authority_id: UUID
    campaign_id: Sha256
    science_sha256: Sha256
    execution_plan_sha256: Sha256
    artifact_plan_sha256: Sha256
    execution_protocol_sha256: Sha256
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    prompt_sha256: Sha256
    source_prompt_sha256: Sha256
    prompt_migration_sha256: Sha256
    prompt_policy_sha256: Sha256
    registry_sha256: Sha256
    evidence_slots: Mapping[str, EvidenceSlotV1]
    facts: CatalogFinalEvidenceFactsV1
    telemetry: CatalogPerformanceTelemetryV1 | None

    @field_validator("evidence_slots")
    @classmethod
    def _require_exact_slot_set(
        cls,
        value: Mapping[str, EvidenceSlotV1],
    ) -> Mapping[str, EvidenceSlotV1]:
        if set(value) != set(FINAL_EVIDENCE_SLOT_NAMES):
            raise ValueError("FINAL_EVIDENCE_SLOT_SET_INVALID")
        for name, slot in value.items():
            if (
                slot.status == "present"
                and slot.artifact_or_receipt_id
                != FINAL_EVIDENCE_FILENAME_BY_SLOT[name]
            ):
                raise ValueError("FINAL_EVIDENCE_SLOT_ID_INVALID")
        return dict(value)

    @model_validator(mode="after")
    def _require_terminal_failure_slot(self) -> "CatalogFinalEvidenceV1":
        slot = self.evidence_slots["terminal_failure_receipt"]
        if self.facts.terminal_failure_code is None:
            if not (
                slot.status == "not_reached"
                and slot.reason_code == "NO_TERMINAL_FAILURE"
            ):
                raise ValueError("FINAL_TERMINAL_FAILURE_SLOT_INVALID")
        elif slot.status != "present":
            raise ValueError("FINAL_TERMINAL_FAILURE_SLOT_INVALID")
        return self


class CatalogFinalizerEnvelopeV1(FrozenModel):
    schema_version: Literal["1"]
    final_evidence: CatalogFinalEvidenceV1
    input_sha256s: Mapping[str, Sha256]

    @field_validator("input_sha256s")
    @classmethod
    def _require_exact_input_set(
        cls,
        value: Mapping[str, Sha256],
    ) -> Mapping[str, Sha256]:
        if set(value) != set(FINALIZER_INPUT_NAMES):
            raise ValueError("CATALOG_FINALIZER_INPUT_SET_INVALID")
        return dict(value)


class CatalogTerminalDecisionV1(FrozenModel):
    schema_version: Literal["1"]
    state: CatalogTerminalState
    reason_code: str
    request_sha256: Sha256
    authority_id: UUID
    campaign_id: Sha256
    science_sha256: Sha256
    execution_plan_sha256: Sha256
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_unit_count: int = Field(ge=0)
    completed_unit_count: int = Field(ge=0)
    missing_unit_ids: tuple[SafeLogicalId, ...]
    duplicate_unit_ids: tuple[SafeLogicalId, ...]
    unexpected_unit_ids: tuple[SafeLogicalId, ...]
    conflicting_attempt_unit_ids: tuple[SafeLogicalId, ...]
    missing_component_ids: tuple[SafeLogicalId, ...]
    missing_evidence_reason_codes: tuple[str, ...]
    evidence_slots: Mapping[str, EvidenceSlotV1]
    authority_append_allowed: bool
    authority_terminal_record_created: Literal[False]
    request_comment_allowed: bool
    standalone_incident_artifact_required: bool
    human_summary: str
    terminal_decision_sha256: Sha256

    @model_validator(mode="after")
    def _require_decision_hash(self) -> "CatalogTerminalDecisionV1":
        payload = self.model_dump(
            mode="json",
            exclude={"terminal_decision_sha256"},
        )
        if _canonical_sha256(payload) != self.terminal_decision_sha256:
            raise ValueError("FINAL_TERMINAL_DECISION_HASH_INVALID")
        return self


def _format_decimal(value: float) -> str:
    rendered = f"{value:,.1f}"
    return rendered.replace(",", "_").replace(".", ",").replace("_", ".")


def _slot_is_present(evidence: CatalogFinalEvidenceV1, name: str) -> bool:
    return evidence.evidence_slots[name].status == "present"


def _first_gate_failure(
    evidence: CatalogFinalEvidenceV1,
    *,
    missing_units: tuple[str, ...],
    duplicate_units: tuple[str, ...],
    unexpected_units: tuple[str, ...],
    missing_components: tuple[str, ...],
) -> str | None:
    for name in FINAL_EVIDENCE_SLOT_NAMES:
        if name == "terminal_failure_receipt":
            continue
        slot = evidence.evidence_slots[name]
        if slot.status == "missing":
            return slot.reason_code
        if slot.status == "not_reached":
            return slot.reason_code

    facts = evidence.facts
    gates = (
        (facts.authority_matches, "FINAL_AUTHORITY_MISMATCH"),
        (facts.campaign_matches, "FINAL_CAMPAIGN_MISMATCH"),
        (facts.science_matches, "FINAL_SCIENCE_MISMATCH"),
        (facts.execution_plan_matches, "FINAL_EXECUTION_PLAN_MISMATCH"),
        (facts.artifact_plan_matches, "FINAL_ARTIFACT_PLAN_MISMATCH"),
        (facts.execution_protocol_matches, "FINAL_EXECUTION_PROTOCOL_MISMATCH"),
        (facts.protected_commit_matches, "FINAL_PROTECTED_COMMIT_MISMATCH"),
        (facts.prompt_chain_matches, "FINAL_PROMPT_CHAIN_MISMATCH"),
        (facts.registry_matches, "FINAL_REGISTRY_MISMATCH"),
        (not missing_units, "FINAL_LOGICAL_UNIT_MISSING"),
        (not duplicate_units, "FINAL_LOGICAL_UNIT_DUPLICATE"),
        (not unexpected_units, "FINAL_LOGICAL_UNIT_UNEXPECTED"),
        (not facts.conflicting_attempt_unit_ids, "FINAL_ATTEMPT_CONFLICT"),
        (not missing_components, "FINAL_COMPONENT_MISSING"),
        (
            not facts.component_recomputed_in_recipe_ids,
            "FINAL_COMPONENT_RECOMPUTED",
        ),
        (facts.source_lineage_valid, "FINAL_SOURCE_LINEAGE_INVALID"),
        (facts.runtime_receipt_valid, "FINAL_RUNTIME_INVALID"),
        (facts.prepared_data_valid, "FINAL_PREPARED_DATA_INVALID"),
        (facts.checkpoint_chain_valid, "FINAL_CHECKPOINT_CHAIN_INVALID"),
        (facts.component_store_sealed, "FINAL_COMPONENT_STORE_UNSEALED"),
        (facts.reducer_complete, "FINAL_REDUCTION_INCOMPLETE"),
        (facts.schemas_valid, "FINAL_SCHEMA_INVALID"),
        (facts.scientific_audit_passed, "FINAL_SCIENTIFIC_AUDIT_FAILED"),
        (facts.equivalence_passed, "FINAL_EQUIVALENCE_FAILED"),
        (facts.regression_passed, "FINAL_REGRESSION_FAILED"),
        (not facts.validation_opened, "FINAL_VALIDATION_OPENED"),
        (not facts.locked_opened, "FINAL_LOCKED_OPENED"),
        (
            facts.standard_runner_only and facts.paid_runner_minutes == 0,
            "FINAL_PAID_RUNNER_USED",
        ),
        (
            facts.estimated_paid_actions_cost_microusd == 0,
            "FINAL_PAID_ACTIONS_USAGE_FORBIDDEN",
        ),
        (
            facts.zero_actions_spend_budget_verified
            and facts.zero_actions_storage_budget_verified
            and facts.zero_cache_storage_budget_verified,
            "FINAL_ZERO_SPEND_BUDGET_DRIFT",
        ),
        (facts.ledger_valid, "FINAL_LEDGER_INVALID"),
        (facts.ledger_writer_provenance_valid, "FINAL_LEDGER_WRITER_INVALID"),
        (facts.ledger_mirror_coverage_valid, "FINAL_LEDGER_MIRROR_COVERAGE_INVALID"),
        (facts.authority_lifecycle_complete, "FINAL_AUTHORITY_LIFECYCLE_INVALID"),
        (
            facts.originating_request_intact and facts.request_lifecycle_complete,
            "FINAL_REQUEST_LIFECYCLE_INVALID",
        ),
        (
            facts.request_receipt_writer_provenance_valid,
            "FINAL_REQUEST_RECEIPT_WRITER_INVALID",
        ),
        (
            facts.request_receipt_mirror_coverage_valid,
            "FINAL_REQUEST_RECEIPT_MIRROR_INVALID",
        ),
        (facts.tamper_incident_inventory_complete, "FINAL_TAMPER_HISTORY_INVALID"),
        (
            facts.github_controls_before_reserve_ready
            and facts.github_controls_before_terminal_ready,
            "FINAL_GITHUB_CONTROLS_DRIFT",
        ),
        (
            facts.same_failure_fingerprint_count < 3,
            "FINAL_REPEATED_FAILURE_LIMIT",
        ),
    )
    return next((reason for passed, reason in gates if not passed), None)


def _render_summary(
    evidence: CatalogFinalEvidenceV1,
    *,
    state: CatalogTerminalState,
    reason_code: str,
    expected_count: int,
    completed_count: int,
) -> str:
    telemetry = evidence.telemetry
    if telemetry is None:
        components_reused = "no medido"
        components_computed = "no medido"
        retries = "no medido"
        speed = "no medido"
    else:
        components_reused = (
            str(telemetry.components_reused)
            if telemetry.components_reused is not None
            else "no medido"
        )
        components_computed = (
            str(telemetry.components_computed_once)
            if telemetry.components_computed_once is not None
            else "no medido"
        )
        retries = (
            str(telemetry.selective_retries)
            if telemetry.selective_retries is not None
            else "no medido"
        )
        speed = (
            f"{_format_decimal(telemetry.strategies_per_minute)} estrategias/min"
            if telemetry.strategies_per_minute is not None
            else "no medido"
        )
    facts = evidence.facts
    zero_cost_verified = (
        _slot_is_present(
            evidence,
            "actions_billing_and_zero_spend_budgets_receipt",
        )
        and facts.paid_runner_minutes == 0
        and facts.estimated_paid_actions_cost_microusd == 0
        and facts.zero_actions_spend_budget_verified
        and facts.zero_actions_storage_budget_verified
        and facts.zero_cache_storage_budget_verified
    )
    boundaries_verified = (
        _slot_is_present(evidence, "validation_opened")
        and _slot_is_present(evidence, "locked_opened")
        and not facts.validation_opened
        and not facts.locked_opened
    )
    lines = [
        "## Resultado del run de catálogo",
        "",
        f"- Estado: {state.value}",
        f"- Campaña: {str(evidence.campaign_id)[:12]}",
        f"- Autoridad: {evidence.authority_id}",
        f"- Commit protegido: {evidence.protected_commit_sha[:12]}",
        f"- Estrategias previstas: {expected_count}",
        f"- Estrategias verificadas: {completed_count}",
        f"- Componentes reutilizados: {components_reused}",
        f"- Componentes calculados una vez: {components_computed}",
        f"- Reintentos selectivos: {retries}",
        f"- Velocidad real: {speed}",
        (
            "- Coste nuevo de GitHub Actions: 0 verificado"
            if zero_cost_verified
            else "- Coste nuevo de GitHub Actions: no verificable"
        ),
        (
            "- Validación y locked abiertos: no verificado"
            if boundaries_verified
            else "- Validación y locked abiertos: no verificable"
        ),
        "",
    ]
    if state is CatalogTerminalState.SUCCESS:
        lines.extend(
            [
                "### Qué ocurrió",
                _REASON_EXPLANATIONS["CATALOG_SUCCESS"],
            ]
        )
    else:
        lines.extend(
            [
                "### Motivo exacto",
                f"{reason_code}: {_REASON_EXPLANATIONS.get(reason_code, 'La evidencia obligatoria no permite un cierre fiable.')}",
                "",
                "### Trabajo conservado",
                facts.work_preserved,
                "",
                "### Acción automática realizada",
                facts.automatic_action,
            ]
        )
    lines.extend(
        [
            "",
            "### Evidencia",
            f"- Solicitud: {evidence.request_sha256}",
            f"- Plan: {evidence.execution_plan_sha256}",
            f"- Ciencia: {evidence.science_sha256}",
        ]
    )
    return "\n".join(lines) + "\n"


def finalize_catalog_run(
    *,
    final_evidence: CatalogFinalEvidenceV1,
) -> CatalogTerminalDecisionV1:
    """Form one terminal decision without performing any external write."""

    evidence = CatalogFinalEvidenceV1.model_validate(
        final_evidence.model_dump(mode="json")
    )
    facts = evidence.facts
    expected = set(facts.expected_unit_ids)
    completed_counter = Counter(facts.completed_unit_ids)
    completed = set(completed_counter)
    missing_units = tuple(sorted(expected - completed))
    duplicate_units = tuple(
        sorted(unit for unit, count in completed_counter.items() if count > 1)
    )
    unexpected_units = tuple(sorted(completed - expected))
    missing_components = tuple(
        sorted(set(facts.expected_component_ids) - set(facts.available_component_ids))
    )
    reason_code = _first_gate_failure(
        evidence,
        missing_units=missing_units,
        duplicate_units=duplicate_units,
        unexpected_units=unexpected_units,
        missing_components=missing_components,
    )
    if reason_code is not None:
        state = CatalogTerminalState.BLOCKED
    elif facts.terminal_failure_code is not None:
        if facts.terminal_failure_code in NON_RETRYABLE_EXECUTION_FAILURE_CODES:
            state = CatalogTerminalState.FAILED
            reason_code = facts.terminal_failure_code
        else:
            state = CatalogTerminalState.BLOCKED
            reason_code = "FINAL_UNKNOWN_FAILURE_CODE"
    else:
        state = CatalogTerminalState.SUCCESS
        reason_code = "CATALOG_SUCCESS"

    ledger_safe = (
        facts.ledger_valid
        and facts.ledger_writer_provenance_valid
        and facts.ledger_mirror_coverage_valid
        and facts.authority_lifecycle_complete
        and facts.tamper_incident_inventory_complete
    )
    request_safe = (
        facts.originating_request_intact
        and facts.request_lifecycle_complete
        and facts.request_receipt_writer_provenance_valid
        and facts.request_receipt_mirror_coverage_valid
        and facts.tamper_incident_inventory_complete
    )
    missing_reasons = tuple(
        dict.fromkeys(
            slot.reason_code
            for name in FINAL_EVIDENCE_SLOT_NAMES
            if (slot := evidence.evidence_slots[name]).status == "missing"
            and slot.reason_code is not None
        )
    )
    human_summary = _render_summary(
        evidence,
        state=state,
        reason_code=reason_code,
        expected_count=len(expected),
        completed_count=len(completed & expected),
    )
    payload = {
        "schema_version": "1",
        "state": state,
        "reason_code": reason_code,
        "request_sha256": evidence.request_sha256,
        "authority_id": evidence.authority_id,
        "campaign_id": evidence.campaign_id,
        "science_sha256": evidence.science_sha256,
        "execution_plan_sha256": evidence.execution_plan_sha256,
        "protected_commit_sha": evidence.protected_commit_sha,
        "expected_unit_count": len(expected),
        "completed_unit_count": len(completed & expected),
        "missing_unit_ids": missing_units,
        "duplicate_unit_ids": duplicate_units,
        "unexpected_unit_ids": unexpected_units,
        "conflicting_attempt_unit_ids": facts.conflicting_attempt_unit_ids,
        "missing_component_ids": missing_components,
        "missing_evidence_reason_codes": missing_reasons,
        "evidence_slots": evidence.evidence_slots,
        "authority_append_allowed": ledger_safe,
        "authority_terminal_record_created": False,
        "request_comment_allowed": request_safe,
        "standalone_incident_artifact_required": not ledger_safe,
        "human_summary": human_summary,
    }
    hash_payload = {
        key: (
            value.model_dump(mode="json")
            if hasattr(value, "model_dump")
            else value
        )
        for key, value in payload.items()
    }
    return CatalogTerminalDecisionV1(
        **payload,
        terminal_decision_sha256=_canonical_sha256(hash_payload),
    )


__all__ = [
    "CLOSED_EVIDENCE_REASON_CODES",
    "FINAL_EVIDENCE_FILENAME_BY_SLOT",
    "FINAL_EVIDENCE_SLOT_NAMES",
    "FINALIZER_INPUT_NAMES",
    "NON_RETRYABLE_EXECUTION_FAILURE_CODES",
    "CatalogFinalEvidenceFactsV1",
    "CatalogFinalEvidenceV1",
    "CatalogFinalizerEnvelopeV1",
    "CatalogPerformanceTelemetryV1",
    "CatalogTerminalDecisionV1",
    "CatalogTerminalState",
    "EvidenceSlotV1",
    "finalize_catalog_run",
]
