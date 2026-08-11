from __future__ import annotations

import argparse
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.snapshot_schema_inventory import (
    build_train_snapshot_schema_inventory,
)


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_TRAIN_SNAPSHOT_SCHEMA_INVENTORY")
    parser = argparse.ArgumentParser(
        description="Inventory train-only SP500 snapshot schemas without sampling values."
    )
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_train_snapshot_schema_inventory(
        args.train_snapshot,
        output_path=args.output,
    )
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
