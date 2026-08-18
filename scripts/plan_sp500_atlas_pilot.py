"""Write the deterministic production-shard pilot manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.atlas_pilot import build_pilot_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260818)
    args = parser.parse_args()
    manifest = build_pilot_manifest(
        load_plan(args.plan),
        shard_count=args.shard_count,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "accepted": True,
        "manifest_sha256": manifest["manifest_sha256"],
        "shard_count": len(manifest["shard_indices"]),
        "expected_recipe_count": manifest["expected_recipe_count"],
        "validation_opened": False,
        "locked_opened": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
