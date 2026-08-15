"""Repack a stopped continuous coordinator clone with LZ4 JSONB storage."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
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
    from psycopg.types.json import Jsonb

    from aurora.infra.sp500_megarun.dehb_continuous_store import (
        decode_checkpoint_bytes,
        decode_storage_json,
        encode_checkpoint_bytes,
        encode_storage_json,
    )

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

    tables = sorted({str(table) for table, _ in columns} | {"islands"})
    encoded_json_rows = 0
    encoded_checkpoint_rows = 0
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
                rows = connection.execute(
                    sql.SQL("SELECT ctid::text, {} FROM {} WHERE {} IS NOT NULL").format(
                        sql.Identifier(column),
                        sql.Identifier(table),
                        sql.Identifier(column),
                    )
                ).fetchall()
                updates = []
                for row_id, payload in rows:
                    if not isinstance(payload, Mapping):
                        raise RuntimeError("COMPACTION_JSON_MAPPING_REQUIRED")
                    decoded = decode_storage_json(payload)
                    encoded = encode_storage_json(decoded)
                    if encoded != payload:
                        updates.append((Jsonb(encoded), str(row_id)))
                if updates:
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            sql.SQL("UPDATE {} SET {} = %s WHERE ctid = %s::tid").format(
                                sql.Identifier(table), sql.Identifier(column)
                            ),
                            updates,
                        )
                    encoded_json_rows += len(updates)
            if table == "islands":
                checkpoints = connection.execute(
                    """
                    SELECT ctid::text, checkpoint_bytes FROM islands
                    WHERE checkpoint_bytes IS NOT NULL
                    """
                ).fetchall()
                updates = []
                for row_id, checkpoint in checkpoints:
                    decoded = decode_checkpoint_bytes(bytes(checkpoint))
                    encoded = encode_checkpoint_bytes(decoded)
                    if encoded != bytes(checkpoint):
                        updates.append((encoded, str(row_id)))
                if updates:
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            "UPDATE islands SET checkpoint_bytes = %s WHERE ctid = %s::tid",
                            updates,
                        )
                    encoded_checkpoint_rows += len(updates)
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
        "encoded_json_rows": encoded_json_rows,
        "encoded_checkpoint_rows": encoded_checkpoint_rows,
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
