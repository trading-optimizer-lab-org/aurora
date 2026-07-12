"""Strictly merge stock protocol shards without filename collisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aurora.research.stock_protocol.manifest import load_protocol_manifest


def merge_phase(
    shards_root: Path,
    phase: str,
    shard_count: int,
    output_root: Path,
    manifest_path: Path,
) -> Path:
    manifest = load_protocol_manifest(manifest_path)
    paths = sorted((shards_root / f"phase={phase}").glob("shard=*/stage_results.jsonl"))
    found = {int(path.parent.name.split("=", 1)[1]) for path in paths}
    expected = set(range(shard_count))
    missing = sorted(expected - found)
    extra = sorted(found - expected)
    if missing:
        raise ValueError(f"missing shard(s): {missing[:10]}")
    if extra:
        raise ValueError(f"extra shard(s): {extra[:10]}")
    rows: list[dict[str, object]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    if not rows:
        raise ValueError(f"phase {phase} has no result rows")
    if any(bool(row.get("locked_opened")) for row in rows):
        raise ValueError("locked_opened must remain false")
    if any(str(row.get("data_end")) != manifest.data_end for row in rows):
        raise ValueError("incompatible data_end in phase rows")
    frame = pd.json_normalize(rows)
    if frame["shard_id"].duplicated().any() and len(rows) == len(found):
        raise ValueError("duplicate shard result")
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / f"{phase}_results.csv"
    frame.to_csv(output, index=False)
    audit = {
        "phase": phase,
        "expected_shards": shard_count,
        "found_shards": len(found),
        "rows": len(frame),
        "partial": False,
        "locked_opened": False,
        "data_end": manifest.data_end,
    }
    output.with_suffix(".audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--shard-count", type=int, default=360)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    print(merge_phase(**vars(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

