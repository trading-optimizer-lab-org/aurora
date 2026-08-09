from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract,
    load_and_validate_source_plan,
)
from aurora.infra.sp500_megarun.source_probe import probe_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe every free source for the SP500 120-lane mega-run.")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = load_and_validate_contract(args.contract)
    source_plan = load_and_validate_source_plan(args.sources, contract)
    report = probe_sources(source_plan, output_path=args.output)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
