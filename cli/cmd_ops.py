"""``forge ops`` subcommand group (R49 split).

P2.B: daily operational report.
"""
from __future__ import annotations

from ._shared import _runtime_error


# ---------------------------------------------------------------------------
# ops subcommands (P2.B daily operational report)
# ---------------------------------------------------------------------------


def _build_ops_report(args):
    """Shared helper for ops commands that need a DailyOpsReport."""
    from pathlib import Path as _Path

    import pandas as pd

    from aurora.core.protocol_policy import get_active_policy
    from aurora.reporting.daily_ops import (
        DailyOpsBuilder,
        DailyOpsConfig,
    )

    if getattr(args, "asof", None):
        asof = pd.Timestamp(args.asof)
    else:
        # default: today's date (kept simple; deterministic given the call).
        asof = pd.Timestamp.today().normalize()
    strategies = (
        [s for s in args.strategies.split(",") if s]
        if getattr(args, "strategies", None) else []
    )
    if not strategies:
        # Fall back to a placeholder so the report still renders.
        strategies = ["(none)"]
    fmt = (
        [s for s in args.format.split(",") if s]
        if getattr(args, "format", None) else ["md", "json"]
    )
    portfolio_id = getattr(args, "portfolio", None)
    output_dir = (
        _Path(args.output_dir) if getattr(args, "output_dir", None)
        else None
    )
    cfg = DailyOpsConfig(
        asof_date=asof,
        strategies=strategies,
        portfolio_id=portfolio_id,
        output_format=fmt,
        output_dir=output_dir,
    )
    policy = get_active_policy()
    return DailyOpsBuilder(cfg, policy).build()


def cmd_ops_daily(args):
    """Build the daily ops report. Writes md/json artifacts to disk."""
    from pathlib import Path as _Path

    report = _build_ops_report(args)
    out_dir = (
        _Path(args.output_dir) if getattr(args, "output_dir", None)
        else None
    )
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        date = report.asof_date.date().isoformat()
        if "md" in (args.format or "").split(","):
            (out_dir / f"daily_{date}.md").write_text(
                report.to_markdown(), encoding="utf-8"
            )
        if "json" in (args.format or "").split(","):
            (out_dir / f"daily_{date}.json").write_text(
                report.to_json(), encoding="utf-8"
            )
    # Always print the markdown to stdout so the user sees the result.
    print(report.to_markdown())
    # Exit code 1 if any critical alert is present.
    return 1 if report.has_critical_alerts() else 0


def cmd_ops_alerts(args):
    """Print only the alerts. ``--severity`` filters output."""
    import json as _json

    report = _build_ops_report(args)
    severity = (args.severity or "").lower().strip()
    alerts = list(report.alerts)
    if severity:
        if severity not in ("info", "warn", "critical"):
            return _runtime_error(
                f"--severity must be info|warn|critical, got {severity!r}"
            )
        # Show >= the requested severity.
        order = {"info": 0, "warn": 1, "critical": 2}
        cutoff = order[severity]
        alerts = [a for a in alerts if order[a.severity] >= cutoff]
    if getattr(args, "json", False):
        print(_json.dumps([a.to_dict() for a in alerts], indent=2))
    else:
        if not alerts:
            print("No alerts.")
        else:
            for a in alerts:
                print(f"[{a.severity.upper()}] {a.code}: {a.title}")
                if a.detail:
                    print(f"  {a.detail}")
                if a.suggested_action:
                    print(f"  -> {a.suggested_action}")
    return 1 if any(a.severity == "critical" for a in alerts) else 0


def cmd_ops_summary(args):
    """Print the one-line summary (cron / slack friendly)."""
    report = _build_ops_report(args)
    print(report.to_summary_line())
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the ``ops`` subcommand group on the top-level subparsers."""
    p_ops = subparsers.add_parser(
        "ops",
        help="Daily operational report and alerts",
        description=(
            "Build the daily ops report (performance, drawdown, exposure, "
            "signals, regime, attribution, no-trade reasoning, alerts) "
            "or extract just the alerts / one-line summary."
        ),
    )
    ops_sub = p_ops.add_subparsers(dest="ops_cmd", required=True)

    def _add_common_ops_args(parser):
        parser.add_argument(
            "--asof", default=None,
            help="ISO date for the report (YYYY-MM-DD). "
                 "Defaults to today's date.",
        )
        parser.add_argument(
            "--strategies", default="",
            help="Comma-separated strategy ids to include in the report.",
        )
        parser.add_argument(
            "--portfolio", default=None,
            help="Portfolio id label.",
        )
        parser.add_argument(
            "--format", default="md,json",
            help="Comma-separated output formats (md and/or json).",
        )

    p_ops_daily = ops_sub.add_parser(
        "daily",
        help="Build the full daily report",
        description=(
            "Assemble all sections + alert checks into a single artifact. "
            "Writes md/json to --output-dir if provided. Exit code 1 "
            "indicates at least one critical alert."
        ),
    )
    _add_common_ops_args(p_ops_daily)
    p_ops_daily.add_argument(
        "--output-dir", default=None, dest="output_dir",
        help="Directory to write daily_<date>.md / .json artifacts to.",
    )
    p_ops_daily.set_defaults(func=cmd_ops_daily)

    p_ops_alerts = ops_sub.add_parser(
        "alerts",
        help="Print only the alerts",
        description=(
            "Run the alert checks and print results. Filter by severity "
            "with --severity {info,warn,critical}. Use --json for JSON "
            "output."
        ),
    )
    _add_common_ops_args(p_ops_alerts)
    p_ops_alerts.add_argument(
        "--severity", default="",
        help="Minimum severity to print (info|warn|critical).",
    )
    p_ops_alerts.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    p_ops_alerts.set_defaults(func=cmd_ops_alerts)

    p_ops_summary = ops_sub.add_parser(
        "summary",
        help="Print one-line summary (cron / slack friendly)",
        description=(
            "Print a compact one-line digest of the report so a cron job "
            "or slack hook can consume it."
        ),
    )
    _add_common_ops_args(p_ops_summary)
    p_ops_summary.set_defaults(func=cmd_ops_summary)
