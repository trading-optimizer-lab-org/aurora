"""Protected import of the public, quiescent local sender snapshot.

This is maintenance evidence, not a user-submitted cloud-qualified flag. The
export must be collected by the narrow administrative cutover operation and
reviewed into protected configuration. Until that actual operation is evidenced
and remote origin qualification passes, deployment must remain OFF. This module
does not stop a sender, copy a secret, or attest that an export actually ran.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .catalog_fast_authority import FastAuthorityStateV1
from .catalog_lineage_migration import prepare_available_lineage_models
from .catalog_lineage_transition import load_lineage_transition
from .catalog_request_contract import CatalogLaunchTicketV1, FrozenModel, Sha256, canonical_sha256
from .catalog_requester import CatalogRequesterCampaignStatusV1
from .catalog_requester_broker import CatalogBrokerTicketJournalV1


class CloudImportedCampaignV1(FrozenModel):
    journal: CatalogBrokerTicketJournalV1
    status: CatalogRequesterCampaignStatusV1

    @model_validator(mode="after")
    def _unused_ticket(self):
        ticket = self.journal.ticket
        if (self.journal.state != "available" or self.status.state != "ticket_available"
                or self.status.campaign_key != ticket.campaign_key
                or self.status.launch_generation != ticket.launch_generation
                or self.status.launch_ticket_sha256 != ticket.launch_ticket_sha256):
            raise ValueError("CATALOG_CLOUD_IMPORTED_TICKET_NOT_AVAILABLE")
        return self


class CloudLocalRetirementV1(FrozenModel):
    schema_version: Literal["1"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    observed_at: datetime
    task_name: Literal["AURORA Catalog Requester Broker"]
    task_state: Literal["Disabled"]
    running_instances: int = Field(strict=True, ge=0, le=0)
    inbox_pending_entries: int = Field(strict=True, ge=0, le=0)
    processing_pending_entries: int = Field(strict=True, ge=0, le=0)
    authority_state_sha256: Sha256
    campaigns: tuple[CloudImportedCampaignV1, ...] = Field(min_length=1, max_length=128)
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def _hash(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("CATALOG_CLOUD_RETIREMENT_TIME_INVALID")
        names = [row.journal.campaign_key for row in self.campaigns]
        if names != sorted(set(names)):
            raise ValueError("CATALOG_CLOUD_RETIREMENT_CAMPAIGNS_INVALID")
        if canonical_sha256(self.model_copy(update={"receipt_sha256": "0" * 64})) != self.receipt_sha256:
            raise ValueError("CATALOG_CLOUD_RETIREMENT_HASH_INVALID")
        if any(max(row.journal.updated_at, row.status.updated_at) > self.observed_at for row in self.campaigns):
            raise ValueError("CATALOG_CLOUD_RETIREMENT_TIME_INVALID")
        return self


def load_cloud_retirement(root: Path) -> CloudLocalRetirementV1:
    path = root / "config/catalog_cloud_local_retirement_v1.json"
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("CATALOG_CLOUD_RETIREMENT_PATH_INVALID")
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("CATALOG_CLOUD_LOCAL_RETIREMENT_REQUIRED") from exc
    if len(raw) > 256 * 1024:
        raise ValueError("CATALOG_CLOUD_RETIREMENT_INVALID")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("CATALOG_CLOUD_RETIREMENT_INVALID")
            result[key] = value
        return result
    payload = json.loads(raw, object_pairs_hook=unique)
    receipt = CloudLocalRetirementV1.model_validate(payload)
    if receipt.observed_at > datetime.now(timezone.utc):
        raise ValueError("CATALOG_CLOUD_RETIREMENT_TIME_INVALID")
    return receipt


def imported_cloud_ticket(
    *, root: Path, authority: FastAuthorityStateV1, campaign_key: str,
    campaign_definition_sha256: str, prompt_sha256: str,
) -> CatalogLaunchTicketV1 | None:
    retirement = load_cloud_retirement(root)
    if any(row.request.campaign_key == campaign_key for row in authority.emissions):
        return None
    rows = [row for row in retirement.campaigns if row.journal.campaign_key == campaign_key]
    if len(rows) != 1:
        raise ValueError("CATALOG_CLOUD_CUTOVER_TICKET_REQUIRED")
    row = rows[0]
    ticket = row.journal.ticket
    target = (campaign_definition_sha256, prompt_sha256)
    if (ticket.campaign_definition_sha256, ticket.prompt_sha256) == target:
        return ticket
    proposed = CatalogLaunchTicketV1.model_validate({
        **ticket.model_dump(mode="json"),
        "campaign_definition_sha256": campaign_definition_sha256,
        "prompt_sha256": prompt_sha256,
    })
    transition = load_lineage_transition(root, proposed)
    owner = next((owner for owner in authority.campaigns if owner.request.campaign_key == campaign_key), None)
    if transition is None or owner is None or not owner.is_terminal:
        raise ValueError("CATALOG_CLOUD_LINEAGE_TRANSITION_REQUIRED")
    migrated, _, _ = prepare_available_lineage_models(
        previous_request=owner.request, transition=transition, ticket=ticket,
        journal=row.journal, status=row.status, observed_at=retirement.observed_at,
    )
    if (migrated.campaign_definition_sha256, migrated.prompt_sha256) != target:
        raise ValueError("CATALOG_CLOUD_TICKET_CONTEXT_MISMATCH")
    return migrated
