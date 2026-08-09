from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract,
    load_and_validate_source_plan,
)
from aurora.infra.sp500_megarun.materializer import materialize_primary_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize free SP500 mega-run sources.")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    contract = load_and_validate_contract(args.contract)
    sources = load_and_validate_source_plan(args.sources, contract)
    report = materialize_primary_sources(
        contract,
        sources,
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
    )
    return 0 if report["primary_sources_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
