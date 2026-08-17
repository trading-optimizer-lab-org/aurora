from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import (
    build_run_plan,
    load_plan,
    partition_ordinals,
    write_plan,
)
from scripts.reduce_sp500_atlas_run import reduce_atlas_run


def _evidence() -> tuple[dict[str, object], dict[str, object]]:
    catalog = {
        "catalog_id": "sp500-atlas-1",
        "manifest_sha256": "a" * 64,
        "artifacts_sha256": {"recipe_space.json": "b" * 64},
        "counts": {"canonical_recipe_count": 100},
        "validation_opened": False,
        "locked_opened": False,
        "execution_authorized": False,
    }
    receipt = {
        "schema_version": "1",
        "catalog_sha256": "a" * 64,
        "hard_limit_seconds": 1200.0,
        "target_recipe_count_with_margin": 8,
        "recipes_per_minute": 10.0,
        "available_minutes_to_target": 100.0,
        "safety_fraction": 0.8,
        "validation_opened": False,
        "locked_opened": False,
    }
    return catalog, receipt


def test_partition_is_contiguous_and_exact() -> None:
    ranges = partition_ordinals(recipe_count=17, total_shards=4)
    assert ranges == ((0, 5), (5, 9), (9, 13), (13, 17))


def test_plan_round_trip_and_hash(tmp_path: Path) -> None:
    catalog, receipt = _evidence()
    plan = build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=receipt,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="91c605b90ab4136c73dd00b8c200460a67571dbe",
        total_shards=4,
    )
    path = tmp_path / "plan.json"
    write_plan(path, plan)
    assert load_plan(path).plan_sha256 == plan.plan_sha256
    assert sum(row.expected_recipe_count for row in plan.shards) == 8
    assert plan.matrix_groups() == ((0, 3), (1,), (2,))


def _write_shard(root: Path, plan, index: int) -> None:
    shard = plan.shard(index)
    target = root / f"shard-{index}"
    target.mkdir()
    rows: list[dict[str, object]] = []
    for ordinal in range(shard.start_ordinal, shard.stop_ordinal):
        row = {
            "ordinal": ordinal,
            "strategy_id": f"ATLAS1-{ordinal}",
            "scientific_recipe_sha256": f"{ordinal:064x}",
            "strategy_kind": "single",
            "components": [],
            "composition": {"kind": "identity", "direction": 1},
            "position_sha256": f"{ordinal:064x}",
            "positive_weeks": ordinal,
            "total_weeks": 10,
            "positive_week_fraction": ordinal / 100.0,
            "positive_months": ordinal,
            "total_months": 10,
            "positive_month_fraction": ordinal / 100.0,
            "joint_positive_above_spy_years": ordinal,
            "total_years": 10,
            "joint_positive_above_spy_fraction": ordinal / 100.0,
            "annual_rows": [],
            "annualized_strategy_return": 0.0,
            "annualized_alpha": 0.0,
            "weeks_beating_spy": 0,
            "week_count": 10,
            "plan_sha256": plan.plan_sha256,
            "shard_index": index,
            "evaluation_origin": "physical",
            "validation_opened": False,
            "locked_opened": False,
        }
        row["result_sha256"] = canonical_sha256(row)
        rows.append(row)
    results = target / "results.jsonl"
    results.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
    receipt = {
        "schema_version": 1,
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "shard_index": index,
        "start_ordinal": shard.start_ordinal,
        "stop_ordinal": shard.stop_ordinal,
        "expected_recipe_count": shard.expected_recipe_count,
        "actual_recipe_count": len(rows),
        "result_sha256": hashlib.sha256(results.read_bytes()).hexdigest(),
        "validation_opened": False,
        "locked_opened": False,
    }
    (target / "worker_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


def test_reducer_requires_every_shard_and_preserves_all_rows(tmp_path: Path) -> None:
    catalog, receipt = _evidence()
    plan = build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=receipt,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="91c605b90ab4136c73dd00b8c200460a67571dbe",
        total_shards=4,
    )
    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, plan)
    shards = tmp_path / "shards"
    shards.mkdir()
    for index in range(4):
        _write_shard(shards, plan, index)
    output = tmp_path / "final"
    summary = reduce_atlas_run(plan_path=plan_path, partitions_root=shards, output_dir=output)
    assert summary["verified_recipe_count"] == 8
    assert len(output.joinpath("results.jsonl").read_text("utf-8").splitlines()) == 8
    assert summary["validation_opened"] is False
    assert summary["locked_opened"] is False


def test_reducer_rejects_missing_shard(tmp_path: Path) -> None:
    catalog, receipt = _evidence()
    plan = build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=receipt,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="91c605b90ab4136c73dd00b8c200460a67571dbe",
        total_shards=4,
    )
    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, plan)
    shards = tmp_path / "shards"
    shards.mkdir()
    for index in range(3):
        _write_shard(shards, plan, index)
    with pytest.raises(ValueError, match="SHARD_COVERAGE_INVALID"):
        reduce_atlas_run(plan_path=plan_path, partitions_root=shards, output_dir=tmp_path / "out")
