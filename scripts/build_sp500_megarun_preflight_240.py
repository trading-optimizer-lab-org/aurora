from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract,
    load_and_validate_source_plan,
)
from aurora.infra.sp500_megarun.materializer import materialize_primary_sources
from aurora.infra.sp500_megarun.preflight_240 import build_preflight_240_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the GitHub-only F001-F240 data preflight without backtests."
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--spy-csv", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    contract = load_and_validate_contract(args.contract)
    source_plan = load_and_validate_source_plan(args.sources, contract)
    materialized_dir = args.work_dir / "materialized"
    primary = materialize_primary_sources(
        contract,
        source_plan,
        output_dir=materialized_dir,
        cache_dir=args.work_dir / "raw_cache",
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    primary_report = materialized_dir / "primary_materialization_report.json"
    if primary_report.exists():
        shutil.copy2(primary_report, args.output_dir / primary_report.name)
    if not primary["primary_sources_ready"]:
        return 1
    report = build_preflight_240_snapshot(
        contract,
        normalized_dir=materialized_dir / "normalized",
        spy_csv=args.spy_csv,
        output_dir=args.output_dir,
    )
    return 0 if report["ready"] and report["ready_lane_count"] == 240 else 1


if __name__ == "__main__":
    raise SystemExit(main())
