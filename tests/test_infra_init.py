"""Smoke tests for aurora.infra package init re-exports."""
from __future__ import annotations


def test_package_importable():
    import aurora.infra as infra

    assert isinstance(infra.__all__, list)


def test_distributed_reexport():
    from aurora.infra import DistributedBacktester, DistributedConfig

    assert DistributedBacktester is not None
    assert DistributedConfig is not None


def test_gpu_runner_reexport():
    from aurora.infra import GPURunner, GPUConfig

    assert GPURunner is not None
    assert GPUConfig is not None


def test_cloud_sync_reexport():
    from aurora.infra import CloudSync, CloudConfig

    assert CloudSync is not None
    assert CloudConfig is not None


def test_postgres_reexport():
    from aurora.infra import PostgresRegistry, PostgresConfig

    assert PostgresRegistry is not None
    assert PostgresConfig is not None


def test_timescale_reexport():
    from aurora.infra import TimescaleAdapter, TimescaleConfig

    assert TimescaleAdapter is not None
    assert TimescaleConfig is not None


def test_parquet_reexport():
    from aurora.infra import (
        PartitionedParquetStore,
        ParquetPartitionConfig,
    )

    assert PartitionedParquetStore is not None
    assert ParquetPartitionConfig is not None


def test_redis_reexport():
    from aurora.infra import RedisCache, RedisCacheConfig

    assert RedisCache is not None
    assert RedisCacheConfig is not None


def test_observability_reexport():
    from aurora.infra import Observability, ObservabilityConfig

    assert Observability is not None
    assert ObservabilityConfig is not None
