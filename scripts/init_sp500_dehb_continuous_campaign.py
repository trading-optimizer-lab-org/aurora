"""Initialize the continuous SP500 DEHB database on GitHub Actions only."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_continuous_bootstrap import bootstrap_campaign
from aurora.infra.sp500_megarun.dehb_continuous_schema import apply_schema
from aurora.infra.sp500_megarun.dehb_launch_contract import (
    load_and_validate_launch_contract,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    numeric_runtime_profile_sha256,
)
from aurora.infra.sp500_megarun.dehb_continuous_supervisor import (
    probe_database_client_capacity,
)


def main() -> int:
    require_github_only_execution("SP500_DEHB_CONTINUOUS_BOOTSTRAP_V2")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--launch-contract", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--database-url-env", default="SP500_DEHB_COORDINATOR_DATABASE_URL")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dsn = os.environ.get(args.database_url_env)
    if not dsn:
        raise RuntimeError("CONTINUOUS_BOOTSTRAP_DATABASE_URL_MISSING")
    database_contract = probe_database_client_capacity(
        dsn,
        required_connections=400,
    )
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    launch = load_and_validate_launch_contract(args.launch_contract, campaign)

    import psycopg

    with psycopg.connect(dsn) as connection:
        receipt = bootstrap_campaign(
            connection,
            campaign_id=args.campaign_id,
            campaign=campaign,
            launch_contract_sha256=launch.sha256,
            code_commit_sha=launch.code_commit_sha,
            numeric_profile_sha256=numeric_runtime_profile_sha256(),
            schema_applier=apply_schema,
        )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(receipt)
    payload["database_contract"] = asdict(database_contract)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
