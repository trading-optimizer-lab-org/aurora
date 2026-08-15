"""Copy only live DEHB state into a fresh PostgreSQL coordinator database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_megarun.dehb_continuous_schema import apply_schema


STATE_TABLES = (
    "campaigns",
    "islands",
    "reducer_snapshots",
    "robustness_evidence",
)
EMPTY_OPERATIONAL_TABLES = (
    "campaign_leases",
    "island_batches",
    "evaluations",
    "proposals",
    "evaluation_subscribers",
    "work_items",
    "worker_sessions",
    "worker_slot_leases",
    "strategy_evaluations",
    "results",
    "audit_events",
    "import_receipts",
)


def _count(connection, table: str, campaign_id: str) -> int:
    return int(
        connection.execute(
            f"SELECT count(*) FROM {table} WHERE campaign_id = %s",
            (campaign_id,),
        ).fetchone()[0]
    )


def main() -> int:
    require_github_only_execution("SP500_DEHB_SEGMENT_LIVE_STATE_V1")
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--source-url-env", default="SP500_DEHB_COORDINATOR_DATABASE_URL")
    parser.add_argument(
        "--target-url-env", default="SP500_DEHB_COORDINATOR_DATABASE_URL_NEXT"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_url = os.environ.get(args.source_url_env, "").strip()
    target_url = os.environ.get(args.target_url_env, "").strip()
    if not source_url or not target_url:
        raise RuntimeError("CONTINUOUS_SEGMENT_DATABASE_URL_MISSING")
    if source_url == target_url:
        raise RuntimeError("CONTINUOUS_SEGMENT_DISTINCT_DATABASES_REQUIRED")

    import psycopg

    with psycopg.connect(source_url) as source, psycopg.connect(target_url) as target:
        campaign = source.execute(
            """
            SELECT state, scientific_contract_sha256, launch_contract_sha256,
                   code_commit_sha, train_manifest_sha256, train_spy_sha256,
                   numeric_profile_sha256, validation_opened, locked_opened
            FROM campaigns WHERE campaign_id = %s
            """,
            (args.campaign_id,),
        ).fetchone()
        if campaign is None:
            raise RuntimeError("CONTINUOUS_SEGMENT_CAMPAIGN_NOT_FOUND")
        if str(campaign[0]) != "searching":
            raise RuntimeError("CONTINUOUS_SEGMENT_CAMPAIGN_NOT_SEARCHING")
        if bool(campaign[7]) or bool(campaign[8]):
            raise RuntimeError("CONTINUOUS_SEGMENT_BOUNDARY_OPEN")
        source_health = source.execute(
            """
            SELECT
              (SELECT count(*) FROM campaign_leases
               WHERE campaign_id = %s AND lease_expires_at >= clock_timestamp()),
              (SELECT count(*) FROM worker_sessions
               WHERE campaign_id = %s AND state <> 'closed'),
              (SELECT count(*) FROM island_batches
               WHERE campaign_id = %s AND status = 'open'),
              (SELECT count(*) FROM evaluations
               WHERE campaign_id = %s AND state = 'conflict') +
              (SELECT count(*) FROM strategy_evaluations
               WHERE campaign_id = %s AND state = 'conflict')
            """,
            (args.campaign_id,) * 5,
        ).fetchone()
        if source_health is None or any(int(value) for value in source_health):
            raise RuntimeError("CONTINUOUS_SEGMENT_SOURCE_NOT_QUIESCENT")

        apply_schema(target)
        target_existing = int(
            target.execute("SELECT count(*) FROM campaigns").fetchone()[0]
        )
        if target_existing:
            raise RuntimeError("CONTINUOUS_SEGMENT_TARGET_NOT_EMPTY")

        copied: dict[str, int] = {}
        for table in STATE_TABLES:
            rows = source.execute(
                f"SELECT row_to_json(t)::text FROM {table} t "
                "WHERE campaign_id = %s ORDER BY 1",
                (args.campaign_id,),
            ).fetchall()
            if rows:
                target.executemany(
                    f"INSERT INTO {table} SELECT * FROM "
                    f"json_populate_record(NULL::{table}, %s::json)",
                    rows,
                )
            copied[table] = len(rows)

        source_sequence = int(
            source.execute("SELECT last_value FROM continuous_event_sequence").fetchone()[0]
        )
        target.execute(
            "SELECT setval('continuous_event_sequence', %s, true)",
            (source_sequence,),
        )
        for table, column in (
            ("reducer_snapshots", "snapshot_id"),
            ("robustness_evidence", "robustness_evidence_id"),
        ):
            maximum = int(
                target.execute(f"SELECT coalesce(max({column}), 0) FROM {table}").fetchone()[0]
            )
            if maximum:
                sequence_name = target.execute(
                    "SELECT pg_get_serial_sequence(%s, %s)", (table, column)
                ).fetchone()[0]
                target.execute(
                    "SELECT setval(%s::regclass, %s::bigint, true)",
                    (sequence_name, maximum),
                )
        target.commit()

        if copied["campaigns"] != 1 or copied["islands"] != 720:
            raise RuntimeError("CONTINUOUS_SEGMENT_STATE_INCOMPLETE")
        target_campaign = target.execute(
            """
            SELECT state, scientific_contract_sha256, launch_contract_sha256,
                   code_commit_sha, train_manifest_sha256, train_spy_sha256,
                   numeric_profile_sha256, validation_opened, locked_opened
            FROM campaigns WHERE campaign_id = %s
            """,
            (args.campaign_id,),
        ).fetchone()
        if target_campaign != campaign:
            raise RuntimeError("CONTINUOUS_SEGMENT_CAMPAIGN_IDENTITY_MISMATCH")
        nonempty = {
            table: _count(target, table, args.campaign_id)
            for table in EMPTY_OPERATIONAL_TABLES
            if _count(target, table, args.campaign_id)
        }
        if nonempty:
            raise RuntimeError("CONTINUOUS_SEGMENT_OPERATIONAL_TABLE_NOT_EMPTY")
        target_sequence = int(
            target.execute("SELECT last_value FROM continuous_event_sequence").fetchone()[0]
        )
        if target_sequence != source_sequence:
            raise RuntimeError("CONTINUOUS_SEGMENT_SEQUENCE_MISMATCH")

        report = {
            "schema_version": 1,
            "campaign_id": args.campaign_id,
            "copied_state_rows": copied,
            "source_sequence": source_sequence,
            "target_sequence": target_sequence,
            "archived_evaluations": _count(source, "evaluations", args.campaign_id),
            "archived_results": _count(source, "results", args.campaign_id),
            "archived_strategies": _count(
                source, "strategy_evaluations", args.campaign_id
            ),
            "target_database_size_bytes": int(
                target.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            ),
            "validation_opened": False,
            "locked_opened": False,
        }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
