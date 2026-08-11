from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.fundamental_feature_smoke import (
    build_fundamental_feature_smoke,
)


def main() -> int:
    require_github_only_execution(
        "SP500_MEGARUN_FUNDAMENTAL_FEATURE_SMOKE_F101_F110"
    )
    parser = argparse.ArgumentParser(
        description="Run the train-only technical feature smoke for F101-F110."
    )
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_fundamental_feature_smoke(
        args.train_snapshot,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready"] and report["executable_lane_count"] == 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
