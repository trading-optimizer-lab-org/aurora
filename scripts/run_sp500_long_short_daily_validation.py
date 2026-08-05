"""Run the one authorized validation phase from frozen train artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_long_short_daily.data import prepare_market_snapshot
from aurora.infra.sp500_long_short_daily.validation import run_validation_once
from aurora.infra.sp500_long_short_daily.workload import _package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-results-dir", type=Path, required=True)
    parser.add_argument("--train-prepared-dir", type=Path, required=True)
    parser.add_argument("--validation-prepared-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--validation-ack", required=True)
    args = parser.parse_args()
    validation_manifest = args.validation_prepared_dir / "market_data_manifest.json"
    if not validation_manifest.is_file():
        prepare_market_snapshot(
            args.validation_prepared_dir,
            _package(),
            start="2011-01-01",
            end="2020-12-31",
            split="validation",
        )
    summary = run_validation_once(
        train_results_dir=args.train_results_dir,
        train_prepared_dir=args.train_prepared_dir,
        validation_prepared_dir=args.validation_prepared_dir,
        output_dir=args.output_dir,
        validation_ack=args.validation_ack,
    )
    return 3 if summary["result_status"] == "TECHNICAL_FAILURE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
