"""Package or verify the frozen GTBI V7 data lake as opaque bytes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aurora.core.runtime_paths import base_data_dir  # noqa: E402
from infra.gtbi_v7_readiness.frozen_data_lake import (  # noqa: E402
    DEFAULT_PART_SIZE,
    MANIFEST_FILENAME,
    RECEIPT_FILENAME,
    package_frozen_data_lake,
    verify_frozen_data_lake_archive,
)


def _default_source() -> Path:
    return base_data_dir() / "prices" / "free_us_daily"


def _default_output() -> Path:
    return base_data_dir() / "exports" / "gtbi_v7_frozen_data_lake_v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    package = subparsers.add_parser("package")
    package.add_argument("--source-root", type=Path, default=_default_source())
    package.add_argument(
        "--source-receipt",
        type=Path,
        default=(
            ROOT / "docs/readiness/gtbi-v7/local_data_lake_receipt.json"
        ),
    )
    package.add_argument("--output-dir", type=Path, default=_default_output())
    package.add_argument(
        "--part-size-bytes",
        type=int,
        default=DEFAULT_PART_SIZE,
    )

    verify = subparsers.add_parser("verify")
    verify.add_argument("--parts-dir", type=Path, default=_default_output())
    verify.add_argument(
        "--manifest",
        type=Path,
        default=_default_output() / MANIFEST_FILENAME,
    )
    verify.add_argument(
        "--receipt",
        type=Path,
        default=_default_output() / RECEIPT_FILENAME,
    )

    args = parser.parse_args()
    if args.command == "package":
        result = package_frozen_data_lake(
            source_root=args.source_root,
            source_receipt_path=args.source_receipt,
            output_dir=args.output_dir,
            part_size=args.part_size_bytes,
        )
    else:
        result = verify_frozen_data_lake_archive(
            parts_dir=args.parts_dir,
            manifest_path=args.manifest,
            receipt_path=args.receipt,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
