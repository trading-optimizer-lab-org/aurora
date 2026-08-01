"""Generate the exact GTBI V7 terminal no-go controller receipt."""

from __future__ import annotations

import argparse
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.readiness_state_controller.no_go import build_no_go_receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--close-id", required=True)
    parser.add_argument("--closed-at-utc", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--receipt-path", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = build_no_go_receipt(
        args.repository_root,
        base_sha=args.base_sha,
        close_id=args.close_id,
        closed_at_utc=args.closed_at_utc,
        run_id=args.run_id,
        run_url=args.run_url,
    )
    args.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_path.write_bytes(canonical_bytes(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
