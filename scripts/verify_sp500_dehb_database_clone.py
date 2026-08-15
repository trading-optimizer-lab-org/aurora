"""Compare every campaign row after a stopped coordinator database clone."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from aurora.infra.sp500_megarun.dehb_continuous_migration import (
    canonical_rows_sha256,
    compare_clone_inventories,
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name}_MISSING")
    return value


def _inventory(connection: Any, campaign_id: str) -> dict[str, Any]:
    from psycopg import sql

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT state, code_commit_sha, validation_opened, locked_opened
            FROM campaigns WHERE campaign_id = %s
            """,
            (campaign_id,),
        )
        campaign = cursor.fetchone()
        if campaign is None:
            raise RuntimeError("CLONE_CAMPAIGN_MISSING")
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name = 'campaign_id'
            ORDER BY table_name
            """
        )
        tables = [str(row[0]) for row in cursor.fetchall()]

    fingerprints: dict[str, dict[str, Any]] = {}
    for index, table in enumerate(tables):
        query = sql.SQL(
            "SELECT to_jsonb(t)::text FROM {} AS t "
            "WHERE campaign_id = %s ORDER BY to_jsonb(t)::text"
        ).format(sql.Identifier(table))
        row_count = 0
        with connection.cursor(name=f"clone_inventory_{index}") as cursor:
            cursor.execute(query, (campaign_id,))

            def rows():
                nonlocal row_count
                for row in cursor:
                    row_count += 1
                    yield str(row[0])

            rows_sha256 = canonical_rows_sha256(rows())
        fingerprints[table] = {
            "row_count": row_count,
            "rows_sha256": rows_sha256,
        }

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              (SELECT count(*) FROM evaluations
               WHERE campaign_id = %s AND state = 'conflict') +
              (SELECT count(*) FROM strategy_evaluations
               WHERE campaign_id = %s AND state = 'conflict'),
              (SELECT count(*) FROM results
               WHERE campaign_id = %s AND (validation_opened OR locked_opened)) +
              (SELECT count(*) FROM robustness_evidence
               WHERE campaign_id = %s AND (validation_opened OR locked_opened)),
              pg_database_size(current_database())
            """,
            (campaign_id,) * 4,
        )
        conflicts, boundary_violations, database_size = cursor.fetchone()
    return {
        "campaign_id": campaign_id,
        "campaign_state": str(campaign[0]),
        "code_commit_sha": str(campaign[1]),
        "validation_opened": bool(campaign[2]),
        "locked_opened": bool(campaign[3]),
        "conflict_count": int(conflicts),
        "boundary_violations": int(boundary_violations),
        "database_size_bytes": int(database_size),
        "tables": fingerprints,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import psycopg

    source_url = _required_environment("SP500_DEHB_COORDINATOR_DATABASE_URL")
    target_url = _required_environment("SP500_DEHB_COORDINATOR_DATABASE_URL_NEXT")
    if source_url == target_url:
        raise RuntimeError("CLONE_SOURCE_EQUALS_TARGET")

    with psycopg.connect(source_url) as source, psycopg.connect(target_url) as target:
        source.execute("SET TRANSACTION READ ONLY")
        target.execute("SET TRANSACTION READ ONLY")
        source_inventory = _inventory(source, args.campaign_id)
        target_inventory = _inventory(target, args.campaign_id)
    report = compare_clone_inventories(source_inventory, target_inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "verified campaign clone "
        f"campaign={args.campaign_id} digest={report['verification_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
