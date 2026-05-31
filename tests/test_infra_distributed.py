"""Tests for aurora.infra.distributed.DistributedBacktester."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from aurora.infra.distributed import DistributedBacktester, DistributedConfig


def _square(x: int) -> int:
    return x * x


def test_local_backend_runs_sequentially():
    runner = DistributedBacktester(DistributedConfig(backend="local"))
    assert runner.resolved_backend == "local"
    assert runner.map(_square, [1, 2, 3, 4]) == [1, 4, 9, 16]


def test_empty_input_returns_empty_list():
    runner = DistributedBacktester(DistributedConfig(backend="local"))
    assert runner.map(_square, []) == []


def test_invalid_backend_raises():
    with pytest.raises(ValueError):
        DistributedBacktester(DistributedConfig(backend="bogus"))


def test_auto_falls_back_to_local_when_no_sdk():
    with patch.object(DistributedBacktester, "_has_ray", return_value=False), \
         patch.object(DistributedBacktester, "_has_dask", return_value=False):
        runner = DistributedBacktester(DistributedConfig(backend="auto"))
        assert runner.resolved_backend == "local"
        assert runner.map(_square, [3]) == [9]


def test_ray_request_falls_back_to_local_when_missing():
    with patch.object(DistributedBacktester, "_has_ray", return_value=False):
        runner = DistributedBacktester(DistributedConfig(backend="ray"))
        assert runner.resolved_backend == "local"


def test_dask_request_falls_back_to_local_when_missing():
    with patch.object(DistributedBacktester, "_has_dask", return_value=False):
        runner = DistributedBacktester(DistributedConfig(backend="dask"))
        assert runner.resolved_backend == "local"


def test_auto_picks_ray_when_available():
    with patch.object(DistributedBacktester, "_has_ray", return_value=True), \
         patch.object(DistributedBacktester, "_has_dask", return_value=True):
        runner = DistributedBacktester(DistributedConfig(backend="auto"))
        assert runner.resolved_backend == "ray"
