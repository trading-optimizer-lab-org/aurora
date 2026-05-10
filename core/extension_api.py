"""R186 - Local extension API and optional plugin contract.

Defines the canonical interface versions and compatibility-policy table
for AURORA's pluggable surfaces (data providers, strategies, validators,
broker adapters, reporters, audit sinks, ...). Also provides the path
allowlist used by :mod:`aurora.core.extension_loader`.

This module deliberately stays minimal:

* No marketplace, no public registry.
* No remote loading. Discovery is path-only and only inside operator
  configured allowlists (env var ``AU_EXTENSION_DIRS``).
* Hard refusal of any extension that declares it bypasses ``OOSGuard``
  or other safety-critical invariants.

Public API
----------
* :data:`INTERFACE_VERSIONS` -- canonical contract versions.
* :class:`InterfaceVersion` -- frozen dataclass entry in the table.
* :exc:`IncompatibleInterfaceError` -- raised on version mismatch.
* :exc:`ExtensionPathBlocked` -- raised when a load path is not in the
  allowlist.
* :func:`check_interface_version` -- runtime contract check.
* :func:`assert_safe_extension_path` -- enforce the directory allowlist.
* :func:`get_allowed_extension_dirs` -- read the env-configured allowlist.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

from aurora.core.env_compat import aurora_env


__all__ = [
    "INTERFACE_VERSIONS",
    "InterfaceVersion",
    "IncompatibleInterfaceError",
    "ExtensionPathBlocked",
    "check_interface_version",
    "assert_safe_extension_path",
    "get_allowed_extension_dirs",
    "parse_semver",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class IncompatibleInterfaceError(Exception):
    """Raised when an extension's ``interface_version`` falls outside
    the supported window declared in :data:`INTERFACE_VERSIONS`.
    """


class ExtensionPathBlocked(Exception):
    """Raised when extension loading is attempted from a path outside
    the operator-configured allowlist (env ``AU_EXTENSION_DIRS``).
    """


# ---------------------------------------------------------------------------
# Interface version table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterfaceVersion:
    """Canonical version + compatibility policy for one extension surface.

    Attributes:
        current: the version emitted by the in-tree implementation.
        min_supported: the oldest extension version Aurora will accept.
        deprecated_after: extensions matching ``current`` after this
            release should treat their version as deprecated; loading
            still succeeds but ``check_interface_version`` warns.
        removed_after: any extension whose declared version is older
            than ``min_supported`` raises
            :class:`IncompatibleInterfaceError`. ``removed_after``
            documents the release in which support is dropped.
    """

    current: str
    min_supported: str
    deprecated_after: str
    removed_after: str
    notes: str = ""


def parse_semver(version: str) -> Tuple[int, int, int]:
    """Parse a sem-ver string (``"1.2.3"``) into a tuple of ints.

    Pre-release / build metadata after ``-`` or ``+`` is dropped. A
    missing minor or patch defaults to ``0`` so ``"1"`` and ``"1.0"``
    both compare equal to ``"1.0.0"``.

    Raises ``ValueError`` on malformed input.
    """
    if not isinstance(version, str) or not version:
        raise ValueError(f"version must be a non-empty string, got {version!r}")
    core = version.split("+", 1)[0].split("-", 1)[0]
    parts = core.split(".")
    if len(parts) > 3:
        raise ValueError(f"version {version!r} has more than 3 numeric parts")
    out: list[int] = []
    for p in parts:
        if not p.isdigit():
            raise ValueError(f"version {version!r} has non-numeric segment {p!r}")
        out.append(int(p))
    while len(out) < 3:
        out.append(0)
    return out[0], out[1], out[2]


# Canonical contract versions. Bumping ``current`` is a SOURCE change in
# the in-tree implementation. Bumping ``min_supported`` is an EXTERNAL
# break -- old extensions stop loading.
INTERFACE_VERSIONS: Mapping[str, InterfaceVersion] = {
    "DataProvider": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes=(
            "DataProvider Protocol. Required: name, version, fetch, "
            "is_point_in_time, supported_tiers."
        ),
    ),
    "Strategy": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes="aurora.strategies.base.Strategy. Required: signals(prices).",
    ),
    "Signal": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes="Per-symbol signal generator returning [-1, 1] weights.",
    ),
    "Feature": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes=(
            "Point-in-time feature producer. Must declare availability "
            "time so the FeatureStore can reject lookahead reads."
        ),
    ),
    "Validator": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes="aurora.validation.pipeline gate. Returns ValidatorResult.",
    ),
    "BrokerAdapter": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes=(
            "aurora.deployment.brokers adapter. Must integrate with "
            "KillSwitch + AuditLog + RateLimiter."
        ),
    ),
    "ExecutionModel": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes="aurora.execution model. Must respect costs + slippage policy.",
    ),
    "RiskModel": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes="aurora.risk model. Must surface ES/VaR/limits for triage.",
    ),
    "ReportRenderer": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes="aurora.reporting renderer. Must propagate provenance hash.",
    ),
    "AuditSink": InterfaceVersion(
        current="1.0.0",
        min_supported="1.0.0",
        deprecated_after="2.0.0",
        removed_after="3.0.0",
        notes=(
            "Append-only audit destination. Must NOT replace AgentAudit "
            "or SOC2AuditTrail; sinks are mirrors only."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Capability flags an extension is forbidden from declaring as ``True``
# ---------------------------------------------------------------------------


# Capability keys an extension MUST NOT set to ``True``. These would
# silently disable safety invariants (point-in-time gates, audit trail,
# provider-terms registry) that AURORA's protocol spine depends on.
FORBIDDEN_CAPABILITY_FLAGS: Tuple[str, ...] = (
    "bypass_oosguard",
    "bypass_audit",
    "bypass_provider_terms",
    "skip_validation_gates",
)


# ---------------------------------------------------------------------------
# Version check
# ---------------------------------------------------------------------------


def check_interface_version(extension: Any, interface_name: str) -> None:
    """Raise :class:`IncompatibleInterfaceError` if ``extension`` is not
    in the supported window for ``interface_name``.

    The extension is expected to expose either a string attribute
    ``interface_version`` or a mapping ``__aurora_extension__`` whose
    ``interface_version`` key holds the version. A missing version is
    refused -- extensions cannot opt out of the contract by omitting the
    field.

    Args:
        extension: any object representing the loaded extension. May be
            a class, instance, dict (the ``__aurora_extension__``
            descriptor) or module.
        interface_name: key into :data:`INTERFACE_VERSIONS`.
    """
    if interface_name not in INTERFACE_VERSIONS:
        raise IncompatibleInterfaceError(
            f"unknown interface {interface_name!r}. "
            f"known={sorted(INTERFACE_VERSIONS)}"
        )
    spec = INTERFACE_VERSIONS[interface_name]

    declared = _extract_interface_version(extension)
    if declared is None:
        raise IncompatibleInterfaceError(
            f"extension does not declare an interface_version for "
            f"{interface_name!r}; refusing to load. "
            f"Add interface_version={spec.current!r} to your extension "
            "(or to its __aurora_extension__ descriptor)."
        )

    try:
        declared_tup = parse_semver(declared)
        min_tup = parse_semver(spec.min_supported)
        cur_tup = parse_semver(spec.current)
    except ValueError as exc:
        raise IncompatibleInterfaceError(
            f"extension declares malformed interface_version "
            f"{declared!r} for {interface_name!r}: {exc}"
        ) from exc

    if declared_tup < min_tup:
        raise IncompatibleInterfaceError(
            f"extension interface_version {declared!r} is older than "
            f"min_supported {spec.min_supported!r} for "
            f"{interface_name!r}; support was dropped after "
            f"{spec.removed_after!r}."
        )
    if declared_tup[0] > cur_tup[0]:
        raise IncompatibleInterfaceError(
            f"extension interface_version {declared!r} declares major "
            f"version newer than the in-tree contract "
            f"{spec.current!r} for {interface_name!r}; refusing to "
            "load to avoid silent ABI break."
        )


def _extract_interface_version(extension: Any) -> Optional[str]:
    """Return ``extension.interface_version`` (or descriptor entry).

    Looks at, in order:
    1. ``extension.interface_version`` attribute (string).
    2. ``extension.__aurora_extension__["interface_version"]`` dict.
    3. ``extension["interface_version"]`` if ``extension`` is a mapping.
    """
    direct = getattr(extension, "interface_version", None)
    if isinstance(direct, str):
        return direct
    descriptor = getattr(extension, "__aurora_extension__", None)
    if isinstance(descriptor, Mapping):
        v = descriptor.get("interface_version")
        if isinstance(v, str):
            return v
    if isinstance(extension, Mapping):
        v = extension.get("interface_version")
        if isinstance(v, str):
            return v
    return None


# ---------------------------------------------------------------------------
# Path allowlist
# ---------------------------------------------------------------------------


def get_allowed_extension_dirs() -> Tuple[Path, ...]:
    """Return the operator-configured extension directories.

    Read from ``AU_EXTENSION_DIRS`` (legacy ``QF_EXTENSION_DIRS``). The
    value is split on the OS path separator. Empty / unset means no
    extension directories are allowed -- a deliberate "fail closed"
    default so a fresh install cannot load anything from disk until the
    operator opts in.
    """
    raw = aurora_env("AU_EXTENSION_DIRS", "QF_EXTENSION_DIRS")
    if not raw:
        return ()
    parts = [p.strip() for p in raw.split(os.pathsep)]
    out: list[Path] = []
    for p in parts:
        if not p:
            continue
        try:
            resolved = Path(p).expanduser().resolve()
        except OSError:
            continue
        out.append(resolved)
    return tuple(out)


def assert_safe_extension_path(
    path: Any,
    *,
    allow_dirs: Optional[Tuple[Path, ...]] = None,
) -> Path:
    """Raise :class:`ExtensionPathBlocked` unless ``path`` lives under
    one of the configured allowed directories.

    Args:
        path: the extension file path to validate.
        allow_dirs: explicit allowlist (used by the loader when the
            caller has already resolved it). Defaults to
            :func:`get_allowed_extension_dirs`.

    Returns:
        The resolved absolute :class:`pathlib.Path`.

    The check resolves both the path and each allowed directory and
    refuses any path that:

    * does not exist,
    * is not a regular file,
    * does not sit under any allow_dir,
    * contains symlinks that would escape the allowlist.
    """
    if path is None:
        raise ExtensionPathBlocked("extension path is None")
    p = Path(path).expanduser()
    try:
        resolved = p.resolve(strict=True)
    except (OSError, FileNotFoundError) as exc:
        raise ExtensionPathBlocked(
            f"extension path {str(path)!r} does not exist or is not "
            f"accessible: {exc}"
        ) from exc

    if not resolved.is_file():
        raise ExtensionPathBlocked(
            f"extension path {str(resolved)!r} is not a regular file"
        )

    dirs = allow_dirs if allow_dirs is not None else get_allowed_extension_dirs()
    if not dirs:
        raise ExtensionPathBlocked(
            f"extension loading refused: AU_EXTENSION_DIRS is empty. "
            f"Set AU_EXTENSION_DIRS to a directory you trust before "
            f"loading {str(resolved)!r}."
        )

    for d in dirs:
        try:
            d_resolved = Path(d).expanduser().resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(d_resolved)
        except ValueError:
            continue
        return resolved

    raise ExtensionPathBlocked(
        f"extension path {str(resolved)!r} is not inside any allowed "
        f"directory ({[str(d) for d in dirs]!r}); refusing to load. "
        "Add the parent directory to AU_EXTENSION_DIRS to opt in."
    )
