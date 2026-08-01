"""Create or verify the provenance-bound GTBI V7 new-reference plan."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from infra.gtbi_v7_new_reference.campaign import (
    DEFAULT_BLOCK_SIZE,
    DEFAULT_EXECUTION_MODE,
    DEFAULT_LOGICAL_WORKERS,
    create_v7_campaign_plan,
    verify_v7_campaign_plan,
)


def _sha() -> str:
    return os.environ.get("GITHUB_SHA") or subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--pack-path", type=Path, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    create.add_argument("--data-manifest", type=Path, required=True)
    create.add_argument("--authorization", type=Path, required=True)
    create.add_argument("--dependency-lock", type=Path, required=True)
    create.add_argument("--logical-workers", type=int, default=DEFAULT_LOGICAL_WORKERS)
    create.add_argument("--execution-mode", default=DEFAULT_EXECUTION_MODE)
    create.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE)
    verify = sub.add_parser("verify")
    verify.add_argument("--plan-root", type=Path, required=True)
    verify.add_argument("--data-manifest", type=Path)
    verify.add_argument("--authorization", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "create":
        payload = create_v7_campaign_plan(
            pack_path=args.pack_path,
            output_dir=args.output_dir,
            data_manifest_path=args.data_manifest,
            authorization_path=args.authorization,
            dependency_lock_path=args.dependency_lock,
            code_sha=_sha(),
            logical_worker_count=args.logical_workers,
            execution_mode=args.execution_mode,
            block_size=args.block_size,
        )
    else:
        payload = verify_v7_campaign_plan(
            plan_root=args.plan_root,
            data_manifest_path=args.data_manifest,
            authorization_path=args.authorization,
        )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
