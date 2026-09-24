"""Bind a validated event to its existing durable intent before ticket access."""

from .catalog_cloud_emission import CatalogCloudCompletedIntentV1, CatalogCloudEmissionV1
from .catalog_cloud_intake import AuthenticatedCloudIntentV1, is_prevalidated_unstaged_atlas_intent
from .catalog_fast_authority import FastAuthorityStateV1


def resolve_cloud_replay(
    authority: FastAuthorityStateV1, intent: AuthenticatedCloudIntentV1,
) -> CatalogCloudEmissionV1 | CatalogCloudCompletedIntentV1 | None:
    """Return the same request binding, never create a generation or signature.

    Both arguments must have been obtained through their production validators.
    A reused UUID from a different issue/actor is a conflict, not a new intent.
    A resume can read existing history. Only the protected, previously validated
    Atlas issue may recover its unstaged first emission.
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
    for superseded_emission in (
            *(item.emission for item in authority.recovery_superseded_intents),
            *(item.emission for item in authority.unreserved_superseded_intents)):
        # It remains a published request, never a fabricated completed intent.
        if superseded_emission.intent_id == intent.intent_id:
            candidates.append(superseded_emission)
    if not candidates:
        if intent.is_resume and not is_prevalidated_unstaged_atlas_intent(intent):
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
