"""GitHub-only runner for the OpenAP 149 feasibility and identity gate."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
import yaml

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.openap_149.feasibility import (
    build_feasibility_register,
    summarize_feasibility,
)
from aurora.research.openap_149.identity_gate import (
    BRIDGE_COLUMNS,
    evaluate_bridge_coverage,
    freeze_bridge,
)
from aurora.research.openap_149.identity_sources import (
    evaluate_public_identity_routes,
    load_identity_source_catalog,
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


def _markdown(summary: dict[str, object], decision: dict[str, object]) -> str:
    classes = summary["feasibility_classes"]
    return "\n".join(
        [
            "# OpenAP 149 feasibility and identity gate",
            "",
            f"- Target signals: {summary['target_count']}",
            f"- Strictly approved: {summary['strictly_approved']}",
            f"- Previously calculated, non-strict: {summary['previously_calculated_non_strict']}",
            f"- Unproved: {classes.get('unproved', 0)}",
            f"- Blocked source: {classes.get('blocked_source', 0)}",
            f"- Not evaluable reference: {classes.get('not_evaluable_reference', 0)}",
            f"- Identity gate: {decision['status']}",
            f"- Pilot authorized: {str(decision['pilot_authorized']).lower()}",
            f"- Reason: {decision['reason']}",
            "",
            "Calculated values are not strict approvals.",
            "",
        ]
    )


def run(args: argparse.Namespace) -> int:
    """Write a complete go/no-go artifact bundle without opening OOS data."""

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    acquisition_path = Path(args.acquisition_matrix)
    reaudit_path = Path(args.reaudit)
    feasibility_path = Path(args.feasibility_contract)
    sources_path = Path(args.identity_sources)

    acquisition = pd.read_csv(acquisition_path)
    reaudit = pd.read_csv(reaudit_path)
    contract = yaml.safe_load(feasibility_path.read_text(encoding="utf-8"))
    register = build_feasibility_register(acquisition, reaudit, contract)
    summary = summarize_feasibility(register)
    source_audit = evaluate_public_identity_routes(
        load_identity_source_catalog(sources_path)
    )

    register.to_csv(output / "openap_149_feasibility_register.csv", index=False)
    source_audit.to_csv(output / "openap_149_identity_source_audit.csv", index=False)

    bridge_path = output / "openap_permno_bridge.parquet"
    audit_path = output / "openap_permno_bridge_audit.csv"
    if args.candidate_bridge is None:
        bridge_manifest = _empty_bridge(bridge_path)
        pd.DataFrame(
            columns=["yyyymm", "coverage", "covered_pairs", "reference_pairs"]
        ).to_csv(audit_path, index=False)
        decision: dict[str, object] = {
            "status": "blocked_identity",
            "reason": "no_authorized_zero_cost_historical_permno_bridge",
            "pilot_authorized": False,
            "strictly_approved": 0,
        }
    else:
        bridge_manifest_object = freeze_bridge(
            _read_frame(Path(args.candidate_bridge)), bridge_path
        )
        bridge_manifest = asdict(bridge_manifest_object)
        if args.reference_spine is None:
            pd.DataFrame(
                columns=["yyyymm", "coverage", "covered_pairs", "reference_pairs"]
            ).to_csv(audit_path, index=False)
            decision = {
                "status": "blocked_identity",
                "reason": "reference_identifier_spine_missing_after_bridge_freeze",
                "pilot_authorized": False,
                "strictly_approved": 0,
            }
        else:
            frozen = pd.read_parquet(bridge_path)
            coverage = evaluate_bridge_coverage(
                frozen,
                _read_frame(Path(args.reference_spine)),
                manifest=bridge_manifest_object,
            )
            pd.DataFrame(
                coverage.monthly_coverage,
                columns=["yyyymm", "coverage", "covered_pairs", "reference_pairs"],
            ).to_csv(audit_path, index=False)
            decision = {
                **asdict(coverage),
                "reason": (
                    "identity_gate_passed"
                    if coverage.status == "pass"
                    else "minimum_monthly_identity_coverage_below_0_70"
                ),
                "pilot_authorized": coverage.status == "pass",
                "strictly_approved": 0,
            }

    decision.update(
        {
            "repository_sha": str(args.repository_sha),
            "locked_opened": False,
            "validation_used_for_identity": False,
            "source_routes_passing": int(source_audit["route_pass"].sum()),
            "input_sha256": {
                "acquisition_matrix": _sha256(acquisition_path),
                "reaudit": _sha256(reaudit_path),
                "feasibility_contract": _sha256(feasibility_path),
                "identity_sources": _sha256(sources_path),
            },
        }
    )
    summary["identity_gate_status"] = decision["status"]
    summary["pilot_authorized"] = decision["pilot_authorized"]

    _write_json(output / "openap_149_feasibility_summary.json", summary)
    _write_json(output / "openap_permno_bridge_manifest.json", bridge_manifest)
    _write_json(output / "openap_identity_gate_decision.json", decision)
    (output / "openap_149_feasibility_summary.md").write_text(
        _markdown(summary, decision), encoding="utf-8"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--acquisition-matrix",
        type=Path,
        default=Path("docs/OPENAP_149_ACQUISITION_MATRIX.csv"),
    )
    parser.add_argument(
        "--reaudit",
        type=Path,
        default=Path("docs/OPENAP_181_CURRENT_FREE_SOURCE_REAUDIT_2026-08-09.csv"),
    )
    parser.add_argument(
        "--feasibility-contract",
        type=Path,
        default=Path("config/openap_149_feasibility.yaml"),
    )
    parser.add_argument(
        "--identity-sources",
        type=Path,
        default=Path("config/openap_149_identity_sources.yaml"),
    )
    parser.add_argument("--candidate-bridge", type=Path)
    parser.add_argument("--reference-spine", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository-sha", default="")
    return parser


if __name__ == "__main__":
    require_github_actions_or_explicit_local_permission("OpenAP 149 identity gate")
    sys.exit(run(build_parser().parse_args()))
