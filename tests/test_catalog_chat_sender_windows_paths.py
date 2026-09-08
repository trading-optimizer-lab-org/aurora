"""Real Windows ACL coverage for the public chat-intent sender."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import stat
import subprocess

import pytest

from aurora.infra.sp500_megarun.catalog_chat_intent import CatalogChatIntentV1, parse_chat_intent
from aurora.infra.sp500_megarun.catalog_chat_sender import enqueue_chat_intent


INTENT = CatalogChatIntentV1(
    schema_version="1",
    campaign_key="sp500-optimized-catalog-v1",
    intent_id="018f47a2-6e91-4c34-8000-000000000002",
)


class _DaclSnapshot:
    """Keep a DACL and its protection state alive for semantic restoration."""

    _SE_FILE_OBJECT = 1
    _DACL_SECURITY_INFORMATION = 0x00000004
    _UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
    _PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
    _SE_DACL_PROTECTED = 0x1000
    _ACL_SIZE_INFORMATION = 2

    def __init__(self, path: Path) -> None:
        advapi32 = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
        get_named_security_info = advapi32.GetNamedSecurityInfoW
        get_named_security_info.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        get_named_security_info.restype = ctypes.c_uint

        self._descriptor = ctypes.c_void_p()
        self._dacl = ctypes.c_void_p()
        result = get_named_security_info(
            str(path),
            self._SE_FILE_OBJECT,
            self._DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(self._dacl),
            None,
            ctypes.byref(self._descriptor),
        )
        if result:
            raise getattr(ctypes, "WinError")(result)
        self._path = path
        self._original_state = self._descriptor_state(self._descriptor)

    @classmethod
    def _descriptor_state(
        cls, descriptor: ctypes.c_void_p
    ) -> tuple[int, bool, bool, bytes | None]:
        advapi32 = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
        get_control = advapi32.GetSecurityDescriptorControl
        get_control.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ushort),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        get_control.restype = ctypes.c_int
        control = ctypes.c_ushort()
        revision = ctypes.c_ulong()
        if not get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())

        get_dacl = advapi32.GetSecurityDescriptorDacl
        get_dacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_int),
        ]
        get_dacl.restype = ctypes.c_int
        dacl_present = ctypes.c_int()
        dacl = ctypes.c_void_p()
        dacl_defaulted = ctypes.c_int()
        if not get_dacl(
            descriptor,
            ctypes.byref(dacl_present),
            ctypes.byref(dacl),
            ctypes.byref(dacl_defaulted),
        ):
            raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())

        dacl_bytes: bytes | None = None
        if dacl:
            class AclSizeInformation(ctypes.Structure):
                _fields_ = [
                    ("AceCount", ctypes.c_ulong),
                    ("AclBytesInUse", ctypes.c_ulong),
                    ("AclBytesFree", ctypes.c_ulong),
                ]

            get_acl_information = advapi32.GetAclInformation
            get_acl_information.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_int,
            ]
            get_acl_information.restype = ctypes.c_int
            size = AclSizeInformation()
            if not get_acl_information(
                dacl,
                ctypes.byref(size),
                ctypes.sizeof(size),
                cls._ACL_SIZE_INFORMATION,
            ):
                raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
            dacl_bytes = ctypes.string_at(dacl, size.AclBytesInUse)
        return (
            control.value,
            bool(dacl_present.value),
            bool(dacl_defaulted.value),
            dacl_bytes,
        )

    @classmethod
    def _read_descriptor(cls, path: Path) -> tuple[ctypes.c_void_p, ctypes.c_void_p]:
        advapi32 = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
        get_named_security_info = advapi32.GetNamedSecurityInfoW
        get_named_security_info.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        get_named_security_info.restype = ctypes.c_uint
        descriptor = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        result = get_named_security_info(
            str(path),
            cls._SE_FILE_OBJECT,
            cls._DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result:
            raise getattr(ctypes, "WinError")(result)
        return descriptor, dacl

    @staticmethod
    def _free_descriptor(descriptor: ctypes.c_void_p) -> None:
        if descriptor:
            kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
            local_free = kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            if local_free(descriptor):
                raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())

    def restore(self) -> None:
        advapi32 = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
        set_named_security_info = advapi32.SetNamedSecurityInfoW
        set_named_security_info.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        set_named_security_info.restype = ctypes.c_uint
        security_information = self._DACL_SECURITY_INFORMATION | (
            self._PROTECTED_DACL_SECURITY_INFORMATION
            if self._original_state[0] & self._SE_DACL_PROTECTED
            else self._UNPROTECTED_DACL_SECURITY_INFORMATION
        )
        result = set_named_security_info(
            str(self._path),
            self._SE_FILE_OBJECT,
            security_information,
            None,
            None,
            self._dacl,
            None,
        )
        if result:
            raise getattr(ctypes, "WinError")(result)

    def verify_restored(self) -> None:
        descriptor, _ = self._read_descriptor(self._path)
        try:
            restored = self._descriptor_state(descriptor)
        finally:
            self._free_descriptor(descriptor)
        assert bool(restored[0] & self._SE_DACL_PROTECTED) == bool(
            self._original_state[0] & self._SE_DACL_PROTECTED
        )
        assert restored[1:] == self._original_state[1:]

    def close(self) -> None:
        if self._descriptor:
            self._free_descriptor(self._descriptor)
            self._descriptor = ctypes.c_void_p()


def _icacls_path() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "icacls.exe"


def _current_user_sid() -> str:
    result = subprocess.run(
        ["whoami.exe", "/user"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "whoami /user failed")
    matches = re.findall(r"S-\d-(?:\d+-)+\d+", result.stdout)
    if len(matches) != 1:
        raise RuntimeError(f"could not identify one current-user SID: {result.stdout!r}")
    return matches[0]


def _icacls(tool: Path, *arguments: object) -> None:
    result = subprocess.run(
        [str(tool), *(str(argument) for argument in arguments)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"icacls failed with {result.returncode}: {detail}")


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows ACL semantics")
def test_public_sender_publishes_one_closed_intent_with_private_parent(tmp_path: Path) -> None:
    tool = _icacls_path()
    if not tool.is_file():
        pytest.skip("icacls.exe is unavailable; exact Windows ACL setup cannot be exercised")

    try:
        sid = _current_user_sid()
    except (OSError, RuntimeError) as exc:
        pytest.skip(f"cannot identify the current Windows SID without changing credentials: {exc}")

    root = tmp_path / "private-root"
    inbox = root / "chat-inbox"
    root.mkdir()
    inbox.mkdir()
    snapshots = [_DaclSnapshot(root), _DaclSnapshot(inbox)]

    try:
        try:
            # The child gets its own explicit ACL.  The parent grants only the
            # attributes and traverse rights needed to reach that child.
            _icacls(tool, inbox, "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F")
            _icacls(tool, root, "/inheritance:r", "/grant:r", f"*{sid}:(RA,X)")

            # Explicitly prove the security boundary before calling the public API.
            root.lstat()
            with pytest.raises(PermissionError) as denied:
                root.resolve(strict=True)
            assert getattr(denied.value, "winerror", None) == 5
            inbox.lstat()
            assert inbox.resolve(strict=True) == inbox.absolute()
        except (OSError, RuntimeError, AssertionError) as exc:
            pytest.skip(f"exact ACL precondition is unavailable without elevation: {exc}")

        result = enqueue_chat_intent(broker_root=root, intent=INTENT)
        assert result == {
            "status": "pending",
            "intent_id": INTENT.intent_id,
            "campaign_key": INTENT.campaign_key,
        }

        target = inbox / f"{INTENT.intent_id}.intent.json"
        entries = list(inbox.iterdir())
        assert [entry.name for entry in entries] == [target.name]
        info = target.lstat()
        assert stat.S_ISREG(info.st_mode)
        assert not getattr(info, "st_file_attributes", 0) & 0x400
        assert info.st_nlink == 1

        expected = json.dumps(
            INTENT.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        with target.open("rb") as stream:
            payload = stream.read()
        assert payload == expected
        assert parse_chat_intent(payload) == INTENT
    finally:
        restore_error: BaseException | None = None
        # Restore ancestors first so an originally unprotected child can
        # inherit the ancestor's original DACL again.
        for snapshot in snapshots:
            try:
                snapshot.restore()
                snapshot.verify_restored()
            except BaseException as exc:  # pragma: no cover - only ACL teardown failures
                restore_error = exc
            finally:
                snapshot.close()
        if restore_error is not None:
            raise restore_error
