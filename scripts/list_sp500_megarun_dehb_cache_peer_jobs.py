"""List the three prior worker artifacts covering two lanes and all replicas."""

from __future__ import annotations

import argparse
from pathlib import Path

from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_job_runner import (
    cache_peer_job_ids,
    load_verified_job_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--job-payload", type=Path, required=True)
    args = parser.parse_args()
    contract = load_and_validate_campaign_contract(args.campaign_contract)
    payload = load_verified_job_payload(args.job_payload)
    for job_id in cache_peer_job_ids(contract, payload):
        print(job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
