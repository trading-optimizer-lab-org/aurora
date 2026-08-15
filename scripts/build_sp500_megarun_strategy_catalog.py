"""Build the deterministic, train-only SP500 strategy catalog."""

from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_megarun.strategy_catalog import (
    CatalogBuildError,
    build_and_write_strategy_catalog,
    canonical_json_bytes,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build_and_write_strategy_catalog(
            args.data_contract,
            args.feature_contract,
            output_dir=args.output_dir,
        )
    except CatalogBuildError as exc:
        parser.exit(1, f"{exc}\n")
    print(canonical_json_bytes(receipt).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
