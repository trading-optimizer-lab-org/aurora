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
