"""Exercise every physical DEHB lane route on GitHub Actions only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    TrainLaneEvaluator,
    default_lane_configurations,
    supported_lane_ids,
)
from aurora.infra.sp500_megarun.dehb_registry_preflight import audit_lane_registry
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


def main() -> int:
    require_github_only_execution("SP500_MEGARUN_DEHB_REGISTRY_PREFLIGHT")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--train-snapshot", type=Path, required=True)
    parser.add_argument("--baseline-price", type=Path, required=True)
    parser.add_argument("--baseline-market", type=Path, required=True)
    parser.add_argument("--baseline-macro", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(
        args.feature_contract, data_contract
    )
    defaults = default_lane_configurations(feature_contract)
    evaluator = TrainLaneEvaluator(
        args.train_snapshot,
        expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
        expected_spy_sha256=campaign.train_spy_sha256,
        default_configurations=defaults,
        baseline_feature_dirs={
            "price": args.baseline_price,
            "market": args.baseline_market,
            "macro": args.baseline_macro,
        },
    )
    report = audit_lane_registry(
        evaluator=evaluator,
        default_configurations=defaults,
        expected_lane_ids=supported_lane_ids(),
        allowed_end=campaign.search_end,
    )
    report = {
        **report,
        "campaign_contract_sha256": campaign.sha256,
        "feature_contract_sha256": feature_contract.sha256,
        "train_source_run_id": campaign.train_source_run_id,
        "train_artifact_digest_sha256": campaign.train_artifact_digest_sha256,
        "train_snapshot_manifest_sha256": campaign.train_snapshot_manifest_sha256,
        "train_spy_sha256": campaign.train_spy_sha256,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready"] and report["lane_count"] == 240 else 1


if __name__ == "__main__":
    raise SystemExit(main())
