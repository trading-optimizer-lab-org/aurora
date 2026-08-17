from __future__ import annotations

import json

import pytest


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def evaluation_key():
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationCacheKeyV2

    return EvaluationCacheKeyV2.build(
        evaluator_sha256=SHA_A,
        numeric_profile_sha256=SHA_B,
        train_manifest_sha256=SHA_C,
        train_spy_sha256=SHA_D,
        campaign_contract_sha256=SHA_E,
        lane_id="F067",
        configuration={"lookback": 21},
        fidelity=12,
        fidelity_recipe_sha256=SHA_F,
        robustness_identity="base-seed:7",
    )


def result_payload():
    return {
        "fitness": -1.25,
        "cost": 0.4,
        "info": {
            "lane_id": "F067",
            "config": {"lookback": 21},
            "archive_key": [0.0, -0.2, -0.6, -0.1],
            "position_fingerprint": SHA_B,
            "strategy_fingerprint": SHA_C,
            "validation_opened": False,
            "locked_opened": False,
        },
    }


def identity():
    from aurora.infra.sp500_megarun.dehb_continuous_archive import ArchiveIdentityV1

    return ArchiveIdentityV1(
        campaign_id="campaign-1",
        scientific_contract_sha256=SHA_E,
        code_commit_sha="1" * 40,
        train_manifest_sha256=SHA_C,
        train_spy_sha256=SHA_D,
        numeric_profile_sha256=SHA_B,
    )


def test_sqlite_archive_round_trips_evaluations_strategies_and_reducer_rows(tmp_path):
    from aurora.infra.sp500_megarun.dehb_continuous_archive import (
        SqliteHistoricalCacheV1,
        write_sqlite_historical_cache,
    )
    from aurora.infra.sp500_megarun.dehb_continuous_models import (
        EvaluationResultV2,
        StrategyEvaluationKeyV1,
    )
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        scientific_result_sha256,
    )

    key = evaluation_key()
    result = result_payload()
    strategy_key = StrategyEvaluationKeyV1.build(
        evaluation_key=key,
        positions_sha256=SHA_B,
    )
    database = tmp_path / "history.sqlite"
    manifest = tmp_path / "history.manifest.json"
    reducer_row = {
        **result["info"],
        "created_sequence": 11,
        "island_id": "F067-R1",
        "batch_sequence": 3,
        "batch_slot": 2,
        "replicate": 1,
        "restart_seed": 7,
        "validation_opened": False,
        "locked_opened": False,
    }

    receipt = write_sqlite_historical_cache(
        database_path=database,
        manifest_path=manifest,
        identity=identity(),
        evaluation_entries=[
            (key, EvaluationResultV2.build(key=key, result=result))
        ],
        strategy_entries=[
            (strategy_key, scientific_result_sha256(result), result)
        ],
        result_rows=[reducer_row],
    )
    cache = SqliteHistoricalCacheV1(
        database_path=database,
        manifest_path=manifest,
        expected_identity=identity(),
    )

    assert receipt.evaluation_count == 1
    assert receipt.strategy_count == 1
    assert receipt.result_row_count == 1
    assert cache.get_evaluation(key) == result
    assert cache.get_strategy(strategy_key) == result
    assert cache.result_rows() == [reducer_row]


def test_sqlite_archive_rejects_conflicting_duplicate_key(tmp_path):
    from aurora.infra.sp500_megarun.dehb_continuous_archive import (
        HistoricalArchiveConflictError,
        write_sqlite_historical_cache,
    )
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationResultV2

    key = evaluation_key()
    first = result_payload()
    second = json.loads(json.dumps(first))
    second["fitness"] = -1.24

    with pytest.raises(
        HistoricalArchiveConflictError,
        match="CONTINUOUS_ARCHIVE_EVALUATION_CONFLICT",
    ):
        write_sqlite_historical_cache(
            database_path=tmp_path / "history.sqlite",
            manifest_path=tmp_path / "history.manifest.json",
            identity=identity(),
            evaluation_entries=[
                (key, EvaluationResultV2.build(key=key, result=first)),
                (key, EvaluationResultV2.build(key=key, result=second)),
            ],
            strategy_entries=[],
            result_rows=[],
        )


def test_sqlite_archive_rejects_file_tampering(tmp_path):
    from aurora.infra.sp500_megarun.dehb_continuous_archive import (
        HistoricalArchiveIntegrityError,
        SqliteHistoricalCacheV1,
        write_sqlite_historical_cache,
    )

    database = tmp_path / "history.sqlite"
    manifest = tmp_path / "history.manifest.json"
    write_sqlite_historical_cache(
        database_path=database,
        manifest_path=manifest,
        identity=identity(),
        evaluation_entries=[],
        strategy_entries=[],
        result_rows=[],
    )
    database.write_bytes(database.read_bytes() + b"tampered")

    with pytest.raises(
        HistoricalArchiveIntegrityError,
        match="CONTINUOUS_ARCHIVE_DATABASE_HASH_MISMATCH",
    ):
        SqliteHistoricalCacheV1(
            database_path=database,
            manifest_path=manifest,
            expected_identity=identity(),
        )
