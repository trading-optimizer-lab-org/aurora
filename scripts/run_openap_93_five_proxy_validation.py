"""GitHub-only runner for the five OpenAP historical proxy comparisons."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from aurora.research.openap_93.historical_proxy_validation import run_validation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-db", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--crosswalk", default=None)
    parser.add_argument("--ff3-daily", default=None)
    parser.add_argument("--earnings-history", default=None)
    parser.add_argument("--ff48-sic-codes", default=None)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-pairs", type=int, default=30)
    args = parser.parse_args()
    run_validation(
        base_db=args.base_db,
        reference=args.reference,
        crosswalk=args.crosswalk,
        ff3_daily=args.ff3_daily,
        earnings_history=args.earnings_history,
        ff48_sic_codes=args.ff48_sic_codes,
        output_dir=args.output_dir,
        min_pairs=args.min_pairs,
    )


if __name__ == "__main__":
    main()
