"""Emit bounded GitHub matrices for one replacement-aware worker generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.dehb_continuous_bootstrap import (
    build_worker_pool_matrices,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool-generation", required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()

    matrices = build_worker_pool_matrices(args.pool_generation)
    output = args.github_output.resolve()
    with output.open("a", encoding="utf-8", newline="\n") as handle:
        for shard in "ABC":
            encoded = json.dumps(matrices[shard], sort_keys=True, separators=(",", ":"))
            handle.write(f"matrix_{shard.lower()}={encoded}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
