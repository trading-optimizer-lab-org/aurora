"""Durable, local-only delivery state for one authenticated chat intent."""

from __future__ import annotations

from collections.abc import Callable
import ctypes
import json
import os
from pathlib import Path
import re
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from .catalog_request_contract import FrozenModel, canonical_model_bytes
from .catalog_requester import CatalogRequesterReceiptV1


_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_MAX_BYTES = 32_768
_TERMINAL = frozenset({"submitted", "existing", "blocked"})
_RETRYABLE_ERRORS = frozenset({"CHAT_INPUT_BUSY", "REQUEST_BROKER_CAPACITY_UNPROVEN"})


class ChatDeliveryV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    intent_id: str = Field(pattern=_UUID4.pattern)
    status: Literal["delivering", "retryable", "pending", "submitted", "existing", "blocked"]
    attempts: int = Field(ge=0, le=3)
    receipt: CatalogRequesterReceiptV1 | None
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @field_validator("intent_id")
    @classmethod
    def _canonical_uuid4(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (AttributeError, ValueError):
            raise ValueError("CHAT_DELIVERY_INTENT_ID_INVALID") from None
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("CHAT_DELIVERY_INTENT_ID_INVALID")
        return value

    @field_validator("reason_code")
    @classmethod
    def _closed_reason_code(cls, value: str) -> str:
        if not _CODE.fullmatch(value):
            raise ValueError("CHAT_DELIVERY_REASON_CODE_INVALID")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "ChatDeliveryV1":
        if self.status in {"submitted", "existing", "pending"}:
            if self.receipt is None or self.receipt.status != self.status:
                raise ValueError("CHAT_DELIVERY_RECEIPT_STATUS_INVALID")
        if self.status == "blocked" and self.receipt is not None and self.receipt.status != "blocked":
            raise ValueError("CHAT_DELIVERY_RECEIPT_STATUS_INVALID")
        return self


class _InvalidState(Exception):
    pass


class _PreservedTerminal(Exception):
    def __init__(self, state: ChatDeliveryV1) -> None:
        self.state = state


def _is_reparse(path: Path) -> bool:
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & 0x400)


def _safe_reply_dir(reply_dir: Path) -> Path:
    directory = Path(reply_dir)
    if directory.is_symlink() or _is_reparse(directory) or not directory.is_dir():
        raise ValueError("CHAT_DELIVERY_REPLY_DIR_INVALID")
    try:
        absolute = directory.absolute()
        if directory.resolve(strict=True) != absolute:
            raise ValueError("CHAT_DELIVERY_REPLY_DIR_INVALID")
    except (OSError, RuntimeError):
        raise ValueError("CHAT_DELIVERY_REPLY_DIR_INVALID") from None
    return absolute


def _target(reply_dir: Path, intent_id: str) -> Path:
    directory = _safe_reply_dir(reply_dir)
    path = directory / f"{intent_id}.delivery.json"
    if path.parent != directory:
        raise ValueError("CHAT_DELIVERY_TARGET_INVALID")
    return path


def _reject_target_link(path: Path) -> None:
    if path.is_symlink() or _is_reparse(path):
        raise _InvalidState


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError


def _load_state(path: Path) -> ChatDeliveryV1 | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        _reject_target_link(path)
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            raise _InvalidState
        data = path.read_bytes()
        if not data.endswith(b"\n"):
            raise _InvalidState
        payload = data[:-1]
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        state = ChatDeliveryV1.model_validate(raw)
        if path.name != f"{state.intent_id}.delivery.json":
            raise _InvalidState
        if canonical_model_bytes(state) != payload:
            raise _InvalidState
        return state
    except _InvalidState:
        raise
    except Exception:
        raise _InvalidState from None


def _atomic_replace(path: Path, data: bytes) -> None:
    temp = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    if temp.parent != path.parent or temp.exists() or temp.is_symlink() or _is_reparse(temp):
        raise OSError
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(temp, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.close(descriptor)
        descriptor = -1
        if os.name == "nt":
            move = getattr(ctypes, "windll").kernel32.MoveFileExW
            move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
            move.restype = ctypes.c_int
            if not move(str(temp), str(path), 9):
                raise OSError
        else:
            os.replace(temp, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temp.exists() and not temp.is_symlink() and not _is_reparse(temp):
            try:
                temp.unlink()
            except OSError:
                pass


def _persist_state(path: Path, state: ChatDeliveryV1) -> None:
    if path.parent != path.parent.absolute() or path.name != f"{state.intent_id}.delivery.json":
        raise ValueError("CHAT_DELIVERY_TARGET_INVALID")
    _safe_reply_dir(path.parent)
    current = _load_state(path)
    if current is not None and current.status in _TERMINAL:
        raise _PreservedTerminal(current)
    payload = canonical_model_bytes(state) + b"\n"
    if len(payload) > _MAX_BYTES:
        raise ValueError("CHAT_DELIVERY_STATE_TOO_LARGE")
    _atomic_replace(path, payload)


def _blocked(intent_id: str, attempts: int, reason_code: str) -> ChatDeliveryV1:
    return ChatDeliveryV1(
        intent_id=intent_id,
        status="blocked",
        attempts=min(max(attempts, 0), 3),
        receipt=None,
        reason_code=reason_code,
    )


def _exception_code(error: BaseException) -> str:
    candidate = getattr(error, "code", None)
    if not isinstance(candidate, str):
        candidate = str(error).split(":", 1)[0]
    return candidate if _CODE.fullmatch(candidate) else "CHAT_DELIVERY_INVALID_INPUT"


def _persist_or_block(path: Path, state: ChatDeliveryV1) -> ChatDeliveryV1 | None:
    try:
        _persist_state(path, state)
    except _PreservedTerminal as preserved:
        return preserved.state
    except Exception:
        return _blocked(state.intent_id, state.attempts, "CHAT_DELIVERY_IO")
    return None


def process_chat_delivery(
    *,
    reply_dir: Path,
    intent_id: str,
    deliver: Callable[[], CatalogRequesterReceiptV1],
    observe: Callable[[CatalogRequesterReceiptV1], CatalogRequesterReceiptV1 | None],
) -> ChatDeliveryV1:
    """Advance local delivery state; the protected service remains the sole writer."""
    if not _UUID4.fullmatch(intent_id):
        raise ValueError("CHAT_DELIVERY_INVALID_INPUT")
    try:
        if UUID(intent_id).version != 4 or str(UUID(intent_id)) != intent_id:
            raise ValueError
    except ValueError:
        raise ValueError("CHAT_DELIVERY_INVALID_INPUT") from None
    path = _target(reply_dir, intent_id)
    try:
        state = _load_state(path)
    except _InvalidState:
        return _blocked(intent_id, 0, "CHAT_DELIVERY_STATE_INVALID")
    if state is not None and state.status in _TERMINAL:
        return state
    if state is not None and state.status == "pending":
        if state.receipt is None:
            return _blocked(intent_id, state.attempts, "CHAT_DELIVERY_STATE_INVALID")
        try:
            observed = observe(state.receipt)
        except OSError:
            return state
        except (RuntimeError, ValueError) as error:
            code = _exception_code(error)
            blocked = _blocked(intent_id, state.attempts, code)
            return _persist_or_block(path, blocked) or blocked
        if observed is None:
            return state
        try:
            observed = CatalogRequesterReceiptV1.model_validate(
                observed.model_dump(mode="json")
            )
        except Exception:
            blocked = _blocked(intent_id, state.attempts, "CHAT_DELIVERY_INVALID_INPUT")
            return _persist_or_block(path, blocked) or blocked
        if any(
            getattr(observed, field) != getattr(state.receipt, field)
            for field in ("campaign_key", "request_id", "submission_key_sha256", "launch_generation")
        ):
            blocked = _blocked(intent_id, state.attempts, "CHAT_DELIVERY_RECEIPT_MISMATCH")
            return _persist_or_block(path, blocked) or blocked
        next_state = ChatDeliveryV1(
            intent_id=intent_id,
            status=observed.status,
            attempts=state.attempts,
            receipt=observed,
            reason_code=f"CHAT_DELIVERY_{observed.status.upper()}",
        )
        return _persist_or_block(path, next_state) or next_state

    attempts = state.attempts if state is not None else 0
    if attempts >= 3:
        blocked = _blocked(intent_id, attempts, "CHAT_DELIVERY_MAX_ATTEMPTS")
        return _persist_or_block(path, blocked) or blocked
    delivering = ChatDeliveryV1(
        intent_id=intent_id,
        status="delivering",
        attempts=attempts + 1,
        receipt=None,
        reason_code="CHAT_DELIVERY_ATTEMPTING",
    )
    persisted = _persist_or_block(path, delivering)
    if persisted is not None:
        return persisted
    try:
        delivered = deliver()
        receipt = CatalogRequesterReceiptV1.model_validate(delivered.model_dump(mode="json"))
        next_state = ChatDeliveryV1(
            intent_id=intent_id,
            status=receipt.status,
            attempts=delivering.attempts,
            receipt=receipt,
            reason_code=f"CHAT_DELIVERY_{receipt.status.upper()}",
        )
    except OSError:
        if delivering.attempts < 3:
            next_state = ChatDeliveryV1(
                intent_id=intent_id,
                status="retryable",
                attempts=delivering.attempts,
                receipt=None,
                reason_code="CHAT_DELIVERY_IO",
            )
        else:
            next_state = _blocked(intent_id, delivering.attempts, "CHAT_DELIVERY_IO")
    except (RuntimeError, ValueError) as error:
        code = _exception_code(error)
        if code in _RETRYABLE_ERRORS and delivering.attempts < 3:
            next_state = ChatDeliveryV1(
                intent_id=intent_id,
                status="retryable",
                attempts=delivering.attempts,
                receipt=None,
                reason_code=code,
            )
        else:
            next_state = _blocked(intent_id, delivering.attempts, code)
    except Exception:
        next_state = _blocked(intent_id, delivering.attempts, "CHAT_DELIVERY_INVALID_INPUT")
    return _persist_or_block(path, next_state) or next_state


__all__ = ["ChatDeliveryV1", "process_chat_delivery"]
