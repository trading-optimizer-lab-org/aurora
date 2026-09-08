"""Campaign-only service inside the verified requester client application.

The CLI must validate AURORAAgent, isolated runtime and application before entry.
The installer owns the fixed ancestors and config; only Agent/System/Admins may
write intent state and delivery replies, while HP may read replies/create input.
"""

from contextlib import contextmanager
from collections import OrderedDict
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from threading import Event
from typing import Iterator, Literal, Protocol
import ctypes
import os
import re

from pydantic import Field

from .catalog_chat_intent import CHAT_INTENT_ID_PATTERN, _parse_json_object, _read_existing_binding
from .catalog_chat_consumer import consume_authenticated_chat_file
from .catalog_chat_delivery import process_chat_delivery, _load_state, _InvalidState
from .catalog_chat_submission import read_bound_chat_receipt
from .catalog_chat_windows_input import (
    _BY_HANDLE_FILE_INFORMATION, _get_windows_api, read_authenticated_intent_file,
)
from .catalog_request_contract import FrozenModel
from .catalog_requester import _fixed_directory
from .catalog_requester import CatalogRequesterReceiptV1


class ChatServiceConfigV1(FrozenModel):
    schema_version: Literal["1"]
    sender_sid: str = Field(pattern=r"^S-1-5-21-(?:[0-9]+-){3}[0-9]+$", max_length=128)


_SCAN_BATCH_SIZE = 32
_TERMINAL_CACHE_SIZE = 1024
_TERMINAL_STATUSES = frozenset({"submitted", "existing", "blocked"})


class _ScandirIterator(Protocol):
    def __next__(self) -> os.DirEntry[str]: ...

    def close(self) -> None: ...


def _load_config(root: Path) -> ChatServiceConfigV1:
    config_dir = _fixed_directory(root / "config")
    payload = read_authenticated_intent_file(
        path=config_dir / "chat-entry-v1.json", expected_owner_sid="S-1-5-32-544",
    )
    return ChatServiceConfigV1.model_validate(
        _parse_json_object(payload, max_bytes=4096, label="chat service config"), strict=True,
    )


def _assert_no_pending_prebound_chat_intents_locked(root: Path) -> None:
    """Read-only maintenance check; caller holds the service lock throughout writes.

    New campaign-only inbox files are intentionally preserved for the resumed
    service. Only already-bound intents can retain the ticket being migrated.
    """
    intents = _fixed_directory(root / "chat-intents")
    replies = _fixed_directory(root / "chat-replies")
    with os.scandir(intents) as entries:
        for entry in entries:
            if entry.name == ".service.lock":
                continue
            if not entry.name.endswith(".json"):
                raise ValueError("CHAT_INTENT_STATE_INVALID")
            intent_id = entry.name[:-5]
            if re.fullmatch(CHAT_INTENT_ID_PATTERN, intent_id) is None:
                raise ValueError("CHAT_INTENT_STATE_INVALID")
            binding = _read_existing_binding(Path(entry.path))
            if binding is None or binding.intent.intent_id != intent_id:
                raise ValueError("CHAT_INTENT_STATE_INVALID")
            try:
                delivery = _load_state(replies / f"{intent_id}.delivery.json")
            except _InvalidState as exc:
                raise ValueError("CHAT_DELIVERY_STATE_INVALID") from exc
            if delivery is None or delivery.status not in _TERMINAL_STATUSES:
                raise ValueError("CHAT_INTENT_PENDING")


@contextmanager
def _exclusive_service_lock(root: Path) -> Iterator[None]:
    if os.name != "nt":
        raise ValueError("CHAT_SERVICE_WINDOWS_ONLY")
    state = _fixed_directory(root / "chat-intents")
    api = _get_windows_api()
    # OPEN_ALWAYS, no truncation; sharing zero holds a process-lifetime lock.
    handle = api.CreateFileW(
        str(state / ".service.lock"), 0x80000000 | 0x40000000, 0, None,
        4, 0x00200000 | 0x02000000, None,
    )
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        raise ValueError("CHAT_SERVICE_LOCK_UNAVAILABLE")
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if (
            api.GetFileType(handle) != 1
            or not api.GetFileInformationByHandle(handle, ctypes.byref(info))
            or info.dwFileAttributes & (0x10 | 0x400)
            or info.nNumberOfLinks != 1
            or info.nFileSizeHigh or info.nFileSizeLow
        ):
            raise ValueError("CHAT_SERVICE_LOCK_UNSAFE")
        yield
    finally:
        api.CloseHandle(handle)


def serve_chat_entry(*, broker_root: Path, _stop: Event | None = None) -> None:
    """Deliver new intents and observe pending ones without invoking a shell.

    `_stop` is an internal test/shutdown hook, never a public CLI parameter.
    The loop scans names only for already-completed deliveries, avoids reading
    their payloads again and never deletes sender files or terminal replies.
    """
    root = _fixed_directory(broker_root)
    config = _load_config(root)
    inbox = _fixed_directory(root / "chat-inbox")
    replies = _fixed_directory(root / "chat-replies")
    stop = _stop if _stop is not None else Event()
    with _exclusive_service_lock(root):
        terminal_cache: OrderedDict[str, None] = OrderedDict()
        iterators: list[_ScandirIterator | None] = [None, None]
        directories = ((replies, ".delivery.json"), (inbox, ".intent.json"))

        def close_iterator(index: int) -> None:
            entries = iterators[index]
            if entries is not None:
                entries.close()
                iterators[index] = None

        try:
            for index, (directory, _suffix) in enumerate(directories):
                iterators[index] = os.scandir(directory)

            while not stop.is_set():
                seen: set[str] = set()
                # Pending replies continue to be observed if input was removed.
                for index, (_directory, suffix) in enumerate(directories):
                    entries = iterators[index]
                    if entries is None:
                        entries = os.scandir(directories[index][0])
                        iterators[index] = entries
                    for _ in range(_SCAN_BATCH_SIZE):
                        if stop.is_set():
                            break
                        try:
                            entry = next(entries)
                        except StopIteration:
                            close_iterator(index)
                            break
                        if not entry.name.endswith(suffix):
                            continue
                        identifier = entry.name[:-len(suffix)]
                        if identifier in seen:
                            continue
                        if re.fullmatch(CHAT_INTENT_ID_PATTERN, identifier) is None:
                            continue
                        if identifier in terminal_cache:
                            terminal_cache.move_to_end(identifier)
                            continue
                        seen.add(identifier)

                        def observe_receipt(
                            previous: CatalogRequesterReceiptV1,
                            *,
                            _intent_id: str = identifier,
                        ) -> CatalogRequesterReceiptV1 | None:
                            return read_bound_chat_receipt(broker_root=root, intent_id=_intent_id)

                        delivery = process_chat_delivery(
                            reply_dir=replies, intent_id=identifier,
                            deliver=partial(consume_authenticated_chat_file,
                                broker_root=root, input_name=f"{identifier}.intent.json",
                                expected_sender_sid=config.sender_sid, observed_at=datetime.now(timezone.utc),
                            ),
                            observe=observe_receipt,
                        )
                        if delivery.status in _TERMINAL_STATUSES:
                            terminal_cache[identifier] = None
                            terminal_cache.move_to_end(identifier)
                            if len(terminal_cache) > _TERMINAL_CACHE_SIZE:
                                terminal_cache.popitem(last=False)
                stop.wait(2.0)
        finally:
            for index in range(len(iterators)):
                close_iterator(index)
