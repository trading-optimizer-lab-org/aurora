"""Infrastructure adapters for QuantForge v2.0.

Optional infra modules. Heavy SDKs (ray, dask, torch, boto3, psycopg2,
redis, prometheus_client, pyarrow.dataset) are imported lazily inside
methods. Each submodule remains importable when its underlying SDK is
missing, so ``import aurora.infra`` never fails because of a missing
optional dependency.
"""
from __future__ import annotations

__all__: list[str] = []


def _try_export(module_name: str, symbols: tuple[str, ...]) -> None:
    """Best-effort import a sibling module and re-export selected symbols.

    Failures are swallowed so that a single broken optional-dep submodule
    does not block ``import aurora.infra``. Importers can still target
    submodules directly to surface the underlying ImportError.
    """
    try:
        mod = __import__(f"aurora.infra.{module_name}", fromlist=symbols)
    except Exception:  # noqa: BLE001 - optional dep failures must not crash init
        return
    for sym in symbols:
        if hasattr(mod, sym):
            globals()[sym] = getattr(mod, sym)
            __all__.append(sym)


_try_export("distributed", ("DistributedBacktester", "DistributedConfig"))
_try_export("gpu_runner", ("GPURunner", "GPUConfig"))
_try_export("cloud_sync", ("CloudSync", "CloudConfig"))
_try_export("postgres_backend", ("PostgresRegistry", "PostgresConfig"))
_try_export("timescaledb", ("TimescaleAdapter", "TimescaleConfig"))
_try_export("parquet_partitioned", ("PartitionedParquetStore", "ParquetPartitionConfig"))
_try_export("redis_cache", ("RedisCache", "RedisCacheConfig"))
_try_export("observability", ("Observability", "ObservabilityConfig"))
