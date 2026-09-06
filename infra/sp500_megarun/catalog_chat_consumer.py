"""Consume one closed, authenticated input; lifecycle is owned by the service.

The installed entry supplies a fixed protected root and configured sender SID.
Neither parameter may come from the submitted JSON. This function does not
delete user input, launch processes, change credentials or install anything.
"""

from datetime import datetime
from pathlib import Path
import re

from .catalog_chat_intent import CHAT_INTENT_ID_PATTERN, parse_chat_intent
from .catalog_chat_submission import submit_registered_chat_intent
from .catalog_chat_windows_input import read_authenticated_intent_file
from .catalog_requester import CatalogRequesterReceiptV1, _fixed_directory


def consume_authenticated_chat_file(
    *, broker_root: Path, input_name: str, expected_sender_sid: str,
    observed_at: datetime,
) -> CatalogRequesterReceiptV1:
    """Authenticate and bind one intention before any request is submitted."""
    suffix = ".intent.json"
    if (
        not isinstance(input_name, str)
        or not input_name.endswith(suffix)
        or re.fullmatch(CHAT_INTENT_ID_PATTERN, input_name[:-len(suffix)]) is None
    ):
        raise ValueError("CHAT_INPUT_NAME_INVALID")
    root = _fixed_directory(broker_root)
    inbox = _fixed_directory(root / "chat-inbox")
    payload = read_authenticated_intent_file(
        path=inbox / input_name, expected_owner_sid=expected_sender_sid,
    )
    intent = parse_chat_intent(payload)
    if input_name != f"{intent.intent_id}{suffix}":
        raise ValueError("CHAT_INPUT_ID_MISMATCH")
    return submit_registered_chat_intent(
        broker_root=root, intent=intent, observed_at=observed_at,
    )
