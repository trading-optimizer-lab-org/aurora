"""Bind a validated event to its existing durable intent before ticket access."""

from .catalog_cloud_emission import CatalogCloudCompletedIntentV1, CatalogCloudEmissionV1
from .catalog_cloud_intake import AuthenticatedCloudIntentV1
from .catalog_fast_authority import FastAuthorityStateV1


def resolve_cloud_replay(
    authority: FastAuthorityStateV1, intent: AuthenticatedCloudIntentV1,
) -> CatalogCloudEmissionV1 | CatalogCloudCompletedIntentV1 | None:
    """Return the same request binding, never create a generation or signature.

    Both arguments must have been obtained through their production validators.
    A reused UUID from a different issue/actor is a conflict, not a new intent.
    A resume can read existing history but can never originate a new emission.
    """
    candidates: list[CatalogCloudEmissionV1 | CatalogCloudCompletedIntentV1] = []
    for emission_row in authority.emissions:
        if not isinstance(emission_row, CatalogCloudEmissionV1):
            raise ValueError("CATALOG_CLOUD_AUTHORITY_INVALID")
        if emission_row.intent_id == intent.intent_id:
            candidates.append(emission_row)
    for completed_row in authority.completed_intents:
        if not isinstance(completed_row, CatalogCloudCompletedIntentV1):
            raise ValueError("CATALOG_CLOUD_AUTHORITY_INVALID")
        if completed_row.intent_id == intent.intent_id:
            candidates.append(completed_row)
    if not candidates:
        if intent.is_resume:
            raise ValueError("CATALOG_CLOUD_RESUME_UNKNOWN")
        return None
    if len(candidates) != 1:
        raise ValueError("CATALOG_CLOUD_INTENT_CONFLICT")
    row: CatalogCloudEmissionV1 | CatalogCloudCompletedIntentV1 = candidates[0]
    if (row.intent_issue_number != intent.issue_number
            or row.repository_id != intent.repository_id
            or row.actor_id != intent.author_id
            or row.intent_sha256 != intent.intent_sha256):
        raise ValueError("CATALOG_CLOUD_INTENT_CONFLICT")
    return row
