import pandas as pd

from aurora.infra.sp500_megarun.catalog_performance import (
    CatalogPerformanceRecorder,
)
from scripts.run_sp500_strategy_catalog_shard import (
    compose_signals,
    weekly_winning_or_positive_metrics,
)


def _s(values):
    return pd.Series(values, index=pd.date_range("2000-01-01", periods=len(values)))


def test_catalog_compositions_follow_frozen_semantics():
    left, right = _s([1, 1, -1, -1]), _s([1, -1, -1, 0])
    assert compose_signals([left, right], {"kind": "and"}).tolist()[:1] == [1.0]
    assert compose_signals([left, right], {"kind": "gate", "base_component_index": 0}).fillna(0).tolist() == [1, 0, -1, 0]
    assert compose_signals([left, right], {"kind": "override", "base_component_index": 0, "priority_component_index": 1}).fillna(0).tolist() == [1, -1, -1, -1]
    assert compose_signals([left, right], {"kind": "weighted_score", "weights": [1, -2]}).fillna(0).tolist() == [-1, 1, 1, -1]


def test_weekly_winning_or_positive_counts_union_without_double_counting():
    dates = pd.to_datetime(["2000-01-07", "2000-01-14", "2000-01-21"])
    strategy = pd.Series([0.01, -0.01, -0.01], index=dates)
    spy = pd.Series([0.02, -0.02, 0.01], index=dates)

    assert weekly_winning_or_positive_metrics(strategy, spy) == {
        "week_count": 3,
        "positive_weeks": 1,
        "weeks_beating_spy": 1,
        "winning_or_positive_weeks": 2,
        "weekly_winning_or_positive_rate": 2 / 3,
    }


def test_component_resolution_profiles_one_physical_build_and_one_cache_hit():
    """Reusing one component must not be measured as a second physical build."""

    from scripts.run_sp500_strategy_catalog_shard import resolve_component_signals

    wall_values = iter((0.0, 0.25))
    cpu_values = iter((0.0, 0.10))
    recorder = CatalogPerformanceRecorder(
        shard_index=0,
        total_shards=1,
        thermal_state="cold",
        clock=lambda: next(wall_values),
        cpu_clock=lambda: next(cpu_values),
        memory_mb=lambda: 32.0,
    )
    index = pd.date_range("2000-01-01", periods=3)
    expected = pd.Series([1.0, float("nan"), -1.0], index=index)
    component = {
        "lane_id": "F001",
        "configuration": {"window": 20},
        "configuration_sha256": "a" * 64,
    }
    calls: list[tuple[str, dict[str, int]]] = []

    def evaluator(lane_id, configuration):
        calls.append((lane_id, configuration))
        return expected

    cache = {}
    first = resolve_component_signals(
        [component],
        evaluator=evaluator,
        decision_index=index,
        allowed_end="2010-12-31",
        component_cache=cache,
        recorder=recorder,
        decision_builder=lambda frame, *, allowed_end: frame,
    )
    second = resolve_component_signals(
        [component],
        evaluator=evaluator,
        decision_index=index,
        allowed_end="2010-12-31",
        component_cache=cache,
        recorder=recorder,
        decision_builder=lambda frame, *, allowed_end: frame,
    )

    assert calls == [("F001", {"window": 20})]
    assert first[0].equals(expected)
    assert second[0].equals(expected)
    assert recorder.summary()["physical_component_builds"] == 1
    assert recorder.summary()["component_cache_hits"] == 1
