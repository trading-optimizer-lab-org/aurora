from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import uuid

import pytest


pytestmark = pytest.mark.integration


@pytest.fixture
def postgres_store():
    dsn = os.environ.get("SP500_DEHB_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("SP500_DEHB_TEST_DATABASE_URL is not configured")

    psycopg = pytest.importorskip("psycopg")
    pool_module = pytest.importorskip("psycopg_pool")
    from aurora.infra.sp500_megarun.dehb_continuous_schema import apply_schema
    from aurora.infra.sp500_megarun.dehb_continuous_store import (
        PostgresContinuousCampaignStore,
    )

    schema = f"continuous_test_{uuid.uuid4().hex}"
    campaign_id = f"campaign-{uuid.uuid4()}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    pool = pool_module.ConnectionPool(
        dsn,
        min_size=4,
        max_size=32,
        kwargs={"options": f"-c search_path={schema}"},
        open=True,
    )
    try:
        with pool.connection() as connection:
            apply_schema(connection)
            with connection.transaction(), connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO campaigns (
                        campaign_id, schema_version, state, scientific_contract_sha256,
                        launch_contract_sha256, code_commit_sha, train_manifest_sha256,
                        train_spy_sha256, numeric_profile_sha256
                    ) VALUES (%s, 1, 'searching', %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        campaign_id,
                        "e" * 64,
                        "1" * 64,
                        "2" * 40,
                        "c" * 64,
                        "d" * 64,
                        "b" * 64,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO islands (
                        campaign_id, island_id, schema_version, lane_id, replica,
                        restart_seed, status, created_sequence, updated_sequence
                    ) VALUES (%s, 'F067-R1', 1, 'F067', 1, 7, 'runnable', 0, 0)
                    """,
                    (campaign_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO island_batches (
                        campaign_id, island_id, batch_sequence, schema_version,
                        status, batch_sha256, created_sequence, updated_sequence
                    ) VALUES (%s, 'F067-R1', 1, 1, 'open', %s, 0, 0)
                    """,
                    (campaign_id, "9" * 64),
                )
        yield PostgresContinuousCampaignStore(
            dsn="postgresql://test.invalid/aurora?sslmode=require",
            campaign_id=campaign_id,
            pool=pool,
        )
    finally:
        pool.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


def test_postgres_registers_one_work_item_for_100_concurrent_duplicates(postgres_store):
    from aurora.infra.sp500_megarun.dehb_continuous_models import (
        EvaluationCacheKeyV2,
        EvaluationProposalV2,
    )

    key = EvaluationCacheKeyV2.build(
        evaluator_sha256="a" * 64,
        numeric_profile_sha256="b" * 64,
        train_manifest_sha256="c" * 64,
        train_spy_sha256="d" * 64,
        campaign_contract_sha256="e" * 64,
        lane_id="F067",
        configuration={"lookback": 21},
        fidelity=12,
        fidelity_recipe_sha256="f" * 64,
        robustness_identity="base-seed:7",
    )

    def register(slot):
        proposal = EvaluationProposalV2.build(
            campaign_id=postgres_store.campaign_id,
            island_id="F067-R1",
            batch_sequence=1,
            batch_slot=slot,
            evaluation_key=key,
            dehb_job={"config_id": slot, "fidelity": 12},
        )
        return postgres_store.register_proposal(proposal)

    with ThreadPoolExecutor(max_workers=32) as executor:
        registrations = list(executor.map(register, [index % 4 for index in range(100)]))

    assert len({row.evaluation_id for row in registrations}) == 1
    assert sum(row.physical_work_created for row in registrations) == 1


def test_postgres_completion_is_visible_to_sequence_cutoff_and_health(postgres_store):
    from aurora.infra.sp500_megarun.dehb_continuous_models import (
        EvaluationCacheKeyV2,
        EvaluationProposalV2,
        EvaluationResultV2,
    )

    key = EvaluationCacheKeyV2.build(
        evaluator_sha256="a" * 64,
        numeric_profile_sha256="b" * 64,
        train_manifest_sha256="c" * 64,
        train_spy_sha256="d" * 64,
        campaign_contract_sha256="e" * 64,
        lane_id="F067",
        configuration={"lookback": 42},
        fidelity=27,
        fidelity_recipe_sha256="f" * 64,
        robustness_identity="base",
    )
    proposal = EvaluationProposalV2.build(
        campaign_id=postgres_store.campaign_id,
        island_id="F067-R1",
        batch_sequence=1,
        batch_slot=0,
        evaluation_key=key,
        dehb_job={"config_id": 0, "fidelity": 27},
    )
    postgres_store.register_proposal(proposal)
    session = postgres_store.claim_worker_session(
        pool_generation="smoke", github_run_id=1, github_job="worker", lease_seconds=60
    )
    lease = postgres_store.claim_evaluation(
        worker_session_id=session.worker_session_id, slot_index=0, lease_seconds=60
    )
    assert lease is not None
    result = EvaluationResultV2.build(
        key=key,
        result={
            "fitness": -0.2,
            "cost": 1.0,
            "info": {
                "validation_opened": False,
                "locked_opened": False,
                "full_fidelity": True,
                "train_feasible": True,
                "archive_key": [-0.2, -0.6, -0.1],
                "strategy_fingerprint": "1" * 64,
                "position_fingerprint": "2" * 64,
                "annualized_strategy_return": 0.2,
                "weekly_spy_beat_rate": 0.6,
            },
        },
    )
    postgres_store.complete_evaluation(lease, result)

    cutoff = postgres_store.latest_event_sequence()
    rows = postgres_store.result_rows(cutoff)
    health = postgres_store.health_snapshot()
    assert len(rows) == 1
    assert rows[0]["island_id"] == "F067-R1"
    assert rows[0]["validation_opened"] is False
    assert health["conflict_count"] == 0
    assert health["boundary_violations"] == 0
