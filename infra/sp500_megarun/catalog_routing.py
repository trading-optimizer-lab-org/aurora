"""Cheap fail-closed routing before privileged catalog admission work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aurora.infra.github_performance.contracts import canonical_sha256

from .catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityRecordV1,
    VerifiedAuthorityLedgerV1,
    select_campaign_authority,
)
from .catalog_controller import CatalogRequestQueueEvidenceV1
from .catalog_request_contract import FrozenModel, Sha256


_ACTIVE_STATES = frozenset(
    {
        AuthorityState.RESERVED,
        AuthorityState.RUNNING,
        AuthorityState.RECOVERING,
        AuthorityState.WAITING_RETRY,
    }
)


class CatalogRouteOutcome(str, Enum):
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    ADOPTED = "adopted"
    ELIGIBLE = "eligible"


class CatalogRoutingPrerequisitesV1(FrozenModel):
    """Bounded facts permitted before the privileged live audit."""

    schema_version: Literal["1"] = "1"
    observed_at: datetime
    request_verified: bool
    campaign_registered: bool
    protected_head_verified: bool
    authority_anchor_verified: bool
    ledger_mirrors_verified: bool
    request_receipt_tamper_free: bool = True
    authority_retry_evidence_verified: bool = True
    authority_retry_not_before: datetime | None = None
    lifecycle_tamper_free: bool
    snapshot_complete: bool
    snapshot_stable: bool
    validation_opened: bool = False
    locked_opened: bool = False
    active_owner_authority_ids: tuple[UUID, ...] = ()
    routing_snapshot_sha256: Sha256

    @field_validator("observed_at", "authority_retry_not_before")
    @classmethod
    def _require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_ROUTING_TIME_INVALID")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _require_canonical_owner_set(self) -> "CatalogRoutingPrerequisitesV1":
        if self.active_owner_authority_ids != tuple(
            sorted(set(self.active_owner_authority_ids), key=str)
        ):
            raise ValueError("CATALOG_ROUTING_OWNER_SET_INVALID")
        if (
            not self.authority_retry_evidence_verified
            and self.authority_retry_not_before is not None
        ):
            raise ValueError("CATALOG_ROUTING_RETRY_EVIDENCE_INVALID")
        return self


class CatalogRoutingDecisionV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    outcome: CatalogRouteOutcome
    reason_code: str = Field(min_length=1, max_length=128)
    request_sha256: Sha256
    campaign_id: Sha256
    authority_id: UUID | None
    needs_live_audit: bool
    should_retry_delivery: bool
    route_sha256: Sha256

    @model_validator(mode="after")
    def _verify_shape_and_hash(self) -> "CatalogRoutingDecisionV1":
        expected_live_audit = self.outcome is CatalogRouteOutcome.ELIGIBLE
        if self.needs_live_audit is not expected_live_audit:
            raise ValueError("CATALOG_ROUTING_DECISION_SHAPE_INVALID")
        if self.should_retry_delivery is not (
            self.outcome is CatalogRouteOutcome.DEFERRED
        ):
            raise ValueError("CATALOG_ROUTING_DECISION_SHAPE_INVALID")
        identity = self.model_dump(mode="json", exclude={"route_sha256"})
        if canonical_sha256(identity) != self.route_sha256:
            raise ValueError("CATALOG_ROUTING_DECISION_HASH_INVALID")
        return self


class CatalogRoutingCommandV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    request_sha256: Sha256
    request_issue_number: int = Field(ge=1)
    campaign_id: Sha256
    queue: CatalogRequestQueueEvidenceV1
    ledger: VerifiedAuthorityLedgerV1
    prerequisites: CatalogRoutingPrerequisitesV1
    verified_github_now: datetime

    @field_validator("verified_github_now")
    @classmethod
    def _require_verified_github_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_ROUTING_TIME_INVALID")
        return value.astimezone(UTC)


def _decision(
    *,
    outcome: CatalogRouteOutcome,
    reason_code: str,
    request_sha256: str,
    campaign_id: str,
    authority: CatalogAuthorityRecordV1 | None = None,
) -> CatalogRoutingDecisionV1:
    identity = {
        "schema_version": "1",
        "outcome": outcome.value,
        "reason_code": reason_code,
        "request_sha256": request_sha256,
        "campaign_id": campaign_id,
        "authority_id": str(authority.authority_id) if authority is not None else None,
        "needs_live_audit": outcome is CatalogRouteOutcome.ELIGIBLE,
        "should_retry_delivery": outcome is CatalogRouteOutcome.DEFERRED,
    }
    return CatalogRoutingDecisionV1(
        **identity,
        route_sha256=canonical_sha256(identity),
    )


def _latest_authorities(
    ledger: VerifiedAuthorityLedgerV1,
) -> tuple[CatalogAuthorityRecordV1, ...]:
    latest: dict[UUID, CatalogAuthorityRecordV1] = {}
    for record in ledger.records:
        latest[record.authority_id] = record
    return tuple(latest[key] for key in sorted(latest, key=str))


def route_catalog_request(
    *,
    request_sha256: str,
    request_issue_number: int,
    campaign_id: str,
    queue: CatalogRequestQueueEvidenceV1,
    ledger: VerifiedAuthorityLedgerV1,
    prerequisites: CatalogRoutingPrerequisitesV1,
    verified_github_now: datetime,
) -> CatalogRoutingDecisionV1:
    """Route one request without source, capacity, secret, or compute access."""

    queue = CatalogRequestQueueEvidenceV1.model_validate(queue.model_dump(mode="json"))
    ledger = VerifiedAuthorityLedgerV1.model_validate(ledger.model_dump(mode="json"))
    prerequisites = CatalogRoutingPrerequisitesV1.model_validate(
        prerequisites.model_dump(mode="json")
    )
    if verified_github_now.tzinfo is None or verified_github_now.utcoffset() is None:
        raise ValueError("CATALOG_ROUTING_TIME_INVALID")
    now = verified_github_now.astimezone(UTC)
    age = now - prerequisites.observed_at
    failures: list[str] = []
    if age > timedelta(minutes=5) or age < -timedelta(seconds=30):
        failures.append("CATALOG_ROUTING_SNAPSHOT_STALE")
    if not prerequisites.request_verified:
        failures.append("CATALOG_REQUEST_INVALID")
    if not prerequisites.campaign_registered:
        failures.append("CATALOG_CAMPAIGN_NOT_REGISTERED")
    if not prerequisites.protected_head_verified:
        failures.append("CATALOG_PROTECTED_HEAD_INVALID")
    if not prerequisites.authority_anchor_verified:
        failures.append("CATALOG_AUTHORITY_ANCHOR_INVALID")
    if not prerequisites.ledger_mirrors_verified:
        failures.append("CATALOG_LEDGER_INVALID")
    if not prerequisites.request_receipt_tamper_free:
        failures.append("CATALOG_REQUEST_RECEIPT_TAMPERED")
    if not prerequisites.authority_retry_evidence_verified:
        failures.append("CATALOG_RETRY_SCHEDULE_UNVERIFIED")
    if not prerequisites.lifecycle_tamper_free:
        failures.append("CATALOG_AUTHORITY_LIFECYCLE_TAMPERED")
    if not prerequisites.snapshot_complete or not queue.complete:
        failures.append("CATALOG_ROUTING_SNAPSHOT_INCOMPLETE")
    if not prerequisites.snapshot_stable or not queue.stable:
        failures.append("CATALOG_ROUTING_SNAPSHOT_UNSTABLE")
    if prerequisites.validation_opened or prerequisites.locked_opened:
        failures.append("CATALOG_CLOSED_DATA_BOUNDARY_OPEN")
    if (
        queue.status != "ready"
        or queue.current_issue_number != request_issue_number
        or request_issue_number not in queue.eligible_open_issue_numbers
    ):
        failures.append("CATALOG_REQUEST_QUEUE_INVALID")
    if failures:
        return _decision(
            outcome=CatalogRouteOutcome.BLOCKED,
            reason_code=failures[0],
            request_sha256=request_sha256,
            campaign_id=campaign_id,
        )

    matching = select_campaign_authority(ledger, campaign_id)
    active_owners = set(prerequisites.active_owner_authority_ids)
    if matching is not None:
        if (
            matching.state is AuthorityState.WAITING_RETRY
            and prerequisites.authority_retry_not_before is not None
            and prerequisites.authority_retry_not_before > now
        ):
            return _decision(
                outcome=CatalogRouteOutcome.DEFERRED,
                reason_code="CATALOG_RETRY_NOT_DUE",
                request_sha256=request_sha256,
                campaign_id=campaign_id,
                authority=matching,
            )
        if matching.state is AuthorityState.SUCCESS:
            return _decision(
                outcome=CatalogRouteOutcome.ADOPTED,
                reason_code="CATALOG_SUCCESS_ALREADY_EXISTS",
                request_sha256=request_sha256,
                campaign_id=campaign_id,
                authority=matching,
            )
        if matching.state in _ACTIVE_STATES and matching.authority_id in active_owners:
            return _decision(
                outcome=CatalogRouteOutcome.ADOPTED,
                reason_code="CATALOG_ACTIVE_AUTHORITY_ADOPTED",
                request_sha256=request_sha256,
                campaign_id=campaign_id,
                authority=matching,
            )
        if matching.state in {AuthorityState.FAILED, AuthorityState.BLOCKED}:
            return _decision(
                outcome=CatalogRouteOutcome.BLOCKED,
                reason_code="CATALOG_TERMINAL_AUTHORITY_NOT_RELAUNCHED",
                request_sha256=request_sha256,
                campaign_id=campaign_id,
                authority=matching,
            )
        return _decision(
            outcome=CatalogRouteOutcome.ELIGIBLE,
            reason_code="CATALOG_RECOVERY_AUDIT_REQUIRED",
            request_sha256=request_sha256,
            campaign_id=campaign_id,
            authority=matching,
        )

    if any(record.state in _ACTIVE_STATES for record in _latest_authorities(ledger)):
        return _decision(
            outcome=CatalogRouteOutcome.DEFERRED,
            reason_code="CATALOG_WAITING_FOR_ACTIVE_CAMPAIGN",
            request_sha256=request_sha256,
            campaign_id=campaign_id,
        )
    if queue.eligible_open_issue_numbers[0] != request_issue_number:
        return _decision(
            outcome=CatalogRouteOutcome.DEFERRED,
            reason_code="CATALOG_WAITING_FOR_EARLIER_REQUEST",
            request_sha256=request_sha256,
            campaign_id=campaign_id,
        )
    return _decision(
        outcome=CatalogRouteOutcome.ELIGIBLE,
        reason_code="CATALOG_LIVE_AUDIT_REQUIRED",
        request_sha256=request_sha256,
        campaign_id=campaign_id,
    )


def route_catalog_command(command: CatalogRoutingCommandV1) -> CatalogRoutingDecisionV1:
    checked = CatalogRoutingCommandV1.model_validate(command.model_dump(mode="json"))
    return route_catalog_request(
        request_sha256=checked.request_sha256,
        request_issue_number=checked.request_issue_number,
        campaign_id=checked.campaign_id,
        queue=checked.queue,
        ledger=checked.ledger,
        prerequisites=checked.prerequisites,
        verified_github_now=checked.verified_github_now,
    )


__all__ = [
    "CatalogRouteOutcome",
    "CatalogRoutingCommandV1",
    "CatalogRoutingDecisionV1",
    "CatalogRoutingPrerequisitesV1",
    "route_catalog_command",
    "route_catalog_request",
]
