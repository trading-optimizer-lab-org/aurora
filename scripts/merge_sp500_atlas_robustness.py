"""Merge disjoint, hash-bound train-only robustness segments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def validate_part_bounds(
    parts: list[dict[str, int]],
    *,
    total_candidates: int,
) -> list[tuple[int, int]]:
    bounds = sorted((int(item["candidate_start"]), int(item["candidate_stop"])) for item in parts)
    cursor = 0
    for start, stop in bounds:
        if start != cursor or stop <= start:
            raise ValueError("ATLAS_ROBUSTNESS_PART_COVERAGE_INVALID")
        cursor = stop
    if cursor != total_candidates:
        raise ValueError("ATLAS_ROBUSTNESS_PART_COVERAGE_INVALID")
    return bounds


def merge_robustness(
    *,
    manifest_path: Path,
    parts_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("validation_opened") is not False or manifest.get("locked_opened") is not False:
        raise ValueError("ATLAS_ROBUSTNESS_MANIFEST_BOUNDARY_OPEN")
    total = len(manifest.get("candidate_strategy_ids", []))
    receipt_paths = sorted(Path(parts_root).rglob("robustness_receipt.json"))
    if not receipt_paths:
        raise ValueError("ATLAS_ROBUSTNESS_PARTS_MISSING")
    receipts = [json.loads(path.read_text("utf-8")) for path in receipt_paths]
    if any(receipt.get("robustness_sha256") != manifest.get("robustness_sha256") for receipt in receipts):
        raise ValueError("ATLAS_ROBUSTNESS_PART_IDENTITY_INVALID")
    bounds = validate_part_bounds(receipts, total_candidates=total)
    frames: dict[str, list[pd.DataFrame]] = {name: [] for name in ("robustness_results", "robustness_classification")}
    for path in receipt_paths:
        root = path.parent
        for name in frames:
            frames[name].append(pd.read_parquet(root / f"{name}.parquet"))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "robustness_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    results = pd.concat(frames["robustness_results"], ignore_index=True)
    classifications = pd.concat(frames["robustness_classification"], ignore_index=True)
    results.to_parquet(output / "robustness_results.parquet", index=False)
    classifications.to_parquet(output / "robustness_classification.parquet", index=False)
    classifications[classifications["status"] == "green"].to_parquet(output / "robust_candidates.parquet", index=False)
    classifications[classifications["status"] == "amber"].to_parquet(output / "fragile_reserve.parquet", index=False)
    classifications[classifications["status"] == "invalid"].to_parquet(output / "invalid_candidates.parquet", index=False)
    receipt = {
        "schema_version": 1,
        "accepted": True,
        "robustness_sha256": manifest["robustness_sha256"],
        "candidate_count": total,
        "segment_count": len(receipts),
        "segment_bounds": bounds,
        "perturbation_result_count": len(results),
        "green_count": int((classifications["status"] == "green").sum()),
        "amber_count": int((classifications["status"] == "amber").sum()),
        "red_count": int((classifications["status"] == "red").sum()),
        "invalid_count": int((classifications["status"] == "invalid").sum()),
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "robustness_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--parts-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(merge_robustness(**vars(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
