"""Run one four-slot continuous SP500 DEHB worker on GitHub Actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from threading import local

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract as load_and_validate_data_contract,
)
from aurora.infra.sp500_megarun.dehb_campaign_contract import (
    load_and_validate_campaign_contract,
)
from aurora.infra.sp500_megarun.dehb_continuous_store import (
    PostgresContinuousCampaignStore,
)
from aurora.infra.sp500_megarun.dehb_continuous_archive import (
    ArchiveIdentityV1,
    SqliteHistoricalCacheV1,
)
from aurora.infra.sp500_megarun.dehb_continuous_worker import (
    ContinuousWorkerRuntime,
    PreparedPhysicalEvaluationV1,
)
from aurora.infra.sp500_megarun.dehb_lane_registry import (
    TrainLaneEvaluator,
    default_lane_configurations,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    numeric_runtime_profile_sha256,
    verify_numeric_runtime_environment,
)
from aurora.infra.sp500_megarun.dehb_runtime_inputs import (
    scientific_input_binding_sha256,
    verify_runtime_input_pack,
)
from aurora.infra.sp500_megarun.dehb_worker import (
    load_train_total_return_ledger,
    prepare_lane_candidate,
    score_prepared_lane_candidate,
)
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


def main() -> int:
    require_github_only_execution("SP500_DEHB_CONTINUOUS_WORKER_V2")
    verify_numeric_runtime_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-contract", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--feature-contract", type=Path, required=True)
    parser.add_argument("--runtime-input-pack", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--pool-generation", required=True)
    parser.add_argument("--worker-lifetime-id", required=True)
    parser.add_argument("--lifetime-minutes", type=int, default=300)
    parser.add_argument("--executor-slots", type=int, default=4)
    parser.add_argument("--database-url-env", default="SP500_DEHB_COORDINATOR_DATABASE_URL")
    parser.add_argument("--historical-cache-database", type=Path)
    parser.add_argument("--historical-cache-manifest", type=Path)
    args = parser.parse_args()

    dsn = os.environ.get(args.database_url_env)
    if not dsn:
        raise RuntimeError("CONTINUOUS_WORKER_DATABASE_URL_MISSING")
    campaign = load_and_validate_campaign_contract(args.campaign_contract)
    data_contract = load_and_validate_data_contract(args.data_contract)
    feature_contract = load_and_validate_feature_contract(args.feature_contract, data_contract)
    runtime_manifest = verify_runtime_input_pack(
        args.runtime_input_pack,
        expected_scientific_input_binding_sha256=scientific_input_binding_sha256(campaign),
    )
    if bool(args.historical_cache_database) != bool(args.historical_cache_manifest):
        raise RuntimeError("CONTINUOUS_WORKER_HISTORICAL_CACHE_PAIR_REQUIRED")
    historical_cache = None
    if args.historical_cache_database is not None:
        scientific_commit = os.environ.get("SP500_DEHB_SCIENTIFIC_COMMIT_SHA", "")
        if len(scientific_commit) != 40:
            raise RuntimeError("CONTINUOUS_WORKER_SCIENTIFIC_COMMIT_MISSING")
        historical_cache = SqliteHistoricalCacheV1(
            database_path=args.historical_cache_database,
            manifest_path=args.historical_cache_manifest,
            expected_identity=ArchiveIdentityV1(
                campaign_id=args.campaign_id,
                scientific_contract_sha256=campaign.sha256,
                code_commit_sha=scientific_commit,
                train_manifest_sha256=campaign.train_snapshot_manifest_sha256,
                train_spy_sha256=campaign.train_spy_sha256,
                numeric_profile_sha256=numeric_runtime_profile_sha256(),
            ),
        )
    pack = args.runtime_input_pack.resolve()
    train_snapshot = pack / "train_snapshot_1993_2010"
    baseline_dirs = {
        "price": pack / "baseline_price",
        "market": pack / "baseline_market",
        "macro": pack / "baseline_macro",
    }
    fidelity_years = {
        int(item.budget): tuple(int(year) for year in item.years)
        for item in campaign.fidelities
    }
    thread_context = local()

    def context():
        value = getattr(thread_context, "value", None)
        if value is None:
            ledger = load_train_total_return_ledger(
                train_snapshot,
                allowed_end=campaign.search_end,
                expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
                expected_spy_sha256=campaign.train_spy_sha256,
            )
            evaluator = TrainLaneEvaluator(
                train_snapshot,
                expected_manifest_sha256=campaign.train_snapshot_manifest_sha256,
                expected_spy_sha256=campaign.train_spy_sha256,
                default_configurations=default_lane_configurations(feature_contract),
                baseline_feature_dirs=baseline_dirs,
            )
            value = (ledger, evaluator)
            thread_context.value = value
        return value

    def position_builder(key):
        _ledger, evaluator = context()
        prepared = prepare_lane_candidate(
            key.payload["configuration"],
            key.payload["fidelity"],
            lane_id=key.payload["lane_id"],
            feature_evaluator=evaluator,
            fidelity_years=fidelity_years,
            allowed_end=campaign.search_end,
        )
        return PreparedPhysicalEvaluationV1(
            positions_sha256=prepared.position_fingerprint,
            payload=prepared,
        )

    def physical_evaluator(prepared, _key):
        ledger, _evaluator = context()
        return score_prepared_lane_candidate(
            prepared.payload,
            ledger=ledger,
            fidelity_years=fidelity_years,
            allowed_end=campaign.search_end,
        )

    def result_binder(result, key, prepared):
        rebound = dict(result)
        info = dict(result["info"])
        lane_candidate = prepared.payload
        configuration = dict(key.payload["configuration"])
        info.update(
            {
                "lane_id": key.payload["lane_id"],
                "config": configuration,
                "config_sha256": hashlib.sha256(
                    json.dumps(
                        configuration, sort_keys=True, separators=(",", ":")
                    ).encode("utf-8")
                ).hexdigest(),
                "strategy_fingerprint": lane_candidate.strategy_fingerprint,
                "position_fingerprint": lane_candidate.position_fingerprint,
            }
        )
        rebound["info"] = info
        return rebound

    store = PostgresContinuousCampaignStore(
        dsn=dsn,
        campaign_id=args.campaign_id,
        pool_min_size=0,
        pool_max_size=1,
    )
    runtime = ContinuousWorkerRuntime(
        store=store,
        pool_generation=args.pool_generation,
        github_run_id=int(os.environ.get("GITHUB_RUN_ID", "0")),
        github_job=args.worker_lifetime_id,
        position_builder=position_builder,
        physical_evaluator=physical_evaluator,
        result_binder=result_binder,
        executor_slots=args.executor_slots,
        historical_cache=historical_cache,
    )
    runtime.run_for(lifetime_seconds=max(1, args.lifetime_minutes) * 60 - 60)
    if runtime_manifest.get("validation_opened") is not False or runtime_manifest.get(
        "locked_opened"
    ) is not False:
        raise RuntimeError("CONTINUOUS_WORKER_BOUNDARY_OPEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
