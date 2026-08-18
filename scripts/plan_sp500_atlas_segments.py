"""Write the immutable disjoint segment manifest for an Atlas plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.atlas_segments import build_segment_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-shards-per-segment", type=int, default=120)
    args = parser.parse_args()
    plan = load_plan(args.plan)
    manifest = build_segment_manifest(
        plan,
        max_shards_per_segment=args.max_shards_per_segment,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "accepted": True,
        "manifest_sha256": manifest["manifest_sha256"],
        "plan_sha256": manifest["plan_sha256"],
        "segment_count": len(manifest["segments"]),
        "total_shards": manifest["total_shards"],
        "validation_opened": False,
        "locked_opened": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
