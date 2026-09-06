"""Publish a campaign-only intention from the ordinary chat identity."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import stat
import tempfile

_BROKER_ROOT = Path("C:/ProgramData/AURORA/CatalogRequester")


def _checked_directory(path: Path) -> Path:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or path.resolve(strict=True) != path.absolute()):
        raise ValueError("CHAT_ENTRY_NOT_INSTALLED_OR_UNSAFE")
    return path


def _publish_exclusively(source: str, target: Path) -> None:
    if os.name == "nt":
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        move = api.MoveFileExW
        move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move.restype = ctypes.c_int
        if not move(source, str(target), 8): # WRITE_THROUGH, never REPLACE_EXISTING.
            code = ctypes.get_last_error()
            if code in (80, 183):
                raise FileExistsError(code, "CHAT_INPUT_EXISTS")
            raise OSError(code, "CHAT_INPUT_IO")
    else:
        os.link(source, target)
        handle = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def enqueue_chat_intent(*, broker_root: Path, intent: dict[str, str]) -> dict[str, str]:
    # This public emitter has no authority. The protected service revalidates
    # identity, schema and registered campaign through its existing strict model.
    if (set(intent) != {"schema_version", "campaign_key", "intent_id"}
            or any(type(value) is not str for value in intent.values())
            or intent["schema_version"] != "1"
            or len(intent["campaign_key"]) > 128
            or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+", intent["campaign_key"]) is None
            or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", intent["intent_id"]) is None):
        raise ValueError("CHAT_INPUT_INVALID")
    try:
        root = _checked_directory(broker_root)
        inbox = _checked_directory(root / "chat-inbox")
    except (OSError, ValueError) as exc:
        raise ValueError("CHAT_ENTRY_NOT_INSTALLED_OR_UNSAFE") from exc
    payload = json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("utf-8")
    target = inbox / f"{intent['intent_id']}.intent.json"
    fd, temporary = tempfile.mkstemp(prefix=f".{intent['intent_id']}.", suffix=".tmp", dir=inbox)
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            _publish_exclusively(temporary, target)
        except FileExistsError:
            info = target.lstat()
            if (not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                    or info.st_nlink != 1 or info.st_size > 4096):
                raise ValueError("CHAT_INPUT_CONFLICT")
            with target.open("rb") as source:
                existing = source.read(4097)
            if existing != payload:
                raise ValueError("CHAT_INPUT_CONFLICT")
    finally:
        if fd != -1:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return {"status": "pending", "intent_id": intent["intent_id"], "campaign_key": intent["campaign_key"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--intent-id", required=True)
    args = parser.parse_args()
    intent = {"schema_version": "1", "campaign_key": args.campaign_key, "intent_id": args.intent_id}
    result = enqueue_chat_intent(
        broker_root=_BROKER_ROOT, intent=intent,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
