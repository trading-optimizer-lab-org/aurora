"""Strict, durable binding of a closed chat intent to one catalog draft.

``state_dir`` is an already-existing protected internal directory.  This
module deliberately does not create it, select it from sender input, or claim
that the operating system has authorized its owner.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Callable, Literal
from uuid import RFC_4122, UUID

from pydantic import ConfigDict, Field, StrictStr, ValidationError, field_validator

from .catalog_request_contract import (
    CAMPAIGN_KEY_PATTERN,
    CatalogRunIntentDraftV1,
    FrozenModel,
    canonical_model_bytes,
)


CHAT_INTENT_ID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
MAX_CHAT_INTENT_BYTES = 4096
MAX_BINDING_BYTES = 65536
_REPARSE_POINT = 0x0400


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


class CatalogChatIntentV1(FrozenModel):
    schema_version: Literal["1"]
    campaign_key: StrictStr = Field(pattern=CAMPAIGN_KEY_PATTERN, max_length=128)
    intent_id: StrictStr = Field(pattern=CHAT_INTENT_ID_PATTERN)

    @field_validator("intent_id")
    @classmethod
    def _require_canonical_uuid4(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 4 or parsed.variant != RFC_4122 or str(parsed) != value:
            raise ValueError("intent_id must be a canonical RFC 4122 UUIDv4")
        return value


class CatalogChatIntentBindingV1(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"]
    intent: CatalogChatIntentV1
    draft: CatalogRunIntentDraftV1


def _invalid(message: str, cause: BaseException | None = None) -> ValueError:
    error = ValueError(f"CHAT_INTENT_INVALID: {message}")
    if cause is not None:
        error.__cause__ = cause
    return error


def _parse_json_object(payload: bytes, *, max_bytes: int, label: str) -> dict[str, object]:
    if type(payload) is not bytes:
        raise _invalid(f"{label} payload must be bytes")
    if len(payload) > max_bytes:
        raise _invalid(f"{label} payload exceeds {max_bytes} bytes")
    try:
        text = payload.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _invalid(f"invalid {label} JSON", exc) from exc
    if type(value) is not dict:
        raise _invalid(f"{label} payload must be a JSON object")
    return value


def parse_chat_intent(payload: bytes) -> CatalogChatIntentV1:
    """Parse only the closed, non-executable chat intent shape."""

    raw = _parse_json_object(payload, max_bytes=MAX_CHAT_INTENT_BYTES, label="chat intent")
    try:
        return CatalogChatIntentV1.model_validate(raw, strict=True)
    except ValidationError as exc:
        raise _invalid("chat intent does not match schema", exc) from exc


def _parse_binding(payload: bytes) -> CatalogChatIntentBindingV1:
    raw = _parse_json_object(payload, max_bytes=MAX_BINDING_BYTES, label="binding")
    try:
        binding = CatalogChatIntentBindingV1.model_validate(raw, strict=True)
    except ValidationError as exc:
        raise _invalid("binding does not match schema", exc) from exc
    if canonical_model_bytes(binding) != payload:
        raise _invalid("binding bytes are not canonical")
    return binding


def _is_reparse(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _validate_state_dir(state_dir: Path) -> None:
    try:
        directory_stat = os.lstat(state_dir)
    except OSError as exc:
        raise _invalid("state directory must already exist", exc) from exc
    if (
        stat.S_ISLNK(directory_stat.st_mode)
        or _is_reparse(directory_stat)
        or not stat.S_ISDIR(directory_stat.st_mode)
    ):
        raise _invalid("state directory must be a non-reparse directory")


def _validate_binding_file(path: Path, file_stat: os.stat_result) -> None:
    if (
        stat.S_ISLNK(file_stat.st_mode)
        or _is_reparse(file_stat)
        or not stat.S_ISREG(file_stat.st_mode)
    ):
        raise _invalid(f"binding path is not a regular non-reparse file: {path.name}")


def _read_existing_binding(path: Path) -> CatalogChatIntentBindingV1 | None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _invalid("cannot inspect existing binding", exc) from exc
    _validate_binding_file(path, path_stat)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise _invalid("cannot open existing binding", exc) from exc
    try:
        opened_stat = os.fstat(fd)
        _validate_binding_file(path, opened_stat)
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            payload = handle.read(MAX_BINDING_BYTES + 1)
    finally:
        if fd != -1:
            os.close(fd)
    if len(payload) > MAX_BINDING_BYTES:
        raise _invalid(f"binding payload exceeds {MAX_BINDING_BYTES} bytes")
    return _parse_binding(payload)


def _ensure_matching_binding(
    binding: CatalogChatIntentBindingV1, intent: CatalogChatIntentV1
) -> CatalogChatIntentBindingV1:
    if binding.intent != intent or binding.intent.campaign_key != intent.campaign_key:
        raise _invalid("existing binding conflicts with the requested intent")
    if binding.draft.campaign_key != intent.campaign_key:
        raise _invalid("existing draft conflicts with the requested campaign")
    return binding


def _publish_binding_exclusively(source: str, target: Path) -> None:
    """Publish without replacement, requesting persistence from the OS.

    The caller already flushed the complete temporary file. Hardware/filesystem
    persistence remains an OS guarantee, not a simulated power-loss test.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        # WRITE_THROUGH only: never REPLACE_EXISTING, COPY_ALLOWED or delayed.
        if not move(source, str(target), 0x8):
            code = getattr(ctypes, "get_last_error")()
            if code in (80, 183):
                raise FileExistsError("binding already published")
            raise getattr(ctypes, "WinError")(code)
    else:
        os.link(source, target)
        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def load_or_bind_chat_intent(
    *,
    state_dir: Path,
    intent: CatalogChatIntentV1,
    resolve_draft: Callable[[], CatalogRunIntentDraftV1],
) -> CatalogChatIntentBindingV1:
    """Return the durable binding, creating it exactly once if absent.

    The existing binding is inspected before ``resolve_draft`` is called.  A
    complete temporary file is flushed and fsynced, then published exclusively
    with OS persistence requested; no replacement operation is used.
    """

    if not isinstance(intent, CatalogChatIntentV1):
        raise _invalid("intent must be CatalogChatIntentV1")
    try:
        intent = CatalogChatIntentV1.model_validate(intent.model_dump(mode="python"), strict=True)
    except ValidationError as exc:
        raise _invalid("intent does not match schema", exc) from exc
    if not isinstance(state_dir, Path):
        raise _invalid("state_dir must be a Path")
    _validate_state_dir(state_dir)
    final_path = state_dir / f"{intent.intent_id}.json"

    existing = _read_existing_binding(final_path)
    if existing is not None:
        return _ensure_matching_binding(existing, intent)

    draft = resolve_draft()
    if not isinstance(draft, CatalogRunIntentDraftV1):
        raise _invalid("resolve_draft must return CatalogRunIntentDraftV1")
    try:
        draft = CatalogRunIntentDraftV1.model_validate(draft.model_dump(mode="python"), strict=True)
    except ValidationError as exc:
        raise _invalid("resolved draft does not match schema", exc) from exc
    if draft.campaign_key != intent.campaign_key:
        raise _invalid("resolved draft conflicts with the requested campaign")

    binding = CatalogChatIntentBindingV1(schema_version="1", intent=intent, draft=draft)
    payload = canonical_model_bytes(binding)
    if len(payload) > MAX_BINDING_BYTES:
        raise _invalid(f"binding payload exceeds {MAX_BINDING_BYTES} bytes")

    _validate_state_dir(state_dir)
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{intent.intent_id}.", suffix=".tmp", dir=state_dir
        )
    except OSError as exc:
        raise _invalid("cannot create exclusive temporary binding", exc) from exc

    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            _publish_binding_exclusively(temp_name, final_path)
        except FileExistsError as exc:
            winner = _read_existing_binding(final_path)
            if winner is None:
                raise _invalid("binding disappeared after exclusive publish race") from exc
            return _ensure_matching_binding(winner, intent)
        except (OSError, NotImplementedError) as exc:
            raise _invalid("exclusive binding publish is unavailable", exc) from exc
        return binding
    finally:
        if fd != -1:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise _invalid("cannot remove own temporary binding", exc) from exc
