from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from aurora.infra.sp500_megarun.catalog_engine_outcome import (
    CatalogEngineOutcomeState,
    select_catalog_engine_outcome,
)


NOW = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
AUTHORITY_ID = UUID("018f47a2-6e91-7c34-8000-000000000101")


def _base(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "request_sha256": "1" * 64,
        "authority_id": AUTHORITY_ID,
        "campaign_id": "2" * 64,
        "science_sha256": "3" * 64,
        "execution_plan_sha256": "4" * 64,
        "execution_protocol_sha256": "5" * 64,
        "protected_commit_sha": "6" * 40,
        "engine_run_id": 1234,
        "engine_run_attempt": 1,
        "stage_results": {
            "engine_verify_sealed_plan": "success",
            "prepare_runtime_and_inputs": "success",
            "verify_component_store": "success",
            "reconcile_wave_0": "success",
            "reduce": "success",
            "verify_terminal_science": "success",
            "audit_runtime": "success",
        },
        "recovery_statuses": ("complete",),
        "final_evidence_artifact": "catalog-final-root-018f47a2",
        "runtime_audit_artifact": "catalog-runtime-audit-018f47a2",
        "science_evidence_artifact": "catalog-terminal-science-018f47a2",
        "recovery_evidence_artifact": "catalog-recovery-evidence-018f47a2",
        "failure_fingerprint": None,
        "failure_occurrence_count": 0,
        "failure_reason_code": None,
        "retry_not_before": None,
        "terminal_failure_code": None,
        "created_at": NOW,
    }
    values.update(updates)
    return values


def test_complete_engine_requires_reduction_science_and_runtime_audit() -> None:
    outcome = select_catalog_engine_outcome(**_base())
    assert outcome.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE
    assert outcome.reason_code == "CATALOG_ENGINE_TERMINAL_EVIDENCE_READY"
    assert outcome.final_evidence_artifact == "catalog-final-root-018f47a2"
    assert len(outcome.evidence_sha256) == 64


@pytest.mark.parametrize(
    "stage,reason",
    [
        ("reduce", "CATALOG_REDUCTION_FAILED"),
        ("verify_terminal_science", "CATALOG_SCIENTIFIC_VERIFICATION_FAILED"),
        ("audit_runtime", "CATALOG_RUNTIME_AUDIT_FAILED"),
    ],
)
def test_no_missing_terminal_gate_can_be_terminal_candidate(
    stage: str,
    reason: str,
) -> None:
    stages = dict(_base()["stage_results"])
    stages[stage] = "failure"
    outcome = select_catalog_engine_outcome(**_base(stage_results=stages))
    assert outcome.state is CatalogEngineOutcomeState.BLOCKED
    assert outcome.reason_code == reason
    assert outcome.final_evidence_artifact is None


def test_long_proven_retry_delay_releases_the_runner() -> None:
    outcome = select_catalog_engine_outcome(
        **_base(
            stage_results={
                **dict(_base()["stage_results"]),
                "reduce": "skipped",
                "verify_terminal_science": "skipped",
                "audit_runtime": "skipped",
            },
            recovery_statuses=("waiting_retry",),
            final_evidence_artifact=None,
            runtime_audit_artifact=None,
            science_evidence_artifact=None,
            failure_fingerprint="a" * 64,
            failure_occurrence_count=2,
            failure_reason_code="PROVIDER_429",
            retry_not_before=NOW + timedelta(minutes=5),
        )
    )
    assert outcome.state is CatalogEngineOutcomeState.WAITING_RETRY
    assert outcome.failure_occurrence_count == 2
    assert outcome.retry_not_before == NOW + timedelta(minutes=5)


def test_waiting_retry_never_accepts_missing_evidence_or_a_third_occurrence() -> None:
    for count, fingerprint in ((1, None), (3, "a" * 64)):
        with pytest.raises(ValueError):
            select_catalog_engine_outcome(
                **_base(
                    stage_results={
                        **dict(_base()["stage_results"]),
                        "reduce": "skipped",
                        "verify_terminal_science": "skipped",
                        "audit_runtime": "skipped",
                    },
                    recovery_statuses=("waiting_retry",),
                    final_evidence_artifact=None,
                    runtime_audit_artifact=None,
                    science_evidence_artifact=None,
                    failure_fingerprint=fingerprint,
                    failure_occurrence_count=count,
                    failure_reason_code="PROVIDER_429",
                    retry_not_before=NOW + timedelta(minutes=5),
                )
            )


def test_unknown_or_cancelled_execution_is_blocked_not_retried() -> None:
    stages = dict(_base()["stage_results"])
    stages["reconcile_wave_0"] = "failure"
    outcome = select_catalog_engine_outcome(
        **_base(
            stage_results=stages,
            recovery_statuses=("blocked",),
            final_evidence_artifact=None,
            runtime_audit_artifact=None,
            science_evidence_artifact=None,
            failure_reason_code="BLOCKED_EXTERNAL_INTERVENTION",
        )
    )
    assert outcome.state is CatalogEngineOutcomeState.BLOCKED
    assert outcome.reason_code == "BLOCKED_EXTERNAL_INTERVENTION"


def test_closed_scientific_failure_is_the_only_failed_state() -> None:
    stages = dict(_base()["stage_results"])
    stages["reduce"] = "skipped"
    stages["verify_terminal_science"] = "skipped"
    stages["audit_runtime"] = "success"
    outcome = select_catalog_engine_outcome(
        **_base(
            stage_results=stages,
            recovery_statuses=("failed_scientific",),
            final_evidence_artifact=None,
            science_evidence_artifact=None,
            terminal_failure_code="SCIENTIFIC_ENGINE_DETERMINISTIC_FAILURE",
            failure_reason_code="SCIENTIFIC_ENGINE_DETERMINISTIC_FAILURE",
        )
    )
    assert outcome.state is CatalogEngineOutcomeState.FAILED
    assert outcome.reason_code == "SCIENTIFIC_ENGINE_DETERMINISTIC_FAILURE"
