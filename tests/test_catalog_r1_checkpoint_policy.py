"""R1 may report transport overhead; it must never waive durability."""

import math

import pytest

from scripts.plan_sp500_optimized_catalog_run import select_checkpoint_slot_count
from aurora.tests.test_sp500_catalog_optimization_contract import _task10_plan_fixture


@pytest.mark.parametrize("seconds", [3.0, 4.0])
def test_r1_accepts_tiny_worker_without_claiming_five_percent(seconds):
    assert select_checkpoint_slot_count(
        projected_worker_seconds_p99=seconds,
        upload_verify_seconds_p95=0.643651,
        overhead_gate="report_only_r1",
    ) == 1
    with pytest.raises(ValueError, match="CHECKPOINT_OVERHEAD_OR_DURABILITY_UNQUALIFIED"):
        select_checkpoint_slot_count(
            projected_worker_seconds_p99=seconds,
            upload_verify_seconds_p95=0.643651,
        )


def test_r1_keeps_durability_limit_even_when_overhead_is_reported():
    assert select_checkpoint_slot_count(
        projected_worker_seconds_p99=840,
        upload_verify_seconds_p95=100,
        overhead_gate="report_only_r1",
    ) == 2
    with pytest.raises(ValueError, match="CHECKPOINT_OVERHEAD_OR_DURABILITY_UNQUALIFIED"):
        select_checkpoint_slot_count(
            projected_worker_seconds_p99=6000,
            upload_verify_seconds_p95=100,
            overhead_gate="report_only_r1",
        )


@pytest.mark.parametrize("seconds,upload", [(math.inf, 1), (3, math.nan), (3, math.inf), (0, 1), (3, -1)])
def test_r1_rejects_invalid_timing_inputs(seconds, upload):
    with pytest.raises(ValueError, match="CHECKPOINT_PROJECTION_INVALID"):
        select_checkpoint_slot_count(
            projected_worker_seconds_p99=seconds,
            upload_verify_seconds_p95=upload,
            overhead_gate="report_only_r1",
        )


def test_hot_planner_binds_r1_mode_and_actual_overhead_to_plan():
    plan = _task10_plan_fixture(
        warm_component_ordinals=set(range(12)),
        qualify_layout=False,
        worker_count_override=4,
        recipe_seconds=1.0,
        recipe_count=8,
        overhead_gate="report_only_r1",
    )
    assert len(plan.recipe_assignments) == 4
    assert sum(len(row.strategy_ids) for row in plan.recipe_assignments) == 8
    assert plan.checkpoint_overhead_gate == "report_only_r1"
    assert plan.checkpoint_upload_seconds_estimate == 5.0
    assert all(row.checkpoint_slot_count == 1 for row in plan.recipe_assignments)
    assert plan.pending_component_ids == ()
    assert plan.component_assignments == ()


def test_checkpoint_segments_use_actual_partition_cost_not_worker_average():
    assert select_checkpoint_slot_count(
        projected_worker_seconds_p99=900,
        upload_verify_seconds_p95=5,
        recipe_seconds=(500.0, 200.0, 100.0, 100.0),
    ) == 4


@pytest.mark.parametrize("mode", ["required", "report_only_r1"])
def test_planner_rejects_indivisible_recipe_above_loss_window(mode):
    with pytest.raises(ValueError, match="CHECKPOINT_OVERHEAD_OR_DURABILITY_UNQUALIFIED"):
        _task10_plan_fixture(
            warm_component_ordinals=set(range(12)),
            qualify_layout=False,
            recipe_seconds=840,
            overhead_gate=mode,
        )
