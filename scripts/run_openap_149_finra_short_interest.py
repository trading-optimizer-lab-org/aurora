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
    calculate_finra_io_short_interest_current,
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
    parser.add_argument("--institutional-root", type=Path, required=True)
    parser.add_argument("--formula-root", type=Path, required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--institutional-source-run-id", required=True)
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
    short_interest = calculate_finra_short_interest_current(
        finra_rows,
        companyfacts,
        status,
        publication_schedule,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
        finra_source_url=str(source_metadata["source_url"]),
    )
    if short_interest.empty or set(short_interest["signal"]) != {"ShortInterest"}:
        raise RuntimeError("FINRA batch did not produce current ShortInterest values")

    institutional_paths = {
        "filings": sorted(args.institutional_root.rglob("sec_13f_filings.parquet")),
        "holdings": sorted(args.institutional_root.rglob("sec_13f_holdings.parquet")),
        "mapping": sorted(args.institutional_root.rglob("openfigi_cusip_map.parquet")),
        "recovery": sorted(
            args.institutional_root.rglob("openap_93_artifact_recovery_manifest.json")
        ),
    }
    if any(len(paths) != 1 for paths in institutional_paths.values()):
        raise RuntimeError(
            "Expected one selectively recovered institutional input of each type: "
            f"{ {name: len(paths) for name, paths in institutional_paths.items()} }"
        )
    recovery = json.loads(
        institutional_paths["recovery"][0].read_text(encoding="utf-8")
    )
    if (
        recovery.get("recovery_profile") != "institutional_inputs"
        or str(recovery.get("source_run_id")) != str(args.institutional_source_run_id)
        or recovery.get("full_artifact_downloaded") is not False
        or recovery.get("locked_opened") is not False
        or recovery.get("validation_used_for_selection") is not False
    ):
        raise RuntimeError("Institutional selective-recovery contract is invalid")
    recovered_hashes = recovery.get("recovered_hashes", {})
    if not isinstance(recovered_hashes, dict):
        raise RuntimeError("Institutional recovery hashes are missing")
    for kind in ("filings", "holdings", "mapping"):
        path = institutional_paths[kind][0]
        expected_hashes = [
            str(value)
            for name, value in recovered_hashes.items()
            if Path(str(name)).name == path.name
        ]
        if len(expected_hashes) != 1 or _sha256(path) != expected_hashes[0]:
            raise RuntimeError(f"Recovered institutional input hash mismatch: {path.name}")

    filings = pd.read_parquet(institutional_paths["filings"][0])
    holdings = pd.read_parquet(institutional_paths["holdings"][0])
    mapping = pd.read_parquet(institutional_paths["mapping"][0])
    expected_rows = {
        "filings": int(recovery.get("sec_13f_filing_rows", 0)),
        "holdings": int(recovery.get("sec_13f_holding_rows", 0)),
        "mapping": int(recovery.get("openfigi_mapping_rows", 0)),
    }
    actual_rows = {
        "filings": len(filings),
        "holdings": len(holdings),
        "mapping": len(mapping),
    }
    if min(expected_rows.values()) <= 0 or actual_rows != expected_rows:
        raise RuntimeError(
            f"Recovered institutional row counts mismatch: expected={expected_rows}:"
            f"actual={actual_rows}"
        )
    io_short_interest = calculate_finra_io_short_interest_current(
        short_interest,
        companyfacts,
        status,
        filings,
        holdings,
        mapping,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
    )
    if io_short_interest.empty or set(io_short_interest["signal"]) != {
        "IO_ShortInterest"
    }:
        raise RuntimeError("FINRA/SEC 13F batch did not produce IO_ShortInterest values")
    current = pd.concat([short_interest, io_short_interest], ignore_index=True)

    formula_matches = sorted(args.formula_root.rglob("openap_181_formula_inventory.csv"))
    if len(formula_matches) != 1:
        raise RuntimeError("Expected one pinned formula inventory")
    formulas = pd.read_csv(formula_matches[0], keep_default_na=False)
    hash_column = "formula_sha256" if "formula_sha256" in formulas else "sha256"
    expected = formulas.set_index("signal")[hash_column].astype(str).to_dict()
    formula_hashes = {
        signal: expected.get(signal, "")
        for signal in ("ShortInterest", "IO_ShortInterest")
    }
    if not pd.Series(list(formula_hashes.values())).str.fullmatch(r"[0-9a-f]{64}").all():
        raise RuntimeError("Pinned short-interest formula hashes are missing")
    current["formula_sha256"] = current["signal"].map(formula_hashes)

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
        "institutional_source_run_id": str(args.institutional_source_run_id),
        "formation_at": pd.Timestamp(args.formation_at).isoformat(),
        "retrieved_at": retrieved_at,
        "sec_source_file_counts": counts,
        "companyfacts_rows": int(len(companyfacts)),
        "status_rows": int(len(status)),
        "finra_rows": int(len(finra_rows)),
        "current_value_rows": int(len(current)),
        "current_value_securities": int(current["security_id"].nunique()),
        "current_value_signal_counts": {
            str(signal): int(count)
            for signal, count in current.groupby("signal").size().items()
        },
        "institutional_input_rows": actual_rows,
        "institutional_recovery": recovery,
        "identity_bridge": {
            "13f_security_key": "cusip",
            "openfigi_security_key": "unique_common_stock_shareClassFIGI",
            "openfigi_exchange_constraint": "exchCode_US",
            "sec_issuer_key": "cik_plus_current_ticker_plus_normalized_entity_name",
            "join_contract": (
                "cusip_to_unique_share_class_figi_then_ticker_and_13f_issuer_name_"
                "must_match_unambiguous_sec_cik_identity"
            ),
            "ticker_only_join_allowed": False,
            "ambiguous_identity_behavior": "omit_value_fail_closed",
        },
        "settlement_dates": sorted(selected_settlements.unique().tolist()),
        "formula_inventory_sha256": _sha256(formula_matches[0]),
        "formula_sha256": formula_hashes,
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
