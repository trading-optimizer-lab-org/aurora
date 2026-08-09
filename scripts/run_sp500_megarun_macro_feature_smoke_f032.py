from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.macro_feature_smoke import (
    build_macro_feature_smoke,
)


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_MACRO_FEATURE_SMOKE_F032_F040")
    parser = argparse.ArgumentParser(
        description="Run the train-only technical feature smoke for F032-F040."
    )
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_macro_feature_smoke(
        args.train_snapshot,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready"] and report["executable_lane_count"] == 9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
