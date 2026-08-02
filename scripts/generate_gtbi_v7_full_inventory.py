"""Generate the complete two-pass, resumable GTBI V7 GitHub inventory."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from infra.gtbi_v7_readiness.full_inventory import (
    GitHubPageClient,
    run_complete_inventory,
    token_from_environment,
)


def _default_cutoff() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="trading-optimizer-lab-org/aurora")
    parser.add_argument("--organization", default="trading-optimizer-lab-org")
    parser.add_argument("--api-url", default="https://api.github.com")
    parser.add_argument("--cutoff-utc", default="")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("inventory-checkpoint/full_inventory_checkpoint.sqlite"),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("inventory-results")
    )
    args = parser.parse_args()
    cutoff = args.cutoff_utc
    if not cutoff and args.checkpoint.is_file():
        with sqlite3.connect(args.checkpoint) as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key='cutoff_utc'"
            ).fetchone()
        cutoff = "" if row is None else str(row[0])
    cutoff = cutoff or _default_cutoff()
    result = run_complete_inventory(
        client=GitHubPageClient(token_from_environment(), api_url=args.api_url),
        repository=args.repository,
        organization=args.organization,
        api_url=args.api_url,
        cutoff_utc=cutoff,
        checkpoint_path=args.checkpoint,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
