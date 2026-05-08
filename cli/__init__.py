"""QuantForge CLI public API surface (R73).

Importers should reach into this package, not the multi-thousand-line
`cli.forge` module directly. Re-exports the entry point so external
callers and tests have a stable surface that survives the future
`cli/forge.py` split (R49).

Stable surface:

- :func:`main` -- the `forge` console-script entry point.

Anything not listed here is internal and may move at any time.
"""
from __future__ import annotations

from .forge import main


__all__ = ["main"]
