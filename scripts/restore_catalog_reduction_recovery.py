"""CLI for the protected catalog reduction recovery reader."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.sp500_megarun.catalog_reduction_recovery_restore import (
    restore_catalog_reduction_recovery,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore the authenticated historical catalog reduction source."
    )
    parser.add_argument("--sealed-plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = restore_catalog_reduction_recovery(
            repo_root=REPOSITORY_ROOT,
            sealed_plan=args.sealed_plan,
            output_dir=args.output_dir,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "output_dir": str(result.output_dir),
                "profile_sha256": result.profile_sha256,
                "owner_run_id": result.owner_run_id,
                "terminal_receipt_sha256": result.terminal_receipt_sha256,
                "source_plan_receipt_sha256": result.source_plan_receipt_sha256,
                "group_receipt_sha256s": list(result.group_receipt_sha256s),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
