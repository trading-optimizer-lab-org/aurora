"""Run the one authorized validation phase from frozen train artifacts."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from aurora.infra.sp500_long_short_daily.data import prepare_market_snapshot
from aurora.infra.sp500_long_short_daily.validation import (
    build_diagnostic_train_freeze,
    run_validation_once,
)
from aurora.infra.sp500_long_short_daily.workload import _package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-results-dir", type=Path, required=True)
    parser.add_argument("--train-prepared-dir", type=Path, required=True)
    parser.add_argument("--validation-prepared-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--validation-ack", required=True)
    parser.add_argument("--diagnostic-strategy-id", default="")
    args = parser.parse_args()
    train_results_dir = args.train_results_dir
    allow_diagnostic = bool(args.diagnostic_strategy_id)
    if allow_diagnostic:
        diagnostic_freeze_dir = args.output_dir.parent / "diagnostic-freeze"
        build_diagnostic_train_freeze(
            source_train_results_dir=args.train_results_dir,
            output_dir=diagnostic_freeze_dir,
            strategy_id=args.diagnostic_strategy_id,
            code_sha=os.environ.get("GITHUB_SHA", "LOCAL_TEST_ONLY"),
        )
        train_results_dir = diagnostic_freeze_dir
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
        train_results_dir=train_results_dir,
        train_prepared_dir=args.train_prepared_dir,
        validation_prepared_dir=args.validation_prepared_dir,
        output_dir=args.output_dir,
        validation_ack=args.validation_ack,
        allow_diagnostic=allow_diagnostic,
    )
    return 3 if summary["result_status"] == "TECHNICAL_FAILURE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
