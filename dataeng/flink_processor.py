"""Flink stream processing topology stub with lazy ``pyflink`` import.

In mock mode operators run as plain Python list comprehensions on the input
batch, so unit tests can exercise topology composition without a JVM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class FlinkConfig:
    """Static config for :class:`FlinkStreamProcessor`.

    Attributes:
        parallelism: parallelism level requested from Flink.
        checkpoint_interval_ms: checkpoint cadence in milliseconds.
        job_name: human-readable job identifier.
    """
    parallelism: int = 1
    checkpoint_interval_ms: int = 60_000
    job_name: str = "aurora-flink-job"


class FlinkStreamProcessor:
    """Composable filter/map/reduce topology over an in-memory iterable."""

    def __init__(self, config: Optional[FlinkConfig] = None,
                 mock: bool = True) -> None:
        self.config = config or FlinkConfig()
        self.mock = bool(mock)
        self._ops: list[tuple[str, Any]] = []
        self._env = None

    # ------------------------------------------------------------------
    # Topology builders
    # ------------------------------------------------------------------
    def map(self, fn: Callable[[Any], Any]) -> "FlinkStreamProcessor":
        self._ops.append(("map", fn))
        return self

    def filter(self, fn: Callable[[Any], bool]) -> "FlinkStreamProcessor":
        self._ops.append(("filter", fn))
        return self

    def reduce(self, fn: Callable[[Any, Any], Any],
               initializer: Any = None) -> "FlinkStreamProcessor":
        self._ops.append(("reduce", (fn, initializer)))
        return self

    def reset(self) -> "FlinkStreamProcessor":
        self._ops.clear()
        return self

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute(self, source: list) -> Any:
        """Run topology over ``source``. Returns list or scalar reduce value."""
        if self.mock:
            return self._run_local(list(source))
        return self._run_flink(source)  # pragma: no cover

    def _run_local(self, source: list) -> Any:
        data: Any = source
        for kind, op in self._ops:
            if kind == "map":
                data = [op(x) for x in data]
            elif kind == "filter":
                data = [x for x in data if op(x)]
            elif kind == "reduce":
                fn, init = op
                acc = init
                for x in data:
                    acc = fn(acc, x) if acc is not None else x
                return acc
        return data

    def _run_flink(self, source: list) -> Any:  # pragma: no cover
        try:
            from pyflink.datastream import StreamExecutionEnvironment
        except ImportError as e:
            raise ImportError("pyflink required for live mode") from e
        env = StreamExecutionEnvironment.get_execution_environment()
        env.set_parallelism(self.config.parallelism)
        ds = env.from_collection(source)
        for kind, op in self._ops:
            if kind == "map":
                ds = ds.map(op)
            elif kind == "filter":
                ds = ds.filter(op)
        ds.print()
        env.execute(self.config.job_name)
        return []

    def topology_size(self) -> int:
        return len(self._ops)
