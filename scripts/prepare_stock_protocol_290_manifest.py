"""Prepare the exact original 10 x 29 stock-protocol manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.stock_protocol.event_study_290_manifest import (
    prepare_original_290_manifest,
)


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "stock-protocol original 290-combination manifest preparation"
    )
    parser = argparse.ArgumentParser(
        description="Derive the exact 10 x 29 grid from an extracted original artifact."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="Directory containing exit_layer_results.csv and entry_layer_results.csv.",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--entry-snapshot", type=Path, required=True)
    parser.add_argument("--exit-snapshot", type=Path, required=True)
    args = parser.parse_args()
    entry_snapshot = next(args.entry_snapshot.rglob("entries_snapshot.json"))
    exit_snapshot = next(args.exit_snapshot.rglob("exits_snapshot.json"))
    result = prepare_original_290_manifest(
        args.source_root,
        args.output_root,
        entry_snapshot=entry_snapshot,
        exit_snapshot=exit_snapshot,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
