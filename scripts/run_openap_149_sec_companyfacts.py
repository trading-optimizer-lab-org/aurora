from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_current_score import ACCOUNTING_FEATURE_DEPENDENCIES
from aurora.research.openap_181.acquisition_149 import load_target_routes
from aurora.research.openap_181.sec_companyfacts_149 import (
    calculate_companyfacts_accounting_current,
    calculate_companyfacts_149_current,
    calculate_companyfacts_rdability_current,
    calculate_companyfacts_realestate_current,
    calculate_companyfacts_tax_current,
    calculate_sec_submission_current,
)
from aurora.research.openap_93.registry import REQUIRED_93


def _read_many(paths: list[Path], reader: object) -> pd.DataFrame:
    if not paths:
        raise RuntimeError("No source files matched the required SEC surface")
    return pd.concat([reader(path) for path in paths], ignore_index=True)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _latest_retrieved_at(paths: list[Path]) -> str:
    values = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        values.append(pd.Timestamp(payload["retrieved_at"]))
    if not values:
        raise RuntimeError("SEC shard summaries are missing")
    return max(values).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-root", type=Path, required=True)
    parser.add_argument("--formula-root", type=Path, required=True)
    parser.add_argument("--route-matrix", type=Path, required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 SEC CompanyFacts current batch"
    )

    facts_paths = sorted(args.sec_root.rglob("sec_companyfacts_*.parquet"))
    submission_paths = sorted(args.sec_root.rglob("sec_submissions_*.parquet"))
    status_paths = sorted(args.sec_root.rglob("sec_status_*.csv"))
    summary_paths = sorted(args.sec_root.rglob("sec_summary_*.json"))
    counts = {
        "companyfacts": len(facts_paths),
        "submissions": len(submission_paths),
        "status": len(status_paths),
        "summary": len(summary_paths),
    }
    if set(counts.values()) != {48}:
        raise RuntimeError(f"Expected 48 complete SEC shards, found {counts}")

    companyfacts = _read_many(facts_paths, pd.read_parquet)
    submissions = _read_many(submission_paths, pd.read_parquet)
    status = _read_many(status_paths, pd.read_csv)
    retrieved_at = _latest_retrieved_at(summary_paths)
    core_values = calculate_companyfacts_149_current(
        companyfacts,
        submissions,
        status,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
    )
    routes = load_target_routes(args.route_matrix)
    accounting_targets = set(
        routes.loc[routes["category"].eq("Accounting"), "signal"].astype(str)
    )
    expanded_targets = accounting_targets.difference(
        {"Cash", "GP", "Investment"}, REQUIRED_93
    )
    supported_targets = expanded_targets.intersection(ACCOUNTING_FEATURE_DEPENDENCIES)
    expanded_values = calculate_companyfacts_accounting_current(
        companyfacts,
        status,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
        target_signals=supported_targets,
    )
    submission_values = calculate_sec_submission_current(
        submissions,
        status,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
    )
    rdability_values = calculate_companyfacts_rdability_current(
        companyfacts,
        status,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
    )
    realestate_values = calculate_companyfacts_realestate_current(
        companyfacts,
        submissions,
        status,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
    )
    tax_values = calculate_companyfacts_tax_current(
        companyfacts,
        status,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
    )
    values = pd.concat(
        [
            core_values,
            expanded_values,
            submission_values,
            rdability_values,
            realestate_values,
            tax_values,
        ],
        ignore_index=True,
    )
    if values.duplicated(["security_id", "signal", "formation_at"]).any():
        raise RuntimeError("Conflicting duplicate SEC accounting values")
    current = values.loc[values["current_usable"] & values["value"].notna()].copy()
    required_signals = {"Cash", "FirmAge", "GP", "Investment", "RDAbility"}
    if not required_signals.issubset(set(current["signal"])):
        raise RuntimeError("The SEC batch did not produce all required signals")

    formula_matches = sorted(args.formula_root.rglob("openap_181_formula_inventory.csv"))
    if len(formula_matches) != 1:
        raise RuntimeError("Expected one pinned formula inventory")
    formulas = pd.read_csv(formula_matches[0], keep_default_na=False)
    hash_column = "formula_sha256" if "formula_sha256" in formulas else "sha256"
    expected = formulas.set_index("signal")[hash_column].astype(str).to_dict()
    values["formula_sha256"] = values["signal"].map(expected).fillna("")
    current["formula_sha256"] = current["signal"].map(expected).fillna("")
    observed = current[["signal", "formula_sha256"]].drop_duplicates()
    if not observed.apply(
        lambda row: expected.get(str(row["signal"])) == row["formula_sha256"], axis=1
    ).all():
        raise RuntimeError("Pinned formula hash mismatch in SEC CompanyFacts batch")

    output = args.output_dir if args.output_dir.is_absolute() else base_data_dir() / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    values.to_csv(output / "openap_149_sec_companyfacts_observations.csv", index=False)
    current.to_csv(output / "openap_149_sec_companyfacts_current.csv", index=False)
    current.to_parquet(
        output / "openap_149_sec_companyfacts_current.parquet",
        index=False,
        compression="zstd",
    )
    manifest = {
        "source_run_id": str(args.source_run_id),
        "formation_at": pd.Timestamp(args.formation_at, tz="UTC").isoformat(),
        "retrieved_at": retrieved_at,
        "source_layout": "48_verified_sec_official_api_shards",
        "source_file_counts": counts,
        "companyfacts_rows": int(len(companyfacts)),
        "submission_rows": int(len(submissions)),
        "status_rows": int(len(status)),
        "observation_rows": int(len(values)),
        "current_value_rows": int(len(current)),
        "signals_calculated": sorted(current["signal"].unique().tolist()),
        "signal_count": int(current["signal"].nunique()),
        "formula_inventory_sha256": _sha256(formula_matches[0]),
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
        "strict_score_eligible": False,
        "cost_eur": 0,
    }
    (output / "openap_149_sec_companyfacts_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
