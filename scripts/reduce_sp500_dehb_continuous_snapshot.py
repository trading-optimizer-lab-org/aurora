"""Build one immutable train-only reducer snapshot on GitHub Actions."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_continuous_reducer import ContinuousReducer
from aurora.infra.sp500_megarun.dehb_continuous_store import (
    PostgresContinuousCampaignStore,
)


def main() -> int:
    require_github_only_execution("SP500_DEHB_CONTINUOUS_REDUCER_V2")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--cutoff-sequence", required=True)
    parser.add_argument("--database-url-env", default="SP500_DEHB_COORDINATOR_DATABASE_URL")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get(args.database_url_env)
    if not dsn:
        raise RuntimeError("CONTINUOUS_REDUCER_DATABASE_URL_MISSING")
    store = PostgresContinuousCampaignStore(dsn=dsn, campaign_id=args.campaign_id)
    cutoff = (
        store.latest_event_sequence()
        if args.cutoff_sequence == "latest"
        else int(args.cutoff_sequence)
    )
    reducer = ContinuousReducer(store)
    snapshot = reducer.build_snapshot(cutoff)
    decision = reducer.attempt_train_freeze(snapshot)
    payload = {"snapshot": asdict(snapshot), "decision": asdict(decision)}
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

