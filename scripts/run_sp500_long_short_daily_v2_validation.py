"""Open V2 validation once, only after every frozen-train gate passes."""

from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_long_short_daily_v2.data import prepare_market_snapshot
from aurora.infra.sp500_long_short_daily_v2.contracts import VALIDATION_ACK
from aurora.infra.sp500_long_short_daily_v2.validation import (
    run_validation_once,
    verify_train_freeze,
)
from aurora.infra.sp500_long_short_daily_v2.workload import _package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-results-dir", type=Path, required=True)
    parser.add_argument("--train-prepared-dir", type=Path, required=True)
    parser.add_argument("--validation-prepared-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--validation-ack", required=True)
    args = parser.parse_args()

    # Fail closed before acquiring or exposing any validation observation.
    if args.validation_ack != VALIDATION_ACK:
        raise SystemExit("VALIDATION_ACK_MISMATCH")
    verify_train_freeze(args.train_results_dir / "v2_train_selection_freeze.json")
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
