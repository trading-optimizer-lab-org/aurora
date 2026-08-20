from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import (
    build_run_plan,
    load_plan,
    partition_ordinals,
    write_plan,
)
from aurora.infra.sp500_megarun.atlas_campaign_selection import build_campaign_selection
from scripts.reduce_sp500_atlas_run import reduce_atlas_run


def test_worker_cli_maps_argparse_names_to_worker_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.run_sp500_atlas_worker as worker

    captured: dict[str, object] = {}

    def fake_run_worker(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(worker, "run_worker", fake_run_worker)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_sp500_atlas_worker.py",
            "--plan",
            "plan.json",
            "--catalog-dir",
            "catalog",
            "--runtime-input-pack",
            "runtime",
            "--campaign-contract",
            "campaign.json",
            "--data-contract",
            "data.json",
            "--feature-contract",
            "feature.json",
            "--shard-index",
            "3",
            "--output-dir",
            "output",
        ],
    )

    assert worker.main() == 0
    assert captured == {
        "plan_path": Path("plan.json"),
        "catalog_dir": Path("catalog"),
        "runtime_input_pack": Path("runtime"),
        "campaign_contract_path": Path("campaign.json"),
        "data_contract_path": Path("data.json"),
        "feature_contract_path": Path("feature.json"),
        "shard_index": 3,
        "output_dir": Path("output"),
    }


def test_reducer_cli_maps_argparse_names_to_reducer_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.reduce_sp500_atlas_run as reducer

    captured: dict[str, object] = {}

    def fake_reduce_atlas_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(reducer, "reduce_atlas_run", fake_reduce_atlas_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reduce_sp500_atlas_run.py",
            "--plan",
            "plan.json",
            "--partitions-root",
            "partitions",
            "--output-dir",
            "output",
        ],
    )

    assert reducer.main() == 0
    assert captured == {
        "plan_path": Path("plan.json"),
        "partitions_root": Path("partitions"),
        "output_dir": Path("output"),
    }


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
        "recommended_mode": "cold",
        "available_minutes_to_target": 100.0,
        "safety_fraction": 0.8,
        "validation_opened": False,
        "locked_opened": False,
    }
    return catalog, receipt


def _selection() -> dict[str, object]:
    return build_campaign_selection(
        {
            "canonical_recipe_count": 100,
            "ranges": [
                {"range_id": "a", "start_ordinal": 0, "stop_ordinal": 50},
                {"range_id": "b", "start_ordinal": 50, "stop_ordinal": 100},
            ],
        },
        requested_recipe_count=8,
        seed=20260818,
    )


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
        selection=_selection(),
    )
    path = tmp_path / "plan.json"
    write_plan(path, plan)
    assert load_plan(path).plan_sha256 == plan.plan_sha256
    assert sum(row.expected_recipe_count for row in plan.shards) == 8
    assert plan.matrix_groups() == ((0, 3), (1,), (2,))


def test_plan_rejects_warm_calibration_for_conservative_sizing() -> None:
    catalog, receipt = _evidence()
    receipt["recommended_mode"] = "component_warm"
    with pytest.raises(ValueError, match="ATLAS_PLAN_CALIBRATION_MODE_INVALID"):
        build_run_plan(
            catalog_manifest=catalog,
            calibration_receipt=receipt,
            target_end_iso="2026-08-20T07:31:00+02:00",
            implementation_commit_sha="91c605b90ab4136c73dd00b8c200460a67571dbe",
            total_shards=4,
            selection=_selection(),
        )


def test_plan_binds_stratified_selection_instead_of_a_prefix(tmp_path: Path) -> None:
    catalog, receipt = _evidence()
    selection = build_campaign_selection(
        {
            "canonical_recipe_count": 100,
            "ranges": [
                {"range_id": "a", "start_ordinal": 0, "stop_ordinal": 50},
                {"range_id": "b", "start_ordinal": 50, "stop_ordinal": 100},
            ],
        },
        requested_recipe_count=8,
        seed=20260818,
    )
    plan = build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=receipt,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="91c605b90ab4136c73dd00b8c200460a67571dbe",
        total_shards=4,
        selection=selection,
    )
    path = tmp_path / "plan.json"
    write_plan(path, plan)
    loaded = load_plan(path)
    assert loaded.selection_sha256 == selection["selection_sha256"]
    assert loaded.selection_ranges


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
        selection=_selection(),
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
    assert output.joinpath("all_results_manifest.json").is_file()
    assert output.joinpath("coverage_report.json").is_file()
    assert output.joinpath("pareto_cells.parquet").is_file()
    assert output.joinpath("pareto_strategies.parquet").is_file()


def test_reducer_near_frontier_checks_exact_unit_cube() -> None:
    import scripts.reduce_sp500_atlas_run as reducer

    frontier = {(10, 20, 3), (12, 18, 4), (20, 20, 8)}
    cells = {
        (9, 19, 2),   # close to (10, 20, 3)
        (10, 20, 2),  # close to (10, 20, 3)
        (11, 18, 3),  # close to (12, 18, 4)
        (8, 19, 2),   # week difference is two: not close
        (10, 19, 1),  # year difference is two: not close
        (19, 20, 6),  # year difference is two: not close
    }

    for cell in cells:
        expected = any(
            all(front[index] >= cell[index] for index in range(3))
            and max(front[index] - cell[index] for index in range(3)) <= 1
            for front in frontier
        )
        assert reducer._is_near_frontier(cell, frontier) is expected


def test_reducer_rejects_missing_shard(tmp_path: Path) -> None:
    catalog, receipt = _evidence()
    plan = build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=receipt,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="91c605b90ab4136c73dd00b8c200460a67571dbe",
        total_shards=4,
        selection=_selection(),
    )
    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, plan)
    shards = tmp_path / "shards"
    shards.mkdir()
    for index in range(3):
        _write_shard(shards, plan, index)
    with pytest.raises(ValueError, match="SHARD_COVERAGE_INVALID"):
        reduce_atlas_run(plan_path=plan_path, partitions_root=shards, output_dir=tmp_path / "out")


def test_reducer_accepts_identical_duplicate_receipt_and_records_redundancy(tmp_path: Path) -> None:
    catalog, receipt = _evidence()
    plan = build_run_plan(
        catalog_manifest=catalog,
        calibration_receipt=receipt,
        target_end_iso="2026-08-20T07:31:00+02:00",
        implementation_commit_sha="91c605b90ab4136c73dd00b8c200460a67571dbe",
        total_shards=4,
        selection=_selection(),
    )
    plan_path = tmp_path / "plan.json"
    write_plan(plan_path, plan)
    shards = tmp_path / "shards"
    shards.mkdir()
    for index in range(4):
        _write_shard(shards, plan, index)
    shutil.copytree(shards / "shard-0", shards / "duplicate-shard-0")

    summary = reduce_atlas_run(
        plan_path=plan_path,
        partitions_root=shards,
        output_dir=tmp_path / "out",
    )

    assert summary["verified_recipe_count"] == 8
    assert summary["redundant_shard_receipt_count"] == 1
