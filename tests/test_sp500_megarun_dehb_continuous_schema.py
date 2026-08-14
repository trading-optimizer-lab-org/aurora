from __future__ import annotations

import re


EXPECTED_TABLES = {
    "campaigns",
    "campaign_leases",
    "islands",
    "island_batches",
    "proposals",
    "evaluations",
    "evaluation_subscribers",
    "work_items",
    "worker_sessions",
    "worker_slot_leases",
    "strategy_evaluations",
    "results",
    "audit_events",
    "reducer_snapshots",
    "import_receipts",
}


def _normalized_sql():
    from aurora.infra.sp500_megarun.dehb_continuous_schema import schema_statements

    return " ".join(" ".join(schema_statements()).lower().split())


def test_schema_creates_every_durable_component():
    sql = _normalized_sql()

    created = set(re.findall(r"create table if not exists ([a-z_]+)", sql))
    assert created == EXPECTED_TABLES


def test_schema_uses_nonblocking_database_sequence_for_event_order():
    sql = _normalized_sql()

    assert "create sequence if not exists continuous_event_sequence" in sql


def test_schema_enforces_global_evaluation_and_position_uniqueness():
    sql = _normalized_sql()

    assert "unique (campaign_id, cache_key_sha256)" in sql
    assert "unique (campaign_id, strategy_key_sha256)" in sql
    assert "unique (campaign_id, island_id, batch_sequence, batch_slot)" in sql
    strategy_section = sql.split("create table if not exists strategy_evaluations", 1)[1]
    strategy_section = strategy_section.split("create table if not exists results", 1)[0]
    assert "result_payload jsonb" in strategy_section


def test_schema_makes_later_partition_flags_false_only():
    sql = _normalized_sql()

    assert sql.count("validation_opened boolean not null default false") >= 2
    assert sql.count("check (validation_opened = false)") >= 2
    assert sql.count("locked_opened boolean not null default false") >= 2
    assert sql.count("check (locked_opened = false)") >= 2


def test_schema_caps_worker_sessions_and_executor_slots():
    sql = _normalized_sql()

    assert "check (permit_number between 1 and 360)" in sql
    assert "check (slot_index between 0 and 3)" in sql
    assert "unique (campaign_id, permit_number)" in sql
    assert "unique (campaign_id, worker_session_id, slot_index)" in sql


def test_schema_persists_island_runtime_and_open_batch_recovery_state():
    sql = _normalized_sql()
    islands = sql.split("create table if not exists islands", 1)[1]
    islands = islands.split("create table if not exists island_batches", 1)[0]
    batches = sql.split("create table if not exists island_batches", 1)[1]
    batches = batches.split("create table if not exists evaluations", 1)[0]

    assert "runtime_state jsonb not null" in islands
    assert "check (replica between 1 and 3)" in islands
    assert "batch_sha256 char(64) not null" in batches


def test_role_contract_separates_coordinator_worker_and_reducer():
    from aurora.infra.sp500_megarun.dehb_continuous_schema import role_statements

    sql = " ".join(" ".join(role_statements()).lower().split())
    assert "sp500_dehb_coordinator" in sql
    assert "sp500_dehb_worker" in sql
    assert "sp500_dehb_reducer" in sql
    assert "grant select, insert, update on work_items to sp500_dehb_worker" in sql
    assert "grant select on all tables in schema %i to sp500_dehb_reducer" in sql
    assert "grant all privileges on all tables in schema %i to sp500_dehb_coordinator" in sql


def test_role_contract_quotes_the_runtime_schema_as_an_identifier():
    from aurora.infra.sp500_megarun.dehb_continuous_schema import role_statements

    raw = "\n".join(role_statements()).lower()
    assert "schema current_schema to" not in raw
    assert "'grant all privileges on all tables in schema %i" in raw
    assert "'grant select on all tables in schema %i" in raw
    assert raw.count("current_schema()") == 3


class _RecordingCursor:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))


class _RecordingConnection:
    def __init__(self):
        self.cursor_instance = _RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_apply_schema_is_one_locked_transaction_with_hash_receipt():
    from aurora.infra.sp500_megarun.dehb_continuous_schema import (
        SCHEMA_VERSION,
        apply_schema,
        schema_statements,
    )

    connection = _RecordingConnection()
    receipt = apply_schema(connection)

    executed = connection.cursor_instance.statements
    assert executed[0][0] == "SELECT pg_advisory_xact_lock(%s)"
    assert len(executed) == len(schema_statements()) + 1
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert receipt.schema_version == SCHEMA_VERSION == 1
    assert receipt.statement_count == len(schema_statements())
    assert len(receipt.schema_sha256) == 64


def test_apply_schema_rolls_back_on_first_database_error():
    from aurora.infra.sp500_megarun.dehb_continuous_schema import apply_schema

    class FailingCursor(_RecordingCursor):
        def execute(self, statement, parameters=None):
            super().execute(statement, parameters)
            if len(self.statements) == 3:
                raise RuntimeError("database rejected statement")

    connection = _RecordingConnection()
    connection.cursor_instance = FailingCursor()

    try:
        apply_schema(connection)
    except RuntimeError as exc:
        assert str(exc) == "database rejected statement"
    else:
        raise AssertionError("schema failure must propagate")

    assert connection.commits == 0
    assert connection.rollbacks == 1
