"""Preserve local Aurora worktrees without mutating their source paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.local_reorganization import (
    preserve_local_worktrees,
    validate_local_reorganization,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-path", type=Path, required=True)
    parser.add_argument("--primary-clone-path", type=Path, required=True)
    parser.add_argument("--public-output-dir", type=Path, required=True)
    parser.add_argument("--private-output-dir", type=Path, required=True)
    parser.add_argument("--observed-at-utc")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.validate_only:
        preserve_local_worktrees(
            repository_path=args.repository_path,
            primary_clone_path=args.primary_clone_path,
            public_output_dir=args.public_output_dir,
            private_output_dir=args.private_output_dir,
            observed_at_utc=args.observed_at_utc,
        )
    errors = validate_local_reorganization(args.public_output_dir)
    if errors:
        for error in errors:
            print(error)
        return 2
    print(f"Local reorganization evidence valid: {args.public_output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
