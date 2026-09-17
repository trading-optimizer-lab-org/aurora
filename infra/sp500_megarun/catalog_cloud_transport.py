"""One-shot transport over the existing authenticated authority and App client.

The caller holds the shared admission lock. ``publish`` must complete the
existing authority edit/artifact publication; ``read`` must authenticate that
publication with the real provenance reader, not deserialize a local snapshot.
No retry, signing, ticket generation, or scientific dispatch lives here.
"""

from datetime import datetime
from typing import Callable

from .catalog_cloud_emission import CatalogCloudEmissionV1
from .catalog_fast_authority import FastAuthorityStateV1
from .catalog_request_contract import canonical_sha256
from .catalog_requester_broker import (
    CatalogBrokerGithubClient, CatalogBrokerProcessingRecordV1,
    reconcile_catalog_request_to_github, submit_catalog_request_to_github,
)
from .catalog_run_request import parse_catalog_run_request


def _processing_record(item: CatalogCloudEmissionV1, signed_at: datetime):
    # Reconstruct the envelope only; never re-sign persisted request bytes.
    unsigned = CatalogBrokerProcessingRecordV1.model_construct(
        schema_version="1", stage="signed_before_post", title=item.title,
        body=item.body, intent_sha256=item.request.intent_sha256,
        request_sha256=item.request.request_sha256, request=item.request,
        signed_at=signed_at, processing_record_sha256="0" * 64,
    )
    return CatalogBrokerProcessingRecordV1.model_validate({
        **unsigned.model_dump(mode="python"),
        "processing_record_sha256": canonical_sha256(unsigned),
    })


def deliver_cloud_emission(
    *, intent_id: str, run_id: int, run_attempt: int,
    read: Callable[[], FastAuthorityStateV1],
    publish: Callable[[FastAuthorityStateV1, FastAuthorityStateV1, str], None],
    client: CatalogBrokerGithubClient, trusted_public_key: bytes,
    post_lower_bound: datetime, post_upper_bound: datetime,
) -> CatalogCloudEmissionV1:
    """Persist uncertainty before exactly one POST, or reconcile an earlier one.

    Bounds must come from authenticated metadata of the recorded POST run, not
    the resume run. A failed publication or readback prevents the first POST.
    An ambiguous POST leaves the durable state uncertain even when no match is
    found; invoking this function again cannot turn that into another POST.
    """
    if (type(run_id) is not int or run_id < 1 or type(run_attempt) is not int
            or run_attempt < 1 or post_lower_bound.tzinfo is None
            or post_upper_bound.tzinfo is None or post_lower_bound > post_upper_bound):
        raise ValueError("CATALOG_CLOUD_TRANSPORT_CONTEXT_INVALID")
    current = read()
    matches = [item for item in current.emissions if item.intent_id == intent_id]
    if len(matches) != 1:
        raise ValueError("CATALOG_CLOUD_EMISSION_UNAVAILABLE")
    item = matches[0]
    if parse_catalog_run_request(item.title, item.body, trusted_public_key) != item.request:
        raise ValueError("CATALOG_CLOUD_REQUEST_INVALID")
    if item.state == "PUBLICADO":
        return item
    fresh = item.state == "SIGNED"
    if fresh:
        candidate = current.advance_emission(
            intent_id=intent_id, state="PUBLICACION_INCIERTA",
            post_run_id=run_id, post_run_attempt=run_attempt,
        )
        publish(current, candidate, "intake-uncertain")
        reopened = read()
        if reopened != candidate:
            raise ValueError("CATALOG_CLOUD_PUBLICATION_READBACK_MISMATCH")
        current, item = reopened, next(x for x in reopened.emissions if x.intent_id == intent_id)
    signed = _processing_record(item, post_lower_bound)
    # These existing consumers enforce exact bytes, actor, repository and time
    # bounds. Only this local branch reached immediately after publication may
    # POST; matching run IDs on a retry never confer permission to POST again.
    if fresh:
        receipt = submit_catalog_request_to_github(
            signed=signed, client=client, post_lower_bound=post_lower_bound,
            post_upper_bound=post_upper_bound,
        )
    else:
        receipt = reconcile_catalog_request_to_github(
            signed=signed, client=client, post_lower_bound=post_lower_bound,
            post_upper_bound=post_upper_bound,
        )
    candidate = current.advance_emission(
        intent_id=intent_id, state="PUBLICADO", issue_number=receipt.issue_number,
    )
    publish(current, candidate, "intake-published")
    reopened = read()
    if reopened != candidate:
        raise ValueError("CATALOG_CLOUD_PUBLICATION_READBACK_MISMATCH")
    return next(x for x in reopened.emissions if x.intent_id == intent_id)
