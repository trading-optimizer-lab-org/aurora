"""Prepare one resumable entry-index checkpoint for the 290 event study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from scripts.merge_stock_protocol_290_event_study import (
    CUTOFF,
    OPPORTUNITIES_PARQUET,
    PREPARED_COVERAGE_PARQUET,
    PREPARED_FINANCING_PARQUET,
    PREPARED_FX_AUDIT_PARQUET,
    PREPARED_PART_AUDIT_NAME,
    PREPARED_SHARD_RECONCILIATION_PARQUET,
    PREPARED_STATISTICAL_PARQUET,
    _contract,
    _load_provenance_inputs,
    _sha256,
    stream_corrected_shards,
)


def prepare_part(
    *,
    entry_index: int,
    contract_root: Path,
    corrected_shards_root: Path,
    prior_audit_root: Path,
    exact_strategy_root: Path,
    source_lock_path: Path,
    fx_rates_path: Path,
    output_root: Path,
) -> dict[str, object]:
    require_github_actions_or_explicit_local_permission(
        "stock protocol 290 checkpoint preparation"
    )
    if entry_index not in range(10):
        raise ValueError("entry_index must be in 0..9")
    output_root.mkdir(parents=True, exist_ok=True)
    if any(output_root.iterdir()):
        raise ValueError("output root must be empty")
    exact_strategy, prior_opportunities, _ = _load_provenance_inputs(
        prior_audit_root=prior_audit_root,
        exact_strategy_root=exact_strategy_root,
        source_lock_path=source_lock_path,
    )
    manifest, _, _ = _contract(contract_root)
    rates = pd.read_csv(fx_rates_path)
    (
        opportunities,
        coverage,
        shard_reconciliation,
        corrected_audits,
        fx_audit,
        financing_reconciliation,
        technical_input_rows,
        technical_duplicates_removed,
    ) = stream_corrected_shards(
        corrected_shards_root,
        manifest,
        fx_rates=rates,
        exact_strategy=exact_strategy,
        prior_opportunities=prior_opportunities,
        output_root=output_root,
        entry_indices={entry_index},
    )
    opportunities.to_parquet(output_root / PREPARED_STATISTICAL_PARQUET, index=False)
    coverage.to_parquet(output_root / PREPARED_COVERAGE_PARQUET, index=False)
    shard_reconciliation.to_parquet(
        output_root / PREPARED_SHARD_RECONCILIATION_PARQUET, index=False
    )
    fx_audit.to_parquet(output_root / PREPARED_FX_AUDIT_PARQUET, index=False)
    if not financing_reconciliation.empty:
        financing_reconciliation.to_parquet(
            output_root / PREPARED_FINANCING_PARQUET, index=False
        )
    file_names = [
        OPPORTUNITIES_PARQUET,
        PREPARED_STATISTICAL_PARQUET,
        PREPARED_COVERAGE_PARQUET,
        PREPARED_SHARD_RECONCILIATION_PARQUET,
        PREPARED_FX_AUDIT_PARQUET,
    ]
    if not financing_reconciliation.empty:
        file_names.append(PREPARED_FINANCING_PARQUET)
    files = {
        name: {
            "bytes": (output_root / name).stat().st_size,
            "sha256": _sha256(output_root / name),
        }
        for name in file_names
    }
    entry_ids = sorted(opportunities["entry_spec_id"].astype(str).unique())
    payload: dict[str, object] = {
        "schema_version": 1,
        "entry_index": entry_index,
        "entry_spec_ids": entry_ids,
        "combination_count": int(opportunities["combination_id"].nunique()),
        "opportunity_rows": len(opportunities),
        "technical_input_rows": technical_input_rows,
        "technical_duplicates_removed": technical_duplicates_removed,
        "corrected_audits": corrected_audits,
        "cutoff": CUTOFF.date().isoformat(),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "capital_rejection_applied": False,
        "portfolio_or_sizing_applied": False,
        "files": files,
    }
    (output_root / PREPARED_PART_AUDIT_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry-index", type=int, required=True)
    parser.add_argument("--contract-root", type=Path, required=True)
    parser.add_argument("--corrected-shards-root", type=Path, required=True)
    parser.add_argument("--prior-audit-root", type=Path, required=True)
    parser.add_argument("--exact-strategy-root", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--fx-rates", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    prepare_part(
        entry_index=args.entry_index,
        contract_root=args.contract_root,
        corrected_shards_root=args.corrected_shards_root,
        prior_audit_root=args.prior_audit_root,
        exact_strategy_root=args.exact_strategy_root,
        source_lock_path=args.source_lock,
        fx_rates_path=args.fx_rates,
        output_root=args.output_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
