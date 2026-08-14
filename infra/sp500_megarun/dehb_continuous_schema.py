"""PostgreSQL schema for the continuous SP500 DEHB campaign."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Sequence


SCHEMA_VERSION = 1
_SCHEMA_LOCK_ID = 5994341454564865352


@dataclass(frozen=True)
class SchemaReceiptV1:
    """Deterministic receipt for one successful schema application."""

    schema_version: int
    statement_count: int
    schema_sha256: str


def schema_statements() -> Sequence[str]:
    """Return idempotent DDL in foreign-key-safe execution order."""

    return (
        "CREATE SEQUENCE IF NOT EXISTS continuous_event_sequence AS bigint",
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            campaign_id text PRIMARY KEY,
            schema_version integer NOT NULL,
            state text NOT NULL CHECK (state IN
                ('bootstrapping', 'searching', 'freezing', 'frozen',
                 'halted_conflict', 'halted_boundary', 'halted_integrity')),
            scientific_contract_sha256 char(64) NOT NULL,
            launch_contract_sha256 char(64) NOT NULL,
            code_commit_sha char(40) NOT NULL,
            train_manifest_sha256 char(64) NOT NULL,
            train_spy_sha256 char(64) NOT NULL,
            numeric_profile_sha256 char(64) NOT NULL,
            validation_opened boolean NOT NULL DEFAULT false
                CHECK (validation_opened = false),
            locked_opened boolean NOT NULL DEFAULT false
                CHECK (locked_opened = false),
            next_event_sequence bigint NOT NULL DEFAULT 1,
            created_sequence bigint NOT NULL DEFAULT 0,
            updated_sequence bigint NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS campaign_leases (
            campaign_id text PRIMARY KEY REFERENCES campaigns(campaign_id),
            schema_version integer NOT NULL,
            owner_token text NOT NULL,
            lease_expires_at timestamptz NOT NULL,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS islands (
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            island_id text NOT NULL,
            schema_version integer NOT NULL,
            lane_id char(4) NOT NULL,
            replica integer NOT NULL CHECK (replica BETWEEN 1 AND 3),
            restart_seed bigint NOT NULL,
            status text NOT NULL CHECK (status IN ('runnable', 'waiting', 'plateau', 'frozen')),
            next_batch_sequence bigint NOT NULL DEFAULT 1,
            checkpoint_bytes bytea,
            checkpoint_sha256 char(64),
            prior_checkpoint_sha256 char(64),
            runtime_state jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (campaign_id, island_id),
            UNIQUE (campaign_id, lane_id, replica)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS island_batches (
            campaign_id text NOT NULL,
            island_id text NOT NULL,
            batch_sequence bigint NOT NULL,
            schema_version integer NOT NULL,
            status text NOT NULL CHECK (status IN ('open', 'resolved', 'applied')),
            batch_sha256 char(64) NOT NULL,
            checkpoint_before_sha256 char(64),
            checkpoint_after_sha256 char(64),
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (campaign_id, island_id, batch_sequence),
            FOREIGN KEY (campaign_id, island_id)
                REFERENCES islands(campaign_id, island_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS evaluations (
            evaluation_id bigserial PRIMARY KEY,
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            schema_version integer NOT NULL,
            cache_key_sha256 char(64) NOT NULL,
            key_payload jsonb NOT NULL,
            state text NOT NULL CHECK (state IN ('ready', 'leased', 'positioned', 'completed', 'conflict')),
            result_id bigint,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, cache_key_sha256)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id bigserial PRIMARY KEY,
            campaign_id text NOT NULL,
            island_id text NOT NULL,
            batch_sequence bigint NOT NULL,
            batch_slot integer NOT NULL CHECK (batch_slot BETWEEN 0 AND 3),
            schema_version integer NOT NULL,
            evaluation_id bigint NOT NULL REFERENCES evaluations(evaluation_id),
            dehb_job jsonb NOT NULL,
            result_sha256 char(64),
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, island_id, batch_sequence, batch_slot),
            FOREIGN KEY (campaign_id, island_id, batch_sequence)
                REFERENCES island_batches(campaign_id, island_id, batch_sequence)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS evaluation_subscribers (
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            evaluation_id bigint NOT NULL REFERENCES evaluations(evaluation_id),
            proposal_id bigint NOT NULL REFERENCES proposals(proposal_id),
            schema_version integer NOT NULL,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (campaign_id, evaluation_id, proposal_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS work_items (
            work_item_id bigserial PRIMARY KEY,
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            evaluation_id bigint NOT NULL REFERENCES evaluations(evaluation_id),
            schema_version integer NOT NULL,
            priority integer NOT NULL DEFAULT 0,
            state text NOT NULL CHECK (state IN ('ready', 'leased', 'completed')),
            lease_token text,
            leased_by_session_id text,
            leased_by_slot integer,
            lease_expires_at timestamptz,
            attempt_count integer NOT NULL DEFAULT 0,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, evaluation_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS worker_sessions (
            worker_session_id text PRIMARY KEY,
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            schema_version integer NOT NULL,
            pool_generation text NOT NULL,
            github_run_id bigint NOT NULL,
            github_job text NOT NULL,
            permit_number integer NOT NULL CHECK (permit_number BETWEEN 1 AND 360),
            state text NOT NULL CHECK (state IN ('warming', 'active', 'draining', 'closed')),
            lease_expires_at timestamptz NOT NULL,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, permit_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS worker_slot_leases (
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            worker_session_id text NOT NULL REFERENCES worker_sessions(worker_session_id),
            slot_index integer NOT NULL CHECK (slot_index BETWEEN 0 AND 3),
            schema_version integer NOT NULL,
            lease_token text NOT NULL,
            lease_expires_at timestamptz NOT NULL,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, worker_session_id, slot_index)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS strategy_evaluations (
            strategy_evaluation_id bigserial PRIMARY KEY,
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            schema_version integer NOT NULL,
            strategy_key_sha256 char(64) NOT NULL,
            key_payload jsonb NOT NULL,
            owner_evaluation_id bigint NOT NULL REFERENCES evaluations(evaluation_id),
            state text NOT NULL CHECK (state IN ('owned', 'completed', 'conflict')),
            result_sha256 char(64),
            result_payload jsonb,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, strategy_key_sha256)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS results (
            result_id bigserial PRIMARY KEY,
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            schema_version integer NOT NULL,
            evaluation_id bigint NOT NULL REFERENCES evaluations(evaluation_id),
            result_sha256 char(64) NOT NULL,
            result_payload jsonb NOT NULL,
            evaluation_origin text NOT NULL,
            physical_runtime_seconds double precision NOT NULL DEFAULT 0,
            validation_opened boolean NOT NULL DEFAULT false
                CHECK (validation_opened = false),
            locked_opened boolean NOT NULL DEFAULT false
                CHECK (locked_opened = false),
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, evaluation_id),
            UNIQUE (campaign_id, result_sha256, evaluation_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            event_sequence bigint NOT NULL,
            schema_version integer NOT NULL,
            event_type text NOT NULL,
            event_payload jsonb NOT NULL,
            prior_event_sha256 char(64),
            event_sha256 char(64) NOT NULL,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (campaign_id, event_sequence),
            UNIQUE (campaign_id, event_sha256)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reducer_snapshots (
            snapshot_id bigserial PRIMARY KEY,
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            schema_version integer NOT NULL,
            cutoff_sequence bigint NOT NULL,
            snapshot_sha256 char(64) NOT NULL,
            snapshot_payload jsonb NOT NULL,
            validation_opened boolean NOT NULL DEFAULT false
                CHECK (validation_opened = false),
            locked_opened boolean NOT NULL DEFAULT false
                CHECK (locked_opened = false),
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, cutoff_sequence),
            UNIQUE (campaign_id, snapshot_sha256)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS import_receipts (
            import_receipt_id bigserial PRIMARY KEY,
            campaign_id text NOT NULL REFERENCES campaigns(campaign_id),
            schema_version integer NOT NULL,
            source_run_id bigint NOT NULL,
            source_artifact text NOT NULL,
            source_artifact_sha256 char(64) NOT NULL,
            receipt_sha256 char(64) NOT NULL,
            receipt_payload jsonb NOT NULL,
            created_sequence bigint NOT NULL,
            updated_sequence bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (campaign_id, source_run_id, source_artifact_sha256),
            UNIQUE (campaign_id, receipt_sha256)
        )
        """,
        """
        CREATE OR REPLACE FUNCTION reject_continuous_result_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'CONTINUOUS_RESULTS_IMMUTABLE';
        END
        $$
        """,
        "DROP TRIGGER IF EXISTS continuous_results_immutable ON results",
        """
        CREATE TRIGGER continuous_results_immutable
        BEFORE UPDATE OR DELETE ON results
        FOR EACH ROW EXECUTE FUNCTION reject_continuous_result_mutation()
        """,
        """
        CREATE INDEX IF NOT EXISTS work_items_claim_order
        ON work_items (campaign_id, state, priority DESC, work_item_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS work_items_lease_expiry
        ON work_items (campaign_id, lease_expires_at)
        WHERE state = 'leased'
        """,
    )


def role_statements() -> Sequence[str]:
    """Return role creation and grants for an administrator bootstrap."""

    return (
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sp500_dehb_coordinator') THEN
                CREATE ROLE sp500_dehb_coordinator NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sp500_dehb_worker') THEN
                CREATE ROLE sp500_dehb_worker NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sp500_dehb_reducer') THEN
                CREATE ROLE sp500_dehb_reducer NOLOGIN;
            END IF;
        END $$
        """,
        """
        DO $$ BEGIN
            EXECUTE format(
                'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I TO sp500_dehb_coordinator',
                current_schema()
            );
            EXECUTE format(
                'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %I TO sp500_dehb_coordinator',
                current_schema()
            );
        END $$
        """,
        "GRANT SELECT, INSERT, UPDATE ON work_items TO sp500_dehb_worker",
        "GRANT SELECT, INSERT, UPDATE ON worker_sessions TO sp500_dehb_worker",
        "GRANT SELECT, INSERT, UPDATE ON worker_slot_leases TO sp500_dehb_worker",
        "GRANT SELECT, INSERT ON results TO sp500_dehb_worker",
        "GRANT SELECT, INSERT, UPDATE ON strategy_evaluations TO sp500_dehb_worker",
        "GRANT USAGE, SELECT ON SEQUENCE continuous_event_sequence TO sp500_dehb_worker",
        """
        DO $$ BEGIN
            EXECUTE format(
                'GRANT SELECT ON ALL TABLES IN SCHEMA %I TO sp500_dehb_reducer',
                current_schema()
            );
        END $$
        """,
        "GRANT INSERT ON reducer_snapshots TO sp500_dehb_reducer",
    )


def _schema_sha256(statements: Sequence[str]) -> str:
    normalized = "\n;\n".join(" ".join(statement.split()) for statement in statements)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def apply_schema(connection: Any) -> SchemaReceiptV1:
    """Apply the schema under one transaction-scoped advisory lock."""

    statements = schema_statements()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_ID,))
            for statement in statements:
                cursor.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return SchemaReceiptV1(
        schema_version=SCHEMA_VERSION,
        statement_count=len(statements),
        schema_sha256=_schema_sha256(statements),
    )


__all__ = [
    "SCHEMA_VERSION",
    "SchemaReceiptV1",
    "apply_schema",
    "role_statements",
    "schema_statements",
]
