"""Execution policy guards for Aurora research scripts."""

from __future__ import annotations

import os


LOCAL_RUN_PERMISSION_ENV = "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT"
LOCAL_RUN_PERMISSION_VALUE = "USER_REQUESTED_LOCAL_RUN_THIS_TURN"

LOCAL_RUN_BLOCKED_MESSAGE = (
    "Run local bloqueado por politica Aurora. "
    "Lanzalo en GitHub Actions o pide explicitamente ejecucion local."
)


class LocalRunBlocked(RuntimeError):
    """Raised when a protected research run is started outside GitHub."""


def running_in_github_actions(env: dict[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return values.get("GITHUB_ACTIONS", "").lower() == "true"


def has_explicit_local_run_permission(env: dict[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return values.get(LOCAL_RUN_PERMISSION_ENV) == LOCAL_RUN_PERMISSION_VALUE


def require_github_actions_or_explicit_local_permission(
    run_kind: str = "research run",
    *,
    env: dict[str, str] | None = None,
) -> None:
    """Block protected research runs unless GitHub or explicit local permission is present."""

    if running_in_github_actions(env) or has_explicit_local_run_permission(env):
        return
    raise LocalRunBlocked(f"{LOCAL_RUN_BLOCKED_MESSAGE} Tipo: {run_kind}.")

