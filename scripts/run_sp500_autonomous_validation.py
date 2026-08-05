"""CLI wrapper for the single authorized validation pass."""

from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_autonomous_discovery.validation import run_validation_once


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-results-dir", type=Path, required=True)
    parser.add_argument("--train-prepared-dir", type=Path, required=True)
    parser.add_argument("--validation-prepared-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--validation-ack", required=True)
    args = parser.parse_args()
    summary = run_validation_once(
        train_results_dir=args.train_results_dir,
        train_prepared_dir=args.train_prepared_dir,
        validation_prepared_dir=args.validation_prepared_dir,
        output_dir=args.output_dir,
        validation_ack=args.validation_ack,
    )
    return 0 if summary["result_status"] != "TECHNICAL_FAILURE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
