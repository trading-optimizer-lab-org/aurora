from __future__ import annotations

import argparse
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.snapshot_normalization_probe import (
    build_train_snapshot_normalization_probe,
)


_F021_F040_DATASETS = (
    "D_SPY",
    "D_VIX",
    "D_VXO",
    "D_CFTC",
    "D_RATES",
    "D_MACRO_PIT",
    "D_FIN_COND",
    "D_PHILLY_RT",
    "D_CALENDAR",
    "D_GOYAL",
    "D_SHILLER",
)


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_F021_F040_NORMALIZATION_PROBE")
    parser = argparse.ArgumentParser(
        description="Probe train-only raw schemas needed by F021-F040."
    )
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_train_snapshot_normalization_probe(
        args.train_snapshot,
        dataset_ids=_F021_F040_DATASETS,
        output_path=args.output,
    )
    return 0 if report["ready"] and report["dataset_count"] == 11 else 1


if __name__ == "__main__":
    raise SystemExit(main())
