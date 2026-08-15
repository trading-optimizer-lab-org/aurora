"""Fail unless a continuous campaign has no live database writer leases."""

from __future__ import annotations

import argparse
import os


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    args = parser.parse_args()
    database_url = os.environ.get("SP500_DEHB_COORDINATOR_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("SP500_DEHB_COORDINATOR_DATABASE_URL_MISSING")

    import psycopg

    with psycopg.connect(database_url) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        row = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM campaign_leases
               WHERE campaign_id = %s AND lease_expires_at >= clock_timestamp()),
              (SELECT count(*) FROM worker_sessions
               WHERE campaign_id = %s AND state <> 'closed'
                 AND lease_expires_at >= clock_timestamp()),
              (SELECT count(*) FROM worker_slot_leases
               WHERE campaign_id = %s AND lease_expires_at >= clock_timestamp())
            """,
            (args.campaign_id,) * 3,
        ).fetchone()
    coordinator_leases, worker_sessions, slot_leases = (int(value) for value in row)
    if coordinator_leases or worker_sessions or slot_leases:
        raise RuntimeError(
            "CLONE_SOURCE_NOT_QUIESCENT "
            f"coordinators={coordinator_leases} "
            f"workers={worker_sessions} slots={slot_leases}"
        )
    print(f"source campaign is quiescent campaign={args.campaign_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
