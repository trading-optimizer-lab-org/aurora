"""Distributed strategy generation scaffold (R90).

Plan + scaffold for distributing the R77 strategy generator across N
workers coordinated by a central node. Each worker is sandboxed,
generates K candidates, hands them back to the central factory for
validation. Pairs with R7 (snapshot store) so workers see the same
snapshots, and R71 (isolation) so concurrent runs do not collide.

Distinct from `infra/distributed.py` (which wraps the backtester
with ray/dask). This module is the FACTORY-side coordinator: it
fans out generation tasks, not backtest tasks.

This module ships:

- :class:`WorkerSpec` -- per-worker description.
- :class:`WorkUnit` -- one generation task assigned to a worker.
- :class:`Coordinator` -- in-process stub that operators can replace
  with Ray / Dask / a queue worker (RabbitMQ, SQS) without changing
  the consumer surface.

The in-process stub lets the rest of the project depend on a stable
interface even when the production deployment is single-machine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class WorkerSpec:
    """One worker the coordinator can assign tasks to."""

    worker_id: str
    max_concurrent: int = 1
    capabilities: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WorkUnit:
    """One generation task."""

    unit_id: str
    seed: int
    n_candidates: int
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkResult:
    """Outcome of a single :class:`WorkUnit`."""

    unit_id: str
    worker_id: str
    n_candidates_returned: int
    finished_at: str
    error: Optional[str] = None


@dataclass
class Coordinator:
    """In-process stub coordinator.

    Operators that want a real distributed runtime swap out the
    backend by inheriting from this class and overriding ``dispatch``.
    The :class:`WorkUnit` / :class:`WorkResult` contract stays the
    same so consumers (factory, daily ops, audit) do not change.
    """

    workers: List[WorkerSpec] = field(default_factory=list)
    _round_robin_idx: int = 0

    def add_worker(self, spec: WorkerSpec) -> None:
        self.workers.append(spec)

    def dispatch(
        self,
        units: List[WorkUnit],
        *,
        run_unit: Callable[[WorkerSpec, WorkUnit], WorkResult],
    ) -> List[WorkResult]:
        """Run every unit on a chosen worker; return ordered results.

        Args:
            units: list of work units to dispatch.
            run_unit: callable that runs ONE unit on ONE worker. The
                in-process stub calls it sequentially. Real
                coordinators dispatch the call to a remote worker.

        Returns:
            One :class:`WorkResult` per input unit, same order.
        """
        if not self.workers:
            raise ValueError("coordinator has no workers; add one first")
        out: List[WorkResult] = []
        for unit in units:
            worker = self._next_worker()
            try:
                res = run_unit(worker, unit)
            except Exception as exc:  # noqa: BLE001 -- surface per-unit errors
                res = WorkResult(
                    unit_id=unit.unit_id,
                    worker_id=worker.worker_id,
                    n_candidates_returned=0,
                    finished_at=datetime.utcnow().isoformat(),
                    error=f"{type(exc).__name__}: {exc}",
                )
            out.append(res)
        return out

    def _next_worker(self) -> WorkerSpec:
        worker = self.workers[self._round_robin_idx % len(self.workers)]
        self._round_robin_idx += 1
        return worker


__all__ = [
    "WorkerSpec",
    "WorkUnit",
    "WorkResult",
    "Coordinator",
]
