"""Read one already-enumerated chat intent file through a checked Win32 handle.

The caller must supply a path that was enumerated internally beneath a fixed,
protected parent ancestor.  This primitive does not resolve a public path,
choose a parent, inspect a username, or authorize a human.  It authenticates
the owner SID of the file object opened by this call; the protected parent ACL
and human authorization remain integration responsibilities.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any, Callable, NoReturn

from ctypes import wintypes


GENERIC_READ = 0x80000000
READ_CONTROL = 0x00020000
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

FILE_TYPE_DISK = 0x0001
FILE_ATTRIBUTE_DIRECTORY = 0x0010
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400

SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004

INHERIT_ONLY_ACE = 0x00000008

ACCESS_ALLOWED_ACE_TYPE = 0x00
ACCESS_DENIED_ACE_TYPE = 0x01
SYSTEM_AUDIT_ACE_TYPE = 0x02
ACCESS_ALLOWED_OBJECT_ACE_TYPE = 0x05
ACCESS_DENIED_OBJECT_ACE_TYPE = 0x06
SYSTEM_AUDIT_OBJECT_ACE_TYPE = 0x07
ACCESS_ALLOWED_CALLBACK_ACE_TYPE = 0x09
ACCESS_DENIED_CALLBACK_ACE_TYPE = 0x0A
ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE = 0x0B
ACCESS_DENIED_CALLBACK_OBJECT_ACE_TYPE = 0x0C
SYSTEM_AUDIT_CALLBACK_ACE_TYPE = 0x0D
SYSTEM_AUDIT_CALLBACK_OBJECT_ACE_TYPE = 0x0F
SYSTEM_MANDATORY_LABEL_ACE_TYPE = 0x11

FILE_WRITE_DATA = 0x0002
FILE_APPEND_DATA = 0x0004
FILE_WRITE_EA = 0x0010
FILE_WRITE_ATTRIBUTES = 0x0100
DELETE = 0x00010000
WRITE_DAC = 0x00040000
WRITE_OWNER = 0x00080000
GENERIC_WRITE = 0x40000000
GENERIC_ALL = 0x10000000

_DANGEROUS_WRITE_MASK = (
    FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_EA
    | FILE_WRITE_ATTRIBUTES
    | DELETE
    | WRITE_DAC
    | WRITE_OWNER
    | GENERIC_WRITE
    | GENERIC_ALL
)
_ALLOW_ACE_TYPES = {
    ACCESS_ALLOWED_ACE_TYPE,
    ACCESS_ALLOWED_OBJECT_ACE_TYPE,
    ACCESS_ALLOWED_CALLBACK_ACE_TYPE,
    ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE,
}
_DENY_ACE_TYPES = {
    ACCESS_DENIED_ACE_TYPE,
    ACCESS_DENIED_OBJECT_ACE_TYPE,
    ACCESS_DENIED_CALLBACK_ACE_TYPE,
    ACCESS_DENIED_CALLBACK_OBJECT_ACE_TYPE,
}
_NON_GRANT_ACE_TYPES = {
    SYSTEM_AUDIT_ACE_TYPE,
    SYSTEM_AUDIT_OBJECT_ACE_TYPE,
    SYSTEM_AUDIT_CALLBACK_ACE_TYPE,
    SYSTEM_AUDIT_CALLBACK_OBJECT_ACE_TYPE,
    SYSTEM_MANDATORY_LABEL_ACE_TYPE,
}
_OBJECT_ACE_TYPES = {
    ACCESS_ALLOWED_OBJECT_ACE_TYPE,
    ACCESS_DENIED_OBJECT_ACE_TYPE,
    ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE,
    ACCESS_DENIED_CALLBACK_OBJECT_ACE_TYPE,
}
_ACL_SIZE_INFORMATION_CLASS = 2
_ACE_OBJECT_TYPE_PRESENT = 0x00000001
_ACE_INHERITED_OBJECT_TYPE_PRESENT = 0x00000002

ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33

MAX_INTENT_BYTES = 4096
READ_BUFFER_BYTES = MAX_INTENT_BYTES + 1
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    )


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    )


class _ACE_HEADER(ctypes.Structure):
    _fields_ = (
        ("AceType", wintypes.BYTE),
        ("AceFlags", wintypes.BYTE),
        ("AceSize", wintypes.WORD),
    )


class ChatWindowsInputError(ValueError):
    """Fixed-code public error with optional Win32 error metadata."""

    def __init__(self, code: str, winerror: int | None = None) -> None:
        self.code = code
        self.winerror = winerror
        suffix = "" if winerror is None else f":{winerror}"
        super().__init__(f"{code}{suffix}")


class _WindowsApi:
    CreateFileW: Callable[..., Any]
    GetFileType: Callable[..., Any]
    GetFileInformationByHandle: Callable[..., Any]
    ReadFile: Callable[..., Any]
    CloseHandle: Callable[..., Any]
    LocalFree: Callable[..., Any]
    GetSecurityInfo: Callable[..., Any]
    EqualSid: Callable[..., Any]
    ConvertStringSidToSidW: Callable[..., Any]
    GetAclInformation: Callable[..., Any]
    GetAce: Callable[..., Any]


_API: _WindowsApi | None = None


def _configure_api() -> _WindowsApi:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    kernel32.CreateFileW.argtypes = (
        ctypes.c_wchar_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.GetFileType.argtypes = (ctypes.c_void_p,)
    kernel32.GetFileType.restype = wintypes.DWORD
    kernel32.GetFileInformationByHandle.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    )
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p

    advapi32.GetSecurityInfo.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = (
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
    )
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetAce.restype = wintypes.BOOL

    api = _WindowsApi()
    api.CreateFileW = kernel32.CreateFileW
    api.GetFileType = kernel32.GetFileType
    api.GetFileInformationByHandle = kernel32.GetFileInformationByHandle
    api.ReadFile = kernel32.ReadFile
    api.CloseHandle = kernel32.CloseHandle
    api.LocalFree = kernel32.LocalFree
    api.GetSecurityInfo = advapi32.GetSecurityInfo
    api.EqualSid = advapi32.EqualSid
    api.ConvertStringSidToSidW = advapi32.ConvertStringSidToSidW
    api.GetAclInformation = advapi32.GetAclInformation
    api.GetAce = advapi32.GetAce
    return api


def _get_windows_api() -> _WindowsApi:
    global _API
    if _API is None:
        try:
            _API = _configure_api()
        except OSError as exc:
            raise ChatWindowsInputError(
                "CHAT_INPUT_API_UNAVAILABLE", getattr(exc, "winerror", None)
            ) from None
    return _API


def _raise(code: str, winerror: int | None = None) -> NoReturn:
    raise ChatWindowsInputError(code, winerror)


def _valid_handle(handle: object) -> bool:
    value = getattr(handle, "value", handle)
    return value is not None and value != _INVALID_HANDLE_VALUE


def _validate_internal_path(path: Path) -> str:
    if not isinstance(path, Path):
        _raise("CHAT_INPUT_PATH_INVALID")
    try:
        path_text = str(path)
        if not path.is_absolute():
            _raise("CHAT_INPUT_PATH_INVALID")
        if path_text.startswith(("\\\\", "//")):
            _raise("CHAT_INPUT_PATH_INVALID")
        if path_text.lower().startswith(("\\device\\", "/device/")):
            _raise("CHAT_INPUT_PATH_INVALID")
        # The drive-letter colon is the only colon permitted in a Win32 path.
        if len(path_text) > 1 and ":" in path_text[2:]:
            _raise("CHAT_INPUT_PATH_INVALID")
        if any(part in {".", ".."} for part in path.parts):
            _raise("CHAT_INPUT_PATH_INVALID")
    except (OSError, ValueError, TypeError):
        _raise("CHAT_INPUT_PATH_INVALID")
    return path_text


def _convert_expected_sid(api: _WindowsApi, expected_owner_sid: str) -> ctypes.c_void_p:
    if not isinstance(expected_owner_sid, str) or not expected_owner_sid:
        _raise("CHAT_INPUT_OWNER_INVALID")
    sid_pointer = ctypes.c_void_p()
    try:
        converted = api.ConvertStringSidToSidW(
            expected_owner_sid, ctypes.byref(sid_pointer)
        )
    except (OSError, TypeError, ValueError):
        _raise("CHAT_INPUT_OWNER_INVALID", ctypes.get_last_error())
    if not converted or not sid_pointer.value:
        _raise("CHAT_INPUT_OWNER_INVALID", ctypes.get_last_error())
    return sid_pointer


def _file_information(api: _WindowsApi, handle: object) -> int:
    file_type = api.GetFileType(handle)
    if file_type != FILE_TYPE_DISK:
        _raise("CHAT_INPUT_NOT_DISK", ctypes.get_last_error())

    information = _BY_HANDLE_FILE_INFORMATION()
    if not api.GetFileInformationByHandle(handle, ctypes.byref(information)):
        _raise("CHAT_INPUT_INFO_FAILED", ctypes.get_last_error())
    attributes = information.dwFileAttributes
    if attributes & FILE_ATTRIBUTE_DIRECTORY:
        _raise("CHAT_INPUT_NOT_FILE")
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        _raise("CHAT_INPUT_REPARSE")
    if information.nNumberOfLinks != 1:
        _raise("CHAT_INPUT_HARDLINK")
    size = (information.nFileSizeHigh << 32) | information.nFileSizeLow
    if size == 0:
        _raise("CHAT_INPUT_EMPTY")
    if size > MAX_INTENT_BYTES:
        _raise("CHAT_INPUT_SIZE_INVALID")
    return size


def _check_dacl(api: _WindowsApi, dacl: ctypes.c_void_p, expected_sid: ctypes.c_void_p) -> None:
    if not dacl.value:
        _raise("CHAT_INPUT_DACL_INVALID")
    info = _ACL_SIZE_INFORMATION()
    if not api.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), _ACL_SIZE_INFORMATION_CLASS):
        _raise("CHAT_INPUT_DACL_UNREADABLE", ctypes.get_last_error())
    if info.AceCount > 4096 or not 8 <= info.AclBytesInUse <= 65535:
        _raise("CHAT_INPUT_DACL_INVALID")
    trusted = []
    try:
        # OWNER RIGHTS refers to the current owner, already compared with the
        # expected sender on this same handle; it is not an unrelated principal.
        for sid in ("S-1-5-18", "S-1-5-32-544", "S-1-3-4"):
            trusted.append(_convert_expected_sid(api, sid))
        for index in range(info.AceCount):
            ace = ctypes.c_void_p()
            if not api.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
                _raise("CHAT_INPUT_DACL_UNREADABLE", ctypes.get_last_error())
            header = ctypes.cast(ace, ctypes.POINTER(_ACE_HEADER)).contents
            if header.AceSize < 8 or header.AceSize > info.AclBytesInUse:
                _raise("CHAT_INPUT_DACL_INVALID")
            if header.AceFlags & INHERIT_ONLY_ACE:
                continue
            if header.AceType == ACCESS_DENIED_ACE_TYPE:
                continue
            # Object/callback/conditional ACEs have different layouts. Reject
            # instead of interpreting them as a plain allow ACE.
            if header.AceType != ACCESS_ALLOWED_ACE_TYPE:
                _raise("CHAT_INPUT_DACL_UNKNOWN_ACE")
            mask = wintypes.DWORD.from_address(ace.value + 4).value
            if not mask & _DANGEROUS_WRITE_MASK:
                continue
            if header.AceSize < 16:
                _raise("CHAT_INPUT_DACL_INVALID")
            sid_header = ctypes.string_at(ace.value + 8, 2)
            if sid_header[0] != 1 or sid_header[1] > 15 or 16 + 4 * sid_header[1] > header.AceSize:
                _raise("CHAT_INPUT_DACL_INVALID")
            ace_sid = ctypes.c_void_p(ace.value + 8)
            if not any(api.EqualSid(ace_sid, allowed) for allowed in (expected_sid, *trusted)):
                _raise("CHAT_INPUT_DACL_WRITE")
    finally:
        for sid_pointer in trusted:
            api.LocalFree(sid_pointer)


def _check_owner(api: _WindowsApi, handle: object, expected_sid: ctypes.c_void_p) -> None:
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    try:
        result = api.GetSecurityInfo(
            handle,
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result != 0:
            _raise("CHAT_INPUT_DACL_UNREADABLE", int(result))
        if not owner.value or not descriptor.value:
            _raise("CHAT_INPUT_OWNER_READ_FAILED")
        if not api.EqualSid(owner, expected_sid):
            _raise("CHAT_INPUT_OWNER_MISMATCH")
        _check_dacl(api, dacl, expected_sid)
    except ChatWindowsInputError:
        raise
    except (OSError, TypeError, ValueError):
        _raise("CHAT_INPUT_OWNER_READ_FAILED", ctypes.get_last_error())
    finally:
        if descriptor.value:
            api.LocalFree(descriptor)


def _read_bytes(api: _WindowsApi, handle: object, expected_size: int) -> bytes:
    buffer = ctypes.create_string_buffer(READ_BUFFER_BYTES)
    bytes_read = wintypes.DWORD()
    try:
        read_ok = api.ReadFile(
            handle,
            ctypes.byref(buffer),
            READ_BUFFER_BYTES,
            ctypes.byref(bytes_read),
            None,
        )
    except (OSError, TypeError, ValueError):
        _raise("CHAT_INPUT_READ_FAILED", ctypes.get_last_error())
    if not read_ok:
        _raise("CHAT_INPUT_READ_FAILED", ctypes.get_last_error())
    actual_size = int(bytes_read.value)
    if actual_size > MAX_INTENT_BYTES or actual_size != expected_size:
        _raise("CHAT_INPUT_LENGTH_MISMATCH")
    return bytes(buffer.raw[:actual_size])


def read_authenticated_intent_file(*, path: Path, expected_owner_sid: str) -> bytes:
    """Read a non-empty, non-reparse, single-link file owned by ``expected_owner_sid``.

    The path is an internal enumerated path under the caller's fixed protected
    ancestor precondition.  It is never resolved or queried by pathname after
    opening; all type, size, owner, and content checks use the same handle.
    The owner check authenticates the file object, not a human authorization.
    """

    if os.name != "nt":
        _raise("CHAT_INPUT_WINDOWS_ONLY")
    path_text = _validate_internal_path(path)
    api = _get_windows_api()
    expected_sid = _convert_expected_sid(api, expected_owner_sid)
    try:
        try:
            handle = api.CreateFileW(
                path_text,
                GENERIC_READ | READ_CONTROL,
                FILE_SHARE_READ,
                None,
                OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
        except (OSError, TypeError, ValueError):
            _raise("CHAT_INPUT_OPEN_FAILED", ctypes.get_last_error())
        if not _valid_handle(handle):
            winerror = ctypes.get_last_error()
            if winerror in {ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION}:
                _raise("CHAT_INPUT_BUSY", winerror)
            _raise("CHAT_INPUT_OPEN_FAILED", winerror)

        try:
            expected_size = _file_information(api, handle)
            _check_owner(api, handle, expected_sid)
            return _read_bytes(api, handle, expected_size)
        finally:
            if _valid_handle(handle):
                try:
                    close_ok = api.CloseHandle(handle)
                except (OSError, TypeError, ValueError):
                    close_ok = False
                if not close_ok and sys.exc_info()[0] is None:
                    _raise("CHAT_INPUT_CLOSE_FAILED", ctypes.get_last_error())
    finally:
        api.LocalFree(expected_sid)
