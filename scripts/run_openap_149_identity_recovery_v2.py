"""GitHub-only runner for OpenAP 149 identity source recovery v2."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.openap_149.identity_gate import (
    BRIDGE_COLUMNS,
    BridgeManifest,
    evaluate_bridge_coverage,
    freeze_bridge,
)
from aurora.research.openap_149.identity_recovery_v2 import (
    ProbeReceipt,
    audit_sources,
    build_candidate_bridge,
    load_recovery_catalog,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_receipts(path: Path, receipts: list[ProbeReceipt]) -> None:
    lines = [json.dumps(asdict(receipt), sort_keys=True) for receipt in receipts]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _empty_bridge(path: Path) -> dict[str, object]:
    pd.DataFrame(columns=BRIDGE_COLUMNS).to_parquet(
        path, engine="pyarrow", index=False, compression="zstd"
    )
    return {
        "rows": 0,
        "min_valid_from": "",
        "max_valid_to": "",
        "bridge_sha256": _sha256(path),
        "frozen_before_reference_read": False,
    }


def _coverage_frame(rows: tuple[tuple[str, float, int, int], ...] = ()) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["yyyymm", "coverage", "covered_pairs", "reference_pairs"],
    )


def _summary(decision: dict[str, object]) -> str:
    classes = decision["route_class_counts"]
    assert isinstance(classes, dict)
    lines = [
        "# OpenAP 149 identity recovery v2",
        "",
        f"- Audited source routes: {sum(int(value) for value in classes.values())}",
        f"- Candidate routes: {decision['candidate_routes']}",
        f"- Frozen bridge rows: {decision['bridge_rows']}",
        f"- Gate status: {decision['status']}",
        f"- Pilot authorized: {str(decision['pilot_authorized']).lower()}",
        f"- Strictly approved signals: {decision['strictly_approved']}",
        f"- Reason: {decision['reason']}",
        "",
        "A reachable source is not a strict identity source unless access, rights,",
        "schema, historical intervals, share class and 2023-2024 coverage all pass.",
        "",
    ]
    return "\n".join(lines)


def _artifact_entry(path: Path, output: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(output).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def run(
    args: argparse.Namespace,
    *,
    getter: Callable[..., Any] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> int:
    """Probe all routes and emit a complete, reconciled fail-closed bundle."""

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence_dir = output / "source_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    catalogue_path = Path(args.catalogue)

    sources = load_recovery_catalog(catalogue_path)
    audit, receipts, payloads = audit_sources(sources, getter=getter, now=now)
    for source_id, payload in sorted(payloads.items()):
        (evidence_dir / f"{source_id}.bin").write_bytes(payload)

    audit_path = output / "openap_149_identity_sources_v2_audit.csv"
    receipts_path = output / "openap_149_identity_source_probe_receipts.jsonl"
    bridge_path = output / "openap_permno_bridge_v2.parquet"
    bridge_manifest_path = output / "openap_permno_bridge_v2_manifest.json"
    coverage_path = output / "openap_permno_bridge_v2_monthly_coverage.csv"
    decision_path = output / "openap_149_identity_recovery_v2_decision.json"
    summary_path = output / "openap_149_identity_recovery_v2_summary.md"
    evidence_manifest_path = (
        output / "openap_149_identity_source_evidence_manifest.json"
    )

    audit.to_csv(audit_path, index=False)
    _write_receipts(receipts_path, receipts)
    bridge = build_candidate_bridge(audit, payloads)
    candidate_routes = int(audit["terminal_class"].eq("pass_candidate").sum())

    coverage_frame = _coverage_frame()
    minimum_coverage: float | None = None
    median_coverage: float | None = None
    maximum_coverage: float | None = None
    retained_pairs = 0
    reference_pairs = 0
    ambiguous_links = 0

    if bridge.empty:
        bridge_manifest = _empty_bridge(bridge_path)
        status = "blocked_identity_v2"
        reason = "no_authorized_zero_cost_historical_permno_bridge"
        pilot_authorized = False
    else:
        frozen_manifest = freeze_bridge(bridge, bridge_path)
        bridge_manifest = asdict(frozen_manifest)
        if args.reference_spine is None:
            status = "candidate_bridge_requires_reference_spine"
            reason = "reference_identifier_spine_missing_after_bridge_freeze"
            pilot_authorized = False
        else:
            frozen_bridge = pd.read_parquet(bridge_path)
            coverage = evaluate_bridge_coverage(
                frozen_bridge,
                _read_frame(Path(args.reference_spine)),
                manifest=BridgeManifest(**bridge_manifest),
            )
            coverage_frame = _coverage_frame(coverage.monthly_coverage)
            minimum_coverage = coverage.minimum_monthly_coverage
            median_coverage = coverage.median_monthly_coverage
            maximum_coverage = coverage.maximum_monthly_coverage
            retained_pairs = coverage.retained_pairs
            reference_pairs = coverage.reference_pairs
            ambiguous_links = coverage.ambiguous_links
            status = (
                "identity_pass"
                if coverage.status == "pass"
                else "blocked_identity_v2"
            )
            reason = (
                "identity_gate_passed"
                if coverage.status == "pass"
                else "minimum_monthly_identity_coverage_below_0_70"
            )
            pilot_authorized = coverage.status == "pass"

    coverage_frame.to_csv(coverage_path, index=False)
    _write_json(bridge_manifest_path, bridge_manifest)
    route_class_counts = {
        str(key): int(value)
        for key, value in audit["terminal_class"].value_counts().sort_index().items()
    }
    decision: dict[str, object] = {
        "status": status,
        "reason": reason,
        "pilot_authorized": pilot_authorized,
        "strictly_approved": 0,
        "candidate_routes": candidate_routes,
        "bridge_rows": int(len(bridge)),
        "minimum_monthly_coverage": minimum_coverage,
        "median_monthly_coverage": median_coverage,
        "maximum_monthly_coverage": maximum_coverage,
        "retained_pairs": retained_pairs,
        "reference_pairs": reference_pairs,
        "ambiguous_links": ambiguous_links,
        "required_months": 24,
        "route_class_counts": route_class_counts,
        "repository_sha": str(args.repository_sha),
        "locked_opened": False,
        "target_derived_used_for_identity": False,
        "validation_used_for_identity": False,
        "catalogue_sha256": _sha256(catalogue_path),
    }
    _write_json(decision_path, decision)
    summary_path.write_text(_summary(decision), encoding="utf-8")

    evidence_files = sorted(evidence_dir.glob("*.bin"))
    bundle_files = [
        audit_path,
        receipts_path,
        bridge_path,
        bridge_manifest_path,
        coverage_path,
        decision_path,
        summary_path,
        *evidence_files,
    ]
    evidence_manifest: dict[str, object] = {
        "catalogue_source_count": len(sources),
        "probe_receipt_count": len(receipts),
        "evidence_snapshot_count": len(evidence_files),
        "repository_sha": str(args.repository_sha),
        "target_derived_used_for_identity": False,
        "artifacts": [_artifact_entry(path, output) for path in bundle_files],
    }
    _write_json(evidence_manifest_path, evidence_manifest)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=Path("config/openap_149_identity_sources_v2.yaml"),
    )
    parser.add_argument("--reference-spine", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository-sha", default="")
    return parser


if __name__ == "__main__":
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 identity source recovery v2"
    )
    sys.exit(run(build_parser().parse_args()))
