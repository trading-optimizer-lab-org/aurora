"""Env var migration helper (R76 -- sub-task of R23 Aurora rename).

The Aurora rename moves QF_* / QFORGE_* env vars to AU_* / AURORA_*. This
helper reads the new name first, falls back to the old name with a
DeprecationWarning, and is removed after the shim window (v1.6).

Migration table is in ``docs/ENV_VAR_MIGRATION_PLAN.md``.

Usage::

    from aurora.core.env_compat import aurora_env

    cache_dir = aurora_env("AU_CACHE_DIR", "QF_CACHE_DIR", default=None)
"""
from __future__ import annotations

import os
import warnings


def aurora_env(
    new_name: str,
    old_name: str | None = None,
    default: str | None = None,
) -> str | None:
    """Resolve an env var with a one-cycle deprecation shim.

    - If ``new_name`` is set, return it.
    - Else if ``old_name`` is provided and set, emit a ``DeprecationWarning``
      and return that value.
    - Else return ``default``.

    The warning is emitted at ``stacklevel=2`` so that operator code sees
    the call site, not this helper.
    """
    if new_name in os.environ:
        return os.environ[new_name]
    if old_name and old_name in os.environ:
        warnings.warn(
            f"{old_name} is deprecated; use {new_name}.",
            DeprecationWarning,
            stacklevel=2,
        )
        return os.environ[old_name]
    return default


__all__ = ["aurora_env"]
