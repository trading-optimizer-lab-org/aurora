"""Build or extend a verified train-only SQLite history on GitHub Actions."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_continuous_archive import (
    ArchiveIdentityV1,
    SqliteHistoricalCacheV1,
    write_sqlite_historical_cache,
)
from aurora.infra.sp500_megarun.dehb_continuous_models import (
    EvaluationCacheKeyV2,
    EvaluationResultV2,
    StrategyEvaluationKeyV1,
)
from aurora.infra.sp500_megarun.dehb_continuous_store import (
    PostgresContinuousCampaignStore,
    decode_storage_json,
)
from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
    scientific_result_sha256,
)


def main() -> int:
    require_github_only_execution("SP500_DEHB_BUILD_HISTORICAL_ARCHIVE_V1")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--database-url-env", default="SP500_DEHB_COORDINATOR_DATABASE_URL")
    parser.add_argument("--prior-database", type=Path)
    parser.add_argument("--prior-manifest", type=Path)
    parser.add_argument("--output-database", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    args = parser.parse_args()
    dsn = os.environ.get(args.database_url_env, "").strip()
    if not dsn:
        raise RuntimeError("CONTINUOUS_ARCHIVE_DATABASE_URL_MISSING")
    if bool(args.prior_database) != bool(args.prior_manifest):
        raise RuntimeError("CONTINUOUS_ARCHIVE_PRIOR_PAIR_REQUIRED")

    import psycopg

    with psycopg.connect(dsn) as connection:
        campaign = connection.execute(
            """
            SELECT scientific_contract_sha256, code_commit_sha,
                   train_manifest_sha256, train_spy_sha256,
                   numeric_profile_sha256, validation_opened, locked_opened
            FROM campaigns WHERE campaign_id = %s
            """,
            (args.campaign_id,),
        ).fetchone()
        if campaign is None:
            raise RuntimeError("CONTINUOUS_ARCHIVE_CAMPAIGN_NOT_FOUND")
        identity = ArchiveIdentityV1(
            campaign_id=args.campaign_id,
            scientific_contract_sha256=str(campaign[0]),
            code_commit_sha=str(campaign[1]),
            train_manifest_sha256=str(campaign[2]),
            train_spy_sha256=str(campaign[3]),
            numeric_profile_sha256=str(campaign[4]),
            validation_opened=bool(campaign[5]),
            locked_opened=bool(campaign[6]),
        )
        evaluation_rows = connection.execute(
            """
            SELECT e.cache_key_sha256, e.key_payload,
                   r.result_sha256, r.result_payload
            FROM evaluations e
            JOIN results r ON r.evaluation_id = e.evaluation_id
            WHERE e.campaign_id = %s AND e.state = 'completed'
              AND r.validation_opened = false AND r.locked_opened = false
            ORDER BY e.cache_key_sha256
            """,
            (args.campaign_id,),
        ).fetchall()
        strategy_rows = connection.execute(
            """
            SELECT strategy_key_sha256, key_payload,
                   result_sha256, result_payload
            FROM strategy_evaluations
            WHERE campaign_id = %s AND state = 'completed'
              AND result_sha256 IS NOT NULL AND result_payload IS NOT NULL
            ORDER BY strategy_key_sha256
            """,
            (args.campaign_id,),
        ).fetchall()

    evaluation_entries = []
    for key_sha, key_payload, result_sha, result_payload in evaluation_rows:
        key = EvaluationCacheKeyV2(
            sha256=str(key_sha), payload=decode_storage_json(key_payload)
        )
        result = EvaluationResultV2.build(
            key=key, result=decode_storage_json(result_payload)
        )
        if result.result_sha256 != str(result_sha):
            raise RuntimeError("CONTINUOUS_ARCHIVE_EVALUATION_HASH_MISMATCH")
        evaluation_entries.append((key, result))

    strategy_entries = []
    for key_sha, key_payload, result_sha, result_payload in strategy_rows:
        key = StrategyEvaluationKeyV1(
            sha256=str(key_sha), payload=decode_storage_json(key_payload)
        )
        result = decode_storage_json(result_payload)
        if scientific_result_sha256(result) != str(result_sha):
            raise RuntimeError("CONTINUOUS_ARCHIVE_STRATEGY_HASH_MISMATCH")
        strategy_entries.append((key, str(result_sha), result))

    store = PostgresContinuousCampaignStore(dsn=dsn, campaign_id=args.campaign_id)
    current_rows = store.result_rows(store.latest_event_sequence())
    if args.prior_database is not None and args.prior_manifest is not None:
        prior = SqliteHistoricalCacheV1(
            database_path=args.prior_database,
            manifest_path=args.prior_manifest,
            expected_identity=identity,
        )
        evaluation_entries = prior.evaluation_entries() + evaluation_entries
        strategy_entries = prior.strategy_entries() + strategy_entries
        current_rows = prior.result_rows() + current_rows

    receipt = write_sqlite_historical_cache(
        database_path=args.output_database,
        manifest_path=args.output_manifest,
        identity=identity,
        evaluation_entries=evaluation_entries,
        strategy_entries=strategy_entries,
        result_rows=current_rows,
    )
    output_receipt = args.output_receipt.resolve()
    output_receipt.parent.mkdir(parents=True, exist_ok=True)
    output_receipt.write_text(
        json.dumps(
            {
                **asdict(receipt),
                "identity": asdict(identity),
                "validation_opened": False,
                "locked_opened": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
