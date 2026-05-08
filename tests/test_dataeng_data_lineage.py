"""Tests for quantforge.dataeng.data_lineage."""
from __future__ import annotations

import pytest

from quantforge.dataeng.data_lineage import (
    DataLineageTracker,
    LineageConfig,
    Transformation,
)


@pytest.fixture
def tracker() -> DataLineageTracker:
    return DataLineageTracker(LineageConfig(prefer_networkx=False))


def test_simple_chain_downstream(tracker: DataLineageTracker):
    tracker.add_transformation(Transformation("t1", ("raw",), ("staging",)))
    tracker.add_transformation(Transformation("t2", ("staging",), ("mart",)))
    assert tracker.downstream("raw") == ["mart", "staging"]
    assert tracker.upstream("mart") == ["raw", "staging"]


def test_no_cycle_in_dag(tracker: DataLineageTracker):
    tracker.add_transformation(Transformation("t1", ("a",), ("b",)))
    tracker.add_transformation(Transformation("t2", ("b",), ("c",)))
    assert tracker.has_cycle() is False


def test_detects_cycle(tracker: DataLineageTracker):
    tracker.add_transformation(Transformation("t1", ("a",), ("b",)))
    tracker.add_transformation(Transformation("t2", ("b",), ("a",)))
    assert tracker.has_cycle() is True


def test_unknown_node_returns_empty(tracker: DataLineageTracker):
    assert tracker.upstream("ghost") == []
    assert tracker.downstream("ghost") == []


def test_nodes_listed(tracker: DataLineageTracker):
    tracker.add_transformation(Transformation("t", ("x",), ("y",)))
    assert "x" in tracker.nodes()
    assert "y" in tracker.nodes()


def test_transformations_recorded(tracker: DataLineageTracker):
    t = Transformation("t1", ("a",), ("b",), description="join")
    tracker.add_transformation(t)
    assert tracker.transformations() == (t,)
