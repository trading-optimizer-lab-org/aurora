"""GitHub-only OpenAP proxy versus official signal correlation audit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_proxy_real_correlation import (
    DEFAULT_PROXY_COUNT_EXPECTED,
    ProxyCorrelationError,
    audit_proxy_real,
    blocked_report,
    load_proxy_names,
    read_panel,
    read_zip_panel,
    validate_identity_bridge,
    write_audit_manifest,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_signs(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    frame = pd.read_csv(path)
    if not {"signalname", "Sign"}.issubset(frame.columns):
        raise ProxyCorrelationError("Metadata de señales necesita signalname y Sign")
    return dict(zip(frame["signalname"].astype(str), pd.to_numeric(frame["Sign"], errors="coerce").fillna(1.0)))


def run(args: argparse.Namespace) -> int:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": _now(),
        "execution_location": "github_actions",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "official_panel": str(args.official_panel or ""),
        "proxy_panel": str(args.proxy_panel or ""),
        "proxy_snapshot": str(args.proxy_snapshot or ""),
        "identity_bridge": str(args.identity_bridge or ""),
    }
    names = load_proxy_names(args.proxy_signal_list, snapshot=args.proxy_snapshot)
    try:
        if not args.official_panel or not args.proxy_panel:
            raise ProxyCorrelationError(
                "Falta el panel histórico oficial o el panel histórico proxy; el snapshot actual no sirve para correlación histórica."
            )
        if not args.identity_bridge:
            raise ProxyCorrelationError(
                "Falta el puente de identificadores ticker↔PERMNO; no se permite unir por posición, nombre o market cap."
            )
        bridge_meta = validate_identity_bridge(args.identity_bridge)
        proxy = read_panel(args.proxy_panel, namespace="permno", require_permno=True)
        names = load_proxy_names(args.proxy_signal_list, proxy, args.proxy_snapshot)
        official = read_zip_panel(args.official_panel, namespace="permno", signals=names)
        signs = _read_signs(Path(args.sign_metadata) if args.sign_metadata else None)
        summary, monthly = audit_proxy_real(
            official,
            proxy,
            signal_names=names,
            signs=signs,
            min_overlap_rows=args.min_overlap_rows,
            min_overlap_months=args.min_overlap_months,
            correlation_threshold=args.correlation_threshold,
        )
        summary.to_csv(output / "proxy_real_correlation.csv", index=False)
        monthly.to_csv(output / "proxy_real_monthly_correlation.csv", index=False)
        overview = {
            **manifest,
            "status": "complete",
            "requested_proxy_count": len(names),
            "correlations_computed": int(summary["spearman_pooled"].notna().sum()),
            "passed_threshold": int(summary["status"].eq("pass").sum()),
            "failed_threshold": int(summary["status"].eq("fail_threshold").sum()),
            "correlation_threshold": args.correlation_threshold,
            "expected_proxy_count": args.expected_proxy_count,
            "observed_proxy_count": len(names),
            "proxy_count_mismatch": len(names) != args.expected_proxy_count,
            "identity_bridge": bridge_meta,
        }
    except (OSError, ValueError, ProxyCorrelationError) as exc:
        observed = len(names) if names else None
        if args.proxy_panel and Path(args.proxy_panel).exists():
            try:
                panel_names = read_panel(args.proxy_panel, namespace="permno", require_permno=True)["signalname"]
                observed = int(panel_names.nunique())
                if not names:
                    names = sorted(panel_names.astype(str).unique().tolist())
            except Exception:
                pass
        summary_frame, overview = blocked_report(
            names,
            reason=str(exc),
            expected_proxy_count=args.expected_proxy_count,
            observed_proxy_count=observed,
        )
        summary_frame.to_csv(output / "proxy_real_correlation.csv", index=False)
        pd.DataFrame(columns=["signalname", "month", "n_instruments", "pearson", "spearman"]).to_csv(
            output / "proxy_real_monthly_correlation.csv", index=False
        )
        overview.update(manifest)
    write_audit_manifest(output, manifest)
    (output / "proxy_real_summary.json").write_text(json.dumps(overview, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(
        [{"status": overview.get("status"), "failure_reason": overview.get("failure_reason", ""), "locked_opened": False}]
    ).to_csv(output / "proxy_real_failures.csv", index=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-panel", type=Path)
    parser.add_argument("--proxy-panel", type=Path)
    parser.add_argument("--proxy-snapshot", type=Path)
    parser.add_argument("--identity-bridge", type=Path)
    parser.add_argument("--proxy-signal-list", type=Path)
    parser.add_argument("--sign-metadata", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-proxy-count", type=int, default=DEFAULT_PROXY_COUNT_EXPECTED)
    parser.add_argument("--min-overlap-rows", type=int, default=60)
    parser.add_argument("--min-overlap-months", type=int, default=12)
    parser.add_argument("--correlation-threshold", type=float, default=0.95)
    return parser


if __name__ == "__main__":
    require_github_actions_or_explicit_local_permission("OpenAP proxy-real correlation audit")
    sys.exit(run(build_parser().parse_args()))
