from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.short_interest_batch import (
    acquire_finra_short_interest_current,
    calculate_finra_short_interest_current,
)


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-root", type=Path, required=True)
    parser.add_argument("--formula-root", type=Path, required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 FINRA short-interest current batch"
    )

    facts_paths = sorted(args.sec_root.rglob("sec_companyfacts_*.parquet"))
    status_paths = sorted(args.sec_root.rglob("sec_status_*.csv"))
    counts = {"companyfacts": len(facts_paths), "status": len(status_paths)}
    if set(counts.values()) != {48}:
        raise RuntimeError(f"Expected 48 complete SEC shards, found {counts}")
    companyfacts = _read_many(facts_paths, pd.read_parquet)
    status = _read_many(status_paths, pd.read_csv)

    finra_rows, publication_schedule, source_metadata = (
        acquire_finra_short_interest_current(formation_at=args.formation_at)
    )
    retrieved_at = datetime.now(UTC).isoformat()
    current = calculate_finra_short_interest_current(
        finra_rows,
        companyfacts,
        status,
        publication_schedule,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
        finra_source_url=str(source_metadata["source_url"]),
    )
    if current.empty or set(current["signal"]) != {"ShortInterest"}:
        raise RuntimeError("FINRA batch did not produce current ShortInterest values")

    formula_matches = sorted(args.formula_root.rglob("openap_181_formula_inventory.csv"))
    if len(formula_matches) != 1:
        raise RuntimeError("Expected one pinned formula inventory")
    formulas = pd.read_csv(formula_matches[0], keep_default_na=False)
    hash_column = "formula_sha256" if "formula_sha256" in formulas else "sha256"
    expected = formulas.set_index("signal")[hash_column].astype(str).to_dict()
    formula_hash = expected.get("ShortInterest", "")
    if not pd.Series([formula_hash]).str.fullmatch(r"[0-9a-f]{64}").all():
        raise RuntimeError("Pinned ShortInterest formula hash is missing")
    current["formula_sha256"] = formula_hash

    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    current.to_csv(output / "openap_149_finra_short_interest_current.csv", index=False)
    current.to_parquet(
        output / "openap_149_finra_short_interest_current.parquet",
        index=False,
        compression="zstd",
    )
    selected_settlements = pd.to_datetime(
        current["period_end"], errors="coerce", utc=True
    ).dt.date.astype(str)
    manifest = {
        "source_run_id": str(args.source_run_id),
        "formation_at": pd.Timestamp(args.formation_at).isoformat(),
        "retrieved_at": retrieved_at,
        "sec_source_file_counts": counts,
        "companyfacts_rows": int(len(companyfacts)),
        "status_rows": int(len(status)),
        "finra_rows": int(len(finra_rows)),
        "current_value_rows": int(len(current)),
        "current_value_securities": int(current["security_id"].nunique()),
        "settlement_dates": sorted(selected_settlements.unique().tolist()),
        "formula_inventory_sha256": _sha256(formula_matches[0]),
        "formula_sha256": formula_hash,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
        "strict_score_eligible": False,
        "cost_eur": 0,
        **source_metadata,
    }
    (output / "openap_149_finra_short_interest_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
