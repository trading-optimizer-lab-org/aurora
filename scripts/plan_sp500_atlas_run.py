"""Create one exact, static, train-only Atlas execution plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.infra.sp500_megarun.atlas_execution_contract import (
    build_run_plan,
    write_plan,
)


def _load(path: Path) -> dict[str, object]:
    value = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"ATLAS_PLAN_JSON_OBJECT_REQUIRED:{path}")
    return value


def plan_atlas_run(
    *,
    catalog_dir: Path,
    calibration_receipt_path: Path,
    output_dir: Path,
    target_end_iso: str,
    implementation_commit_sha: str,
    total_shards: int = 360,
    recipe_count: int | None = None,
) -> dict[str, object]:
    catalog_root = Path(catalog_dir)
    catalog_manifest = _load(catalog_root / "manifest.json")
    calibration = _load(Path(calibration_receipt_path))
    if not (catalog_root / "recipe_space.json").is_file():
        raise ValueError("ATLAS_PLAN_RECIPE_SPACE_MISSING")
    plan = build_run_plan(
        catalog_manifest=catalog_manifest,
        calibration_receipt=calibration,
        target_end_iso=target_end_iso,
        implementation_commit_sha=implementation_commit_sha,
        total_shards=total_shards,
        recipe_count=recipe_count,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    plan_sha256 = write_plan(output / "atlas_run_plan.json", plan)
    groups = plan.matrix_groups(3)
    matrix_payload = {
        "matrix_a": {"shard": list(groups[0])},
        "matrix_b": {"shard": list(groups[1])},
        "matrix_c": {"shard": list(groups[2])},
    }
    (output / "atlas_worker_matrices.json").write_text(
        json.dumps(matrix_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        "accepted": True,
        "plan_sha256": plan_sha256,
        "catalog_id": plan.catalog_id,
        "requested_recipe_count": plan.requested_recipe_count,
        "canonical_recipe_count": plan.canonical_recipe_count,
        "total_shards": plan.total_shards,
        "recipes_per_shard_min": min(row.expected_recipe_count for row in plan.shards),
        "recipes_per_shard_max": max(row.expected_recipe_count for row in plan.shards),
        "target_end_iso": plan.target_end_iso,
        "validation_opened": False,
        "locked_opened": False,
        "execution_authorized": False,
    }
    (output / "atlas_plan_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--calibration-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-end-iso", required=True)
    parser.add_argument("--implementation-commit-sha", required=True)
    parser.add_argument("--total-shards", type=int, default=360)
    parser.add_argument("--recipe-count", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            plan_atlas_run(
                catalog_dir=args.catalog_dir,
                calibration_receipt_path=args.calibration_receipt,
                output_dir=args.output_dir,
                target_end_iso=args.target_end_iso,
                implementation_commit_sha=args.implementation_commit_sha,
                total_shards=args.total_shards,
                recipe_count=args.recipe_count,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
