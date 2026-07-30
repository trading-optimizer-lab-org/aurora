"""Central execution-location policy for expensive Aurora operations."""

from __future__ import annotations

import os
from typing import Mapping


EXPLICIT_LOCAL_TOKEN = "USER_REQUESTED_LOCAL_RUN_THIS_TURN"


class LocalRunBlocked(RuntimeError):
    """Raised when a protected operation is attempted outside GitHub Actions."""


def require_github_execution(
    operation: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Require GitHub Actions or the exact one-turn local permission token."""

    env = os.environ if environ is None else environ
    if env.get("GITHUB_ACTIONS", "").lower() == "true":
        return
    if env.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") == EXPLICIT_LOCAL_TOKEN:
        return
    raise LocalRunBlocked(
        "Run local bloqueado por politica Aurora. "
        f"Operacion: {operation}. Lanzalo en GitHub Actions o pide "
        "explicitamente ejecucion local."
    )


def require_github_actions_or_explicit_local_permission(
    run_kind: str = "research run",
    environ: Mapping[str, str] | None = None,
) -> None:
    """Compatibility name for legacy scripts using the same exact policy."""

    require_github_execution(run_kind, environ)


def require_github_only_execution(
    operation: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Require GitHub Actions with no local override.

    GTBI V7 scientific work, heavy merges, mass downloads and preservation
    transport use this stricter policy. The legacy one-turn override remains
    available only to callers that explicitly retain the older policy.
    """

    env = os.environ if environ is None else environ
    if env.get("GITHUB_ACTIONS", "").lower() == "true":
        return
    raise LocalRunBlocked(
        "Run local bloqueado por politica GitHub-only de GTBI V7. "
        f"Operacion: {operation}. Debe ejecutarse en GitHub Actions."
    )
