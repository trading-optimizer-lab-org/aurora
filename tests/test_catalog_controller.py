from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    VerifiedAuthorityLedgerV1,
    append_authority_record,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignEntryV1,
)
from aurora.infra.sp500_megarun.catalog_controller import (
    CatalogAuthorityAnchorEvidenceV1,
    CatalogCampaignDefinitionEvidenceV1,
    CatalogCapacityAdmissionEvidenceV1,
    CatalogControllerDecisionV1,
    CatalogGithubControlsEvidenceV1,
    CatalogPromptPolicyEvidenceV1,
    CatalogProtectedHeadEvidenceV1,
    CatalogRequestQueueEvidenceV1,
    CatalogScienceAdmissionEvidenceV1,
    CatalogSealedInputsV1,
    CatalogSourceArtifactsEvidenceV1,
    ControllerOutcome,
    catalog_authority_id,
    catalog_campaign_id,
    catalog_execution_plan_sha256,
    decide_catalog_run,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogRunRequestV1,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000001"
REQUEST_ACTOR = "aurora-catalog-requester[bot]"
CAMPAIGN_KEY = "sp500-optimized-catalog-v1"
PROMPT_SHA256 = "2" * 64
PROMPT_POLICY_SHA256 = "3" * 64
CAMPAIGN_DEFINITION_SHA256 = "4" * 64
SCIENCE_SHA256 = "5" * 64
EXECUTION_PROTOCOL_SHA256 = "6" * 64
PROTECTED_COMMIT = "a" * 40
OPERATIONAL_PLAN = {
    "workers": 173,
    "batch_size": 64,
    "checkpoint_interval": 4,
    "compression": "zstd-3",
    "merge_fan_in": 30,
}


def _request(**updates: object) -> CatalogRunRequestV1:
    payload: dict[str, object] = {
        "schema_version": "1",
        "request_id": REQUEST_ID,
        "campaign_key": CAMPAIGN_KEY,
        "launch_generation": 1,
        "launch_ticket_sha256": "1" * 64,
        "previous_terminal_request_sha256": None,
        "campaign_definition_sha256": CAMPAIGN_DEFINITION_SHA256,
        "prompt_sha256": PROMPT_SHA256,
        "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        "free_resources_only": True,
        "automatic_recovery": True,
        "max_same_failure_count": 3,
        "requester_public_key_sha256": "7" * 64,
        "requester_attestation_algorithm": "rsa-pss-sha256-v1",
        "requester_attestation_b64": "A" * 344,
    }
    payload.update(updates)
    return CatalogRunRequestV1.model_validate(payload)


def _registry_entry() -> CatalogCampaignEntryV1:
    return CatalogCampaignEntryV1(
        campaign_key=CAMPAIGN_KEY,
        engine_id="optimized_catalog_v1",
        definition_manifest_path=(
            "config/catalog_campaign_definitions/sp500-optimized-catalog-v1.manifest.json"
        ),
        optimization_policy_path="config/sp500_catalog_optimization_policy_v1.json",
        campaign_contract_path="config/sp500_megarun_dehb_campaign_v1.json",
        catalog_dir="config/sp500_megarun_strategy_catalog_v1",
        selected_config_path="config/sp500_megarun_selected_dehb_13.json",
        admission_evidence_path=("config/sp500_catalog_admission_evidence_current_v1.json"),
        data_contract_path="config/sp500_megarun_free_data_240.json",
        feature_contract_path="config/sp500_megarun_feature_contract_240.json",
        runtime_input_run_id=31418682679,
        reference_run_id=31948898747,
        max_free_workers=360,
        active=True,
    )


def _common_evidence() -> dict[str, object]:
    return {
        "schema_version": "1",
        "status": "ready",
        "observed_at": NOW,
        "source_sha256": "8" * 64,
        "content_sha256": "9" * 64,
        "receipt_sha256": "b" * 64,
        "reason_codes": (),
    }


def _prompt_evidence() -> CatalogPromptPolicyEvidenceV1:
    return CatalogPromptPolicyEvidenceV1(
        **_common_evidence(),
        applicable_commit_sha=PROTECTED_COMMIT,
        prompt_sha256=PROMPT_SHA256,
        prompt_policy_sha256=PROMPT_POLICY_SHA256,
        prompt_bytes_verified=True,
        prompt_policy_schema_valid=True,
        enforced_policy_rule_ids=tuple(f"CAT-{index:03d}" for index in range(1, 26)),
    )


def _definition_evidence() -> CatalogCampaignDefinitionEvidenceV1:
    return CatalogCampaignDefinitionEvidenceV1(
        **_common_evidence(),
        applicable_commit_sha=PROTECTED_COMMIT,
        campaign_key=CAMPAIGN_KEY,
        registry_entry_resolved=True,
        safe_paths_verified=True,
        manifest_schema_valid=True,
        repository_rehash_complete=True,
        campaign_registry_sha256="c" * 64,
        campaign_definition_manifest_sha256="d" * 64,
        campaign_definition_sha256=CAMPAIGN_DEFINITION_SHA256,
        campaign_definition_rehash_receipt_sha256="e" * 64,
    )


def _anchor_evidence(
    ledger: VerifiedAuthorityLedgerV1 | None = None,
) -> CatalogAuthorityAnchorEvidenceV1:
    bound_ledger = _empty_ledger() if ledger is None else ledger
    return CatalogAuthorityAnchorEvidenceV1(
        **_common_evidence(),
        identity_verified=True,
        live_variable_matches=True,
        ledger_integrity_verified=True,
        ledger_sha256=bound_ledger.ledger_sha256,
        authority_anchor_evidence_sha256="f" * 64,
    )


def _head_evidence() -> CatalogProtectedHeadEvidenceV1:
    return CatalogProtectedHeadEvidenceV1(
        **_common_evidence(),
        current_protected_head_sha=PROTECTED_COMMIT,
        applicable_commit_sha=PROTECTED_COMMIT,
        original_bound_commit_sha=None,
        original_commit_reachable_from_protected_history=True,
        execution_protocol_compatible=True,
        protected_ref_verified=True,
    )


def _github_evidence() -> CatalogGithubControlsEvidenceV1:
    return CatalogGithubControlsEvidenceV1(
        **_common_evidence(),
        controls_verified=True,
        production_environment_verified=True,
        admin_credential_exposed=False,
        requester_credential_exposed=False,
        auditor_credential_exposed=False,
        standard_free_runner_only=True,
        paid_runner_minutes=0,
        estimated_paid_actions_cost=0,
        zero_actions_spend_budget_verified=True,
        zero_actions_storage_budget_verified=True,
        zero_cache_storage_budget_verified=True,
        cache_limit_gb=10,
        cache_retention_days=90,
        validation_opened=False,
        locked_opened=False,
    )


def _science_evidence() -> CatalogScienceAdmissionEvidenceV1:
    return CatalogScienceAdmissionEvidenceV1(
        **_common_evidence(),
        scientific_contract_sha256=SCIENCE_SHA256,
        optimization_admission_verified=True,
        science_identity_verified=True,
        data_contract_verified=True,
        feature_contract_verified=True,
        metric_contract_verified=True,
        cache_contract_verified=True,
        component_contract_verified=True,
    )


def _source_evidence() -> CatalogSourceArtifactsEvidenceV1:
    return CatalogSourceArtifactsEvidenceV1(
        **_common_evidence(),
        artifacts_exist=True,
        hashes_bound=True,
        runtime_artifact_fresh=True,
        unexpired_or_verified_mirror=True,
        immutable=True,
        source_artifact_manifest_sha256="1" * 64,
        artifact_plan_sha256="2" * 64,
    )


def _capacity_evidence() -> CatalogCapacityAdmissionEvidenceV1:
    return CatalogCapacityAdmissionEvidenceV1(
        **_common_evidence(),
        capacity_known=True,
        temporarily_unavailable=False,
        compatible_qualified_ceiling=360,
        current_safe_free_capacity=173,
        selected_workers=173,
        standard_runner_only=True,
        paid_runner_minutes=0,
        estimated_paid_actions_cost=0,
        artifact_storage_headroom_proven=True,
        cache_storage_headroom_proven=True,
        resource_margin_verified=True,
        compatible_safe_floor_used=False,
        retry_not_before=None,
        capacity_receipt_sha256="3" * 64,
    )


def _queue_evidence() -> CatalogRequestQueueEvidenceV1:
    return CatalogRequestQueueEvidenceV1(
        **_common_evidence(),
        complete=True,
        stable=True,
        current_issue_number=101,
        eligible_open_issue_numbers=(101,),
        request_queue_snapshot_sha256="4" * 64,
    )


def _empty_ledger() -> VerifiedAuthorityLedgerV1:
    return VerifiedAuthorityLedgerV1.from_records(())


def _ledger_fixture(
    *,
    state: str,
    same_science: bool,
) -> VerifiedAuthorityLedgerV1:
    campaign_id = (
        catalog_campaign_id(
            campaign_key=CAMPAIGN_KEY,
            scientific_contract_sha256=SCIENCE_SHA256,
        )
        if same_science
        else "d" * 64
    )
    science_sha256 = SCIENCE_SHA256 if same_science else "e" * 64
    request = _request()
    first = append_authority_record(
        previous=None,
        authority_id=catalog_authority_id(
            request_sha256=request.request_sha256,
            campaign_id=campaign_id,
        ),
        request_issue_number=91,
        campaign_id=campaign_id,
        request_sha256=request.request_sha256,
        science_sha256=science_sha256,
        execution_plan_sha256=catalog_execution_plan_sha256(
            campaign_id=campaign_id,
            operational_plan=OPERATIONAL_PLAN,
        ),
        execution_protocol_sha256=EXECUTION_PROTOCOL_SHA256,
        state=AuthorityState.RESERVED,
        run_id=1001,
        run_attempt=1,
        writer_job_id="reserve",
        writer_job_database_id=2001,
        protected_commit_sha=PROTECTED_COMMIT,
        created_at=NOW - timedelta(minutes=2),
    )
    records = [first]
    if state == "reserved":
        return VerifiedAuthorityLedgerV1.from_records(records)
    running = append_authority_record(
        previous=first,
        state=AuthorityState.RUNNING,
        writer_job_id="record_running",
        writer_job_database_id=2002,
        created_at=NOW - timedelta(minutes=1, seconds=50),
    )
    records.append(running)
    if state == "running":
        return VerifiedAuthorityLedgerV1.from_records(records)
    if state == "recovering":
        records.append(
            append_authority_record(
                previous=running,
                state=AuthorityState.RECOVERING,
                writer_job_id="record_nonterminal_wait",
                writer_job_database_id=2003,
                created_at=NOW - timedelta(minutes=1, seconds=40),
            )
        )
    elif state == "waiting_retry":
        records.append(
            append_authority_record(
                previous=running,
                state=AuthorityState.WAITING_RETRY,
                writer_job_id="record_nonterminal_wait",
                writer_job_database_id=2003,
                created_at=NOW - timedelta(minutes=1, seconds=40),
            )
        )
    elif state == "success":
        records.append(
            append_authority_record(
                previous=running,
                state=AuthorityState.SUCCESS,
                writer_job_id="finalize",
                writer_job_database_id=2003,
                evidence_sha256="a" * 64,
                created_at=NOW - timedelta(minutes=1, seconds=40),
            )
        )
    elif state == "failed":
        records.append(
            append_authority_record(
                previous=running,
                state=AuthorityState.FAILED,
                writer_job_id="finalize",
                writer_job_database_id=2003,
                evidence_sha256="a" * 64,
                created_at=NOW - timedelta(minutes=1, seconds=40),
            )
        )
    elif state == "blocked":
        one = append_authority_record(
            previous=running,
            state=AuthorityState.RECOVERING,
            writer_job_id="record_nonterminal_wait",
            writer_job_database_id=2003,
            failure_fingerprint="f" * 64,
            failure_occurrence_count=1,
            created_at=NOW - timedelta(minutes=1, seconds=40),
        )
        two = append_authority_record(
            previous=one,
            state=AuthorityState.RECOVERING,
            writer_job_database_id=2004,
            failure_fingerprint="f" * 64,
            failure_occurrence_count=2,
            created_at=NOW - timedelta(minutes=1, seconds=30),
        )
        records.extend((one, two))
        records.append(
            append_authority_record(
                previous=two,
                state=AuthorityState.BLOCKED,
                writer_job_id="finalize",
                writer_job_database_id=2005,
                failure_fingerprint="f" * 64,
                failure_occurrence_count=3,
                evidence_sha256="a" * 64,
                created_at=NOW - timedelta(minutes=1, seconds=20),
            )
        )
    else:
        raise AssertionError(state)
    return VerifiedAuthorityLedgerV1.from_records(records)


def _valid_controller_inputs(**updates: object) -> dict[str, object]:
    request = _request()
    values: dict[str, object] = {
        "request": request,
        "request_issue_number": 101,
        "request_issue_author": REQUEST_ACTOR,
        "allowed_request_actors": (REQUEST_ACTOR,),
        "observed_request_sha256": request.request_sha256,
        "registry_entry": _registry_entry(),
        "prompt_evidence": _prompt_evidence(),
        "campaign_definition_evidence": _definition_evidence(),
        "authority_anchor_evidence": _anchor_evidence(),
        "protected_head_evidence": _head_evidence(),
        "github_controls_evidence": _github_evidence(),
        "science_evidence": _science_evidence(),
        "source_artifacts_evidence": _source_evidence(),
        "capacity_evidence": _capacity_evidence(),
        "request_queue_evidence": _queue_evidence(),
        "ledger": _empty_ledger(),
        "operational_plan": OPERATIONAL_PLAN,
        "execution_protocol_sha256": EXECUTION_PROTOCOL_SHA256,
        "verified_github_now": NOW,
        "active_owner_run": True,
    }
    values.update(updates)
    if "ledger" in updates:
        supplied_ledger = updates["ledger"]
        assert isinstance(supplied_ledger, VerifiedAuthorityLedgerV1)
        if "authority_anchor_evidence" not in updates:
            values["authority_anchor_evidence"] = _anchor_evidence(supplied_ledger)
        if "protected_head_evidence" not in updates and supplied_ledger.latest is not None:
            values["protected_head_evidence"] = _head_evidence().model_copy(
                update={
                    "applicable_commit_sha": (supplied_ledger.latest.protected_commit_sha),
                    "original_bound_commit_sha": (supplied_ledger.latest.protected_commit_sha),
                }
            )
    return values


def test_clean_new_science_is_admitted_once() -> None:
    decision = decide_catalog_run(**_valid_controller_inputs())
    assert decision.outcome is ControllerOutcome.ADMITTED
    assert decision.reason_code == "CATALOG_ADMITTED"
    assert len(decision.campaign_id or "") == 64
    assert decision.should_create_authority is True
    assert decision.should_schedule_compute is True
    assert decision.sealed_inputs is not None
    assert decision.sealed_inputs.protected_commit_sha == PROTECTED_COMMIT
    assert set(CatalogSealedInputsV1.model_fields) == {
        "engine_id",
        "request_sha256",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
        "protected_commit_sha",
        "prompt_sha256",
        "prompt_policy_sha256",
        "campaign_registry_sha256",
        "campaign_definition_manifest_sha256",
        "campaign_definition_sha256",
        "campaign_definition_rehash_receipt_sha256",
        "authority_id",
        "authority_anchor_evidence_sha256",
        "github_controls_receipt_sha256",
        "capacity_receipt_sha256",
        "source_artifact_manifest_sha256",
        "artifact_plan_sha256",
    }


def test_decision_hash_detects_any_changed_field() -> None:
    decision = decide_catalog_run(**_valid_controller_inputs())
    payload = decision.model_dump(mode="json")
    payload["reason_code"] = "CHANGED"
    with pytest.raises(ValueError, match="CATALOG_CONTROLLER_DECISION_HASH_INVALID"):
        CatalogControllerDecisionV1.model_validate(payload)


def test_equivalent_active_campaign_is_adopted_without_new_compute() -> None:
    inputs = _valid_controller_inputs(ledger=_ledger_fixture(state="running", same_science=True))
    decision = decide_catalog_run(**inputs)
    assert decision.outcome is ControllerOutcome.ADOPTED
    assert decision.should_create_authority is False
    assert decision.should_schedule_compute is False
    assert decision.sealed_inputs is None
    assert decision.authority_id == inputs["ledger"].latest.authority_id


def test_equivalent_success_is_reused_without_rerun() -> None:
    decision = decide_catalog_run(
        **_valid_controller_inputs(ledger=_ledger_fixture(state="success", same_science=True))
    )
    assert decision.outcome is ControllerOutcome.ADOPTED
    assert decision.reason_code == "CATALOG_SUCCESS_ALREADY_EXISTS"
    assert decision.should_schedule_compute is False


def test_two_equivalent_requests_converge_on_the_existing_authority() -> None:
    ledger = _ledger_fixture(state="running", same_science=True)
    second_request = _request(
        request_id="018f47a2-6e91-7c34-8000-000000000002",
        requester_attestation_b64="B" * 344,
    )
    decision = decide_catalog_run(
        **_valid_controller_inputs(
            request=second_request,
            observed_request_sha256=second_request.request_sha256,
            ledger=ledger,
        )
    )
    assert decision.outcome is ControllerOutcome.ADOPTED
    assert decision.authority_id == ledger.latest.authority_id
    assert decision.should_create_authority is False


@pytest.mark.parametrize("state", ["reserved", "running", "recovering"])
def test_duplicate_delivery_never_steals_active_execution(state: str) -> None:
    decision = decide_catalog_run(
        **_valid_controller_inputs(
            ledger=_ledger_fixture(state=state, same_science=True),
            active_owner_run=True,
        )
    )
    assert decision.outcome is ControllerOutcome.ADOPTED
    assert decision.should_schedule_compute is False
    assert decision.should_resume_existing is False


def test_watchdog_can_resume_only_the_bound_reachable_commit() -> None:
    ledger = _ledger_fixture(state="recovering", same_science=True)
    head = _head_evidence().model_copy(
        update={
            "current_protected_head_sha": "b" * 40,
            "applicable_commit_sha": PROTECTED_COMMIT,
            "original_bound_commit_sha": PROTECTED_COMMIT,
        }
    )
    decision = decide_catalog_run(
        **_valid_controller_inputs(
            ledger=ledger,
            active_owner_run=False,
            protected_head_evidence=head,
        )
    )
    assert decision.outcome is ControllerOutcome.ADOPTED
    assert decision.should_resume_existing is True
    assert decision.should_schedule_compute is True
    assert decision.sealed_inputs is not None
    assert decision.sealed_inputs.protected_commit_sha == PROTECTED_COMMIT

    unreachable = head.model_copy(
        update={"original_commit_reachable_from_protected_history": False}
    )
    blocked = decide_catalog_run(
        **_valid_controller_inputs(
            ledger=ledger,
            active_owner_run=False,
            protected_head_evidence=unreachable,
        )
    )
    assert blocked.outcome is ControllerOutcome.BLOCKED
    assert blocked.reason_code == "CATALOG_BOUND_COMMIT_UNREACHABLE"


def test_distinct_campaign_waits_while_one_heavy_campaign_is_active() -> None:
    decision = decide_catalog_run(
        **_valid_controller_inputs(ledger=_ledger_fixture(state="running", same_science=False))
    )
    assert decision.outcome is ControllerOutcome.DEFERRED
    assert decision.reason_code == "CATALOG_WAITING_FOR_FREE_CAPACITY"
    assert decision.should_create_authority is False
    assert decision.should_schedule_compute is False
    assert decision.should_retry_delivery is True
    assert decision.sealed_inputs is None


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("wrong_prompt_hash", "CATALOG_PROMPT_HASH_MISMATCH"),
        ("unprotected_commit", "CATALOG_COMMIT_NOT_PROTECTED_HEAD"),
        ("unregistered_campaign", "CATALOG_CAMPAIGN_NOT_REGISTERED"),
        ("campaign_definition_mismatch", "CATALOG_CAMPAIGN_DEFINITION_MISMATCH"),
        ("stale_runtime_artifact", "CATALOG_RUNTIME_ARTIFACT_STALE"),
        ("science_mismatch", "CATALOG_SCIENCE_IDENTITY_MISMATCH"),
        ("component_contract_mismatch", "CATALOG_COMPONENT_CONTRACT_MISMATCH"),
        ("paid_runner", "CATALOG_FREE_CAPACITY_REQUIRED"),
        ("zero_spend_budget_missing", "CATALOG_ZERO_SPEND_BUDGET_REQUIRED"),
        (
            "actions_storage_budget_missing",
            "CATALOG_ZERO_ACTIONS_STORAGE_BUDGET_REQUIRED",
        ),
        (
            "cache_storage_budget_missing",
            "CATALOG_ZERO_CACHE_STORAGE_BUDGET_REQUIRED",
        ),
        ("cache_controls_wrong", "CATALOG_FREE_CACHE_CONTROLS_REQUIRED"),
        ("artifact_storage_headroom_unproven", "CATALOG_FREE_STORAGE_UNPROVEN"),
        (
            "cache_storage_headroom_unproven",
            "CATALOG_FREE_CACHE_STORAGE_UNPROVEN",
        ),
        ("capacity_unknown", "CATALOG_CAPACITY_UNPROVEN"),
        ("validation_open", "CATALOG_VALIDATION_MUST_REMAIN_CLOSED"),
        ("locked_open", "CATALOG_LOCKED_MUST_REMAIN_CLOSED"),
        ("ledger_invalid", "CATALOG_LEDGER_INVALID"),
        ("admin_credential_exposed", "AGENT_ADMIN_CREDENTIAL_EXPOSED"),
        ("requester_credential_exposed", "AGENT_REQUESTER_CREDENTIAL_EXPOSED"),
        ("auditor_credential_exposed", "AGENT_AUDITOR_CREDENTIAL_EXPOSED"),
        ("same_failure_third_time", "CATALOG_FAILURE_LIMIT_REACHED"),
    ],
)
def test_every_missing_or_unsafe_fact_blocks(mutation: str, reason: str) -> None:
    inputs = _valid_controller_inputs()
    if mutation == "wrong_prompt_hash":
        inputs["prompt_evidence"] = _prompt_evidence().model_copy(
            update={"prompt_sha256": "f" * 64}
        )
    elif mutation == "unprotected_commit":
        inputs["protected_head_evidence"] = _head_evidence().model_copy(
            update={"applicable_commit_sha": "b" * 40}
        )
        inputs["prompt_evidence"] = _prompt_evidence().model_copy(
            update={"applicable_commit_sha": "b" * 40}
        )
        inputs["campaign_definition_evidence"] = _definition_evidence().model_copy(
            update={"applicable_commit_sha": "b" * 40}
        )
    elif mutation == "unregistered_campaign":
        inputs["registry_entry"] = None
    elif mutation == "campaign_definition_mismatch":
        inputs["campaign_definition_evidence"] = _definition_evidence().model_copy(
            update={"campaign_definition_sha256": "f" * 64}
        )
    elif mutation == "stale_runtime_artifact":
        inputs["source_artifacts_evidence"] = _source_evidence().model_copy(
            update={"runtime_artifact_fresh": False}
        )
    elif mutation == "science_mismatch":
        inputs["science_evidence"] = _science_evidence().model_copy(
            update={"science_identity_verified": False}
        )
    elif mutation == "component_contract_mismatch":
        inputs["science_evidence"] = _science_evidence().model_copy(
            update={"component_contract_verified": False}
        )
    elif mutation == "paid_runner":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"standard_free_runner_only": False, "paid_runner_minutes": 1}
        )
    elif mutation == "zero_spend_budget_missing":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"zero_actions_spend_budget_verified": False}
        )
    elif mutation == "actions_storage_budget_missing":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"zero_actions_storage_budget_verified": False}
        )
    elif mutation == "cache_storage_budget_missing":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"zero_cache_storage_budget_verified": False}
        )
    elif mutation == "cache_controls_wrong":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"cache_limit_gb": 11}
        )
    elif mutation == "artifact_storage_headroom_unproven":
        inputs["capacity_evidence"] = _capacity_evidence().model_copy(
            update={"artifact_storage_headroom_proven": False}
        )
    elif mutation == "cache_storage_headroom_unproven":
        inputs["capacity_evidence"] = _capacity_evidence().model_copy(
            update={"cache_storage_headroom_proven": False}
        )
    elif mutation == "capacity_unknown":
        inputs["capacity_evidence"] = _capacity_evidence().model_copy(
            update={"capacity_known": False}
        )
    elif mutation == "validation_open":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"validation_opened": True}
        )
    elif mutation == "locked_open":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"locked_opened": True}
        )
    elif mutation == "ledger_invalid":
        inputs["authority_anchor_evidence"] = _anchor_evidence().model_copy(
            update={"ledger_integrity_verified": False}
        )
    elif mutation == "admin_credential_exposed":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"admin_credential_exposed": True}
        )
    elif mutation == "requester_credential_exposed":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"requester_credential_exposed": True}
        )
    elif mutation == "auditor_credential_exposed":
        inputs["github_controls_evidence"] = _github_evidence().model_copy(
            update={"auditor_credential_exposed": True}
        )
    elif mutation == "same_failure_third_time":
        ledger = _ledger_fixture(state="blocked", same_science=True)
        inputs["ledger"] = ledger
        inputs["authority_anchor_evidence"] = _anchor_evidence(ledger)
        inputs["protected_head_evidence"] = _head_evidence().model_copy(
            update={"original_bound_commit_sha": ledger.latest.protected_commit_sha}
        )
    else:
        raise AssertionError(mutation)
    decision = decide_catalog_run(**inputs)
    assert decision.outcome is ControllerOutcome.BLOCKED
    assert decision.reason_code == reason
    assert decision.should_create_authority is False
    assert decision.should_schedule_compute is False
    assert decision.sealed_inputs is None


def test_issue_actor_and_exact_request_hash_are_mandatory() -> None:
    wrong_actor = decide_catalog_run(**_valid_controller_inputs(request_issue_author="gomez5757"))
    assert wrong_actor.reason_code == "CATALOG_REQUEST_ACTOR_NOT_ALLOWED"
    edited = decide_catalog_run(**_valid_controller_inputs(observed_request_sha256="f" * 64))
    assert edited.reason_code == "CATALOG_REQUEST_SHA_MISMATCH"


def test_ledger_evidence_cannot_be_reused_for_a_different_snapshot() -> None:
    ledger = _ledger_fixture(state="running", same_science=False)
    decision = decide_catalog_run(
        **_valid_controller_inputs(
            ledger=ledger,
            authority_anchor_evidence=_anchor_evidence(),
        )
    )
    assert decision.outcome is ControllerOutcome.BLOCKED
    assert decision.reason_code == "CATALOG_LEDGER_INVALID"


def test_identity_functions_are_stable_and_separate_science_from_operations() -> None:
    first = catalog_campaign_id(
        campaign_key=CAMPAIGN_KEY,
        scientific_contract_sha256=SCIENCE_SHA256,
    )
    assert first == catalog_campaign_id(
        campaign_key=CAMPAIGN_KEY,
        scientific_contract_sha256=SCIENCE_SHA256,
    )
    assert first != catalog_campaign_id(
        campaign_key=CAMPAIGN_KEY,
        scientific_contract_sha256="f" * 64,
    )
    authority = catalog_authority_id(
        request_sha256=_request().request_sha256,
        campaign_id=first,
    )
    assert authority.version == 5
    assert authority == catalog_authority_id(
        request_sha256=_request().request_sha256,
        campaign_id=first,
    )

    changed_operations = {**OPERATIONAL_PLAN, "workers": 120}
    assert catalog_execution_plan_sha256(
        campaign_id=first,
        operational_plan=OPERATIONAL_PLAN,
    ) != catalog_execution_plan_sha256(
        campaign_id=first,
        operational_plan=changed_operations,
    )
    assert first == catalog_campaign_id(
        campaign_key=CAMPAIGN_KEY,
        scientific_contract_sha256=SCIENCE_SHA256,
    )


@pytest.mark.parametrize(
    "age_seconds,outcome,reason",
    [
        (300, ControllerOutcome.ADMITTED, "CATALOG_ADMITTED"),
        (
            301,
            ControllerOutcome.DEFERRED,
            "DEFERRED_ADMISSION_AUDIT_EXPIRED",
        ),
    ],
)
def test_admission_audit_freshness_boundary(
    age_seconds: int,
    outcome: ControllerOutcome,
    reason: str,
) -> None:
    evidence = _github_evidence().model_copy(
        update={"observed_at": NOW - timedelta(seconds=age_seconds)}
    )
    decision = decide_catalog_run(**_valid_controller_inputs(github_controls_evidence=evidence))
    assert decision.outcome is outcome
    assert decision.reason_code == reason
    if outcome is ControllerOutcome.DEFERRED:
        assert decision.should_create_authority is False
        assert decision.should_schedule_compute is False


def test_audit_more_than_thirty_seconds_in_future_blocks() -> None:
    evidence = _github_evidence().model_copy(update={"observed_at": NOW + timedelta(seconds=31)})
    decision = decide_catalog_run(**_valid_controller_inputs(github_controls_evidence=evidence))
    assert decision.outcome is ControllerOutcome.BLOCKED
    assert decision.reason_code == "CATALOG_GITHUB_AUDIT_TIME_INVALID"


def test_known_temporary_capacity_shortage_defers_but_unknown_blocks() -> None:
    deferred_capacity = _capacity_evidence().model_copy(
        update={
            "temporarily_unavailable": True,
            "selected_workers": 0,
            "retry_not_before": NOW + timedelta(minutes=5),
        }
    )
    deferred = decide_catalog_run(**_valid_controller_inputs(capacity_evidence=deferred_capacity))
    assert deferred.outcome is ControllerOutcome.DEFERRED
    assert deferred.reason_code == "CATALOG_WAITING_FOR_FREE_CAPACITY"
    assert deferred.retry_not_before == NOW + timedelta(minutes=5)

    unknown = decide_catalog_run(
        **_valid_controller_inputs(
            capacity_evidence=_capacity_evidence().model_copy(update={"capacity_known": False})
        )
    )
    assert unknown.outcome is ControllerOutcome.BLOCKED
    assert unknown.reason_code == "CATALOG_CAPACITY_UNPROVEN"

    stale = decide_catalog_run(
        **_valid_controller_inputs(
            capacity_evidence=_capacity_evidence().model_copy(
                update={"observed_at": NOW - timedelta(seconds=301)}
            )
        )
    )
    assert stale.outcome is ControllerOutcome.BLOCKED
    assert stale.reason_code == "CATALOG_CAPACITY_UNPROVEN"


def test_fifo_queue_prevents_job_start_order_overtaking() -> None:
    queue = _queue_evidence().model_copy(update={"eligible_open_issue_numbers": (90, 101)})
    decision = decide_catalog_run(**_valid_controller_inputs(request_queue_evidence=queue))
    assert decision.outcome is ControllerOutcome.DEFERRED
    assert decision.reason_code == "CATALOG_WAITING_FOR_EARLIER_REQUEST"
    assert decision.should_create_authority is False

    incomplete = queue.model_copy(update={"complete": False})
    blocked = decide_catalog_run(**_valid_controller_inputs(request_queue_evidence=incomplete))
    assert blocked.outcome is ControllerOutcome.BLOCKED
    assert blocked.reason_code == "CATALOG_REQUEST_QUEUE_INVALID"


@pytest.mark.parametrize("state", ["failed", "blocked"])
def test_failed_or_blocked_authority_is_never_silently_relaunched(state: str) -> None:
    decision = decide_catalog_run(
        **_valid_controller_inputs(ledger=_ledger_fixture(state=state, same_science=True))
    )
    assert decision.outcome is ControllerOutcome.BLOCKED
    assert decision.should_schedule_compute is False
    assert decision.should_resume_existing is False


def test_all_failed_gates_are_returned_in_deterministic_order() -> None:
    controls = _github_evidence().model_copy(
        update={
            "admin_credential_exposed": True,
            "zero_actions_spend_budget_verified": False,
            "validation_opened": True,
        }
    )
    science = _science_evidence().model_copy(update={"component_contract_verified": False})
    decision = decide_catalog_run(
        **_valid_controller_inputs(
            github_controls_evidence=controls,
            science_evidence=science,
        )
    )
    assert decision.failed_gate_codes == (
        "AGENT_ADMIN_CREDENTIAL_EXPOSED",
        "CATALOG_ZERO_SPEND_BUDGET_REQUIRED",
        "CATALOG_VALIDATION_MUST_REMAIN_CLOSED",
        "CATALOG_COMPONENT_CONTRACT_MISMATCH",
    )
    assert decision.reason_code == decision.failed_gate_codes[0]


def test_controller_is_pure_and_does_not_import_mutating_interfaces() -> None:
    text = (ROOT / "infra/sp500_megarun/catalog_controller.py").read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "requests",
        "urllib",
        "github.",
        "Path(",
        "open(",
    ):
        assert forbidden not in text
