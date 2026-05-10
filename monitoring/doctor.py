"""R187 - Operator doctor.

``aurora doctor`` runs a registry of read-only health checks and reports
status per check. The default invocation must not perform network I/O.

Each check returns a :class:`HealthStatus`. Results are aggregated into
:class:`DoctorReport` which can render as table text or JSON.

Public surface (small on purpose):

* :func:`run_doctor` -- run all (or a filtered subset of) checks
* :func:`default_checks` -- the built-in check list
* :class:`HealthStatus`, :class:`DoctorReport`, :class:`HealthCheck`
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Literal, Optional, Sequence

Severity = Literal["pass", "warn", "fail", "skip"]


@dataclass(frozen=True)
class HealthStatus:
    """Result of a single health check."""

    name: str
    severity: Severity
    message: str
    remediation: Optional[str] = None
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "severity": self.severity,
            "message": self.message,
        }
        if self.remediation:
            d["remediation"] = self.remediation
        if self.detail:
            d["detail"] = self.detail
        return d


@dataclass
class HealthCheck:
    """A single named health check.

    ``run`` must be a function returning a :class:`HealthStatus`. It must
    not raise -- failure to execute should surface as ``severity="fail"``.
    """

    name: str
    description: str
    run: Callable[[], HealthStatus]
    requires_network: bool = False


@dataclass
class DoctorReport:
    """Aggregated result of running every check."""

    statuses: List[HealthStatus] = field(default_factory=list)

    def add(self, status: HealthStatus) -> None:
        self.statuses.append(status)

    def counts(self) -> dict:
        out = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
        for s in self.statuses:
            out[s.severity] = out.get(s.severity, 0) + 1
        return out

    def overall_severity(self) -> Severity:
        c = self.counts()
        if c["fail"]:
            return "fail"
        if c["warn"]:
            return "warn"
        return "pass"

    def to_json(self) -> str:
        return json.dumps(
            {
                "overall": self.overall_severity(),
                "counts": self.counts(),
                "checks": [s.to_dict() for s in self.statuses],
            },
            indent=2,
            sort_keys=True,
        )

    def to_table(self) -> str:
        if not self.statuses:
            return "(no checks)"
        rows = [("CHECK", "SEVERITY", "MESSAGE")]
        rows.extend((s.name, s.severity, s.message) for s in self.statuses)
        widths = [max(len(r[i]) for r in rows) for i in range(3)]
        lines = []
        for r in rows:
            lines.append(
                "  ".join(r[i].ljust(widths[i]) for i in range(3))
            )
        c = self.counts()
        lines.append("")
        lines.append(
            f"overall: {self.overall_severity()}  "
            f"pass={c['pass']} warn={c['warn']} "
            f"fail={c['fail']} skip={c['skip']}"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Built-in checks. Each helper is small and self-contained so it can be
# tested in isolation.
# ---------------------------------------------------------------------------


def _check_package_import() -> HealthStatus:
    name = "package_import"
    try:
        import aurora  # noqa: F401
    except Exception as exc:  # pragma: no cover - import failure is the bug
        return HealthStatus(
            name=name,
            severity="fail",
            message=f"cannot import aurora: {exc}",
            remediation="pip install -e . from the repo root",
        )
    version = getattr(__import__("aurora"), "__version__", "unknown")
    return HealthStatus(
        name=name,
        severity="pass",
        message=f"aurora {version} imports cleanly",
    )


def _check_python_version() -> HealthStatus:
    name = "python_version"
    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) < (3, 10):
        return HealthStatus(
            name=name,
            severity="fail",
            message=f"python {major}.{minor} too old; need >=3.10",
            remediation="install a supported python interpreter",
        )
    return HealthStatus(
        name=name,
        severity="pass",
        message=f"python {major}.{minor}",
    )


def _check_runtime_paths() -> HealthStatus:
    name = "runtime_paths"
    try:
        from aurora.core import runtime_paths as rp
        targets = {
            "data": rp.base_data_dir(),
            "cache": rp.cache_dir(),
        }
    except Exception as exc:
        return HealthStatus(
            name=name,
            severity="fail",
            message=f"runtime_paths unavailable: {exc}",
            remediation="check AU_DATA_DIR and AU_CACHE_DIR env vars",
        )
    bad = [k for k, p in targets.items() if not _is_writable_dir(p)]
    if bad:
        return HealthStatus(
            name=name,
            severity="fail",
            message=f"non-writable runtime dirs: {','.join(bad)}",
            remediation="chmod the directories or override AU_DATA_DIR",
            detail=str({k: str(p) for k, p in targets.items()}),
        )
    return HealthStatus(
        name=name,
        severity="pass",
        message="data + cache dirs writable",
        detail=str({k: str(p) for k, p in targets.items()}),
    )


def _check_audit_log_writable() -> HealthStatus:
    name = "audit_log"
    try:
        from aurora.core import runtime_paths as rp
        log_path = rp.audit_log_path()
    except Exception as exc:
        return HealthStatus(
            name=name,
            severity="warn",
            message=f"audit_log_path unavailable: {exc}",
            remediation="check AU_AUDIT_LOG override",
        )
    parent = log_path.parent
    if not _is_writable_dir(parent):
        return HealthStatus(
            name=name,
            severity="fail",
            message=f"audit log parent not writable: {parent}",
            remediation="chmod or override AU_AUDIT_LOG",
        )
    return HealthStatus(
        name=name,
        severity="pass",
        message=f"audit log writable at {log_path}",
    )


def _check_oos_lock() -> HealthStatus:
    name = "oos_lock"
    try:
        from aurora.core import runtime_paths as rp
        lock_path = rp.oos_lock_path()
    except Exception as exc:
        return HealthStatus(
            name=name,
            severity="warn",
            message=f"oos lock path unavailable: {exc}",
        )
    if not lock_path.exists():
        return HealthStatus(
            name=name,
            severity="pass",
            message="no active oos unlock",
        )
    try:
        size = lock_path.stat().st_size
    except OSError as exc:
        return HealthStatus(
            name=name,
            severity="warn",
            message=f"cannot stat lock: {exc}",
        )
    return HealthStatus(
        name=name,
        severity="warn",
        message=f"oos lock present ({size} bytes)",
        remediation="review aurora policy verify before promotion",
    )


def _check_optional_deps() -> HealthStatus:
    name = "optional_deps"
    optional = {
        "scikit-learn": "ml extras (sklearn)",
        "torch": "deep-learning extras",
        "deap": "ga extras",
        "cvxpy": "portfolio optimisation",
        "streamlit": "monitoring dashboard",
    }
    found, missing = [], []
    for pkg, _purpose in optional.items():
        if _module_importable(pkg.replace("-", "_")):
            found.append(pkg)
        else:
            missing.append(pkg)
    return HealthStatus(
        name=name,
        severity="warn" if missing else "pass",
        message=(
            f"present: {','.join(found) or 'none'}; "
            f"missing: {','.join(missing) or 'none'}"
        ),
        remediation=(
            "pip install 'aurora[ml,dl,ga,portfolio,monitoring]'"
            if missing else None
        ),
    )


def _check_first_dataset() -> HealthStatus:
    name = "first_dataset"
    try:
        from aurora.core import runtime_paths as rp
        snap = rp.snapshot_root()
    except Exception as exc:
        return HealthStatus(
            name=name,
            severity="warn",
            message=f"snapshots root unavailable: {exc}",
        )
    if not snap.exists() or not any(snap.iterdir()):
        return HealthStatus(
            name=name,
            severity="warn",
            message=f"no snapshots present at {snap}",
            remediation="aurora data fetch or build a first snapshot",
        )
    n = sum(1 for _ in snap.iterdir())
    return HealthStatus(
        name=name,
        severity="pass",
        message=f"{n} snapshot entries at {snap}",
    )


def _check_provider_credentials() -> HealthStatus:
    name = "provider_credentials"
    keys = (
        "AURORA_TIINGO_TOKEN", "AURORA_FRED_KEY", "AURORA_ALPACA_KEY",
        "AURORA_BINANCE_KEY",
    )
    present = [k for k in keys if os.environ.get(k)]
    return HealthStatus(
        name=name,
        severity="pass" if present else "warn",
        message=(
            f"{len(present)}/{len(keys)} provider credentials present"
        ),
        remediation=(
            "set env vars for any provider you intend to use"
            if not present else None
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_writable_dir(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        if not path.is_dir():
            return False
        return os.access(path, os.W_OK)
    except OSError:
        return False


def _module_importable(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ValueError, ModuleNotFoundError):
        return False


# ---------------------------------------------------------------------------
# Registry + driver
# ---------------------------------------------------------------------------


def default_checks() -> List[HealthCheck]:
    """Return the built-in check registry. Order is stable for tests."""
    return [
        HealthCheck(
            "package_import",
            "import aurora package and report version",
            _check_package_import,
        ),
        HealthCheck(
            "python_version",
            "verify python interpreter version >= 3.10",
            _check_python_version,
        ),
        HealthCheck(
            "runtime_paths",
            "verify data and cache dirs exist and are writable",
            _check_runtime_paths,
        ),
        HealthCheck(
            "audit_log",
            "verify audit log destination is writable",
            _check_audit_log_writable,
        ),
        HealthCheck(
            "oos_lock",
            "report whether OOS unlock ceremony is active",
            _check_oos_lock,
        ),
        HealthCheck(
            "optional_deps",
            "report which optional dependency stacks are installed",
            _check_optional_deps,
        ),
        HealthCheck(
            "first_dataset",
            "report whether at least one snapshot has been built",
            _check_first_dataset,
        ),
        HealthCheck(
            "provider_credentials",
            "report which provider credential env vars are set",
            _check_provider_credentials,
        ),
    ]


def run_doctor(
    checks: Optional[Sequence[HealthCheck]] = None,
    *,
    allow_network: bool = False,
    only: Optional[Sequence[str]] = None,
) -> DoctorReport:
    """Run health checks and aggregate into a :class:`DoctorReport`.

    Args:
        checks: explicit check list; defaults to :func:`default_checks`.
        allow_network: include checks marked ``requires_network``. Default
            is False so ``aurora doctor`` is offline by default.
        only: restrict to checks whose name appears in this iterable.
    """
    selected = list(checks) if checks is not None else default_checks()
    if only is not None:
        wanted = set(only)
        selected = [c for c in selected if c.name in wanted]
    report = DoctorReport()
    for check in selected:
        if check.requires_network and not allow_network:
            report.add(
                HealthStatus(
                    name=check.name,
                    severity="skip",
                    message="skipped: network check; pass --allow-network",
                )
            )
            continue
        try:
            status = check.run()
        except Exception as exc:  # defensive -- a check should not raise
            status = HealthStatus(
                name=check.name,
                severity="fail",
                message=f"check raised {type(exc).__name__}: {exc}",
            )
        report.add(status)
    return report


__all__ = [
    "DoctorReport",
    "HealthCheck",
    "HealthStatus",
    "Severity",
    "default_checks",
    "run_doctor",
]
