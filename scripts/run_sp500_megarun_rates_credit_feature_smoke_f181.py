from __future__ import annotations

import argparse
import json

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.rates_credit_feature_smoke import (
    build_rates_credit_feature_smoke,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run train-only rates/credit/money smoke F181-F190."
    )
    parser.add_argument("--train-snapshot", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    require_github_only_execution("SP500_MEGARUN_RATES_CREDIT_FEATURE_SMOKE_F181_F190")
    report = build_rates_credit_feature_smoke(
        args.train_snapshot,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
