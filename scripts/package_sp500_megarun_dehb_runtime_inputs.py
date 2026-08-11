"""Package one immutable train-only worker input artifact on GitHub Actions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import package_runtime_inputs


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_PACKAGE_RUNTIME_INPUTS")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--baseline-price", type=Path, required=True)
    parser.add_argument("--baseline-market", type=Path, required=True)
    parser.add_argument("--baseline-macro", type=Path, required=True)
    parser.add_argument("--registry-report", type=Path, required=True)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    contract = load_and_validate_campaign_contract(args.campaign_contract)
    manifest = package_runtime_inputs(
        contract=contract,
        train_snapshot=args.train_snapshot,
        baseline_feature_dirs={
            "price": args.baseline_price,
            "market": args.baseline_market,
            "macro": args.baseline_macro,
        },
        registry_report=args.registry_report,
        baseline_run_id=args.baseline_run_id,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
