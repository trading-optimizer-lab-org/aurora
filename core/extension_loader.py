"""R186 - Local-only extension loader.

Imports ``*_aurora_ext.py`` files from operator-configured directories
and registers the extensions they declare with the appropriate Aurora
registry (currently :class:`aurora.core.data_providers.DataProviderRegistry`
and the strategy class registry).

The loader is intentionally minimal:

* Path-only discovery (no entry-points, no PyPI scanning).
* Refuses to load anything outside the env-configured allowlist
  (see :func:`aurora.core.extension_api.assert_safe_extension_path`).
* Refuses any extension that declares ``bypass_oosguard=True`` or any
  other capability flag in
  :data:`aurora.core.extension_api.FORBIDDEN_CAPABILITY_FLAGS`.

The loader does NOT execute arbitrary network code, does NOT shell out,
and never persists state. Failures during ``load_extension`` raise and
register nothing.

Public API
----------
* :func:`discover_extensions` -- walk allow_dirs, return descriptors.
* :func:`load_extension` -- load a single file, return its descriptor.
* :func:`register_loaded_extensions` -- register descriptors with the
  matching Aurora registry.
* :class:`LoadedExtension` -- typed result returned by both helpers.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from aurora.core.extension_api import (
    FORBIDDEN_CAPABILITY_FLAGS,
    ExtensionPathBlocked,
    IncompatibleInterfaceError,
    assert_safe_extension_path,
    check_interface_version,
    get_allowed_extension_dirs,
)


__all__ = [
    "EXTENSION_FILE_SUFFIX",
    "ExtensionLoadError",
    "LoadedExtension",
    "discover_extensions",
    "load_extension",
    "register_loaded_extensions",
]


_log = logging.getLogger(__name__)


EXTENSION_FILE_SUFFIX = "_aurora_ext.py"
_DESCRIPTOR_ATTR = "__aurora_extension__"


class ExtensionLoadError(Exception):
    """Raised when an extension file is structurally invalid.

    Distinct from :class:`IncompatibleInterfaceError` (version mismatch)
    and :class:`ExtensionPathBlocked` (allowlist refusal).
    """


@dataclass
class LoadedExtension:
    """One loaded extension's descriptor + factory.

    Attributes:
        path: absolute path of the source file.
        name: stable extension name (descriptor['name']).
        kind: one of ``"DataProvider"``, ``"Strategy"``, ... matching a
            key in :data:`INTERFACE_VERSIONS`.
        interface_version: the version string the extension declared.
        factory: a zero-arg callable that returns a freshly-built
            instance (provider object, strategy class, validator, ...).
        capabilities: the descriptor's ``capabilities`` dict (whitelist
            of flags the extension claims). ``FORBIDDEN_CAPABILITY_FLAGS``
            entries set to True are refused at load time.
        descriptor: the raw ``__aurora_extension__`` mapping for
            inspection / audit.
    """

    path: Path
    name: str
    kind: str
    interface_version: str
    factory: Any
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    descriptor: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Discovery + load
# ---------------------------------------------------------------------------


def discover_extensions(
    allow_dirs: Optional[Sequence[Path]] = None,
) -> List[LoadedExtension]:
    """Walk ``allow_dirs`` and load every ``*_aurora_ext.py`` file.

    Files that fail to load (bad path, invalid descriptor, version
    mismatch, forbidden capability flag) are SKIPPED with a logged
    warning. The returned list contains only successfully-loaded
    extensions.

    Args:
        allow_dirs: explicit allowlist; defaults to the env-configured
            :func:`get_allowed_extension_dirs`.
    """
    if allow_dirs is None:
        allow_dirs = list(get_allowed_extension_dirs())
    else:
        allow_dirs = [Path(d).expanduser().resolve() for d in allow_dirs]

    if not allow_dirs:
        return []

    out: List[LoadedExtension] = []
    seen: set[Path] = set()
    for d in allow_dirs:
        if not d.is_dir():
            continue
        for path in sorted(d.rglob(f"*{EXTENSION_FILE_SUFFIX}")):
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                ext = load_extension(
                    resolved, allow_dirs=tuple(allow_dirs)
                )
            except (
                ExtensionPathBlocked,
                IncompatibleInterfaceError,
                ExtensionLoadError,
            ) as exc:
                _log.warning(
                    "skipping extension %s: %s", str(resolved), exc
                )
                continue
            out.append(ext)
    return out


def load_extension(
    path: Any,
    *,
    allow_dirs: Optional[Sequence[Path]] = None,
) -> LoadedExtension:
    """Import ``path`` (a ``*_aurora_ext.py`` file) and return its
    :class:`LoadedExtension` descriptor.

    The function:

    1. Calls :func:`assert_safe_extension_path` to refuse paths outside
       the operator allowlist.
    2. Imports the file via :func:`importlib.util.spec_from_file_location`
       under a synthetic module name (``aurora_ext.<stem>``).
    3. Reads the module's ``__aurora_extension__`` dict; refuses
       extensions that omit it.
    4. Calls :func:`check_interface_version` for the declared kind.
    5. Refuses any extension whose ``capabilities`` dict sets a
       :data:`FORBIDDEN_CAPABILITY_FLAGS` key to ``True``.

    Returns:
        A :class:`LoadedExtension`. The caller is responsible for
        :func:`register_loaded_extensions`.
    """
    dirs: Optional[Tuple[Path, ...]]
    if allow_dirs is None:
        dirs = None
    else:
        dirs = tuple(Path(d).expanduser().resolve() for d in allow_dirs)
    resolved = assert_safe_extension_path(path, allow_dirs=dirs)

    if not resolved.name.endswith(EXTENSION_FILE_SUFFIX):
        raise ExtensionLoadError(
            f"extension file {resolved.name!r} must end in "
            f"{EXTENSION_FILE_SUFFIX!r}; refusing to load."
        )

    module_name = f"aurora_ext.{resolved.stem}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise ExtensionLoadError(
            f"cannot build import spec for {str(resolved)!r}"
        )
    # Replace any stale prior load of the same synthetic module name so
    # repeated load_extension calls (e.g. ``replace=True``) do not surface
    # the previously-cached module.
    sys.modules.pop(module_name, None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ExtensionLoadError(
            f"executing {str(resolved)!r} raised: {exc}"
        ) from exc

    descriptor = getattr(module, _DESCRIPTOR_ATTR, None)
    if not isinstance(descriptor, Mapping):
        sys.modules.pop(module_name, None)
        raise ExtensionLoadError(
            f"extension {str(resolved)!r} is missing the "
            f"{_DESCRIPTOR_ATTR!r} mapping at module scope."
        )

    name = descriptor.get("name")
    kind = descriptor.get("kind")
    interface_version = descriptor.get("interface_version")
    factory = descriptor.get("factory")
    capabilities: Mapping[str, Any] = descriptor.get("capabilities", {}) or {}

    if not isinstance(name, str) or not name:
        raise ExtensionLoadError(
            f"extension {str(resolved)!r} descriptor missing a "
            "non-empty 'name' string."
        )
    if not isinstance(kind, str) or not kind:
        raise ExtensionLoadError(
            f"extension {str(resolved)!r} descriptor missing a "
            "non-empty 'kind' string."
        )
    if not isinstance(interface_version, str) or not interface_version:
        raise ExtensionLoadError(
            f"extension {str(resolved)!r} descriptor missing a "
            "non-empty 'interface_version' string."
        )
    if not callable(factory):
        raise ExtensionLoadError(
            f"extension {str(resolved)!r} descriptor 'factory' must be "
            "a zero-arg callable returning the extension instance."
        )

    if not isinstance(capabilities, Mapping):
        raise ExtensionLoadError(
            f"extension {str(resolved)!r} descriptor 'capabilities' "
            "must be a mapping."
        )
    for flag in FORBIDDEN_CAPABILITY_FLAGS:
        if bool(capabilities.get(flag)):
            raise ExtensionLoadError(
                f"extension {str(resolved)!r} declares forbidden "
                f"capability {flag!r}=True. AURORA refuses to load any "
                "extension that opts out of OOSGuard / audit / "
                "provider-terms invariants."
            )

    # Surface the version check itself; we want the loader to raise
    # IncompatibleInterfaceError so callers can distinguish the cause.
    check_interface_version(descriptor, kind)

    return LoadedExtension(
        path=resolved,
        name=name,
        kind=kind,
        interface_version=interface_version,
        factory=factory,
        capabilities=dict(capabilities),
        descriptor=dict(descriptor),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_loaded_extensions(
    extensions: Iterable[LoadedExtension],
    *,
    replace: bool = False,
) -> Dict[str, List[str]]:
    """Register each :class:`LoadedExtension` with the right registry.

    Args:
        extensions: iterable of descriptors from
            :func:`load_extension` / :func:`discover_extensions`.
        replace: when True, allow overwriting an existing registration.

    Returns:
        A dict ``{kind: [registered_names]}`` summarising what was added.

    Currently supported registries:

    * ``"DataProvider"`` -> :func:`get_default_registry().register`.
    * ``"Strategy"`` -> appended to the in-process strategy class table
      so callers can look them up by name. (Aurora has no global strategy
      registry; we expose the loaded class via the returned summary.)

    Other ``kind`` values are returned in the summary but not auto-
    registered; the caller is expected to plug them into the matching
    subsystem.
    """
    summary: Dict[str, List[str]] = {}

    for ext in extensions:
        if ext.kind == "DataProvider":
            from aurora.core.data_providers import (
                get_default_registry,
            )
            registry = get_default_registry()
            instance = ext.factory()
            registry.register(instance, replace=replace)
            summary.setdefault("DataProvider", []).append(ext.name)
        elif ext.kind == "Strategy":
            # Strategy registration: the factory is expected to return a
            # Strategy SUBCLASS (not an instance) so callers can keep
            # constructing fresh instances per-experiment. We record the
            # name in the summary; in-process discovery is enough.
            cls = ext.factory()
            if not isinstance(cls, type):
                raise ExtensionLoadError(
                    f"strategy extension {ext.name!r} factory must "
                    "return a class, got "
                    f"{type(cls).__name__}"
                )
            summary.setdefault("Strategy", []).append(ext.name)
        else:
            # Validator / BrokerAdapter / ReportRenderer / AuditSink /
            # Signal / Feature / ExecutionModel / RiskModel: surface in
            # the summary so the caller can wire them in. We do not have
            # a single global registry for these surfaces today.
            summary.setdefault(ext.kind, []).append(ext.name)

    return summary
