from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityCampaignV1, FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1, CatalogTerminalReceiptV1
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence
from aurora.tests.test_catalog_fast_reservation import _request
from scripts import admit_catalog_fast_request as admission


def _case():
    previous = _request()
    request = previous.model_copy(update={"launch_generation": 2,
        "request_id": "018f47a2-6e91-7c34-8000-000000000002",
        "previous_terminal_request_sha256": previous.request_sha256})
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED", reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256=previous.request_sha256, submission_key_sha256=previous.submission_key_sha256,
        campaign_key=previous.campaign_key, prepared_receipt_sha256="f" * 64,
        selected_workers=4, launch_required=True, existing_run_id=None,
        decided_at=now, expires_at=now + timedelta(minutes=30))
    owner = FastGateOwnerEvidence(run_id=17, decision=decision,
        run={"head_sha": "a" * 40, "run_attempt": 1, "status": "completed"})
    terminal = CatalogTerminalReceiptV1.create(
        state="BLOCKED", reason_code="CATALOG_REDUCTION_FAILED",
        request_sha256=previous.request_sha256, submission_key_sha256=previous.submission_key_sha256,
        campaign_key=previous.campaign_key, prepared_receipt_sha256="f" * 64,
        engine_run_id=17, run_url="https://github.com/trading-optimizer-lab-org/aurora/actions/runs/17",
        expected_recipe_count=2, observed_recipe_count=0, queue_seconds=0.0,
        preparation_seconds=0.0, computation_seconds=0.0, recovery_seconds=0.0,
        reduction_seconds=0.0, recovered_block_count=0, failure_class="infrastructure",
        result_science_sha256=None, created_at=now + timedelta(minutes=10))
    state = FastAuthorityStateV1.bootstrap(campaigns=(FastAuthorityCampaignV1(
        request=previous, owner_issue_number=23, owner_run_id=17,
        terminal_receipt_sha256=terminal.receipt_sha256),))
    profile = {"campaign_key": previous.campaign_key, "target_generation": 2,
        "source_request_sha256": previous.request_sha256, "source_issue_number": 23,
        "source_run_id": 17, "source_run_attempt": 1,
        "source_terminal_receipt_sha256": terminal.receipt_sha256,
        "strategy_ids": ["one", "two"],
        "source_plan_bindings": {"protected_commit_sha": "a" * 40,
                                 "decision_sha256": decision.decision_sha256}}
    return request, owner, terminal, state, profile


def _verify(monkeypatch, *, owner, terminal, state, request, profile):
    function = getattr(admission, "_require_reduction_recovery_predecessor", None)
    assert callable(function), "protected predecessor binding is missing"
    monkeypatch.setattr(admission, "load_owner_terminal_receipt", lambda **kwargs: terminal)
    return function(profile=profile, authority=state, request=request,
                    client=SimpleNamespace(), lookup_owner=lambda *args: owner,
                    download_archive=lambda artifact_id: b"unused")


def test_recovery_requires_exact_terminal_owner_and_does_not_change_authority(monkeypatch):
    request, owner, terminal, state, profile = _case()
    before = state.model_dump_json()
    _verify(monkeypatch, owner=owner, terminal=terminal, state=state, request=request, profile=profile)
    assert state.model_dump_json() == before


@pytest.mark.parametrize("field,value", [
    ("source_request_sha256", "0" * 64), ("source_run_id", 18),
    ("source_issue_number", 24), ("source_run_attempt", 2),
    ("source_terminal_receipt_sha256", "0" * 64), ("target_generation", 3),
    ("campaign_key", "other-campaign"), ("strategy_ids", ["one"]),
])
def test_recovery_rejects_profile_that_does_not_bind_predecessor(monkeypatch, field, value):
    request, owner, terminal, state, profile = _case()
    profile[field] = value
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_PREDECESSOR"):
        _verify(monkeypatch, owner=owner, terminal=terminal, state=state, request=request, profile=profile)


def test_recovery_rejects_unauthenticated_terminal(monkeypatch):
    request, owner, _terminal, state, profile = _case()
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_PREDECESSOR"):
        _verify(monkeypatch, owner=owner, terminal=None, state=state, request=request, profile=profile)


def test_recovery_rejects_active_owner(monkeypatch):
    request, owner, terminal, state, profile = _case()
    active = state.model_copy(update={"campaigns": (
        state.campaigns[0].model_copy(update={"terminal_receipt_sha256": None}),)})
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_PREDECESSOR"):
        _verify(monkeypatch, owner=owner, terminal=terminal, state=active, request=request, profile=profile)


@pytest.mark.parametrize("field,value", [
    ("reason_code", "CATALOG_SCIENCE_FAILED"), ("state", "SUCCESS"),
    ("engine_run_id", 18),
])
def test_recovery_never_reuses_a_different_terminal_kind(monkeypatch, field, value):
    request, owner, terminal, state, profile = _case()
    altered = terminal.model_copy(update={field: value})
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_PREDECESSOR"):
        _verify(monkeypatch, owner=owner, terminal=altered, state=state, request=request, profile=profile)
