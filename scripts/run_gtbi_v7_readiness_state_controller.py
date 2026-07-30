"""Run the closed GTBI V7 readiness state controller."""

from __future__ import annotations

import argparse
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.readiness_state_controller.engine import (
    build_transition_projection,
    write_transition_projection,
)
from infra.readiness_state_controller.policy import (
    load_transition_manifest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--mode", choices=("dry_run", "apply"), required=True)
    parser.add_argument("--receipt-path", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.repository_root.resolve()
    manifest = load_transition_manifest(root, args.manifest_id)
    projection = build_transition_projection(
        root,
        manifest,
        base_sha=args.base_sha,
    )
    if args.mode == "apply":
        write_transition_projection(root, projection)
    args.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_path.write_bytes(
        canonical_bytes(projection.receipt) + b"\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
