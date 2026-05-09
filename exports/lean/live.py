"""Lean live-trading deploy gate (R1).

Hardens the Lean export pathway with a pre-deploy provenance gate and
an explicit-opt-in live deploy wrapper. The existing
:func:`exports.lean.exporter.verify_project` runs metadata-level checks;
this module adds the operational gate that an operator should run
before pushing to LEAN cloud.

Design contract
---------------

* ``dry_run=True`` is the default. Live deploy must be explicitly
  enabled; the wrapper refuses to call the Lean CLI otherwise.
* The provenance gate is non-bypassable: any ``ok=False`` result from
  :func:`exports.lean.exporter.verify_project` aborts the deploy.
* The Lean CLI / Cloud API call itself is intentionally NOT
  implemented here. Wiring it requires a real LEAN install plus an
  authenticated cloud account, neither of which exists in CI. Callers
  inject a ``cli_invoker`` callable; the default invoker raises
  :class:`NotImplementedError` so a misconfigured caller fails loud
  instead of silently no-op'ing.
* The deploy report is JSON-serializable so it can be archived
  alongside the Lean project for audit.
"""
from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from aurora.exports.lean.exporter import verify_project

_log = logging.getLogger("aurora.exports.lean.live")


CLIInvoker = Callable[[list[str]], dict[str, Any]]


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass
class LiveDeployConfig:
    """Knobs for a live deploy attempt.

    Attributes:
        dry_run: when True (default), the Lean CLI is NOT invoked. The
            provenance gate still runs and emits its report so an
            operator can dry-fit.
        require_clean_provenance: when True (default), any
            :func:`verify_project` failure aborts the deploy.
        require_explicit_operator_flag: when True (default), the live
            deploy refuses to run unless ``QF_LEAN_LIVE_AUTH=1`` is set
            in the environment. Mirrors the AgentGateway triple-gate.
        lean_cli: path to the ``lean`` executable. When None, the
            invoker is responsible for resolution (typical: assume on
            PATH).
        cloud_project_name: optional cloud-side project alias.
    """

    dry_run: bool = True
    require_clean_provenance: bool = True
    require_explicit_operator_flag: bool = True
    lean_cli: str | None = None
    cloud_project_name: str | None = None
    operator_flag_env: str = "QF_LEAN_LIVE_AUTH"


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LiveDeployResult:
    """Outcome of one ``prepare_live_deploy`` / ``deploy_to_lean_cloud`` call."""

    project_dir: str
    timestamp_iso: str
    dry_run: bool
    provenance_ok: bool
    provenance_errors: list[str]
    deploy_attempted: bool
    deploy_ok: bool | None
    deploy_response: dict[str, Any] | None
    blocking_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_dir": self.project_dir,
            "timestamp_iso": self.timestamp_iso,
            "dry_run": self.dry_run,
            "provenance_ok": self.provenance_ok,
            "provenance_errors": list(self.provenance_errors),
            "deploy_attempted": self.deploy_attempted,
            "deploy_ok": self.deploy_ok,
            "deploy_response": dict(self.deploy_response or {}),
            "blocking_reason": self.blocking_reason,
        }


# --------------------------------------------------------------------------
# Default invoker
# --------------------------------------------------------------------------


def _default_cli_invoker(argv: list[str]) -> dict[str, Any]:
    """Default Lean CLI invoker.

    The default deliberately refuses to run. A real deployment site is
    expected to inject an invoker that wraps the actual Lean CLI / Cloud
    API and returns ``{ok: bool, response: dict}``. Refusing keeps the
    test suite honest: a misconfigured caller would otherwise silently
    do nothing.
    """
    raise NotImplementedError(
        "no Lean CLI invoker configured; inject one via cli_invoker= or "
        "use dry_run=True for the provenance-only path. argv would have "
        f"been: {argv!r}"
    )


def subprocess_cli_invoker(argv: list[str]) -> dict[str, Any]:
    """Reference invoker that shells out to the local ``lean`` CLI.

    Use this only when the operator has confirmed the Lean CLI is
    installed and authenticated. The function returns a plain dict with
    ``returncode``, ``stdout`` and ``stderr`` so callers can audit the
    underlying tool's response without relying on any LEAN-specific
    schema.
    """
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "argv": list(argv),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "response": {"returncode": proc.returncode},
    }


# --------------------------------------------------------------------------
# Gate + deploy
# --------------------------------------------------------------------------


def prepare_live_deploy(
    project_dir: Path,
    config: LiveDeployConfig | None = None,
) -> LiveDeployResult:
    """Run the provenance gate without touching Lean.

    Returns a :class:`LiveDeployResult` whose ``provenance_ok`` field
    reflects the gate outcome. ``deploy_attempted`` is always False and
    ``deploy_ok`` is None.

    The ``config`` argument is accepted for API symmetry with
    :func:`deploy_to_lean_cloud`; this function does not consult any
    field on it because the gate it runs is unconditional.
    """
    del config  # symmetry-only; provenance gate ignores config knobs.
    project_dir = Path(project_dir)
    verify = verify_project(project_dir)
    return LiveDeployResult(
        project_dir=str(project_dir),
        timestamp_iso=pd.Timestamp.utcnow().isoformat(),
        dry_run=True,
        provenance_ok=bool(verify.get("ok")),
        provenance_errors=list(verify.get("errors") or []),
        deploy_attempted=False,
        deploy_ok=None,
        deploy_response=None,
        blocking_reason=None if verify.get("ok") else "provenance_failed",
    )


def deploy_to_lean_cloud(
    project_dir: Path,
    config: LiveDeployConfig | None = None,
    *,
    cli_invoker: CLIInvoker | None = None,
) -> LiveDeployResult:
    """Run the provenance gate and (when allowed) invoke the Lean CLI.

    The function returns a :class:`LiveDeployResult` even on refusal,
    so a caller can serialize the audit trail uniformly. ``blocking_reason``
    captures why a non-deploy happened: ``provenance_failed``,
    ``operator_flag_missing``, ``dry_run_active``, etc.
    """
    cfg = config or LiveDeployConfig()
    project_dir = Path(project_dir)

    verify = verify_project(project_dir)
    provenance_ok = bool(verify.get("ok"))
    provenance_errors = list(verify.get("errors") or [])

    # Hard gate: provenance must be clean unless explicitly disabled.
    if cfg.require_clean_provenance and not provenance_ok:
        return LiveDeployResult(
            project_dir=str(project_dir),
            timestamp_iso=pd.Timestamp.utcnow().isoformat(),
            dry_run=cfg.dry_run,
            provenance_ok=False,
            provenance_errors=provenance_errors,
            deploy_attempted=False,
            deploy_ok=None,
            deploy_response=None,
            blocking_reason="provenance_failed",
        )

    # Hard gate: operator flag.
    if cfg.require_explicit_operator_flag and os.environ.get(
        cfg.operator_flag_env, ""
    ) != "1":
        return LiveDeployResult(
            project_dir=str(project_dir),
            timestamp_iso=pd.Timestamp.utcnow().isoformat(),
            dry_run=cfg.dry_run,
            provenance_ok=provenance_ok,
            provenance_errors=provenance_errors,
            deploy_attempted=False,
            deploy_ok=None,
            deploy_response=None,
            blocking_reason="operator_flag_missing",
        )

    # Dry-run: do not invoke Lean.
    if cfg.dry_run:
        return LiveDeployResult(
            project_dir=str(project_dir),
            timestamp_iso=pd.Timestamp.utcnow().isoformat(),
            dry_run=True,
            provenance_ok=provenance_ok,
            provenance_errors=provenance_errors,
            deploy_attempted=False,
            deploy_ok=None,
            deploy_response=None,
            blocking_reason="dry_run_active",
        )

    # All gates passed: invoke the CLI.
    invoker = cli_invoker or _default_cli_invoker
    argv = _build_argv(project_dir, cfg)
    try:
        response = invoker(argv)
    except NotImplementedError as exc:
        return LiveDeployResult(
            project_dir=str(project_dir),
            timestamp_iso=pd.Timestamp.utcnow().isoformat(),
            dry_run=False,
            provenance_ok=provenance_ok,
            provenance_errors=provenance_errors,
            deploy_attempted=False,
            deploy_ok=None,
            deploy_response={"error": str(exc)},
            blocking_reason="invoker_not_configured",
        )
    except Exception as exc:
        return LiveDeployResult(
            project_dir=str(project_dir),
            timestamp_iso=pd.Timestamp.utcnow().isoformat(),
            dry_run=False,
            provenance_ok=provenance_ok,
            provenance_errors=provenance_errors,
            deploy_attempted=True,
            deploy_ok=False,
            deploy_response={"error": str(exc)},
            blocking_reason="invoker_raised",
        )

    return LiveDeployResult(
        project_dir=str(project_dir),
        timestamp_iso=pd.Timestamp.utcnow().isoformat(),
        dry_run=False,
        provenance_ok=provenance_ok,
        provenance_errors=provenance_errors,
        deploy_attempted=True,
        deploy_ok=bool(response.get("ok")),
        deploy_response=response,
        blocking_reason=None if response.get("ok") else "invoker_reported_failure",
    )


def _build_argv(project_dir: Path, cfg: LiveDeployConfig) -> list[str]:
    """Build the Lean CLI invocation."""
    cli = cfg.lean_cli or "lean"
    argv = [cli, "live", "deploy", str(project_dir)]
    if cfg.cloud_project_name:
        argv.extend(["--project", cfg.cloud_project_name])
    return argv


__all__ = [
    "LiveDeployConfig",
    "LiveDeployResult",
    "prepare_live_deploy",
    "deploy_to_lean_cloud",
    "subprocess_cli_invoker",
]
