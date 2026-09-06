"""Unprivileged publication of closed intents; never invokes the protected client."""

from pathlib import Path

from .catalog_chat_intent import CatalogChatIntentV1
from scripts.submit_catalog_chat_intent import enqueue_chat_intent as _publish_intent


def enqueue_chat_intent(*, broker_root: Path, intent: CatalogChatIntentV1) -> dict[str, str]:
    """Publish once and return immediately; pending is not run acceptance."""
    checked = CatalogChatIntentV1.model_validate(intent.model_dump(mode="python"), strict=True)
    return _publish_intent(broker_root=broker_root, intent=checked.model_dump(mode="json"))
