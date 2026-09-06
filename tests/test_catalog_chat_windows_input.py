from __future__ import annotations

import ctypes
import os
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, TypeAlias

import pytest

from aurora.infra.sp500_megarun import catalog_chat_windows_input as target


if TYPE_CHECKING:
    _CtypesCastArg: TypeAlias = (
        ctypes._CData | ctypes._CDataType | ctypes._CArgObject | int
    )
    _CtypesPointerArg: TypeAlias = (
        ctypes._PointerLike | ctypes.Array[Any] | ctypes._CArgObject | int
    )


def _require_windows() -> None:
    if os.name != "nt":
        pytest.skip("Windows-only integration test")


def _current_process_sid() -> str:
    _require_windows()
    advapi32 = getattr(ctypes, "WinDLL")("advapi32", use_last_error=True)
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_ulong)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("User", SidAndAttributes)]

    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = ()
    get_current_process.restype = ctypes.c_void_p
    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = (
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
    )
    open_process_token.restype = ctypes.c_int
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = (
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    )
    get_token_information.restype = ctypes.c_int
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    convert_sid.restype = ctypes.c_int
    local_free = kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int

    token = ctypes.c_void_p()
    assert open_process_token(
        get_current_process(), 0x0008, ctypes.byref(token)
    ), getattr(ctypes, "get_last_error")()
    try:
        required = ctypes.c_ulong()
        assert not get_token_information(
            token, 1, None, 0, ctypes.byref(required)
        )
        assert required.value > 0
        buffer = ctypes.create_string_buffer(required.value)
        assert get_token_information(
            token,
            1,
            buffer,
            required.value,
            ctypes.byref(required),
        ), getattr(ctypes, "get_last_error")()
        token_user = TokenUser.from_buffer(buffer)
        text_pointer = ctypes.c_void_p()
        assert convert_sid(token_user.User.Sid, ctypes.byref(text_pointer)), getattr(ctypes, "get_last_error")()
        try:
            assert text_pointer.value is not None
            return ctypes.wstring_at(text_pointer.value)
        finally:
            assert not local_free(text_pointer)
    finally:
        assert close_handle(token)


def _different_sid(sid: str) -> str:
    prefix, rid = sid.rsplit("-", 1)
    return f"{prefix}-{int(rid) + 1}"


def _assert_error(exc_info: pytest.ExceptionInfo[target.ChatWindowsInputError], code: str) -> None:
    error = exc_info.value
    assert isinstance(error, target.ChatWindowsInputError)
    assert error.code == code
    assert str(error).startswith(code)
    assert "\\" not in str(error)
    assert "/" not in str(error)


def _open_write_denied_handle(path: Path) -> ctypes.c_void_p:
    _require_windows()
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(path),
        0x40000000,  # GENERIC_WRITE
        0,  # deny read/write/delete while this handle is held
        None,
        3,  # OPEN_EXISTING
        0,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    assert handle not in (None, invalid), getattr(ctypes, "get_last_error")()
    return ctypes.c_void_p(handle)


def _process_handle_count() -> int:
    _require_windows()
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = ()
    get_current_process.restype = ctypes.c_void_p
    get_process_handle_count = kernel32.GetProcessHandleCount
    get_process_handle_count.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    )
    get_process_handle_count.restype = ctypes.c_int
    count = ctypes.c_ulong()
    assert get_process_handle_count(get_current_process(), ctypes.byref(count))
    return count.value


def _sid_bytes(sid: str) -> bytes:
    parts = sid.split("-")
    assert parts[:2] == ["S", "1"]
    authority = int(parts[2])
    subauthorities = [int(item) for item in parts[3:]]
    return (
        struct.pack("<BB", 1, len(subauthorities))
        + authority.to_bytes(6, "big")
        + b"".join(struct.pack("<I", item) for item in subauthorities)
    )


def _build_ace(
    *, ace_type: int, sid: str, mask: int, flags: int = 0
) -> bytes:
    body = struct.pack("<BBH", ace_type, flags, 0) + struct.pack("<I", mask)
    body += _sid_bytes(sid)
    size = (len(body) + 3) & ~3
    return struct.pack("<BBH", ace_type, flags, size) + body[4:] + b"\0" * (size - len(body))


def _sid_from_pointer(pointer: _CtypesCastArg) -> bytes:
    address = getattr(pointer, "value", pointer)
    assert isinstance(address, (int, ctypes.c_void_p))
    header = ctypes.string_at(address, 2)
    length = 8 + header[1] * 4
    return ctypes.string_at(address, length)


class _MockAclApi:
    def __init__(
        self,
        *,
        expected_owner_sid: str,
        aces: list[bytes],
        dacl_state: str = "present",
    ) -> None:
        self.closed: list[object] = []
        self._sid_buffers: list[ctypes.Array[ctypes.c_char]] = []
        self._ace_buffers = [ctypes.create_string_buffer(ace) for ace in aces]
        self._dacl_buffer = ctypes.create_string_buffer(max(1, sum(map(len, aces))))
        self._descriptor_buffer = ctypes.create_string_buffer(b"descriptor")
        self._expected_owner_sid = expected_owner_sid
        self._aces = aces
        self._dacl_state = dacl_state
        self._payload = b"mocked ACL payload"

    def _sid_pointer(self, sid: str) -> int:
        buffer = ctypes.create_string_buffer(_sid_bytes(sid))
        self._sid_buffers.append(buffer)
        return ctypes.addressof(buffer)

    def CreateFileW(self, *_args: object) -> int:
        return 101

    def GetFileType(self, _handle: object) -> int:
        return target.FILE_TYPE_DISK

    def GetFileInformationByHandle(
        self, _handle: object, info: _CtypesCastArg
    ) -> int:
        file_info = ctypes.cast(
            info, ctypes.POINTER(target._BY_HANDLE_FILE_INFORMATION)
        ).contents
        file_info.dwFileAttributes = 0
        file_info.nFileSizeHigh = 0
        file_info.nFileSizeLow = len(self._payload)
        file_info.nNumberOfLinks = 1
        return 1

    def GetSecurityInfo(
        self,
        _handle: object,
        _object_type: int,
        _security_information: int,
        owner: _CtypesCastArg,
        _group: object,
        dacl: _CtypesCastArg,
        _sacl: object,
        descriptor: _CtypesCastArg,
    ) -> int:
        if self._dacl_state == "unreadable":
            return 5
        ctypes.cast(owner, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(
            self._sid_pointer(self._expected_owner_sid)
        )
        if self._dacl_state == "null":
            ctypes.cast(dacl, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p()
        else:
            ctypes.cast(dacl, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(
                ctypes.addressof(self._dacl_buffer)
            )
        ctypes.cast(descriptor, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(
            ctypes.addressof(self._descriptor_buffer)
        )
        return 0

    def GetAclInformation(
        self, _dacl: object, info: _CtypesCastArg, _length: int, _class_id: int
    ) -> int:
        acl_info = ctypes.cast(
            info, ctypes.POINTER(target._ACL_SIZE_INFORMATION)
        ).contents
        acl_info.AceCount = len(self._aces)
        acl_info.AclBytesInUse = sum(map(len, self._aces))
        acl_info.AclBytesFree = 0
        return 1

    def GetAce(self, _dacl: object, index: int, ace: _CtypesCastArg) -> int:
        ctypes.cast(ace, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(
            ctypes.addressof(self._ace_buffers[index])
        )
        return 1

    def EqualSid(self, left: _CtypesCastArg, right: _CtypesCastArg) -> int:
        return int(_sid_from_pointer(left) == _sid_from_pointer(right))

    def ConvertStringSidToSidW(self, sid: str, output: _CtypesCastArg) -> int:
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(
            self._sid_pointer(sid)
        )
        return 1

    def ReadFile(
        self,
        _handle: object,
        buffer: _CtypesPointerArg,
        _maximum: int,
        bytes_read: _CtypesCastArg,
        _overlapped: object,
    ) -> int:
        ctypes.memmove(buffer, self._payload, len(self._payload))
        ctypes.cast(bytes_read, ctypes.POINTER(ctypes.c_ulong))[0] = len(self._payload)
        return 1

    def CloseHandle(self, handle: object) -> int:
        self.closed.append(handle)
        return 1

    def LocalFree(self, _pointer: object) -> int:
        return 0


def _assign_test_file_to_sender(path: Path) -> str:
    """CI administrators may create files owned by their group, unlike HP."""
    sid = _current_process_sid()
    subprocess.run(
        ["icacls", str(path), "/setowner", "*" + sid],
        check=True, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW"),
    )
    subprocess.run(
        ["icacls", str(path), "/grant:r", "*" + sid + ":(F)"],
        check=True, capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW"),
    )
    return sid


def test_correct_owner_reads_nonempty_bytes_from_real_windows_file(tmp_path: Path) -> None:
    _require_windows()
    path = tmp_path / "intent.bin"
    path.write_bytes(b"hello authenticated input")
    sender_sid = _assign_test_file_to_sender(path)

    assert target.read_authenticated_intent_file(
        path=path, expected_owner_sid=sender_sid
    ) == b"hello authenticated input"


def test_real_windows_sender_to_consumer_without_production_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real file publication and OS auth; only downstream submission is mocked."""
    _require_windows()
    from aurora.infra.sp500_megarun import catalog_chat_consumer as consumer
    from aurora.infra.sp500_megarun.catalog_chat_intent import CatalogChatIntentV1
    from aurora.infra.sp500_megarun.catalog_chat_sender import enqueue_chat_intent
    from datetime import datetime, timezone

    (tmp_path / "chat-inbox").mkdir()
    intent = CatalogChatIntentV1(
        schema_version="1", campaign_key="catalog-fast-canary-v1",
        intent_id="018f47a2-6e91-4c34-8000-000000000001",
    )
    enqueue_chat_intent(broker_root=tmp_path, intent=intent)
    sender_sid = _assign_test_file_to_sender(
        tmp_path / "chat-inbox" / f"{intent.intent_id}.intent.json"
    )
    seen = []
    def record(**kwargs):
        seen.append(kwargs["intent"])
        return "local-no-production"
    monkeypatch.setattr(consumer, "submit_registered_chat_intent", record)
    assert consumer.consume_authenticated_chat_file(
        broker_root=tmp_path, input_name=f"{intent.intent_id}.intent.json",
        expected_sender_sid=sender_sid, observed_at=datetime.now(timezone.utc),
    ) == "local-no-production"
    assert seen == [intent]


def test_wrong_expected_owner_sid_is_rejected_before_read(tmp_path: Path) -> None:
    _require_windows()
    path = tmp_path / "intent.bin"
    path.write_bytes(b"must not be returned")

    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(
            path=path, expected_owner_sid=_different_sid(_current_process_sid())
        )

    _assert_error(exc_info, "CHAT_INPUT_OWNER_MISMATCH")


def test_directory_is_rejected(tmp_path: Path) -> None:
    _require_windows()
    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(
            path=tmp_path, expected_owner_sid=_current_process_sid()
        )

    _assert_error(exc_info, "CHAT_INPUT_NOT_FILE")


def test_oversize_file_is_rejected_before_read(tmp_path: Path) -> None:
    _require_windows()
    path = tmp_path / "oversize.bin"
    path.write_bytes(b"x" * 4097)

    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(
            path=path, expected_owner_sid=_current_process_sid()
        )

    _assert_error(exc_info, "CHAT_INPUT_SIZE_INVALID")


def test_hardlink_is_rejected_from_same_handle_metadata(tmp_path: Path) -> None:
    _require_windows()
    path = tmp_path / "intent.bin"
    path.write_bytes(b"hardlink must be rejected")
    hardlink = tmp_path / "intent-alias.bin"
    try:
        try:
            os.link(path, hardlink)
        except OSError as exc:
            pytest.skip(f"hardlink unavailable on this Windows test volume: {exc}")

        with pytest.raises(target.ChatWindowsInputError) as exc_info:
            target.read_authenticated_intent_file(
                path=path, expected_owner_sid=_current_process_sid()
            )

        _assert_error(exc_info, "CHAT_INPUT_HARDLINK")
    finally:
        hardlink.unlink(missing_ok=True)


def test_concurrent_writable_handle_produces_deterministic_busy_error(tmp_path: Path) -> None:
    _require_windows()
    path = tmp_path / "intent.bin"
    path.write_bytes(b"writer holds an incompatible share")
    handle = _open_write_denied_handle(path)
    try:
        with pytest.raises(target.ChatWindowsInputError) as exc_info:
            target.read_authenticated_intent_file(
                path=path, expected_owner_sid=_current_process_sid()
            )

        _assert_error(exc_info, "CHAT_INPUT_BUSY")
        assert exc_info.value.winerror == 32
    finally:
        kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        assert kernel32.CloseHandle(handle)


def test_malformed_expected_sid_fails_closed_without_path_or_payload(tmp_path: Path) -> None:
    _require_windows()
    path = tmp_path / "private-intent.bin"
    path.write_bytes(b"secret payload")

    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(path=path, expected_owner_sid="not-a-sid")

    _assert_error(exc_info, "CHAT_INPUT_OWNER_INVALID")
    assert "secret payload" not in str(exc_info.value)


def test_missing_file_does_not_leak_a_process_handle(tmp_path: Path) -> None:
    _require_windows()
    path = tmp_path / "does-not-exist.bin"
    before = _process_handle_count()

    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(
            path=path, expected_owner_sid=_current_process_sid()
        )

    after = _process_handle_count()
    _assert_error(exc_info, "CHAT_INPUT_OPEN_FAILED")
    assert after == before


def test_relative_unc_device_and_ads_paths_are_rejected_lexically(tmp_path: Path) -> None:
    _require_windows()
    candidates = (
        Path("relative-intent.bin"),
        Path(r"\\server\share\intent.bin"),
        Path(r"\\.\PIPE\intent"),
        tmp_path / "intent.bin:secret",
    )
    for path in candidates:
        with pytest.raises(target.ChatWindowsInputError) as exc_info:
            target.read_authenticated_intent_file(
                path=path, expected_owner_sid="not-a-sid"
            )
        _assert_error(exc_info, "CHAT_INPUT_PATH_INVALID")


def test_non_windows_execution_fails_closed_without_loading_win32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(
        target,
        "_get_windows_api",
        lambda: pytest.fail("Win32 API must not be loaded on non-Windows"),
    )

    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(
            path=Path("relative-intent.bin"), expected_owner_sid="not-a-sid"
        )

    _assert_error(exc_info, "CHAT_INPUT_WINDOWS_ONLY")


_MOCK_OWNER = "S-1-5-21-111-222-333-1001"
_MOCK_FOREIGN = "S-1-5-21-111-222-333-1002"


def _mock_windows_api(monkeypatch: pytest.MonkeyPatch, api: object) -> None:
    """Replace the complete Win32 boundary, without changing global os.name."""
    monkeypatch.setattr(target, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(target, "_get_windows_api", lambda: api)
    monkeypatch.setattr(target.ctypes, "get_last_error", lambda: 5, raising=False)


@pytest.mark.parametrize(
    ("case_name", "ace", "expected_code"),
    [
        (
            "foreign effective write",
            _build_ace(ace_type=0, sid=_MOCK_FOREIGN, mask=0x0002),
            "CHAT_INPUT_DACL_WRITE",
        ),
        (
            "foreign read only",
            _build_ace(ace_type=0, sid=_MOCK_FOREIGN, mask=0x0001),
            None,
        ),
        (
            "foreign deny write",
            _build_ace(ace_type=1, sid=_MOCK_FOREIGN, mask=0x0002),
            None,
        ),
        (
            "foreign inherit only write",
            _build_ace(ace_type=0, sid=_MOCK_FOREIGN, mask=0x0002, flags=0x08),
            None,
        ),
        (
            "unknown effective ACE",
            _build_ace(ace_type=0x7F, sid=_MOCK_FOREIGN, mask=0x0001),
            "CHAT_INPUT_DACL_UNKNOWN_ACE",
        ),
    ],
)
def test_mocked_acl_cases_fail_closed_or_allow_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    ace: bytes,
    expected_code: str | None,
) -> None:
    del case_name  # The parameter gives each ACL decision a readable pytest id.
    fake = _MockAclApi(expected_owner_sid=_MOCK_OWNER, aces=[ace])
    _mock_windows_api(monkeypatch, fake)

    if expected_code is None:
        assert target.read_authenticated_intent_file(
            path=tmp_path / "mocked-intent.bin", expected_owner_sid=_MOCK_OWNER
        ) == b"mocked ACL payload"
        return

    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(
            path=tmp_path / "mocked-intent.bin", expected_owner_sid=_MOCK_OWNER
        )

    _assert_error(exc_info, expected_code)


@pytest.mark.parametrize("allowed_sid", ["S-1-5-18", "S-1-5-32-544", "S-1-3-4", _MOCK_OWNER])
def test_mocked_acl_allows_dangerous_write_for_explicit_trusted_sid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    allowed_sid: str,
) -> None:
    fake = _MockAclApi(
        expected_owner_sid=_MOCK_OWNER,
        aces=[_build_ace(ace_type=0, sid=allowed_sid, mask=0x0002 | 0x00010000)],
    )
    _mock_windows_api(monkeypatch, fake)

    assert target.read_authenticated_intent_file(
        path=tmp_path / "mocked-intent.bin", expected_owner_sid=_MOCK_OWNER
    ) == b"mocked ACL payload"


@pytest.mark.parametrize(
    ("dacl_state", "expected_code"),
    [
        ("null", "CHAT_INPUT_DACL_INVALID"),
        ("unreadable", "CHAT_INPUT_DACL_UNREADABLE"),
    ],
)
def test_mocked_acl_rejects_null_or_unreadable_dacl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dacl_state: str,
    expected_code: str,
) -> None:
    fake = _MockAclApi(
        expected_owner_sid=_MOCK_OWNER, aces=[], dacl_state=dacl_state
    )
    _mock_windows_api(monkeypatch, fake)

    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(
            path=tmp_path / "mocked-intent.bin", expected_owner_sid=_MOCK_OWNER
        )

    _assert_error(exc_info, expected_code)


def test_simulated_reparse_attribute_is_rejected_before_read_mocked_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unit simulation only: no privileged symlink/reparse point is created."""

    class FakeApi:
        def __init__(self) -> None:
            self.closed: list[object] = []
            self.read_called = False
            self.sid_storage: object | None = None

        def CreateFileW(self, *_args: object) -> int:
            return 101

        def GetFileType(self, _handle: object) -> int:
            return target.FILE_TYPE_DISK

        def GetFileInformationByHandle(
            self, _handle: object, info: _CtypesCastArg
        ) -> int:
            file_info = ctypes.cast(
                info, ctypes.POINTER(target._BY_HANDLE_FILE_INFORMATION)
            ).contents
            file_info.dwFileAttributes = target.FILE_ATTRIBUTE_REPARSE_POINT
            file_info.nFileSizeHigh = 0
            file_info.nFileSizeLow = 1
            file_info.nNumberOfLinks = 1
            return 1

        def CloseHandle(self, handle: object) -> int:
            self.closed.append(handle)
            return 1

        def ConvertStringSidToSidW(
            self, _sid: str, output: _CtypesCastArg
        ) -> int:
            self.sid_storage = ctypes.create_string_buffer(b"fake-sid")
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(
                ctypes.addressof(self.sid_storage)
            )
            return 1

        def LocalFree(self, _pointer: object) -> int:
            return 0

        def ReadFile(self, *_args: object) -> int:
            self.read_called = True
            return 1

    fake = FakeApi()
    path = tmp_path / "reparse-simulation.bin"
    path.write_bytes(b"x")
    _mock_windows_api(monkeypatch, fake)

    with pytest.raises(target.ChatWindowsInputError) as exc_info:
        target.read_authenticated_intent_file(
            path=path, expected_owner_sid="S-1-5-18"
        )

    _assert_error(exc_info, "CHAT_INPUT_REPARSE")
    assert fake.closed == [101]
    assert fake.read_called is False
