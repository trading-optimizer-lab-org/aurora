"""Generate or validate the bounded GTBI V7 preservation inventory."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.inventory import (
    GitHubApiClient,
    generate_local_inventory,
    generate_remote_inventory,
    load_query_manifest,
    token_from_environment,
    validate_inventory,
)

DEFAULT_QUERY_MANIFEST = (
    ROOT / "config/gtbi/contracts/emergency_inventory_query_manifest_v1.json"
)
DEFAULT_OUTPUT = ROOT / "docs/project_inventory"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=["remote", "local", "validate"], required=True
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--query-manifest", type=Path, default=DEFAULT_QUERY_MANIFEST
    )
    parser.add_argument("--repository-path", type=Path, default=ROOT)
    parser.add_argument("--audited-at-utc")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "remote":
        manifest = load_query_manifest(args.query_manifest)
        metadata = generate_remote_inventory(
            client=GitHubApiClient(token_from_environment()),
            query_manifest=manifest,
            query_manifest_path=args.query_manifest,
            output_dir=args.output_dir,
            audited_at_utc=args.audited_at_utc,
            workflow_run_id=os.environ.get("GITHUB_RUN_ID"),
        )
        if args.strict and not metadata["complete"]:
            print(
                "Remote inventory incomplete:",
                ",".join(metadata["missing_required_surfaces"]),
            )
            return 2
        return 0
    if args.mode == "local":
        generate_local_inventory(
            repository_path=args.repository_path,
            output_dir=args.output_dir,
            observed_at_utc=args.audited_at_utc,
        )
        return 0
    errors = validate_inventory(args.output_dir, require_complete=args.strict)
    if errors:
        for error in errors:
            print(error)
        return 2
    print(f"Inventory valid: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
