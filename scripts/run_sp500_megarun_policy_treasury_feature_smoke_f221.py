from __future__ import annotations

import argparse
import json

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.policy_treasury_feature_smoke import (
    build_policy_treasury_feature_smoke,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run train-only policy and Treasury smoke F221-F230."
    )
    parser.add_argument("--train-snapshot", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    require_github_only_execution("SP500_MEGARUN_POLICY_TREASURY_SMOKE_F221_F230")
    report = build_policy_treasury_feature_smoke(
        args.train_snapshot,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
