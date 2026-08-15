"""Close database writer sessions after their GitHub run is proven completed."""

from __future__ import annotations

import argparse
import json
import os
from urllib.parse import urlsplit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--github-run-id", required=True, type=int)
    parser.add_argument("--terminate-stopped-run-backends", action="store_true")
    parser.add_argument("--rebuild-open-batches", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("SP500_DEHB_COORDINATOR_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("SP500_DEHB_COORDINATOR_DATABASE_URL_MISSING")
    if os.environ.get("SP500_DEHB_SOURCE_RUN_COMPLETED") != "true":
        raise RuntimeError("SOURCE_RUN_COMPLETION_NOT_PROVEN")

    import psycopg

    terminated_backends = 0
    if args.terminate_stopped_run_backends:
        if "-pooler." in str(urlsplit(database_url).hostname or ""):
            raise RuntimeError(
                "STOPPED_RUN_BACKEND_TERMINATION_REQUIRES_DIRECT_URL"
            )
        with psycopg.connect(database_url, autocommit=True) as admin_connection:
            live_coordinators = int(
                admin_connection.execute(
                    """
                    SELECT count(*) FROM campaign_leases
                    WHERE campaign_id = %s
                      AND lease_expires_at >= clock_timestamp()
                    """,
                    (args.campaign_id,),
                ).fetchone()[0]
            )
            foreign_live_sessions = int(
                admin_connection.execute(
                    """
                    SELECT count(*) FROM worker_sessions
                    WHERE campaign_id = %s AND state <> 'closed'
                      AND lease_expires_at >= clock_timestamp()
                      AND github_run_id <> %s
                    """,
                    (args.campaign_id, args.github_run_id),
                ).fetchone()[0]
            )
            if live_coordinators:
                raise RuntimeError("SOURCE_RUN_COORDINATOR_STILL_LIVE")
            if foreign_live_sessions:
                raise RuntimeError("OTHER_GITHUB_RUN_WORKERS_STILL_LIVE")
            backend_pids = [
                int(row[0])
                for row in admin_connection.execute(
                    """
                    SELECT pid FROM pg_stat_activity
                    WHERE datname = current_database() AND usename = current_user
                      AND pid <> pg_backend_pid()
                    """
                ).fetchall()
            ]
            for backend_pid in backend_pids:
                terminated_backends += int(
                    bool(
                        admin_connection.execute(
                            "SELECT pg_terminate_backend(%s)", (backend_pid,)
                        ).fetchone()[0]
                    )
                )

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
            deleted_strategy_claims = 0
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
                        """
                        DELETE FROM strategy_evaluations
                        WHERE campaign_id = %s AND state = 'owned'
                          AND result_sha256 IS NULL AND result_payload IS NULL
                          AND owner_evaluation_id = ANY(%s)
                        """,
                        (args.campaign_id, released_evaluations),
                    )
                    deleted_strategy_claims = cursor.rowcount
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
            if args.rebuild_open_batches:
                reset_batches = cursor.execute(
                    """
                    SELECT island_id, batch_sequence FROM island_batches
                    WHERE campaign_id = %s AND status = 'open'
                    ORDER BY island_id, batch_sequence
                    """,
                    (args.campaign_id,),
                ).fetchall()
            else:
                reset_batches = cursor.execute(
                    """
                    SELECT b.island_id, b.batch_sequence
                    FROM island_batches b
                    LEFT JOIN proposals p ON p.campaign_id = b.campaign_id
                      AND p.island_id = b.island_id
                      AND p.batch_sequence = b.batch_sequence
                    WHERE b.campaign_id = %s AND b.status = 'open'
                    GROUP BY b.island_id, b.batch_sequence
                    HAVING count(p.proposal_id) <> 4
                    """,
                    (args.campaign_id,),
                ).fetchall()
            deleted_open_batch_proposals = 0
            for island_id, batch_sequence in reset_batches:
                cursor.execute(
                    """
                    DELETE FROM evaluation_subscribers
                    WHERE campaign_id = %s AND proposal_id IN (
                      SELECT proposal_id FROM proposals
                      WHERE campaign_id = %s AND island_id = %s
                        AND batch_sequence = %s
                    )
                    """,
                    (
                        args.campaign_id,
                        args.campaign_id,
                        str(island_id),
                        int(batch_sequence),
                    ),
                )
                cursor.execute(
                    """
                    DELETE FROM proposals
                    WHERE campaign_id = %s AND island_id = %s
                      AND batch_sequence = %s
                    """,
                    (args.campaign_id, str(island_id), int(batch_sequence)),
                )
                deleted_open_batch_proposals += cursor.rowcount
                cursor.execute(
                    """
                    DELETE FROM island_batches
                    WHERE campaign_id = %s AND island_id = %s
                      AND batch_sequence = %s AND status = 'open'
                    """,
                    (args.campaign_id, str(island_id), int(batch_sequence)),
                )
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
                "deleted_orphaned_strategy_claims": deleted_strategy_claims,
                "rebuilt_open_batches": len(reset_batches),
                "detached_open_batch_proposals": deleted_open_batch_proposals,
                "terminated_backends": terminated_backends,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
