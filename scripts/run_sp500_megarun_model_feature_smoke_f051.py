from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.model_feature_smoke import build_model_feature_smoke


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_MODEL_FEATURE_SMOKE_F051_F060")
    parser = argparse.ArgumentParser(
        description="Run the train-only technical feature smoke for F051-F060."
    )
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--price-feature-dir", type=Path, required=True)
    parser.add_argument("--market-feature-dir", type=Path, required=True)
    parser.add_argument("--macro-feature-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_model_feature_smoke(
        args.train_snapshot,
        price_feature_dir=args.price_feature_dir,
        market_feature_dir=args.market_feature_dir,
        macro_feature_dir=args.macro_feature_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready"] and report["executable_lane_count"] == 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
