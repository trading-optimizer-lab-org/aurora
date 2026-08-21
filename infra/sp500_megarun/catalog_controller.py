"""Pure fail-closed decision controller for autonomous catalog runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import Field, field_validator, model_validator

from .catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityRecordV1,
    VerifiedAuthorityLedgerV1,
    select_campaign_authority,
)
from .catalog_campaign_registry import CatalogCampaignEntryV1
from .catalog_request_contract import CatalogRunRequestV1, FrozenModel, Sha256


CATALOG_AUTHORITY_NAMESPACE = UUID("5e7dd0d2-7950-5c4f-a80b-35a2f283e134")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_PROMPT_RULE_IDS = tuple(f"CAT-{index:03d}" for index in range(1, 26))
_ACTIVE_STATES = frozenset(
    {
        AuthorityState.RESERVED,
        AuthorityState.RUNNING,
        AuthorityState.RECOVERING,
        AuthorityState.WAITING_RETRY,
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


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


class ControllerOutcome(str, Enum):
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    ADMITTED = "admitted"
    ADOPTED = "adopted"


class _CatalogEvidenceV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    status: Literal["ready", "blocked"]
    observed_at: datetime
    source_sha256: Sha256
    content_sha256: Sha256
    receipt_sha256: Sha256
    reason_codes: tuple[str, ...] = ()

    @field_validator("observed_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _require_status_reason_consistency(self) -> "_CatalogEvidenceV1":
        if self.status == "ready" and self.reason_codes:
            raise ValueError("ready evidence cannot contain blocking reasons")
        if self.status == "blocked" and not self.reason_codes:
            raise ValueError("blocked evidence requires a reason")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("evidence reasons must be unique")
        return self


class CatalogPromptPolicyEvidenceV1(_CatalogEvidenceV1):
    applicable_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    prompt_sha256: Sha256
    prompt_policy_sha256: Sha256
    prompt_bytes_verified: bool
    prompt_policy_schema_valid: bool
    enforced_policy_rule_ids: tuple[str, ...]


class CatalogProtectedHeadEvidenceV1(_CatalogEvidenceV1):
    current_protected_head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    applicable_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    original_bound_commit_sha: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    original_commit_reachable_from_protected_history: bool
    execution_protocol_compatible: bool
    protected_ref_verified: bool


class CatalogCampaignDefinitionEvidenceV1(_CatalogEvidenceV1):
    applicable_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    campaign_key: str
    registry_entry_resolved: bool
    safe_paths_verified: bool
    manifest_schema_valid: bool
    repository_rehash_complete: bool
    campaign_registry_sha256: Sha256
    campaign_definition_manifest_sha256: Sha256
    campaign_definition_sha256: Sha256
    campaign_definition_rehash_receipt_sha256: Sha256


class CatalogAuthorityAnchorEvidenceV1(_CatalogEvidenceV1):
    identity_verified: bool
    live_variable_matches: bool
    ledger_integrity_verified: bool
    ledger_sha256: Sha256
    authority_anchor_evidence_sha256: Sha256


class CatalogGithubControlsEvidenceV1(_CatalogEvidenceV1):
    controls_verified: bool
    production_environment_verified: bool
    admin_credential_exposed: bool
    requester_credential_exposed: bool
    auditor_credential_exposed: bool
    standard_free_runner_only: bool
    paid_runner_minutes: Annotated[int, Field(ge=0)]
    estimated_paid_actions_cost: Annotated[int, Field(ge=0)]
    zero_actions_spend_budget_verified: bool
    zero_actions_storage_budget_verified: bool
    zero_cache_storage_budget_verified: bool
    cache_limit_gb: Annotated[int, Field(ge=0)]
    cache_retention_days: Annotated[int, Field(ge=0)]
    validation_opened: bool
    locked_opened: bool


class CatalogScienceAdmissionEvidenceV1(_CatalogEvidenceV1):
    scientific_contract_sha256: Sha256
    optimization_admission_verified: bool
    science_identity_verified: bool
    data_contract_verified: bool
    feature_contract_verified: bool
    metric_contract_verified: bool
    cache_contract_verified: bool
    component_contract_verified: bool


class CatalogSourceArtifactsEvidenceV1(_CatalogEvidenceV1):
    artifacts_exist: bool
    hashes_bound: bool
    runtime_artifact_fresh: bool
    unexpired_or_verified_mirror: bool
    immutable: bool
    source_artifact_manifest_sha256: Sha256
    artifact_plan_sha256: Sha256


class CatalogCapacityAdmissionEvidenceV1(_CatalogEvidenceV1):
    capacity_known: bool
    temporarily_unavailable: bool
    compatible_qualified_ceiling: Annotated[int, Field(ge=1, le=360)]
    current_safe_free_capacity: Annotated[int, Field(ge=0, le=360)]
    selected_workers: Annotated[int, Field(ge=0, le=360)]
    standard_runner_only: bool
    paid_runner_minutes: Annotated[int, Field(ge=0)]
    estimated_paid_actions_cost: Annotated[int, Field(ge=0)]
    artifact_storage_headroom_proven: bool
    cache_storage_headroom_proven: bool
    resource_margin_verified: bool
    compatible_safe_floor_used: bool
    retry_not_before: datetime | None
    capacity_receipt_sha256: Sha256

    @field_validator("retry_not_before")
    @classmethod
    def _require_aware_retry(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value)

    @model_validator(mode="after")
    def _require_availability_shape(self) -> "CatalogCapacityAdmissionEvidenceV1":
        if self.temporarily_unavailable and self.selected_workers != 0:
            raise ValueError("temporary unavailability must select zero workers")
        if not self.temporarily_unavailable and self.selected_workers == 0:
            raise ValueError("available capacity must select workers")
        return self


class CatalogRequestQueueEvidenceV1(_CatalogEvidenceV1):
    complete: bool
    stable: bool
    current_issue_number: Annotated[int, Field(ge=1)]
    eligible_open_issue_numbers: tuple[int, ...]
    request_queue_snapshot_sha256: Sha256

    @model_validator(mode="after")
    def _require_canonical_issue_order(self) -> "CatalogRequestQueueEvidenceV1":
        if any(isinstance(value, bool) or value < 1 for value in self.eligible_open_issue_numbers):
            raise ValueError("invalid queue issue number")
        if tuple(sorted(set(self.eligible_open_issue_numbers))) != (
            self.eligible_open_issue_numbers
        ):
            raise ValueError("queue issue numbers must be sorted and unique")
        return self


class CatalogSealedInputsV1(FrozenModel):
    engine_id: Literal["optimized_catalog_v1"]
    request_sha256: Sha256
    campaign_id: Sha256
    science_sha256: Sha256
    execution_plan_sha256: Sha256
    execution_protocol_sha256: Sha256
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    prompt_sha256: Sha256
    prompt_policy_sha256: Sha256
    campaign_registry_sha256: Sha256
    campaign_definition_manifest_sha256: Sha256
    campaign_definition_sha256: Sha256
    campaign_definition_rehash_receipt_sha256: Sha256
    authority_id: UUID
    authority_anchor_evidence_sha256: Sha256
    github_controls_receipt_sha256: Sha256
    capacity_receipt_sha256: Sha256
    source_artifact_manifest_sha256: Sha256
    artifact_plan_sha256: Sha256


class CatalogControllerDecisionV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    outcome: ControllerOutcome
    reason_code: str
    failed_gate_codes: tuple[str, ...]
    request_sha256: Sha256
    campaign_id: Sha256 | None
    science_sha256: Sha256 | None
    execution_plan_sha256: Sha256 | None
    execution_protocol_sha256: Sha256 | None
    authority_id: UUID | None
    should_create_authority: bool
    should_schedule_compute: bool
    should_resume_existing: bool
    should_retry_delivery: bool
    retry_not_before: datetime | None
    sealed_inputs: CatalogSealedInputsV1 | None
    decision_sha256: Sha256

    @field_validator("retry_not_before")
    @classmethod
    def _require_aware_retry(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value)

    @model_validator(mode="after")
    def _verify_decision(self) -> "CatalogControllerDecisionV1":
        payload = self.model_dump(mode="json", exclude={"decision_sha256"})
        if self.decision_sha256 != _canonical_sha256(payload):
            raise ValueError("CATALOG_CONTROLLER_DECISION_HASH_INVALID")
        if len(set(self.failed_gate_codes)) != len(self.failed_gate_codes):
            raise ValueError("CATALOG_CONTROLLER_DUPLICATE_GATE")
        if self.outcome is ControllerOutcome.BLOCKED:
            if not self.failed_gate_codes or self.reason_code != self.failed_gate_codes[0]:
                raise ValueError("CATALOG_CONTROLLER_BLOCKED_SHAPE_INVALID")
        elif self.failed_gate_codes:
            raise ValueError("nonblocked decision cannot contain failed gates")
        if self.outcome in {ControllerOutcome.BLOCKED, ControllerOutcome.DEFERRED}:
            if (
                self.should_create_authority
                or self.should_schedule_compute
                or self.should_resume_existing
                or self.sealed_inputs is not None
            ):
                raise ValueError("CATALOG_CONTROLLER_NONEXECUTING_SHAPE_INVALID")
        if self.outcome is ControllerOutcome.ADMITTED and (
            not self.should_create_authority
            or not self.should_schedule_compute
            or self.should_resume_existing
            or self.sealed_inputs is None
        ):
            raise ValueError("CATALOG_CONTROLLER_ADMITTED_SHAPE_INVALID")
        if self.outcome is ControllerOutcome.ADOPTED:
            if self.should_create_authority:
                raise ValueError("CATALOG_CONTROLLER_ADOPTED_SHAPE_INVALID")
            if self.should_resume_existing != self.should_schedule_compute:
                raise ValueError("CATALOG_CONTROLLER_ADOPTED_SHAPE_INVALID")
            if self.should_resume_existing != (self.sealed_inputs is not None):
                raise ValueError("CATALOG_CONTROLLER_ADOPTED_SHAPE_INVALID")
        if self.outcome is ControllerOutcome.DEFERRED:
            if not self.should_retry_delivery or self.retry_not_before is None:
                raise ValueError("CATALOG_CONTROLLER_DEFERRED_SHAPE_INVALID")
        elif self.should_retry_delivery or self.retry_not_before is not None:
            raise ValueError("CATALOG_CONTROLLER_RETRY_SHAPE_INVALID")
        return self


def catalog_campaign_id(*, campaign_key: str, scientific_contract_sha256: str) -> str:
    payload = {
        "schema_version": "catalog-campaign-id-v1",
        "campaign_key": campaign_key,
        "scientific_contract_sha256": scientific_contract_sha256,
    }
    return _canonical_sha256(payload)


def catalog_execution_plan_sha256(
    *, campaign_id: str, operational_plan: Mapping[str, object]
) -> str:
    return _canonical_sha256(
        {
            "schema_version": "catalog-execution-plan-v1",
            "campaign_id": campaign_id,
            "operational_plan": operational_plan,
        }
    )


def catalog_authority_id(*, request_sha256: str, campaign_id: str) -> UUID:
    return uuid5(
        CATALOG_AUTHORITY_NAMESPACE,
        f"catalog-authority-v1:{request_sha256}:{campaign_id}",
    )


def _append_unique(values: list[str], code: str) -> None:
    if code not in values:
        values.append(code)


def _append_status_failures(
    values: list[str],
    evidence: _CatalogEvidenceV1,
    fallback: str,
) -> None:
    if evidence.status == "blocked":
        for code in evidence.reason_codes or (fallback,):
            _append_unique(values, code)


def _decision(
    *,
    outcome: ControllerOutcome,
    reason_code: str,
    request_sha256: str,
    campaign_id: str | None,
    science_sha256: str | None,
    execution_plan_sha256: str | None,
    execution_protocol_sha256: str | None,
    authority_id: UUID | None,
    failed_gate_codes: Sequence[str] = (),
    should_create_authority: bool = False,
    should_schedule_compute: bool = False,
    should_resume_existing: bool = False,
    should_retry_delivery: bool = False,
    retry_not_before: datetime | None = None,
    sealed_inputs: CatalogSealedInputsV1 | None = None,
) -> CatalogControllerDecisionV1:
    payload: dict[str, object] = {
        "schema_version": "1",
        "outcome": outcome.value,
        "reason_code": reason_code,
        "failed_gate_codes": list(failed_gate_codes),
        "request_sha256": request_sha256,
        "campaign_id": campaign_id,
        "science_sha256": science_sha256,
        "execution_plan_sha256": execution_plan_sha256,
        "execution_protocol_sha256": execution_protocol_sha256,
        "authority_id": str(authority_id) if authority_id is not None else None,
        "should_create_authority": should_create_authority,
        "should_schedule_compute": should_schedule_compute,
        "should_resume_existing": should_resume_existing,
        "should_retry_delivery": should_retry_delivery,
        "retry_not_before": (
            _aware_utc(retry_not_before).isoformat().replace("+00:00", "Z")
            if retry_not_before is not None
            else None
        ),
        "sealed_inputs": (
            sealed_inputs.model_dump(mode="json") if sealed_inputs is not None else None
        ),
    }
    payload["decision_sha256"] = _canonical_sha256(payload)
    return CatalogControllerDecisionV1.model_validate(payload)


def _latest_authorities(
    ledger: VerifiedAuthorityLedgerV1,
) -> tuple[CatalogAuthorityRecordV1, ...]:
    latest: dict[UUID, CatalogAuthorityRecordV1] = {}
    for record in ledger.records:
        latest[record.authority_id] = record
    return tuple(latest.values())


def _blocked_decision(
    *,
    failures: Sequence[str],
    request_sha256: str,
    campaign_id: str | None,
    science_sha256: str | None,
    execution_plan_sha256: str | None,
    execution_protocol_sha256: str | None,
    authority_id: UUID | None,
) -> CatalogControllerDecisionV1:
    ordered = tuple(dict.fromkeys(failures))
    return _decision(
        outcome=ControllerOutcome.BLOCKED,
        reason_code=ordered[0],
        failed_gate_codes=ordered,
        request_sha256=request_sha256,
        campaign_id=campaign_id,
        science_sha256=science_sha256,
        execution_plan_sha256=execution_plan_sha256,
        execution_protocol_sha256=execution_protocol_sha256,
        authority_id=authority_id,
    )


def decide_catalog_run(
    *,
    request: CatalogRunRequestV1,
    request_issue_number: int,
    request_issue_author: str,
    allowed_request_actors: Sequence[str],
    observed_request_sha256: str,
    registry_entry: CatalogCampaignEntryV1 | None,
    prompt_evidence: CatalogPromptPolicyEvidenceV1,
    campaign_definition_evidence: CatalogCampaignDefinitionEvidenceV1,
    authority_anchor_evidence: CatalogAuthorityAnchorEvidenceV1,
    protected_head_evidence: CatalogProtectedHeadEvidenceV1,
    github_controls_evidence: CatalogGithubControlsEvidenceV1,
    science_evidence: CatalogScienceAdmissionEvidenceV1,
    source_artifacts_evidence: CatalogSourceArtifactsEvidenceV1,
    capacity_evidence: CatalogCapacityAdmissionEvidenceV1,
    request_queue_evidence: CatalogRequestQueueEvidenceV1,
    ledger: VerifiedAuthorityLedgerV1,
    operational_plan: Mapping[str, object],
    execution_protocol_sha256: str,
    verified_github_now: datetime,
    active_owner_run: bool,
) -> CatalogControllerDecisionV1:
    request = CatalogRunRequestV1.model_validate(request.model_dump(mode="json"))
    prompt_evidence = CatalogPromptPolicyEvidenceV1.model_validate(
        prompt_evidence.model_dump(mode="json")
    )
    campaign_definition_evidence = CatalogCampaignDefinitionEvidenceV1.model_validate(
        campaign_definition_evidence.model_dump(mode="json")
    )
    authority_anchor_evidence = CatalogAuthorityAnchorEvidenceV1.model_validate(
        authority_anchor_evidence.model_dump(mode="json")
    )
    protected_head_evidence = CatalogProtectedHeadEvidenceV1.model_validate(
        protected_head_evidence.model_dump(mode="json")
    )
    github_controls_evidence = CatalogGithubControlsEvidenceV1.model_validate(
        github_controls_evidence.model_dump(mode="json")
    )
    science_evidence = CatalogScienceAdmissionEvidenceV1.model_validate(
        science_evidence.model_dump(mode="json")
    )
    source_artifacts_evidence = CatalogSourceArtifactsEvidenceV1.model_validate(
        source_artifacts_evidence.model_dump(mode="json")
    )
    capacity_evidence = CatalogCapacityAdmissionEvidenceV1.model_validate(
        capacity_evidence.model_dump(mode="json")
    )
    request_queue_evidence = CatalogRequestQueueEvidenceV1.model_validate(
        request_queue_evidence.model_dump(mode="json")
    )
    ledger = VerifiedAuthorityLedgerV1.model_validate(ledger.model_dump(mode="json"))
    if registry_entry is not None:
        registry_entry = CatalogCampaignEntryV1.model_validate(
            registry_entry.model_dump(mode="json")
        )
    now = _aware_utc(verified_github_now)

    failures: list[str] = []
    request_sha256 = request.request_sha256
    science_sha256 = science_evidence.scientific_contract_sha256
    campaign_id = catalog_campaign_id(
        campaign_key=request.campaign_key,
        scientific_contract_sha256=science_sha256,
    )
    try:
        execution_plan_sha256 = catalog_execution_plan_sha256(
            campaign_id=campaign_id,
            operational_plan=operational_plan,
        )
    except (TypeError, ValueError):
        execution_plan_sha256 = None
        _append_unique(failures, "CATALOG_EXECUTION_PLAN_INVALID")

    # 1. Exact request grammar, actor, body binding, and authorization.
    if request_issue_author not in allowed_request_actors or not request_issue_author.endswith(
        "[bot]"
    ):
        _append_unique(failures, "CATALOG_REQUEST_ACTOR_NOT_ALLOWED")
    if observed_request_sha256 != request_sha256:
        _append_unique(failures, "CATALOG_REQUEST_SHA_MISMATCH")
    if request_issue_number < 1:
        _append_unique(failures, "CATALOG_REQUEST_ISSUE_INVALID")

    # 2. Prompt bytes, policy, and all migrated rules at the applicable commit.
    _append_status_failures(failures, prompt_evidence, "CATALOG_PROMPT_POLICY_INVALID")
    if request.prompt_sha256 != prompt_evidence.prompt_sha256:
        _append_unique(failures, "CATALOG_PROMPT_HASH_MISMATCH")
    if not prompt_evidence.prompt_bytes_verified:
        _append_unique(failures, "CATALOG_PROMPT_BYTES_UNVERIFIED")
    if not prompt_evidence.prompt_policy_schema_valid:
        _append_unique(failures, "CATALOG_PROMPT_POLICY_INVALID")
    if prompt_evidence.enforced_policy_rule_ids != _EXPECTED_PROMPT_RULE_IDS:
        _append_unique(failures, "CATALOG_PROMPT_POLICY_MAPPINGS_INCOMPLETE")
    if prompt_evidence.applicable_commit_sha != protected_head_evidence.applicable_commit_sha:
        _append_unique(failures, "CATALOG_PROMPT_COMMIT_MISMATCH")

    # 3. Closed registry and repository-rebuilt campaign definition.
    if (
        registry_entry is None
        or not registry_entry.active
        or registry_entry.campaign_key != request.campaign_key
    ):
        _append_unique(failures, "CATALOG_CAMPAIGN_NOT_REGISTERED")
    _append_status_failures(
        failures,
        campaign_definition_evidence,
        "CATALOG_CAMPAIGN_DEFINITION_INVALID",
    )
    if (
        campaign_definition_evidence.campaign_key != request.campaign_key
        or not campaign_definition_evidence.registry_entry_resolved
    ):
        _append_unique(failures, "CATALOG_CAMPAIGN_NOT_REGISTERED")
    if not campaign_definition_evidence.safe_paths_verified:
        _append_unique(failures, "CATALOG_CAMPAIGN_PATHS_UNSAFE")
    if not campaign_definition_evidence.manifest_schema_valid:
        _append_unique(failures, "CATALOG_CAMPAIGN_MANIFEST_INVALID")
    if not campaign_definition_evidence.repository_rehash_complete:
        _append_unique(failures, "CATALOG_CAMPAIGN_REHASH_INCOMPLETE")
    if (
        request.campaign_definition_sha256
        != campaign_definition_evidence.campaign_definition_sha256
    ):
        _append_unique(failures, "CATALOG_CAMPAIGN_DEFINITION_MISMATCH")
    if (
        campaign_definition_evidence.applicable_commit_sha
        != protected_head_evidence.applicable_commit_sha
    ):
        _append_unique(failures, "CATALOG_CAMPAIGN_DEFINITION_COMMIT_MISMATCH")

    # 4. Protected authority anchor and verified append-only ledger.
    _append_status_failures(
        failures,
        authority_anchor_evidence,
        "CATALOG_AUTHORITY_ANCHOR_INVALID",
    )
    if not authority_anchor_evidence.identity_verified or not (
        authority_anchor_evidence.live_variable_matches
    ):
        _append_unique(failures, "CATALOG_AUTHORITY_ANCHOR_INVALID")
    if not authority_anchor_evidence.ledger_integrity_verified:
        _append_unique(failures, "CATALOG_LEDGER_INVALID")
    if authority_anchor_evidence.ledger_sha256 != ledger.ledger_sha256:
        _append_unique(failures, "CATALOG_LEDGER_INVALID")

    try:
        matching_authority = select_campaign_authority(ledger, campaign_id)
    except ValueError:
        matching_authority = None
        _append_unique(failures, "CATALOG_LEDGER_INVALID")

    # 5. New work binds HEAD; recovery binds the original reachable commit.
    _append_status_failures(
        failures,
        protected_head_evidence,
        "CATALOG_COMMIT_EVIDENCE_INVALID",
    )
    effective_protocol_sha256 = execution_protocol_sha256
    if not _SHA256.fullmatch(execution_protocol_sha256):
        _append_unique(failures, "CATALOG_EXECUTION_PROTOCOL_INVALID")
    if not protected_head_evidence.protected_ref_verified:
        _append_unique(failures, "CATALOG_COMMIT_NOT_PROTECTED_HEAD")
    if matching_authority is None:
        if (
            not _COMMIT_SHA.fullmatch(protected_head_evidence.current_protected_head_sha)
            or protected_head_evidence.applicable_commit_sha
            != protected_head_evidence.current_protected_head_sha
        ):
            _append_unique(failures, "CATALOG_COMMIT_NOT_PROTECTED_HEAD")
    else:
        effective_protocol_sha256 = matching_authority.execution_protocol_sha256
        if (
            protected_head_evidence.original_bound_commit_sha
            != matching_authority.protected_commit_sha
            or protected_head_evidence.applicable_commit_sha
            != matching_authority.protected_commit_sha
        ):
            _append_unique(failures, "CATALOG_BOUND_COMMIT_MISMATCH")
        if not protected_head_evidence.original_commit_reachable_from_protected_history:
            _append_unique(failures, "CATALOG_BOUND_COMMIT_UNREACHABLE")
        if not protected_head_evidence.execution_protocol_compatible:
            _append_unique(failures, "CATALOG_EXECUTION_PROTOCOL_INCOMPATIBLE")

    # 6. Live controls, credential separation, and audit freshness.
    _append_status_failures(
        failures,
        github_controls_evidence,
        "CATALOG_GITHUB_CONTROLS_INVALID",
    )
    audit_age = now - github_controls_evidence.observed_at
    audit_expired = audit_age > timedelta(seconds=300)
    if audit_age < -timedelta(seconds=30):
        _append_unique(failures, "CATALOG_GITHUB_AUDIT_TIME_INVALID")
        audit_expired = False
    if not github_controls_evidence.controls_verified or not (
        github_controls_evidence.production_environment_verified
    ):
        _append_unique(failures, "CATALOG_GITHUB_CONTROLS_INVALID")
    if github_controls_evidence.admin_credential_exposed:
        _append_unique(failures, "AGENT_ADMIN_CREDENTIAL_EXPOSED")
    if github_controls_evidence.requester_credential_exposed:
        _append_unique(failures, "AGENT_REQUESTER_CREDENTIAL_EXPOSED")
    if github_controls_evidence.auditor_credential_exposed:
        _append_unique(failures, "AGENT_AUDITOR_CREDENTIAL_EXPOSED")
    if (
        not github_controls_evidence.standard_free_runner_only
        or github_controls_evidence.paid_runner_minutes != 0
        or github_controls_evidence.estimated_paid_actions_cost != 0
    ):
        _append_unique(failures, "CATALOG_FREE_CAPACITY_REQUIRED")
    if not github_controls_evidence.zero_actions_spend_budget_verified:
        _append_unique(failures, "CATALOG_ZERO_SPEND_BUDGET_REQUIRED")
    if not github_controls_evidence.zero_actions_storage_budget_verified:
        _append_unique(failures, "CATALOG_ZERO_ACTIONS_STORAGE_BUDGET_REQUIRED")
    if not github_controls_evidence.zero_cache_storage_budget_verified:
        _append_unique(failures, "CATALOG_ZERO_CACHE_STORAGE_BUDGET_REQUIRED")
    if (
        github_controls_evidence.cache_limit_gb != 10
        or github_controls_evidence.cache_retention_days != 90
    ):
        _append_unique(failures, "CATALOG_FREE_CACHE_CONTROLS_REQUIRED")

    # 7. Validation and locked periods stay closed.
    if github_controls_evidence.validation_opened:
        _append_unique(failures, "CATALOG_VALIDATION_MUST_REMAIN_CLOSED")
    if github_controls_evidence.locked_opened:
        _append_unique(failures, "CATALOG_LOCKED_MUST_REMAIN_CLOSED")

    # 8. Scientific, data, metric, cache, and component contracts.
    _append_status_failures(
        failures,
        science_evidence,
        "CATALOG_SCIENCE_EVIDENCE_INVALID",
    )
    if not science_evidence.optimization_admission_verified:
        _append_unique(failures, "CATALOG_OPTIMIZATION_ADMISSION_FAILED")
    if not science_evidence.science_identity_verified:
        _append_unique(failures, "CATALOG_SCIENCE_IDENTITY_MISMATCH")
    if not science_evidence.data_contract_verified:
        _append_unique(failures, "CATALOG_DATA_CONTRACT_MISMATCH")
    if not science_evidence.feature_contract_verified:
        _append_unique(failures, "CATALOG_FEATURE_CONTRACT_MISMATCH")
    if not science_evidence.metric_contract_verified:
        _append_unique(failures, "CATALOG_METRIC_CONTRACT_MISMATCH")
    if not science_evidence.cache_contract_verified:
        _append_unique(failures, "CATALOG_CACHE_CONTRACT_MISMATCH")
    if not science_evidence.component_contract_verified:
        _append_unique(failures, "CATALOG_COMPONENT_CONTRACT_MISMATCH")

    # 9. Exact immutable source artifacts or their identity-preserving mirrors.
    _append_status_failures(
        failures,
        source_artifacts_evidence,
        "CATALOG_SOURCE_ARTIFACTS_INVALID",
    )
    if not source_artifacts_evidence.artifacts_exist:
        _append_unique(failures, "CATALOG_SOURCE_ARTIFACT_MISSING")
    if not source_artifacts_evidence.hashes_bound:
        _append_unique(failures, "CATALOG_SOURCE_ARTIFACT_HASH_MISMATCH")
    if not source_artifacts_evidence.runtime_artifact_fresh:
        _append_unique(failures, "CATALOG_RUNTIME_ARTIFACT_STALE")
    if not source_artifacts_evidence.unexpired_or_verified_mirror:
        _append_unique(failures, "CATALOG_SOURCE_ARTIFACT_UNAVAILABLE")
    if not source_artifacts_evidence.immutable:
        _append_unique(failures, "CATALOG_SOURCE_ARTIFACT_MUTABLE")

    authority_id = (
        matching_authority.authority_id
        if matching_authority is not None
        else catalog_authority_id(
            request_sha256=request_sha256,
            campaign_id=campaign_id,
        )
    )
    if failures:
        return _blocked_decision(
            failures=failures,
            request_sha256=request_sha256,
            campaign_id=campaign_id,
            science_sha256=science_sha256,
            execution_plan_sha256=execution_plan_sha256,
            execution_protocol_sha256=effective_protocol_sha256,
            authority_id=authority_id,
        )
    if audit_expired:
        return _decision(
            outcome=ControllerOutcome.DEFERRED,
            reason_code="DEFERRED_ADMISSION_AUDIT_EXPIRED",
            request_sha256=request_sha256,
            campaign_id=campaign_id,
            science_sha256=science_sha256,
            execution_plan_sha256=execution_plan_sha256,
            execution_protocol_sha256=effective_protocol_sha256,
            authority_id=authority_id,
            should_retry_delivery=True,
            retry_not_before=now + timedelta(seconds=30),
        )

    # 10. Idempotent adoption and terminal-result reuse precede capacity.
    resume_existing = False
    if matching_authority is not None:
        if matching_authority.state is AuthorityState.SUCCESS:
            return _decision(
                outcome=ControllerOutcome.ADOPTED,
                reason_code="CATALOG_SUCCESS_ALREADY_EXISTS",
                request_sha256=request_sha256,
                campaign_id=campaign_id,
                science_sha256=science_sha256,
                execution_plan_sha256=matching_authority.execution_plan_sha256,
                execution_protocol_sha256=effective_protocol_sha256,
                authority_id=authority_id,
            )
        if matching_authority.state in {AuthorityState.FAILED, AuthorityState.BLOCKED}:
            reason = (
                "CATALOG_FAILURE_LIMIT_REACHED"
                if matching_authority.failure_occurrence_count == 3
                else "CATALOG_TERMINAL_AUTHORITY_NOT_RELAUNCHABLE"
            )
            return _blocked_decision(
                failures=(reason,),
                request_sha256=request_sha256,
                campaign_id=campaign_id,
                science_sha256=science_sha256,
                execution_plan_sha256=matching_authority.execution_plan_sha256,
                execution_protocol_sha256=effective_protocol_sha256,
                authority_id=authority_id,
            )
        if matching_authority.state in _ACTIVE_STATES and active_owner_run:
            return _decision(
                outcome=ControllerOutcome.ADOPTED,
                reason_code="CATALOG_ACTIVE_AUTHORITY_ADOPTED",
                request_sha256=request_sha256,
                campaign_id=campaign_id,
                science_sha256=science_sha256,
                execution_plan_sha256=matching_authority.execution_plan_sha256,
                execution_protocol_sha256=effective_protocol_sha256,
                authority_id=authority_id,
            )
        resume_existing = True

    # 11. FIFO, one-heavy-campaign lease, and proven free capacity.
    capacity_failures: list[str] = []
    queue_wait = False
    active_lease_wait = False
    if not resume_existing:
        _append_status_failures(
            capacity_failures,
            request_queue_evidence,
            "CATALOG_REQUEST_QUEUE_INVALID",
        )
        if (
            not request_queue_evidence.complete
            or not request_queue_evidence.stable
            or request_queue_evidence.current_issue_number != request_issue_number
            or request_issue_number not in request_queue_evidence.eligible_open_issue_numbers
        ):
            _append_unique(capacity_failures, "CATALOG_REQUEST_QUEUE_INVALID")
        elif request_queue_evidence.eligible_open_issue_numbers[0] != request_issue_number:
            queue_wait = True
        active_lease_wait = any(
            record.state in _ACTIVE_STATES and record.campaign_id != campaign_id
            for record in _latest_authorities(ledger)
        )

    _append_status_failures(
        capacity_failures,
        capacity_evidence,
        "CATALOG_CAPACITY_UNPROVEN",
    )
    capacity_age = now - capacity_evidence.observed_at
    if capacity_age > timedelta(seconds=300) or capacity_age < -timedelta(seconds=30):
        _append_unique(capacity_failures, "CATALOG_CAPACITY_UNPROVEN")
    if not capacity_evidence.capacity_known:
        _append_unique(capacity_failures, "CATALOG_CAPACITY_UNPROVEN")
    if (
        not capacity_evidence.standard_runner_only
        or capacity_evidence.paid_runner_minutes != 0
        or capacity_evidence.estimated_paid_actions_cost != 0
    ):
        _append_unique(capacity_failures, "CATALOG_FREE_CAPACITY_REQUIRED")
    if not capacity_evidence.artifact_storage_headroom_proven:
        _append_unique(capacity_failures, "CATALOG_FREE_STORAGE_UNPROVEN")
    if not capacity_evidence.cache_storage_headroom_proven:
        _append_unique(capacity_failures, "CATALOG_FREE_CACHE_STORAGE_UNPROVEN")
    if not capacity_evidence.resource_margin_verified:
        _append_unique(capacity_failures, "CATALOG_CAPACITY_MARGIN_UNPROVEN")
    if registry_entry is None:
        _append_unique(capacity_failures, "CATALOG_CAMPAIGN_NOT_REGISTERED")
    elif not capacity_evidence.temporarily_unavailable:
        expected_workers = registry_entry.select_safe_worker_ceiling(
            compatible_qualified_ceiling=(capacity_evidence.compatible_qualified_ceiling),
            current_safe_free_capacity=(capacity_evidence.current_safe_free_capacity),
        )
        if capacity_evidence.selected_workers != expected_workers:
            _append_unique(capacity_failures, "CATALOG_CAPACITY_SELECTION_INVALID")
        planned_workers = operational_plan.get("workers")
        if planned_workers != expected_workers:
            _append_unique(capacity_failures, "CATALOG_EXECUTION_PLAN_CAPACITY_MISMATCH")

    if capacity_failures:
        return _blocked_decision(
            failures=capacity_failures,
            request_sha256=request_sha256,
            campaign_id=campaign_id,
            science_sha256=science_sha256,
            execution_plan_sha256=execution_plan_sha256,
            execution_protocol_sha256=effective_protocol_sha256,
            authority_id=authority_id,
        )
    if queue_wait:
        return _decision(
            outcome=ControllerOutcome.DEFERRED,
            reason_code="CATALOG_WAITING_FOR_EARLIER_REQUEST",
            request_sha256=request_sha256,
            campaign_id=campaign_id,
            science_sha256=science_sha256,
            execution_plan_sha256=execution_plan_sha256,
            execution_protocol_sha256=effective_protocol_sha256,
            authority_id=authority_id,
            should_retry_delivery=True,
            retry_not_before=now + timedelta(minutes=1),
        )
    if active_lease_wait or capacity_evidence.temporarily_unavailable:
        return _decision(
            outcome=ControllerOutcome.DEFERRED,
            reason_code="CATALOG_WAITING_FOR_FREE_CAPACITY",
            request_sha256=request_sha256,
            campaign_id=campaign_id,
            science_sha256=science_sha256,
            execution_plan_sha256=execution_plan_sha256,
            execution_protocol_sha256=effective_protocol_sha256,
            authority_id=authority_id,
            should_retry_delivery=True,
            retry_not_before=(capacity_evidence.retry_not_before or now + timedelta(minutes=1)),
        )

    # 12. Seal the only inputs that a heavy workflow may receive.
    assert registry_entry is not None
    assert execution_plan_sha256 is not None
    sealed = CatalogSealedInputsV1(
        engine_id=registry_entry.engine_id,
        request_sha256=request_sha256,
        campaign_id=campaign_id,
        science_sha256=science_sha256,
        execution_plan_sha256=execution_plan_sha256,
        execution_protocol_sha256=effective_protocol_sha256,
        protected_commit_sha=protected_head_evidence.applicable_commit_sha,
        prompt_sha256=prompt_evidence.prompt_sha256,
        prompt_policy_sha256=prompt_evidence.prompt_policy_sha256,
        campaign_registry_sha256=(campaign_definition_evidence.campaign_registry_sha256),
        campaign_definition_manifest_sha256=(
            campaign_definition_evidence.campaign_definition_manifest_sha256
        ),
        campaign_definition_sha256=(campaign_definition_evidence.campaign_definition_sha256),
        campaign_definition_rehash_receipt_sha256=(
            campaign_definition_evidence.campaign_definition_rehash_receipt_sha256
        ),
        authority_id=authority_id,
        authority_anchor_evidence_sha256=(
            authority_anchor_evidence.authority_anchor_evidence_sha256
        ),
        github_controls_receipt_sha256=github_controls_evidence.receipt_sha256,
        capacity_receipt_sha256=capacity_evidence.capacity_receipt_sha256,
        source_artifact_manifest_sha256=(source_artifacts_evidence.source_artifact_manifest_sha256),
        artifact_plan_sha256=source_artifacts_evidence.artifact_plan_sha256,
    )
    if resume_existing:
        return _decision(
            outcome=ControllerOutcome.ADOPTED,
            reason_code="CATALOG_RECOVERY_AUTHORIZED",
            request_sha256=request_sha256,
            campaign_id=campaign_id,
            science_sha256=science_sha256,
            execution_plan_sha256=execution_plan_sha256,
            execution_protocol_sha256=effective_protocol_sha256,
            authority_id=authority_id,
            should_schedule_compute=True,
            should_resume_existing=True,
            sealed_inputs=sealed,
        )
    return _decision(
        outcome=ControllerOutcome.ADMITTED,
        reason_code="CATALOG_ADMITTED",
        request_sha256=request_sha256,
        campaign_id=campaign_id,
        science_sha256=science_sha256,
        execution_plan_sha256=execution_plan_sha256,
        execution_protocol_sha256=effective_protocol_sha256,
        authority_id=authority_id,
        should_create_authority=True,
        should_schedule_compute=True,
        sealed_inputs=sealed,
    )


__all__ = [
    "CATALOG_AUTHORITY_NAMESPACE",
    "CatalogAuthorityAnchorEvidenceV1",
    "CatalogCampaignDefinitionEvidenceV1",
    "CatalogCapacityAdmissionEvidenceV1",
    "CatalogControllerDecisionV1",
    "CatalogGithubControlsEvidenceV1",
    "CatalogPromptPolicyEvidenceV1",
    "CatalogProtectedHeadEvidenceV1",
    "CatalogRequestQueueEvidenceV1",
    "CatalogScienceAdmissionEvidenceV1",
    "CatalogSealedInputsV1",
    "CatalogSourceArtifactsEvidenceV1",
    "ControllerOutcome",
    "catalog_authority_id",
    "catalog_campaign_id",
    "catalog_execution_plan_sha256",
    "decide_catalog_run",
]
