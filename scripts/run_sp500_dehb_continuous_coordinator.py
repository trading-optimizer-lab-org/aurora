"""Run the leased continuous official-DEHB coordinator in GitHub Actions."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import time
import uuid

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_continuous_runtime import (
    build_continuous_coordinator,
)
from aurora.infra.sp500_megarun.dehb_continuous_store import (
    PostgresContinuousCampaignStore,
)
from aurora.infra.sp500_megarun.dehb_launch_contract import (
    load_and_validate_launch_contract,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    verify_numeric_runtime_environment,
)
from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract as load_and_validate_data_contract,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


def main() -> int:
    require_github_only_execution("SP500_DEHB_CONTINUOUS_COORDINATOR_V2")
    verify_numeric_runtime_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--launch-contract", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--lifetime-minutes", type=int, default=300)
    parser.add_argument("--database-url-env", default="SP500_DEHB_COORDINATOR_DATABASE_URL")
    args = parser.parse_args()

    dsn = os.environ.get(args.database_url_env)
    if not dsn:
        raise RuntimeError("CONTINUOUS_COORDINATOR_DATABASE_URL_MISSING")
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_data_contract(args.data_contract)
    feature = load_and_validate_feature_contract(args.feature_contract, data_contract)
    launch = load_and_validate_launch_contract(args.launch_contract, campaign)
    store = PostgresContinuousCampaignStore(dsn=dsn, campaign_id=args.campaign_id)
    coordinator = build_continuous_coordinator(
        store=store,
        campaign=campaign,
        feature_contract=feature,
        launch=launch,
        work_root=args.work_root,
        owner_token=f"{os.environ.get('GITHUB_RUN_ID', 'unknown')}:{uuid.uuid4()}",
    )
    deadline = time.monotonic() + max(1, args.lifetime_minutes) * 60 - 60
    try:
        while time.monotonic() < deadline:
            cycle = coordinator.run_once()
            activity = cycle.batches_created + cycle.batches_applied
            time.sleep(0.2 if activity else 1.0)
    finally:
        coordinator.release_leadership()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
