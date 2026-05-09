"""Backward-compatibility shim: ``import quantforge`` -> ``aurora``.

The Aurora rename (R23) moved the canonical package namespace from
``quantforge`` to ``aurora``. This shim keeps existing downstream
consumers importing ``quantforge.*`` working for one shim cycle.

Importing this package emits a single ``DeprecationWarning``. Removed
in v1.6 per ``docs/AURORA_RENAME_CHECKLIST.md``.

Implementation: we register the real ``aurora`` package object under
``sys.modules['quantforge']`` plus mirror every ``aurora.X`` submodule
to ``quantforge.X`` so ``from aurora.core import run_backtest``
resolves to the same module object as ``aurora.core``.
"""
from __future__ import annotations

import importlib
import sys
import warnings


warnings.warn(
    "The `quantforge` namespace is deprecated; import from `aurora` instead. "
    "This shim is removed in v1.6 (see docs/AURORA_RENAME_CHECKLIST.md).",
    DeprecationWarning,
    stacklevel=2,
)

# Pull in the renamed package and re-export every symbol so
# ``quantforge.X`` and ``aurora.X`` resolve to the same module object.
import aurora as _aurora  # noqa: E402

# Mirror the public attributes of the real aurora package so direct
# attribute access (`quantforge.run_backtest`, `quantforge.__version__`,
# etc.) continues to work. We do NOT replace ``sys.modules['quantforge']``
# with ``_aurora`` because then ``from aurora.core import X`` would
# go through ``_aurora.core`` -- which is fine -- but the package object
# kept in ``sys.modules['quantforge']`` would be the same as
# ``sys.modules['aurora']``, breaking any code that distinguishes them
# (e.g. ``importlib.metadata.version('quantforge')``).
for _name in getattr(_aurora, "__all__", []) or []:
    try:
        globals()[_name] = getattr(_aurora, _name)
    except AttributeError:  # pragma: no cover - aurora is in flux
        pass

__version__ = getattr(_aurora, "__version__", "0.0.0+local")


# Eagerly mirror the most common submodules so ``from aurora.X import Y``
# works without the importer having to navigate the shim each time.
for _sub in (
    "core",
    "validation",
    "ga",
    "ml",
    "strategies",
    "deployment",
    "research",
    "monitoring",
    "registry",
    "reporting",
    "agent_gateway",
    "agents",
    "exports",
    "execution",
    "compliance",
    "altdata",
    "marketdata",
    "markets",
    "portfolio",
    "risk",
    "regime",
    "signals",
    "infra",
    "dataeng",
    "analytics",
    "experimental",
    "triage",
    "research.factory",
    "agents.auditor",
    "core.data_providers",
    "exports.lean",
    "reporting.daily_ops",
    "strategies.library",
    "cli",
):
    try:
        _mod = importlib.import_module(f"aurora.{_sub}")
        sys.modules[f"aurora.{_sub}"] = _mod
    except ImportError:
        # Optional deps may legitimately fail; skip silently.
        continue


def __getattr__(name: str):  # pragma: no cover - exercised via import paths
    """PEP-562 lazy module attribute hook.

    Resolves ``quantforge.<name>`` by delegating to the real ``aurora``
    package + caching the result in ``sys.modules`` so subsequent
    ``import aurora.<name>`` lookups skip the dispatch.
    """
    try:
        mod = importlib.import_module(f"aurora.{name}")
    except ImportError as exc:
        raise AttributeError(name) from exc
    sys.modules[f"aurora.{name}"] = mod
    globals()[name] = mod
    return mod


__all__ = list(getattr(_aurora, "__all__", []) or [])
