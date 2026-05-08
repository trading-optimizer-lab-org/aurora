"""Data engineering modules for QuantForge v3.0.

Each module exposes a primary class with a dataclass config and a main method.
External dependencies (kafka, flink, dbt, great_expectations, networkx) are
imported lazily so the package is importable without them. All modules ship a
deterministic ``mock=True`` path for offline testing.
"""
from __future__ import annotations

__all__: list[str] = []


def _try_export(module_name: str, symbols: tuple[str, ...]) -> None:
    try:
        mod = __import__(f"quantforge.dataeng.{module_name}", fromlist=symbols)
    except Exception:  # noqa: BLE001
        return
    for sym in symbols:
        if hasattr(mod, sym):
            globals()[sym] = getattr(mod, sym)
            __all__.append(sym)


_try_export("kafka_streams", ("KafkaEventStream", "KafkaConfig"))
_try_export("flink_processor", ("FlinkStreamProcessor", "FlinkConfig"))
_try_export("airflow_dags", ("AirflowDAGGenerator", "AirflowConfig"))
_try_export("dbt_runner", ("DBTRunner", "DBTConfig"))
_try_export("great_expectations", ("DataQualityValidator", "GEConfig"))
_try_export("data_lineage", ("DataLineageTracker", "LineageConfig"))
_try_export("schema_registry", ("SchemaRegistry", "SchemaRegistryConfig"))
_try_export("cdc_capture", ("ChangeDataCapture", "CDCConfig"))
_try_export("materialized_views", ("MaterializedViewManager", "MVConfig"))
_try_export("star_schema", ("StarSchemaWarehouse", "StarSchemaConfig"))
