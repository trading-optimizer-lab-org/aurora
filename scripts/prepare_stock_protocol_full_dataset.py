"""Build and verify the immutable full-universe pre-2021 data artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.stock_protocol.full_dataset import build_full_pre2021_pack


def main() -> int:
    require_github_actions_or_explicit_local_permission("full stock-protocol data build")
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", action="append", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--end-date", default="2020-12-31")
    parser.add_argument("--shard-count", type=int, default=32)
    parser.add_argument("--minimum-symbols", type=int, default=1000)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-artifact-name", required=True)
    parser.add_argument("--source-artifact-digest", required=True)
    parser.add_argument("--expected-source-symbols", type=int)
    parser.add_argument("--expected-source-rows", type=int)
    parser.add_argument("--expected-pack-symbols", type=int)
    parser.add_argument("--expected-pack-rows", type=int)
    args = parser.parse_args()
    provenance = {
        "run_id": args.source_run_id,
        "artifact_name": args.source_artifact_name,
        "artifact_digest": args.source_artifact_digest,
    }
    audit = build_full_pre2021_pack(
        source_roots=[Path(value) for value in args.source_root],
        output_root=Path(args.output_root),
        end_date=args.end_date,
        shard_count=args.shard_count,
        minimum_symbols=args.minimum_symbols,
        provenance=provenance,
    )
    controls = {
        "source_symbols": args.expected_source_symbols,
        "source_rows": args.expected_source_rows,
        "pack_symbols": args.expected_pack_symbols,
        "pack_rows": args.expected_pack_rows,
    }
    mismatches = {
        key: {"expected": expected, "actual": audit[key]}
        for key, expected in controls.items()
        if expected is not None and int(audit[key]) != expected
    }
    if mismatches:
        raise ValueError(f"strict expected-count mismatch: {json.dumps(mismatches, sort_keys=True)}")
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
