"""Tests for quantforge.dataeng.flink_processor."""
from __future__ import annotations

import pytest

from quantforge.dataeng.flink_processor import (
    FlinkConfig,
    FlinkStreamProcessor,
)


@pytest.fixture
def proc() -> FlinkStreamProcessor:
    return FlinkStreamProcessor(FlinkConfig(parallelism=2), mock=True)


def test_map_then_filter(proc: FlinkStreamProcessor):
    out = (proc.map(lambda x: x * 2)
                .filter(lambda x: x > 5)
                .execute([1, 2, 3, 4, 5]))
    assert out == [6, 8, 10]


def test_topology_size_grows(proc: FlinkStreamProcessor):
    assert proc.topology_size() == 0
    proc.map(lambda x: x)
    proc.filter(lambda x: True)
    assert proc.topology_size() == 2


def test_reduce_sums(proc: FlinkStreamProcessor):
    out = proc.reduce(lambda a, b: a + b, initializer=0).execute([1, 2, 3, 4])
    assert out == 10


def test_reset_clears_topology(proc: FlinkStreamProcessor):
    proc.map(lambda x: x).filter(lambda x: True)
    proc.reset()
    assert proc.topology_size() == 0
    assert proc.execute([1, 2, 3]) == [1, 2, 3]


def test_empty_source_returns_empty(proc: FlinkStreamProcessor):
    out = proc.map(lambda x: x + 1).execute([])
    assert out == []
