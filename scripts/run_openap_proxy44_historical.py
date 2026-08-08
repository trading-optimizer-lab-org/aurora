"""GitHub-only entry point for the canonical OpenAP 44-proxy historical audit."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from aurora.research.openap_proxy44_historical import run_proxy44_historical  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-db", required=True)
    parser.add_argument("--official-long-short", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    run_proxy44_historical(
        base_database=args.base_db,
        official_long_short=args.official_long_short,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
