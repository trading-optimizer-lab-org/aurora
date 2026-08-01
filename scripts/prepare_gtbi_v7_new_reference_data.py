"""Verify the frozen release and build the pre-2021 GTBI V7 data pack."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from infra.gtbi_v7_new_reference.release import (
    MIN_MARKET_CAP_USD,
    build_historical_execution_pack,
    verify_and_extract_required_release_files,
)


def _require_github() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("GTBI V7 data preparation is GitHub Actions only")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--extracted-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--min-market-cap", type=float, default=MIN_MARKET_CAP_USD)
    return parser


def main(argv: list[str] | None = None) -> int:
    _require_github()
    args = _parser().parse_args(argv)
    verification = verify_and_extract_required_release_files(
        release_root=args.release_root,
        output_dir=args.extracted_root,
    )
    pack = build_historical_execution_pack(
        extracted_root=args.extracted_root,
        output_root=args.output_root,
        min_market_cap=args.min_market_cap,
    )
    print(json.dumps({"release": verification, "execution_pack": pack}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
