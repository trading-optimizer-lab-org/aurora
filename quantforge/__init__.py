"""Backward-compatibility shim: ``import quantforge`` -> ``aurora``.

The Aurora rename (R23) moved the canonical package namespace from
``quantforge`` to ``aurora``. This shim keeps existing downstream
consumers importing ``quantforge.*`` working for one shim cycle.

Importing this package emits a single ``DeprecationWarning``. Removed
in v1.6 per ``docs/AURORA_RENAME_CHECKLIST.md``.

Implementation: a meta-path finder resolves any ``quantforge.<X>``
import by creating a proxy module whose ``__dict__`` shares references
with the corresponding ``aurora.<X>`` module. That keeps
``aurora.cli.forge.main is quantforge.cli.forge.main`` (same function
object) while letting ``runpy`` accept ``python -m quantforge.<X>``
because the proxy module's ``__name__`` matches what runpy asked for.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
import warnings


warnings.warn(
    "The `quantforge` namespace is deprecated; import from `aurora` instead. "
    "This shim is removed in v1.6 (see docs/AURORA_RENAME_CHECKLIST.md).",
    DeprecationWarning,
    stacklevel=2,
)


import aurora as _aurora  # noqa: E402


# Mirror the public attributes of the real aurora package on this shim
# package object so direct attribute access (`quantforge.run_backtest`,
# `quantforge.__version__`) resolves to the same objects.
for _name in getattr(_aurora, "__all__", []) or []:
    try:
        globals()[_name] = getattr(_aurora, _name)
    except AttributeError:  # pragma: no cover - aurora is in flux
        pass

__version__ = getattr(_aurora, "__version__", "0.0.0+local")


# ---------------------------------------------------------------------------
# Meta-path finder for `quantforge.<X>` -> `aurora.<X>`
# ---------------------------------------------------------------------------


class _QuantforgeAliasLoader(importlib.abc.Loader):
    """Loader that fills a module's __dict__ from the aurora.<X> module.

    The proxy module keeps ``__name__ = "quantforge.<X>"`` (so runpy's
    -m check passes) but its globals share references with the aurora
    submodule, so attribute access yields the SAME function / class
    objects across both namespaces.
    """

    def __init__(self, aurora_name: str) -> None:
        self.aurora_name = aurora_name

    def create_module(self, spec):  # noqa: D401 - default semantics
        return None  # use the default module type

    def exec_module(self, module) -> None:
        target = importlib.import_module(self.aurora_name)
        # Copy the aurora module's __dict__ into the proxy. Functions,
        # classes, constants -- all references point at the same
        # objects, which preserves `is` identity for callable lookups.
        module.__dict__.update(target.__dict__)
        # Restore the proxy's own identity so runpy's name check (which
        # compares ``module.__name__`` to the user-requested name) still
        # passes for ``python -m quantforge.<X>`` invocations.
        module.__name__ = module.__spec__.name
        if "__path__" in target.__dict__:
            module.__path__ = list(target.__path__)
        module.__doc__ = target.__doc__

    # runpy's ``_get_module_details`` reaches into ``loader.get_filename``
    # and ``loader.get_code`` to pre-compile the module before handing it
    # to the script-runner. Forward both to the aurora module's own
    # source so ``python -m quantforge.<X>`` works.
    def get_filename(self, fullname):  # noqa: D401
        target = importlib.import_module(self.aurora_name)
        return getattr(target, "__file__", None)

    def get_code(self, fullname):  # noqa: D401
        filename = self.get_filename(fullname)
        if not filename:
            return None
        with open(filename, "rb") as fh:
            source = fh.read()
        return compile(source, filename, "exec")

    def is_package(self, fullname):  # noqa: D401
        target = importlib.import_module(self.aurora_name)
        return hasattr(target, "__path__")

    def get_source(self, fullname):  # noqa: D401
        filename = self.get_filename(fullname)
        if not filename:
            return None
        with open(filename, "r", encoding="utf-8") as fh:
            return fh.read()


class _QuantforgeAliasFinder(importlib.abc.MetaPathFinder):
    """Resolve ``quantforge.<X>`` imports as aurora-aliased proxies."""

    _PREFIX = "quantforge."

    def find_spec(self, fullname, path, target=None):  # noqa: D401
        if not fullname.startswith(self._PREFIX):
            return None
        # Avoid hijacking the bare ``quantforge`` package import (handled
        # by this very file's __init__.py).
        if fullname == "quantforge":
            return None
        aurora_name = "aurora." + fullname[len(self._PREFIX):]
        try:
            target_spec = importlib.util.find_spec(aurora_name)
        except (ImportError, ValueError):
            return None
        if target_spec is None:
            return None
        loader = _QuantforgeAliasLoader(aurora_name)
        is_package = bool(getattr(target_spec, "submodule_search_locations", None))
        spec = importlib.machinery.ModuleSpec(
            fullname,
            loader,
            origin=getattr(target_spec, "origin", None),
            is_package=is_package,
        )
        if is_package:
            spec.submodule_search_locations = list(
                target_spec.submodule_search_locations or []
            )
        return spec


# Install the finder in front of the default machinery so it wins for
# any ``quantforge.<X>`` lookup. Idempotent: only one instance ever
# lands on sys.meta_path.
_finder = _QuantforgeAliasFinder()
if not any(isinstance(f, _QuantforgeAliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _finder)


__all__ = list(getattr(_aurora, "__all__", []) or [])
