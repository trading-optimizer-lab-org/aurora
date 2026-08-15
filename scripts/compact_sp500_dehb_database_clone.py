"""Repack a stopped continuous coordinator clone with LZ4 JSONB storage."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    database_url = os.environ.get(
        "SP500_DEHB_COORDINATOR_DATABASE_URL_NEXT", ""
    ).strip()
    if not database_url:
        raise RuntimeError("SP500_DEHB_COORDINATOR_DATABASE_URL_NEXT_MISSING")

    import psycopg
    from psycopg import sql

    with psycopg.connect(database_url) as connection:
        campaign = connection.execute(
            """
            SELECT validation_opened, locked_opened
            FROM campaigns WHERE campaign_id = %s
            """,
            (args.campaign_id,),
        ).fetchone()
        if campaign is None:
            raise RuntimeError("COMPACTION_CAMPAIGN_MISSING")
        if bool(campaign[0]) or bool(campaign[1]):
            raise RuntimeError("COMPACTION_BOUNDARY_OPENED")
        conflicts = int(
            connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM evaluations
                   WHERE campaign_id = %s AND state = 'conflict') +
                  (SELECT count(*) FROM strategy_evaluations
                   WHERE campaign_id = %s AND state = 'conflict')
                """,
                (args.campaign_id, args.campaign_id),
            ).fetchone()[0]
        )
        if conflicts:
            raise RuntimeError("COMPACTION_CONFLICT_PRESENT")
        before_bytes = int(
            connection.execute("SELECT pg_database_size(current_database())").fetchone()[
                0
            ]
        )
        columns = connection.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND data_type = 'jsonb'
            ORDER BY table_name, column_name
            """
        ).fetchall()

    tables = sorted({str(table) for table, _ in columns})
    for table in tables:
        table_columns = [
            str(column) for candidate, column in columns if str(candidate) == table
        ]
        with psycopg.connect(database_url) as connection, connection.transaction():
            connection.execute("SET LOCAL lock_timeout = '60s'")
            connection.execute(
                sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(
                    sql.Identifier(table)
                )
            )
            for column in table_columns:
                connection.execute(
                    sql.SQL(
                        "ALTER TABLE {} ALTER COLUMN {} SET COMPRESSION lz4"
                    ).format(sql.Identifier(table), sql.Identifier(column))
                )
                connection.execute(
                    sql.SQL(
                        "UPDATE {} SET {} = ({}::text)::jsonb WHERE {} IS NOT NULL"
                    ).format(
                        sql.Identifier(table),
                        sql.Identifier(column),
                        sql.Identifier(column),
                        sql.Identifier(column),
                    )
                )
            connection.execute(
                sql.SQL("ALTER TABLE {} ENABLE TRIGGER USER").format(
                    sql.Identifier(table)
                )
            )
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("VACUUM (FULL, ANALYZE) {}").format(sql.Identifier(table))
            )

    with psycopg.connect(database_url) as connection:
        disabled_triggers = int(
            connection.execute(
                """
                SELECT count(*) FROM pg_trigger
                WHERE NOT tgisinternal AND tgenabled <> 'O'
                """
            ).fetchone()[0]
        )
        if disabled_triggers:
            raise RuntimeError("COMPACTION_TRIGGER_NOT_ENABLED")
        after_bytes = int(
            connection.execute("SELECT pg_database_size(current_database())").fetchone()[
                0
            ]
        )
    report = {
        "schema_version": 1,
        "campaign_id": args.campaign_id,
        "compression": "lz4",
        "jsonb_table_count": len(tables),
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
        "saved_bytes": before_bytes - after_bytes,
        "validation_opened": False,
        "locked_opened": False,
        "conflict_count": 0,
        "all_user_triggers_enabled": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
