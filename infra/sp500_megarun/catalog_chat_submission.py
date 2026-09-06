"""Bind an authenticated chat intent before using the existing locked spool.

This library is not an authentication boundary. Only the protected consumer may
call it; the installed entry must validate its OS identity and fixed state ACLs.
It neither launches processes nor obtains network credentials.
"""

from datetime import datetime
from pathlib import Path
import re

from .catalog_chat_intent import (
    CHAT_INTENT_ID_PATTERN, CatalogChatIntentV1, _ensure_matching_binding,
    _read_existing_binding, load_or_bind_chat_intent,
)
from .catalog_request_contract import CatalogRunIntentDraftV1, canonical_model_bytes
from .catalog_requester import (
    CatalogRequesterConfigV1,
    CatalogRequesterReceiptV1,
    _fixed_directory,
    _load_fresh_broker_capacity,
    _load_verified_production_seal,
    _read_campaign_status,
    _read_existing_receipt,
    _require_utc,
    _strict_json_object,
    build_registered_catalog_draft,
    submit_catalog_intent_to_spool,
)


def submit_registered_chat_intent(
    *, broker_root: Path, intent: CatalogChatIntentV1, observed_at: datetime,
) -> CatalogRequesterReceiptV1:
    """Return promptly, keeping an immutable request identity across retries."""
    now = _require_utc(observed_at)
    checked = CatalogChatIntentV1.model_validate_json(canonical_model_bytes(intent))
    root = _fixed_directory(broker_root)
    config = CatalogRequesterConfigV1.model_validate(_strict_json_object(
        root / "config/catalog_requester_v1.json", maximum_bytes=32768,
    ))
    # The normal chat path cannot bootstrap itself or bypass a revoked seal.
    if checked.campaign_key == config.bootstrap_qualification.campaign_key:
        raise ValueError("CHAT_BOOTSTRAP_CAMPAIGN_FORBIDDEN")
    _load_verified_production_seal(broker_root=root, config=config)

    def resolve_draft() -> CatalogRunIntentDraftV1:
        status_path = root / config.broker.campaign_status / f"{checked.campaign_key}.status.json"
        if status_path.exists() or status_path.is_symlink():
            status = _read_campaign_status(path=status_path, campaign_key=checked.campaign_key)
            if status.state != "ticket_available":
                raise ValueError("CHAT_CAMPAIGN_TICKET_NOT_AVAILABLE")
        observed_config, draft = build_registered_catalog_draft(
            broker_root=root, campaign_key=checked.campaign_key,
        )
        if observed_config != config:
            raise ValueError("REQUESTER_CONFIG_CHANGED_DURING_READ")
        return draft

    binding = load_or_bind_chat_intent(
        state_dir=root / "chat-intents", intent=checked, resolve_draft=resolve_draft,
    )
    existing = _read_existing_receipt(
        path=root / config.broker.receipts / f"{binding.draft.submission_key_sha256}.receipt.json",
        draft=binding.draft,
    )
    if existing is not None:
        return existing
    capacity = _load_fresh_broker_capacity(root=root, config=config, observed_at=now)
    return submit_catalog_intent_to_spool(
        draft=binding.draft, inbox=root / config.broker.inbox,
        receipts=root / config.broker.receipts, capacity=capacity, observed_at=now,
    )


def read_bound_chat_receipt(*, broker_root: Path, intent_id: str) -> CatalogRequesterReceiptV1 | None:
    """Observe an already-bound request, never create a binding or enqueue.

    Observation remains available when admission is disarmed; no production
    permission is acquired or exercised by this read-only operation.
    """
    if not isinstance(intent_id, str) or re.fullmatch(CHAT_INTENT_ID_PATTERN, intent_id) is None:
        raise ValueError("CHAT_INTENT_ID_INVALID")
    root = _fixed_directory(broker_root)
    binding = _read_existing_binding(_fixed_directory(root / "chat-intents") / f"{intent_id}.json")
    if binding is None:
        raise ValueError("CHAT_INTENT_NOT_BOUND")
    if binding.intent.intent_id != intent_id:
        raise ValueError("CHAT_INTENT_ID_MISMATCH")
    _ensure_matching_binding(binding, binding.intent)
    config = CatalogRequesterConfigV1.model_validate(_strict_json_object(
        root / "config/catalog_requester_v1.json", maximum_bytes=32768,
    ))
    return _read_existing_receipt(
        path=_fixed_directory(root / config.broker.receipts) / f"{binding.draft.submission_key_sha256}.receipt.json",
        draft=binding.draft,
    )
