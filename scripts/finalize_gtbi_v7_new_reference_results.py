"""Validate and seal the final independent GTBI V7 historical artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from infra.gtbi_v7_new_reference.campaign import (
    CAMPAIGN_ID,
    HISTORICAL_EXCLUSION_START,
    PRODUCT_ID,
    VALIDATION_END,
    validate_benchmark_evidence,
    validate_smoke_evidence,
    verify_v7_campaign_plan,
)
from infra.gtbi_v7_readiness.canonical import canonical_bytes
from scripts.validate_gtbi_fast_strict_artifact import validate_artifact


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return dict(value)


def _assert_no_locked_result_rows(root: Path) -> None:
    boundary = pd.Timestamp(HISTORICAL_EXCLUSION_START, tz="UTC")
    for path in sorted(Path(root).glob("*.csv")):
        try:
            columns = list(pd.read_csv(path, nrows=0).columns)
        except pd.errors.EmptyDataError:
            continue
        date_columns = [column for column in columns if str(column).lower() in {"date", "entry_date", "exit_date"}]
        if not date_columns:
            continue
        frame = pd.read_csv(path, usecols=date_columns)
        for column in date_columns:
            dates = pd.to_datetime(frame[column], errors="coerce", utc=True)
            if bool((dates >= boundary).fillna(False).any()):
                raise ValueError(f"final artifact exposes locked result rows in {path.name}:{column}")
    yearly_path = Path(root) / "yearly_trade_performance.csv"
    if yearly_path.is_file():
        yearly = pd.read_csv(yearly_path)
        if "year" in yearly.columns and not yearly.empty:
            years = pd.to_numeric(yearly["year"], errors="raise")
            if int(years.max()) > int(VALIDATION_END[:4]):
                raise ValueError("yearly results expose a year after validation_end")


def finalize(
    *,
    artifact_root: Path,
    plan_root: Path,
    data_manifest_path: Path,
    authorization_path: Path,
    benchmark_path: Path,
    smoke_validation_path: Path,
    expected_strategy_count: int = 72_000,
) -> dict[str, Any]:
    root = Path(artifact_root)
    verification = validate_artifact(root, expected_strategy_count=expected_strategy_count)
    campaign = verify_v7_campaign_plan(
        plan_root=Path(plan_root),
        data_manifest_path=Path(data_manifest_path),
        authorization_path=Path(authorization_path),
    )
    campaign_manifest_path = Path(plan_root) / "campaign_manifest.json"
    benchmark = validate_benchmark_evidence(
        campaign_manifest_path=campaign_manifest_path,
        benchmark_path=Path(benchmark_path),
    )
    smoke = validate_smoke_evidence(
        campaign_manifest_path=campaign_manifest_path,
        smoke_validation_path=Path(smoke_validation_path),
    )
    _assert_no_locked_result_rows(root)
    summary_path = root / "summary.json"
    summary = _json(summary_path)
    summary.update(
        {
            "campaign_id": CAMPAIGN_ID,
            "product_identity": PRODUCT_ID,
            "separate_from_v6": True,
            "v6_equivalence_claim_allowed": False,
            "survivorship_biased": True,
            "point_in_time_universe": False,
            "retrospectively_adjusted_reference": True,
            "historical_causal_claims_allowed": False,
            "locked_authorized": False,
            "locked_data_accessed": False,
            "historical_exclusion_start": HISTORICAL_EXCLUSION_START,
            "selected_processes_per_runner": int(benchmark["selected_processes_per_runner"]),
            "selected_symbol_workers_per_process": int(
                benchmark["selected_symbol_workers_per_process"]
            ),
            "effective_cpu_count": int(benchmark["effective_cpu_count"]),
            "benchmark_receipt_digest": benchmark["receipt_digest"],
            "smoke_validation_digest": smoke["receipt_digest"],
            "v7_campaign_contract_digest": campaign["v7_campaign_contract"]["contract_digest"],
            "optimized_evaluation_mode": campaign["inputs"]["execution_mode"],
        }
    )
    summary_path.write_bytes(canonical_bytes(summary) + b"\n")
    (root / "final_summary.json").write_bytes(canonical_bytes(summary) + b"\n")
    verification = validate_artifact(root, expected_strategy_count=expected_strategy_count)
    report = {
        "schema_version": "gtbi_v7_new_reference_final_report_v1",
        "campaign_id": CAMPAIGN_ID,
        "product_identity": PRODUCT_ID,
        "campaign_fingerprint": summary["campaign_fingerprint"],
        "campaign_contract_digest": campaign["v7_campaign_contract"]["contract_digest"],
        "valid": True,
        "historical_campaign_complete": True,
        "terminal_strategy_identities": int(verification["terminal_count"]),
        "leaderboard_rows": int(verification["leaderboard_rows"]),
        "early_rejected_rows": int(verification["early_rejected_rows"]),
        "best_candidate_id": verification["best_candidate_id"],
        "selected_processes_per_runner": int(benchmark["selected_processes_per_runner"]),
        "selected_symbol_workers_per_process": int(
            benchmark["selected_symbol_workers_per_process"]
        ),
        "effective_cpu_count": int(benchmark["effective_cpu_count"]),
        "benchmark_receipt_digest": benchmark["receipt_digest"],
        "smoke_validation_digest": smoke["receipt_digest"],
        "locked_authorized": False,
        "locked_data_accessed": False,
        "scientific_cutoff": VALIDATION_END,
        "github_only_run": True,
        "requires_local_machine": False,
        "maximum_incremental_net_spend_usd": 0,
        "limitations": [
            "separate_from_v6",
            "not_v6_equivalent",
            "survivorship_biased",
            "not_point_in_time",
            "retrospectively_adjusted_reference",
            "historical_causal_claims_prohibited",
        ],
    }
    report["receipt_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(report)).hexdigest()
    (root / "v7_final_report.json").write_bytes(canonical_bytes(report) + b"\n")
    inventory = [
        {"path": path.name, "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in sorted(root.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.name != "v7_artifact_inventory.json"
    ]
    artifact_inventory = {
        "schema_version": "gtbi_v7_new_reference_artifact_inventory_v1",
        "campaign_id": CAMPAIGN_ID,
        "files": inventory,
    }
    artifact_inventory["inventory_digest"] = "sha256:" + hashlib.sha256(
        canonical_bytes(artifact_inventory)
    ).hexdigest()
    (root / "v7_artifact_inventory.json").write_bytes(canonical_bytes(artifact_inventory) + b"\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--smoke-validation", type=Path, required=True)
    parser.add_argument("--expected-strategy-count", type=int, default=72_000)
    args = parser.parse_args(argv)
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("GTBI V7 result finalization is GitHub Actions only")
    report = finalize(
        artifact_root=args.artifact_root,
        plan_root=args.plan_root,
        data_manifest_path=args.data_manifest,
        authorization_path=args.authorization,
        benchmark_path=args.benchmark,
        smoke_validation_path=args.smoke_validation,
        expected_strategy_count=args.expected_strategy_count,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
