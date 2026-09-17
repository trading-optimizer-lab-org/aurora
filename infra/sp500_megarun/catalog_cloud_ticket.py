"""Ticket continuity for cloud intake; never infer generations from issue counts."""

from typing import Callable
from uuid import UUID

from .catalog_cloud_intake import AuthenticatedCloudIntentV1
from .catalog_cloud_replay import resolve_cloud_replay
from .catalog_fast_authority import FastAuthorityStateV1
from .catalog_lineage_transition import CatalogLineageTransitionV1
from .catalog_request_contract import CatalogLaunchTicketV1
from .catalog_requester_broker import _uuid7


def select_cloud_launch_ticket(
    *, authority: FastAuthorityStateV1, intent: AuthenticatedCloudIntentV1,
    campaign_definition_sha256: str, prompt_sha256: str,
    imported_ticket: CatalogLaunchTicketV1 | None,
    lineage_transition: CatalogLineageTransitionV1 | None = None,
    new_request_id: Callable[[], UUID] = _uuid7,
) -> CatalogLaunchTicketV1:
    """Preserve the verified cutover ticket or advance one cloud terminal.

    ``imported_ticket`` is obtained only from the protected, verified cutover
    package. This function cannot accredit that package or revoke a local
    sender. An absent initial ticket is an error, never a bootstrap trigger.
    An existing intent must take the replay branch before this is called.
    """
    if resolve_cloud_replay(authority, intent) is not None:
        raise ValueError("CATALOG_CLOUD_REPLAY_REQUIRED")
    prior = next((row for row in authority.emissions
                  if row.request.campaign_key == intent.campaign_key), None)
    owner = next((row for row in authority.campaigns
                  if row.request.campaign_key == intent.campaign_key), None)
    if prior is None:
        if imported_ticket is None:
            raise ValueError("CATALOG_CLOUD_CUTOVER_TICKET_REQUIRED")
        ticket = imported_ticket
    else:
        if (prior.state != "PUBLICADO" or owner is None
                or owner.terminal_receipt_sha256 is None
                or owner.owner_issue_number != prior.issue_number
                or owner.request != prior.request):
            raise ValueError("CATALOG_CAMPAIGN_BUSY")
        ticket = CatalogLaunchTicketV1(
            schema_version="1", request_id=str(new_request_id()),
            campaign_key=intent.campaign_key,
            launch_generation=owner.generation + 1,
            campaign_definition_sha256=campaign_definition_sha256,
            prompt_sha256=prompt_sha256,
            previous_terminal_request_sha256=owner.request.request_sha256,
        )
    if (ticket.campaign_key != intent.campaign_key
            or ticket.campaign_definition_sha256 != campaign_definition_sha256
            or ticket.prompt_sha256 != prompt_sha256):
        raise ValueError("CATALOG_CLOUD_TICKET_CONTEXT_MISMATCH")
    if owner is None:
        if ticket.launch_generation != 1 or ticket.previous_terminal_request_sha256 is not None:
            raise ValueError("CATALOG_CLOUD_TICKET_PREDECESSOR_INVALID")
    else:
        if (not owner.is_terminal or ticket.launch_generation != owner.generation + 1
                or ticket.previous_terminal_request_sha256 != owner.request.request_sha256
                or ticket.request_id == owner.request.request_id):
            raise ValueError("CATALOG_CLOUD_TICKET_PREDECESSOR_INVALID")
        context_changed = (
            ticket.campaign_definition_sha256 != owner.request.campaign_definition_sha256
            or ticket.prompt_sha256 != owner.request.prompt_sha256
        )
        if context_changed and (lineage_transition is None
                                or not lineage_transition.authorizes(owner.request, ticket)):
            raise ValueError("CATALOG_CLOUD_LINEAGE_TRANSITION_REQUIRED")
    return ticket
