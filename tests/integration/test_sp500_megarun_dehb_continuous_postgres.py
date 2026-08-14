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
    schema_dsn = f"{dsn} options='-c search_path={schema}'"
    pool = pool_module.ConnectionPool(schema_dsn, min_size=4, max_size=32, open=True)
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
                    ) VALUES (%s, 'F067-R0', 1, 'F067', 0, 7, 'runnable', 0, 0)
                    """,
                    (campaign_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO island_batches (
                        campaign_id, island_id, batch_sequence, schema_version,
                        status, created_sequence, updated_sequence
                    ) VALUES (%s, 'F067-R0', 1, 1, 'open', 0, 0)
                    """,
                    (campaign_id,),
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
            island_id="F067-R0",
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
