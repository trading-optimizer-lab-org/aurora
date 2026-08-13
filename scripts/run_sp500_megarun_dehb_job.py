"""Run one exact two-island mega job on GitHub Actions only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_job_runner import (
    load_verified_job_payload,
    run_dehb_job,
)
from aurora.infra.sp500_megarun.dehb_launch_contract import (
    load_and_validate_launch_contract,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("GITHUB_ACTIONS_REQUIRED_FOR_REAL_DEHB_JOB")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--launch-contract", type=Path, required=True)
    parser.add_argument("--expected-code-commit-sha", required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--job-payload", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--previous-worker-dir", type=Path)
    parser.add_argument("--evaluation-cache-root", type=Path)
    parser.add_argument("--slice-seconds", type=float)
    args = parser.parse_args()
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    launch = load_and_validate_launch_contract(
        args.launch_contract,
        campaign,
        runtime_input_pack=args.runtime_input_pack,
        expected_code_commit_sha=args.expected_code_commit_sha,
    )
    data_contract = load_and_validate_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(args.feature_contract, data_contract)
    result = run_dehb_job(
        campaign,
        feature_contract,
        launch_contract=launch,
        payload=load_verified_job_payload(args.job_payload),
        runtime_input_pack=args.runtime_input_pack,
        output_dir=args.output_dir,
        previous_worker_dir=args.previous_worker_dir,
        evaluation_cache_root=args.evaluation_cache_root,
        current_run_id=int(os.environ["GITHUB_RUN_ID"]),
        slice_seconds=args.slice_seconds,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
