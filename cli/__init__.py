"""QuantForge CLI public API surface (R73).

Importers should reach into this package, not the multi-thousand-line
`cli.forge` module directly. Lazy re-export of the entry point so
external callers and tests have a stable surface that survives the
future `cli/forge.py` split (R49). Lazy import avoids a runpy
RuntimeWarning when the user runs ``python -m quantforge.cli.forge``
because eager re-export populates `sys.modules` before runpy executes
the module.

Stable surface:

- :func:`main` -- the `forge` console-script entry point.

Anything not listed here is internal and may move at any time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any


__all__ = ["main"]


def __getattr__(name: str) -> Any:
    if name == "main":
        from .forge import main as _main
        return _main
    raise AttributeError(f"module 'quantforge.cli' has no attribute {name!r}")


if TYPE_CHECKING:
    from .forge import main  # noqa: F401
