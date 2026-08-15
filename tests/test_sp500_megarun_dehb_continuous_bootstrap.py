from __future__ import annotations

from collections import Counter
from pathlib import Path


def campaign():
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )

    return load_and_validate_campaign_contract(
        Path(__file__).resolve().parents[1] / "config" / "sp500_megarun_dehb_campaign_v1.json"
    )


def test_bootstrap_records_cover_240_lanes_and_three_independent_replicas():
    from aurora.infra.sp500_megarun.dehb_continuous_bootstrap import (
        build_island_bootstrap_records,
    )

    records = build_island_bootstrap_records(campaign())
    lanes = Counter(record.lane_id for record in records)

    assert len(records) == 720
    assert lanes == {f"F{lane:03d}": 3 for lane in range(1, 241)}
    assert {record.replica for record in records} == {1, 2, 3}
    assert len({record.island_id for record in records}) == 720
    assert all(record.validation_opened is False for record in records)
    assert all(record.locked_opened is False for record in records)


def test_pool_generation_has_three_240_entry_shards_and_360_concurrency():
    from aurora.infra.sp500_megarun.dehb_continuous_bootstrap import (
        build_worker_pool_matrices,
    )

    matrices = build_worker_pool_matrices("pool-0001")

    assert set(matrices) == {"A", "B", "C"}
    assert {shard: len(entries["include"]) for shard, entries in matrices.items()} == {
        "A": 240,
        "B": 240,
        "C": 240,
    }
    all_entries = [entry for shard in matrices.values() for entry in shard["include"]]
    assert len({entry["worker_lifetime_id"] for entry in all_entries}) == 720
    assert all(entry["pool_generation"] == "pool-0001" for entry in all_entries)
    assert all(entry["executor_slots"] == 4 for entry in all_entries)
    assert all(entry["lifetime_minutes"] == 300 for entry in all_entries)


def test_pool_generation_emits_valid_github_matrix_payloads():
    from aurora.infra.sp500_megarun.dehb_continuous_bootstrap import (
        build_worker_pool_matrices,
    )

    matrices = build_worker_pool_matrices("pool-0001")

    # GitHub accepts ``include`` in a matrix payload, but scalar execution
    # controls such as max-parallel belong to ``strategy``, not ``matrix``.
    assert all(set(matrix) == {"include"} for matrix in matrices.values())


class RecordingCursor:
    def __init__(self):
        self.executed = []
        self.many = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, parameters=None):
        self.executed.append((sql, parameters))

    def executemany(self, sql, parameters):
        self.many.append((sql, list(parameters)))


class RecordingConnection:
    def __init__(self):
        self.recording_cursor = RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.recording_cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_bootstrap_inserts_one_closed_campaign_and_exactly_720_islands():
    from aurora.infra.sp500_megarun.dehb_continuous_bootstrap import bootstrap_campaign

    connection = RecordingConnection()
    applied = []
    receipt = bootstrap_campaign(
        connection,
        campaign_id="campaign-1",
        campaign=campaign(),
        launch_contract_sha256="1" * 64,
        code_commit_sha="2" * 40,
        numeric_profile_sha256="3" * 64,
        schema_applier=lambda value: applied.append(value),
    )

    assert applied == [connection]
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert len(connection.recording_cursor.many) == 1
    assert len(connection.recording_cursor.many[0][1]) == 720
    assert receipt.island_count == 720
    assert receipt.validation_opened is False
    assert receipt.locked_opened is False
