from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.feature_smoke import build_price_feature_smoke


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_FEATURE_SMOKE_F001_F020")
    parser = argparse.ArgumentParser(
        description="Run the train-only technical feature smoke for F001-F020."
    )
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    spy_path = args.train_snapshot / "D_SPY.parquet"
    if not spy_path.is_file():
        raise FileNotFoundError(f"TRAIN_SPY_ARTIFACT_MISSING:{spy_path}")
    report = build_price_feature_smoke(
        pd.read_parquet(spy_path),
        output_dir=args.output_dir,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready"] and report["executable_lane_count"] == 20 else 1


if __name__ == "__main__":
    raise SystemExit(main())
