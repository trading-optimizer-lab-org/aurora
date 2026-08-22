from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aurora.infra.sp500_megarun.catalog_controller import (
    CatalogRequestQueueEvidenceV1,
)
from aurora.infra.sp500_megarun.catalog_routing import (
    CatalogRouteOutcome,
    CatalogRoutingPrerequisitesV1,
    route_catalog_request,
)

from test_catalog_controller import _empty_ledger, _ledger_fixture, _queue_evidence


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
REQUEST_SHA256 = "a" * 64
CAMPAIGN_ID = "b" * 64


def _prerequisites(**updates: object) -> CatalogRoutingPrerequisitesV1:
    payload: dict[str, object] = {
        "observed_at": NOW,
        "request_verified": True,
        "campaign_registered": True,
        "protected_head_verified": True,
        "authority_anchor_verified": True,
        "ledger_mirrors_verified": True,
        "lifecycle_tamper_free": True,
        "snapshot_complete": True,
        "snapshot_stable": True,
        "validation_opened": False,
        "locked_opened": False,
        "active_owner_authority_ids": (),
        "routing_snapshot_sha256": "c" * 64,
    }
    payload.update(updates)
    return CatalogRoutingPrerequisitesV1.model_validate(payload)


def _route(
    *,
    issue_number: int = 101,
    queue: CatalogRequestQueueEvidenceV1 | None = None,
    ledger=None,
    prerequisites: CatalogRoutingPrerequisitesV1 | None = None,
):
    return route_catalog_request(
        request_sha256=REQUEST_SHA256,
        request_issue_number=issue_number,
        campaign_id=CAMPAIGN_ID,
        queue=queue or _queue_evidence(),
        ledger=ledger or _empty_ledger(),
        prerequisites=prerequisites or _prerequisites(),
        verified_github_now=NOW,
    )


def test_ninety_shuffled_requests_route_only_the_lowest_to_live_audit() -> None:
    issues = tuple(range(101, 191))
    job_order = issues[::2][::-1] + issues[1::2][::-1]
    decisions = []
    for issue_number in job_order:
        queue = _queue_evidence().model_copy(
            update={
                "current_issue_number": issue_number,
                "eligible_open_issue_numbers": issues,
            }
        )
        decisions.append((issue_number, _route(issue_number=issue_number, queue=queue)))

    privileged = [issue for issue, decision in decisions if decision.needs_live_audit]
    assert privileged == [issues[0]]
    waiting = [decision for issue, decision in decisions if issue != issues[0]]
    assert len(waiting) == 89
    assert all(decision.outcome is CatalogRouteOutcome.DEFERRED for decision in waiting)
    assert all(
        decision.reason_code == "CATALOG_WAITING_FOR_EARLIER_REQUEST"
        for decision in waiting
    )


def test_equivalent_active_authority_is_adopted_without_live_audit() -> None:
    ledger = _ledger_fixture(state="running", same_science=True)
    authority = ledger.latest
    assert authority is not None
    decision = route_catalog_request(
        request_sha256=REQUEST_SHA256,
        request_issue_number=101,
        campaign_id=authority.campaign_id,
        queue=_queue_evidence(),
        ledger=ledger,
        prerequisites=_prerequisites(
            active_owner_authority_ids=(authority.authority_id,)
        ),
        verified_github_now=NOW,
    )
    assert decision.outcome is CatalogRouteOutcome.ADOPTED
    assert decision.needs_live_audit is False
    assert decision.reason_code == "CATALOG_ACTIVE_AUTHORITY_ADOPTED"


def test_orphaned_equivalent_authority_routes_only_to_recovery_audit() -> None:
    ledger = _ledger_fixture(state="running", same_science=True)
    authority = ledger.latest
    assert authority is not None
    decision = route_catalog_request(
        request_sha256=REQUEST_SHA256,
        request_issue_number=101,
        campaign_id=authority.campaign_id,
        queue=_queue_evidence(),
        ledger=ledger,
        prerequisites=_prerequisites(),
        verified_github_now=NOW,
    )
    assert decision.outcome is CatalogRouteOutcome.ELIGIBLE
    assert decision.needs_live_audit is True
    assert decision.reason_code == "CATALOG_RECOVERY_AUDIT_REQUIRED"


def test_active_distinct_campaign_defers_without_live_audit() -> None:
    decision = _route(ledger=_ledger_fixture(state="running", same_science=False))
    assert decision.outcome is CatalogRouteOutcome.DEFERRED
    assert decision.needs_live_audit is False
    assert decision.reason_code == "CATALOG_WAITING_FOR_ACTIVE_CAMPAIGN"


def test_partial_or_tampered_routing_snapshot_blocks() -> None:
    partial = _route(prerequisites=_prerequisites(snapshot_complete=False))
    tampered = _route(prerequisites=_prerequisites(lifecycle_tamper_free=False))
    assert partial.outcome is CatalogRouteOutcome.BLOCKED
    assert partial.reason_code == "CATALOG_ROUTING_SNAPSHOT_INCOMPLETE"
    assert tampered.outcome is CatalogRouteOutcome.BLOCKED
    assert tampered.reason_code == "CATALOG_AUTHORITY_LIFECYCLE_TAMPERED"


def test_waiting_retry_authority_cannot_resume_before_its_sealed_deadline() -> None:
    ledger = _ledger_fixture(state="waiting_retry", same_science=True)
    authority = ledger.latest
    assert authority is not None
    early = route_catalog_request(
        request_sha256=REQUEST_SHA256,
        request_issue_number=101,
        campaign_id=authority.campaign_id,
        queue=_queue_evidence(),
        ledger=ledger,
        prerequisites=_prerequisites(
            authority_retry_not_before=NOW + timedelta(minutes=5),
            authority_retry_evidence_verified=True,
        ),
        verified_github_now=NOW,
    )
    assert early.outcome is CatalogRouteOutcome.DEFERRED
    assert early.reason_code == "CATALOG_RETRY_NOT_DUE"
    assert early.needs_live_audit is False


def test_waiting_retry_authority_resumes_when_due_but_not_without_evidence() -> None:
    ledger = _ledger_fixture(state="waiting_retry", same_science=True)
    authority = ledger.latest
    assert authority is not None
    due = route_catalog_request(
        request_sha256=REQUEST_SHA256,
        request_issue_number=101,
        campaign_id=authority.campaign_id,
        queue=_queue_evidence(),
        ledger=ledger,
        prerequisites=_prerequisites(
            authority_retry_not_before=NOW - timedelta(seconds=1),
            authority_retry_evidence_verified=True,
        ),
        verified_github_now=NOW,
    )
    missing = route_catalog_request(
        request_sha256=REQUEST_SHA256,
        request_issue_number=101,
        campaign_id=authority.campaign_id,
        queue=_queue_evidence(),
        ledger=ledger,
        prerequisites=_prerequisites(authority_retry_evidence_verified=False),
        verified_github_now=NOW,
    )
    assert due.outcome is CatalogRouteOutcome.ELIGIBLE
    assert due.reason_code == "CATALOG_RECOVERY_AUDIT_REQUIRED"
    assert missing.outcome is CatalogRouteOutcome.BLOCKED
    assert missing.reason_code == "CATALOG_RETRY_SCHEDULE_UNVERIFIED"
