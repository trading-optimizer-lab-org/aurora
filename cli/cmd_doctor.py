"""``aurora doctor`` subcommand (R187).

Runs the operator health-check registry and prints either a human
table (default) or JSON. Read-only and offline by default; pass
``--allow-network`` to opt into network-touching checks.
"""
from __future__ import annotations

import sys


def cmd_doctor(args) -> int:
    """Drive :mod:`aurora.monitoring.doctor.run_doctor` and emit output."""
    from aurora.monitoring.doctor import run_doctor

    only = None
    if getattr(args, "only", None):
        only = [s.strip() for s in args.only.split(",") if s.strip()]
    report = run_doctor(
        allow_network=bool(getattr(args, "allow_network", False)),
        only=only,
    )
    if getattr(args, "json", False):
        print(report.to_json())
    else:
        print(report.to_table())
    severity = report.overall_severity()
    if severity == "fail":
        return 2
    if severity == "warn":
        return 1
    return 0


def register(subparsers, parent_parser=None) -> None:
    """Register ``forge doctor`` subcommand."""
    p = subparsers.add_parser(
        "doctor",
        help="Health-check the local environment",
        description=(
            "Run a registry of read-only checks and report pass/warn/"
            "fail/skip per check. Offline by default."
        ),
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of a table.",
    )
    p.add_argument(
        "--allow-network", action="store_true", dest="allow_network",
        help="Allow checks marked as network-dependent.",
    )
    p.add_argument(
        "--only", default=None,
        help="Comma-separated subset of check names to run.",
    )
    p.set_defaults(func=lambda a: sys.exit(cmd_doctor(a)))
