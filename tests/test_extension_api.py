"""R186 - Tests for the extension API contract layer.

Validates the version table, version-check helper, path allowlist, and
the forbidden-capability invariant under tmp_path + monkeypatched env
vars.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aurora.core.extension_api import (
    FORBIDDEN_CAPABILITY_FLAGS,
    INTERFACE_VERSIONS,
    ExtensionPathBlocked,
    IncompatibleInterfaceError,
    InterfaceVersion,
    assert_safe_extension_path,
    check_interface_version,
    get_allowed_extension_dirs,
    parse_semver,
)
from aurora.core.extension_loader import ExtensionLoadError, load_extension


# ---------------------------------------------------------------------------
# Interface table
# ---------------------------------------------------------------------------


REQUIRED_INTERFACES = {
    "DataProvider",
    "Strategy",
    "Signal",
    "Feature",
    "Validator",
    "BrokerAdapter",
    "ExecutionModel",
    "RiskModel",
    "ReportRenderer",
    "AuditSink",
}


def test_interface_table_covers_required_surfaces():
    assert REQUIRED_INTERFACES.issubset(set(INTERFACE_VERSIONS))
    for name, spec in INTERFACE_VERSIONS.items():
        assert isinstance(spec, InterfaceVersion), name
        # Each entry is well-formed sem-ver triplet.
        for field in ("current", "min_supported", "deprecated_after",
                      "removed_after"):
            value = getattr(spec, field)
            parse_semver(value)  # raises if malformed


# ---------------------------------------------------------------------------
# check_interface_version
# ---------------------------------------------------------------------------


class _ExtCompatible:
    interface_version = "1.0.0"


class _ExtTooOld:
    interface_version = "0.9.0"


class _ExtTooNew:
    interface_version = "2.0.0"


class _ExtMissing:
    pass


def test_version_check_passes_for_current_version():
    check_interface_version(_ExtCompatible(), "DataProvider")
    check_interface_version(
        {"interface_version": "1.0.0"}, "Strategy"
    )


def test_version_check_raises_for_too_old_version():
    with pytest.raises(IncompatibleInterfaceError) as exc:
        check_interface_version(_ExtTooOld(), "DataProvider")
    assert "older than min_supported" in str(exc.value)


def test_version_check_raises_for_too_new_major_version():
    with pytest.raises(IncompatibleInterfaceError) as exc:
        check_interface_version(_ExtTooNew(), "DataProvider")
    assert "newer than the in-tree contract" in str(exc.value)


def test_version_check_refuses_extension_without_interface_version():
    with pytest.raises(IncompatibleInterfaceError) as exc:
        check_interface_version(_ExtMissing(), "DataProvider")
    assert "does not declare an interface_version" in str(exc.value)


def test_version_check_rejects_unknown_interface_name():
    with pytest.raises(IncompatibleInterfaceError) as exc:
        check_interface_version(_ExtCompatible(), "DoesNotExist")
    assert "unknown interface" in str(exc.value)


# ---------------------------------------------------------------------------
# Path allowlist
# ---------------------------------------------------------------------------


def _write_ext(tmp_path: Path, name: str = "x_aurora_ext.py") -> Path:
    p = tmp_path / name
    p.write_text("__aurora_extension__ = {}\n", encoding="utf-8")
    return p.resolve()


def test_assert_safe_path_refuses_unconfigured_directories(monkeypatch, tmp_path):
    monkeypatch.delenv("AU_EXTENSION_DIRS", raising=False)
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    p = _write_ext(tmp_path)
    with pytest.raises(ExtensionPathBlocked) as exc:
        assert_safe_extension_path(p)
    assert "AU_EXTENSION_DIRS is empty" in str(exc.value)


def test_assert_safe_path_respects_au_extension_dirs_env(monkeypatch, tmp_path):
    p = _write_ext(tmp_path)
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(tmp_path))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    resolved = assert_safe_extension_path(p)
    assert resolved == p
    dirs = get_allowed_extension_dirs()
    assert tmp_path.resolve() in dirs


def test_assert_safe_path_refuses_outside_allowlist(monkeypatch, tmp_path):
    inside = tmp_path / "inside"
    outside = tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    p_outside = _write_ext(outside)
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(inside))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    with pytest.raises(ExtensionPathBlocked) as exc:
        assert_safe_extension_path(p_outside)
    assert "not inside any allowed directory" in str(exc.value)


def test_assert_safe_path_handles_multiple_dirs_and_pathsep(
    monkeypatch, tmp_path
):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    pa = _write_ext(a, "a_aurora_ext.py")
    pb = _write_ext(b, "b_aurora_ext.py")
    monkeypatch.setenv(
        "AU_EXTENSION_DIRS", os.pathsep.join([str(a), str(b)])
    )
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    assert assert_safe_extension_path(pa) == pa
    assert assert_safe_extension_path(pb) == pb


def test_assert_safe_path_refuses_nonexistent_path(monkeypatch, tmp_path):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(tmp_path))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    with pytest.raises(ExtensionPathBlocked):
        assert_safe_extension_path(tmp_path / "nope.py")


# ---------------------------------------------------------------------------
# Forbidden capability flag invariant
# ---------------------------------------------------------------------------


def test_forbidden_capability_flags_table_is_non_empty():
    assert "bypass_oosguard" in FORBIDDEN_CAPABILITY_FLAGS
    assert "bypass_audit" in FORBIDDEN_CAPABILITY_FLAGS
    assert "bypass_provider_terms" in FORBIDDEN_CAPABILITY_FLAGS


_BYPASS_EXT_BODY = '''
class _NoOpProvider:
    name = "bypass_provider"
    version = "0.0"
    interface_version = "1.0.0"

    def fetch(self, *a, **kw):
        raise NotImplementedError

    def is_point_in_time(self):
        return False

    def supported_tiers(self):
        return {"IS_TRAIN"}

__aurora_extension__ = {
    "name": "bypass_provider",
    "kind": "DataProvider",
    "interface_version": "1.0.0",
    "factory": _NoOpProvider,
    "capabilities": {"bypass_oosguard": True},
}
'''


def test_extension_with_bypass_oosguard_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("AU_EXTENSION_DIRS", str(tmp_path))
    monkeypatch.delenv("QF_EXTENSION_DIRS", raising=False)
    p = tmp_path / "bypass_aurora_ext.py"
    p.write_text(_BYPASS_EXT_BODY, encoding="utf-8")
    with pytest.raises(ExtensionLoadError) as exc:
        load_extension(p)
    assert "bypass_oosguard" in str(exc.value)


def test_parse_semver_accepts_prerelease_and_build():
    assert parse_semver("1.2.3") == (1, 2, 3)
    assert parse_semver("1.2.3-rc.1") == (1, 2, 3)
    assert parse_semver("1.2.3+sha.abc") == (1, 2, 3)
    assert parse_semver("1") == (1, 0, 0)
    with pytest.raises(ValueError):
        parse_semver("abc")
