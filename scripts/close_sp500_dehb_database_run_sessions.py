"""Close database writer sessions after their GitHub run is proven completed."""

from __future__ import annotations

import argparse
import json
import os


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--github-run-id", required=True, type=int)
    args = parser.parse_args()
    database_url = os.environ.get("SP500_DEHB_COORDINATOR_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("SP500_DEHB_COORDINATOR_DATABASE_URL_MISSING")
    if os.environ.get("SP500_DEHB_SOURCE_RUN_COMPLETED") != "true":
        raise RuntimeError("SOURCE_RUN_COMPLETION_NOT_PROVEN")

    import psycopg

    with psycopg.connect(database_url) as connection, connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 360))",
                (args.campaign_id,),
            )
            campaign = cursor.execute(
                """
                SELECT state, validation_opened, locked_opened
                FROM campaigns WHERE campaign_id = %s
                """,
                (args.campaign_id,),
            ).fetchone()
            if campaign is None:
                raise RuntimeError("CAMPAIGN_NOT_FOUND")
            if bool(campaign[1]) or bool(campaign[2]):
                raise RuntimeError("CAMPAIGN_BOUNDARY_OPENED")
            live_coordinators = int(
                cursor.execute(
                    """
                    SELECT count(*) FROM campaign_leases
                    WHERE campaign_id = %s
                      AND lease_expires_at >= clock_timestamp()
                    """,
                    (args.campaign_id,),
                ).fetchone()[0]
            )
            if live_coordinators:
                raise RuntimeError("SOURCE_RUN_COORDINATOR_STILL_LIVE")
            foreign_live_sessions = int(
                cursor.execute(
                    """
                    SELECT count(*) FROM worker_sessions
                    WHERE campaign_id = %s AND state <> 'closed'
                      AND lease_expires_at >= clock_timestamp()
                      AND github_run_id <> %s
                    """,
                    (args.campaign_id, args.github_run_id),
                ).fetchone()[0]
            )
            if foreign_live_sessions:
                raise RuntimeError("OTHER_GITHUB_RUN_WORKERS_STILL_LIVE")
            session_ids = [
                str(row[0])
                for row in cursor.execute(
                    """
                    SELECT worker_session_id FROM worker_sessions
                    WHERE campaign_id = %s AND github_run_id = %s
                      AND state <> 'closed'
                    FOR UPDATE
                    """,
                    (args.campaign_id, args.github_run_id),
                ).fetchall()
            ]
            sequence = int(
                cursor.execute(
                    "SELECT nextval('continuous_event_sequence')"
                ).fetchone()[0]
            )
            released_evaluations: list[int] = []
            if session_ids:
                cursor.execute(
                    """
                    UPDATE work_items SET state = 'ready', lease_token = NULL,
                        leased_by_session_id = NULL, leased_by_slot = NULL,
                        lease_expires_at = NULL, updated_sequence = %s,
                        updated_at = clock_timestamp()
                    WHERE campaign_id = %s AND leased_by_session_id = ANY(%s)
                      AND state = 'leased'
                    RETURNING evaluation_id
                    """,
                    (sequence, args.campaign_id, session_ids),
                )
                released_evaluations = [int(row[0]) for row in cursor.fetchall()]
                if released_evaluations:
                    cursor.execute(
                        """
                        UPDATE evaluations SET state = 'ready', updated_sequence = %s,
                            updated_at = clock_timestamp()
                        WHERE campaign_id = %s AND evaluation_id = ANY(%s)
                        """,
                        (sequence, args.campaign_id, released_evaluations),
                    )
                cursor.execute(
                    "DELETE FROM worker_slot_leases WHERE worker_session_id = ANY(%s)",
                    (session_ids,),
                )
                deleted_slots = cursor.rowcount
                cursor.execute(
                    """
                    UPDATE worker_sessions SET state = 'closed',
                        updated_sequence = %s, updated_at = clock_timestamp()
                    WHERE campaign_id = %s AND worker_session_id = ANY(%s)
                    """,
                    (sequence, args.campaign_id, session_ids),
                )
                closed_sessions = cursor.rowcount
            else:
                deleted_slots = 0
                closed_sessions = 0
            cursor.execute(
                """
                ALTER TABLE worker_sessions DROP CONSTRAINT IF EXISTS
                worker_sessions_campaign_id_permit_number_key
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                worker_sessions_active_permit_unique
                ON worker_sessions (campaign_id, permit_number)
                WHERE state <> 'closed'
                """
            )
    print(
        json.dumps(
            {
                "campaign_id": args.campaign_id,
                "github_run_id": args.github_run_id,
                "closed_sessions": closed_sessions,
                "released_evaluations": len(released_evaluations),
                "deleted_slot_leases": deleted_slots,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
