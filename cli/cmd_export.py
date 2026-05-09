"""``forge export`` subcommand group (R49 split).

P3.B: Lean (QuantConnect) cross-validation adapter.
"""
from __future__ import annotations

from ._shared import _runtime_error, _strategy_spec_from_yaml


# ---------------------------------------------------------------------------
# Export subcommands (P3.B Lean export adapter)
# ---------------------------------------------------------------------------


def _strategy_spec_for_export(spec_path):
    """Load a StrategySpec from YAML/JSON for the Lean exporter.

    Reuses ``_strategy_spec_from_yaml``; isolated here so the export
    flow stays decoupled from research-factory specifics in future
    refactors (e.g. supporting a GA spec file directly).
    """
    return _strategy_spec_from_yaml(spec_path)


def cmd_export_lean(args):
    """Export a vetted QuantForge spec to a Lean (QuantConnect) project."""
    import json as _json
    from pathlib import Path as _Path

    import pandas as _pd

    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.exports.lean import LeanExportConfig, LeanExporter

    spec = _strategy_spec_for_export(args.spec_path)
    target_dir = _Path(args.target_dir).resolve()
    if not target_dir.parent.exists():
        return _runtime_error(
            f"target-dir parent does not exist: {target_dir.parent}"
        )
    target_dir.mkdir(parents=True, exist_ok=True)

    start = _pd.Timestamp(args.start_date) if args.start_date else _pd.Timestamp("2015-01-01")
    end = _pd.Timestamp(args.end_date) if args.end_date else None
    cfg = LeanExportConfig(
        target_directory=target_dir,
        project_name=args.project_name,
        cash=float(args.cash),
        benchmark=args.benchmark,
        resolution=args.resolution,
        universe_resolution=args.resolution,
        start_date=start,
        end_date=end,
    )
    policy = ProtocolPolicy.load()
    exporter = LeanExporter(cfg, policy)
    marker = None
    if args.validation_marker:
        try:
            marker = _json.loads(args.validation_marker)
        except Exception as e:
            return _runtime_error(f"--validation-marker must be JSON: {e}")
    try:
        artifact = exporter.export(spec, validation_marker=marker, force=args.force)
    except FileExistsError as e:
        return _runtime_error(str(e))
    print(_json.dumps({
        "project_name": artifact.project_name,
        "policy_hash": artifact.policy_hash,
        "files": [str(f) for f in artifact.files_written],
    }, indent=2))
    return 0


def cmd_export_lean_list(args):
    """Print the per-strategy translation tier (full/partial/scaffold-only)."""
    from aurora.exports.lean.exporter import list_translation_tiers

    rows = list_translation_tiers()
    width = max((len(n) for n, _ in rows), default=10)
    for name, tier in rows:
        print(f"{name.ljust(width)}  {tier}")
    return 0


def cmd_export_verify(args):
    """Verify provenance of a Lean export against the active policy."""
    import json as _json
    from pathlib import Path as _Path

    from aurora.exports.lean.exporter import verify_project

    result = verify_project(_Path(args.project_dir))
    if getattr(args, "json", False):
        # Avoid serializing nested Path objects in metadata if present.
        print(_json.dumps({
            "ok": result["ok"],
            "errors": result["errors"],
            "metadata": result["metadata"],
        }, indent=2, default=str))
    else:
        if result["ok"]:
            print("OK")
        else:
            print("FAIL")
            for e in result["errors"]:
                print(f"  - {e}")
    return 0 if result["ok"] else 1


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the ``export`` subcommand group on the top-level subparsers."""
    p_export = subparsers.add_parser(
        "export",
        help="Cross-validation adapters (Lean / QuantConnect)",
        description=(
            "Export a vetted QuantForge spec to a Lean (QuantConnect) C# "
            "project skeleton + provenance metadata for cross-validation. "
            "Export only -- promotion still goes through the QuantForge "
            "research protocol."
        ),
    )
    export_sub = p_export.add_subparsers(dest="export_cmd", required=True)

    p_ex_lean = export_sub.add_parser(
        "lean",
        help="Export a single StrategySpec (YAML/JSON) to a Lean project",
    )
    p_ex_lean.add_argument("spec_path",
                            help="Path to a single-spec YAML/JSON file")
    p_ex_lean.add_argument("--target-dir", required=True, dest="target_dir",
                            help="Parent dir; project goes under <target_dir>/<project_name>/")
    p_ex_lean.add_argument("--project-name", required=True, dest="project_name",
                            help="Lean project / C# class name (sanitized)")
    p_ex_lean.add_argument("--cash", default="100000",
                            help="Initial cash for SetCash() [default: 100000]")
    p_ex_lean.add_argument("--benchmark", default="SPY",
                            help="Lean benchmark symbol [default: SPY]")
    p_ex_lean.add_argument(
        "--resolution", default="Daily",
        choices=["Daily", "Hour", "Minute", "Tick"],
        help="Lean Resolution enum value [default: Daily]",
    )
    p_ex_lean.add_argument("--start-date", default=None, dest="start_date",
                            help="Backtest start date (YYYY-MM-DD)")
    p_ex_lean.add_argument("--end-date", default=None, dest="end_date",
                            help="Backtest end date (YYYY-MM-DD); omit for open")
    p_ex_lean.add_argument(
        "--validation-marker", default=None, dest="validation_marker",
        help="JSON blob recorded as 'validation_marker' in qf_metadata.json",
    )
    p_ex_lean.add_argument("--force", action="store_true",
                            help="Overwrite existing project directory")
    p_ex_lean.set_defaults(func=cmd_export_lean)

    p_ex_list = export_sub.add_parser(
        "lean-list",
        help="List strategies with translation tier (full/partial/scaffold-only)",
    )
    p_ex_list.set_defaults(func=cmd_export_lean_list)

    p_ex_verify = export_sub.add_parser(
        "verify",
        help="Verify qf_metadata.json provenance for an exported Lean project",
    )
    p_ex_verify.add_argument("project_dir",
                              help="Path to a Lean project produced by 'forge export lean'")
    p_ex_verify.add_argument("--json", action="store_true",
                              help="Print verification result as JSON")
    p_ex_verify.set_defaults(func=cmd_export_verify)
