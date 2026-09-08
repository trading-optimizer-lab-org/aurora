"""Real Windows ACL coverage for the public chat-intent sender."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from typing import TypedDict, cast

import pytest

from aurora.infra.sp500_megarun.catalog_chat_intent import CatalogChatIntentV1, parse_chat_intent
from aurora.infra.sp500_megarun.catalog_chat_sender import enqueue_chat_intent
from aurora.infra.sp500_megarun.catalog_chat_windows_input import read_authenticated_intent_file


INTENT = CatalogChatIntentV1(
    schema_version="1",
    campaign_key="sp500-optimized-catalog-v1",
    intent_id="018f47a2-6e91-4c34-8000-000000000002",
)

_INSTALLER = Path(__file__).resolve().parents[1] / "scripts" / "install_catalog_chat_entry.ps1"
_HP_INBOX_MASK = 0x1201BF
_DELETE = 0x00010000
_DELETE_CHILD = 0x00000040
_WRITE_DAC = 0x00040000
_WRITE_OWNER = 0x00080000
_SYNCHRONIZE = 0x00100000
_HP_FILE_MASK = 0x1301BF
_OBJECT_INHERIT = 0x2
_CONTAINER_INHERIT = 0x1
_INHERIT_ONLY = 0x2
_AGENT_SID = "S-1-5-21-1-2-3-4242"


class _AclRule(TypedDict):
    sid: str
    mask: int
    inherited: bool
    inheritance_flags: int
    propagation_flags: int
    access_type: str


class _AclObservation(TypedDict):
    owner: str
    protected: bool
    rules: list[_AclRule]


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


def _ps_literal(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _powershell() -> str:
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required for the installer ACL fixture")
    return shell


def _apply_installer_inbox_acl(inbox: Path, hp_sid: str, script_path: Path) -> None:
    script = f"""
$ErrorActionPreference = 'Stop'
. {_ps_literal(_INSTALLER)}
function global:Get-LocalUser {{
    [CmdletBinding()]
    param([string]$Name)
    if ($Name -eq 'HP') {{ return [pscustomobject]@{{ SID = {_ps_literal(hp_sid)} }} }}
if ($Name -eq 'AURORAAgent') {{ return [pscustomobject]@{{ SID = {_ps_literal(_AGENT_SID)} }} }}
    throw "unexpected local user: $Name"
}}
function global:Set-CatalogChatEntryAcl {{
    [CmdletBinding()]
    param([string]$Path, $AclObject)
    # The real setter also pins the owner to Administrators.  Keep the
    # temporary directory's existing owner here because this test is not an
    # elevation test; all generated ACEs and protection flags remain real.
    $existing = [System.IO.Directory]::GetAccessControl($Path)
    $AclObject.SetOwner([System.Security.Principal.NTAccount]$existing.Owner)
    if ($AclObject -is [System.Security.AccessControl.DirectorySecurity]) {{
        [System.IO.Directory]::SetAccessControl($Path, $AclObject)
    }} else {{
        [System.IO.File]::SetAccessControl($Path, $AclObject)
    }}
}}
Set-CatalogChatEntryResourceAcl -LogicalPath {_ps_literal(inbox)} -ObjectKind directory -Profile inbox
"""
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-File", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"installer ACL fixture failed with {result.returncode}: {detail}")


def _read_acl_rules(path: Path, script_path: Path) -> _AclObservation:
    script = f"""
$ErrorActionPreference = 'Stop'
$acl = if ([System.IO.Directory]::Exists({_ps_literal(path)})) {{
    [System.IO.Directory]::GetAccessControl({_ps_literal(path)})
}} else {{
    [System.IO.File]::GetAccessControl({_ps_literal(path)})
}}
$owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
$rules = @($acl.Access | ForEach-Object {{
    $sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    [pscustomobject]@{{
        sid = $sid
        mask = [long]$_.FileSystemRights
        inherited = [bool]$_.IsInherited
        inheritance_flags = [int]$_.InheritanceFlags
        propagation_flags = [int]$_.PropagationFlags
        access_type = [string]$_.AccessControlType
    }}
}})
[pscustomobject]@{{
    owner = $owner
    protected = [bool]$acl.AreAccessRulesProtected
    rules = $rules
}} | ConvertTo-Json -Depth 8 -Compress
"""
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-File", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"ACL observation failed with {result.returncode}: {detail}")
    observation = json.loads(result.stdout)
    if not isinstance(observation, dict):
        raise RuntimeError("ACL observation is not an object")
    rules = observation.get("rules", [])
    if isinstance(rules, dict):
        rules = [rules]
    if not isinstance(rules, list):
        raise RuntimeError("ACL observation rules are not a list")
    observation["rules"] = rules
    return cast(_AclObservation, observation)


def _rules_for(acl: _AclObservation, sid: str) -> list[_AclRule]:
    return [rule for rule in acl["rules"] if rule["sid"] == sid]


def _require_private_parent_resolution(root: Path, inbox: Path) -> None:
    root.lstat()
    try:
        root.resolve(strict=True)
    except PermissionError as denied:
        assert getattr(denied, "winerror", None) == 5
    else:
        pytest.skip("exact ACL precondition unavailable: root.resolve() remained accessible")
    inbox.lstat()
    assert inbox.resolve(strict=True) == inbox.absolute()


def test_acl_precondition_skips_when_parent_is_accessible(tmp_path: Path) -> None:
    root = tmp_path / "private-root"
    inbox = root / "chat-inbox"
    inbox.mkdir(parents=True)
    with pytest.raises(
        pytest.skip.Exception,
        match=r"root\.resolve\(\) remained accessible",
    ):
        _require_private_parent_resolution(root, inbox)


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
            _require_private_parent_resolution(root, inbox)
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


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows ACL semantics")
def test_public_sender_round_trips_under_installed_inbox_acl_and_child_delete_rule(
    tmp_path: Path,
) -> None:
    """The sender needs DELETE on child files, never DELETE on the inbox."""
    try:
        sid = _current_user_sid()
    except (OSError, RuntimeError) as exc:
        pytest.skip(f"cannot identify the current Windows SID without changing credentials: {exc}")

    root = tmp_path / "private-root"
    inbox = root / "chat-inbox"
    root.mkdir()
    inbox.mkdir()
    snapshots = [_DaclSnapshot(root), _DaclSnapshot(inbox)]
    acl_script = tmp_path / "acl-fixture.ps1"
    try:
        # Apply the real installer setter in an isolated PowerShell child;
        # only local-user lookup is stubbed so no account state is changed.
        _apply_installer_inbox_acl(inbox, sid, acl_script)
        inbox_acl = _read_acl_rules(inbox, acl_script)

        assert inbox_acl["protected"] is True
        hp_rules = _rules_for(inbox_acl, sid)
        assert any(
            not rule["inherited"]
            and rule["inheritance_flags"] == _OBJECT_INHERIT | _CONTAINER_INHERIT
            and rule["propagation_flags"] == 0
            and rule["mask"] == _HP_INBOX_MASK
            for rule in hp_rules
        )
        child_delete_rules = [
            rule
            for rule in hp_rules
            if not rule["inherited"]
            and rule["inheritance_flags"] == _OBJECT_INHERIT
            and rule["propagation_flags"] == _INHERIT_ONLY
        ]
        assert len(child_delete_rules) == 1
        assert child_delete_rules[0]["mask"] & _DELETE == _DELETE
        assert child_delete_rules[0]["mask"] & ~(_DELETE | _SYNCHRONIZE) == 0
        for rule in hp_rules:
            assert rule["mask"] & (_DELETE_CHILD | _WRITE_DAC | _WRITE_OWNER) == 0
            if not rule["propagation_flags"] & _INHERIT_ONLY:
                assert rule["mask"] & _DELETE == 0

        first = enqueue_chat_intent(broker_root=root, intent=INTENT)
        target = inbox / f"{INTENT.intent_id}.intent.json"
        assert first == {
            "status": "pending",
            "intent_id": INTENT.intent_id,
            "campaign_key": INTENT.campaign_key,
        }
        target_acl = _read_acl_rules(target, acl_script)
        target_hp_rules = _rules_for(target_acl, sid)
        assert target_hp_rules
        assert all(rule["inherited"] for rule in target_hp_rules)
        assert all(
            not rule["propagation_flags"] & _INHERIT_ONLY for rule in target_hp_rules
        )
        target_hp_mask = 0
        for rule in target_hp_rules:
            target_hp_mask |= rule["mask"]
        assert target_hp_mask == _HP_FILE_MASK
        assert target_hp_mask & _DELETE_CHILD == 0
        assert target_hp_mask & (_WRITE_DAC | _WRITE_OWNER) == 0

        expected = (
            b'{"campaign_key":"sp500-optimized-catalog-v1",'
            b'"intent_id":"018f47a2-6e91-4c34-8000-000000000002",'
            b'"schema_version":"1"}'
        )
        assert read_authenticated_intent_file(path=target, expected_owner_sid=sid) == expected
        assert parse_chat_intent(expected) == INTENT
        before_duplicate = target.read_bytes()

        second = enqueue_chat_intent(broker_root=root, intent=INTENT)
        assert second == first
        assert target.read_bytes() == before_duplicate == expected
        assert read_authenticated_intent_file(path=target, expected_owner_sid=sid) == expected
        assert [entry.name for entry in inbox.iterdir()] == [target.name]
    finally:
        restore_error: BaseException | None = None
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
        # A red run can leave the temporary source behind after WinError 5;
        # cleanup is safe only after the original DACLs have been restored.
        for entry in inbox.glob("*"):
            try:
                entry.unlink()
            except FileNotFoundError:
                pass
