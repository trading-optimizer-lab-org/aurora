"""Build one immutable train-only reducer snapshot on GitHub Actions."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract as load_and_validate_data_contract,
)
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace
from aurora.infra.sp500_megarun.dehb_continuous_reducer import ContinuousReducer
from aurora.infra.sp500_megarun.dehb_continuous_robustness import (
    execute_candidate_local_reviews,
)
from aurora.infra.sp500_megarun.dehb_continuous_store import (
    PostgresContinuousCampaignStore,
)
from aurora.infra.sp500_megarun.dehb_robustness import (
    build_physical_candidate_robustness_reviewer,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


class _RobustnessEnrichedStore:
    def __init__(self, base, enriched_rows):
        self.base = base
        self.enriched_rows = list(enriched_rows)

    def result_rows(self, _cutoff):
        return list(self.enriched_rows)

    def persist_reducer_snapshot(self, snapshot):
        return self.base.persist_reducer_snapshot(snapshot)

    def freeze_campaign(self, snapshot_sha256, winner):
        return self.base.freeze_campaign(snapshot_sha256, winner)


def main() -> int:
    require_github_only_execution("SP500_DEHB_CONTINUOUS_REDUCER_V2")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
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
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_data_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(
        args.feature_contract, data_contract
    )
    pack = args.runtime_input_pack.resolve()
    train_snapshot = pack / "train_snapshot_1993_2010"
    baseline_dirs = {
        "price": pack / "baseline_price",
        "market": pack / "baseline_market",
        "macro": pack / "baseline_macro",
    }
    raw_rows = store.result_rows(cutoff)
    reviewer_cache = {}

    def reviewer(request):
        identity = (request.lane_id, request.robustness_seed)
        bound = reviewer_cache.get(identity)
        if bound is None:
            lane_space = build_lane_configspace(
                feature_contract, request.lane_id, seed=request.robustness_seed
            )
            bound = build_physical_candidate_robustness_reviewer(
                campaign,
                feature_contract,
                lane_id=request.lane_id,
                train_snapshot=train_snapshot,
                baseline_feature_dirs=baseline_dirs,
                lane_configspace=lane_space,
                seed=request.robustness_seed,
            )
            reviewer_cache[identity] = bound
        return bound(
            {"info": dict(request.candidate), "configuration": dict(request.configuration)}
        )

    reviewed = execute_candidate_local_reviews(raw_rows, store=store, reviewer=reviewer)
    by_identity = {
        (row["island_id"], row["strategy_fingerprint"]): row for row in reviewed
    }
    enriched_rows = [
        by_identity.get((row.get("island_id"), row.get("strategy_fingerprint")), row)
        for row in raw_rows
    ]
    reducer = ContinuousReducer(_RobustnessEnrichedStore(store, enriched_rows))
    snapshot = reducer.build_snapshot(cutoff)
    decision = reducer.attempt_train_freeze(snapshot)
    payload = {"snapshot": asdict(snapshot), "decision": asdict(decision)}
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
