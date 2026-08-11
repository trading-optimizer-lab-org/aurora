from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_megarun.complete_snapshot import build_complete_snapshot
from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract,
    load_and_validate_source_plan,
)
from aurora.infra.sp500_megarun.materializer import materialize_primary_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Build all data for F001-F120.")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--spy-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    contract = load_and_validate_contract(args.contract)
    source_plan = load_and_validate_source_plan(args.sources, contract)
    primary = materialize_primary_sources(
        contract,
        source_plan,
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
    )
    if not primary["primary_sources_ready"]:
        return 1
    report = build_complete_snapshot(
        contract,
        normalized_dir=args.output_dir / "normalized",
        spy_csv=args.spy_csv,
        output_dir=args.output_dir,
    )
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
