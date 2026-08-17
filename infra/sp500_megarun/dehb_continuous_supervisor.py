"""Fail-closed health decisions for the continuous SP500 worker pool."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse


class ContinuousSupervisorError(RuntimeError):
    """Raised when production prerequisites are unsafe or incomplete."""


@dataclass(frozen=True)
class DatabaseContractV1:
    tls_required: bool
    max_connections: int
    required_connections: int = 400
    validation_opened: bool = False
    locked_opened: bool = False


@dataclass(frozen=True)
class PoolGenerationReservationV1:
    pool_generation: str
    dispatch: bool


@dataclass(frozen=True)
class PoolDecisionV1:
    action: str
    target_sessions: int
    target_slots: int
    active_sessions: int
    active_slots: int
    ready_work: int
    validation_opened: bool = False
    locked_opened: bool = False


def verify_database_contract(dsn: str, *, max_connections: int) -> DatabaseContractV1:
    """Reject non-TLS databases and pools too small for 360 long-lived workers."""

    parsed = urlparse(str(dsn))
    sslmode = parse_qs(parsed.query).get("sslmode", [""])[0].lower()
    if parsed.scheme not in {"postgres", "postgresql"} or sslmode not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise ContinuousSupervisorError("CONTINUOUS_DATABASE_TLS_REQUIRED")
    if int(max_connections) < 400:
        raise ContinuousSupervisorError("CONTINUOUS_DATABASE_CAPACITY_TOO_LOW")
    return DatabaseContractV1(tls_required=True, max_connections=int(max_connections))


def probe_database_client_capacity(
    dsn: str,
    *,
    required_connections: int = 400,
    connection_factory: Callable[[str], Any] | None = None,
    max_workers: int = 40,
) -> DatabaseContractV1:
    """Prove that the TLS endpoint accepts the required simultaneous clients."""

    required = int(required_connections)
    workers = int(max_workers)
    if required < 1 or required > 10_000 or workers < 1:
        raise ContinuousSupervisorError("CONTINUOUS_DATABASE_CAPACITY_PROBE_INVALID")
    contract = verify_database_contract(dsn, max_connections=required)

    if connection_factory is None:
        import psycopg

        def connection_factory(value: str) -> Any:
            return psycopg.connect(
                value,
                connect_timeout=15,
                autocommit=True,
            )

    def open_checked_connection() -> Any:
        connection = connection_factory(str(dsn))
        try:
            row = connection.execute("SELECT 1").fetchone()
            if row is None or int(row[0]) != 1:
                raise RuntimeError("database probe returned an invalid result")
            return connection
        except Exception:
            connection.close()
            raise

    connections: list[Any] = []
    first_error: BaseException | None = None
    try:
        with ThreadPoolExecutor(max_workers=min(required, workers)) as executor:
            futures = [executor.submit(open_checked_connection) for _ in range(required)]
            for future in as_completed(futures):
                try:
                    connections.append(future.result())
                except BaseException as exc:  # fail closed after all clients are reaped
                    if first_error is None:
                        first_error = exc
        if first_error is not None or len(connections) != required:
            raise ContinuousSupervisorError(
                "CONTINUOUS_DATABASE_CAPACITY_PROBE_FAILED"
            ) from first_error
        return contract
    finally:
        for connection in connections:
            connection.close()


class PoolSupervisor:
    """Make idempotent replacement decisions without touching scientific data."""

    def __init__(self) -> None:
        self._reserved_generations: set[str] = set()

    def reserve_generation(self, pool_generation: str) -> PoolGenerationReservationV1:
        generation = str(pool_generation).strip()
        if not generation:
            raise ContinuousSupervisorError("CONTINUOUS_POOL_GENERATION_INVALID")
        dispatch = generation not in self._reserved_generations
        self._reserved_generations.add(generation)
        return PoolGenerationReservationV1(generation, dispatch)

    def decide(
        self,
        *,
        campaign_state: str,
        active_sessions: int,
        active_slots: int,
        ready_work: int,
        coordinator_healthy: bool,
        conflict_count: int,
        boundary_violations: int,
    ) -> PoolDecisionV1:
        if int(conflict_count) > 0 or str(campaign_state) == "halted_conflict":
            action = "halt_conflict"
        elif int(boundary_violations) > 0 or str(campaign_state) == "halted_boundary":
            action = "halt_boundary"
        elif str(campaign_state) in {"freezing", "frozen", "halted_integrity"}:
            action = "drain"
        elif not coordinator_healthy:
            action = "recover_coordinator"
        elif int(active_sessions) < 355:
            action = "dispatch_next_generation"
        else:
            action = "healthy"
        return PoolDecisionV1(
            action=action,
            target_sessions=360,
            target_slots=1_440,
            active_sessions=int(active_sessions),
            active_slots=int(active_slots),
            ready_work=int(ready_work),
        )


__all__ = [
    "ContinuousSupervisorError",
    "DatabaseContractV1",
    "PoolDecisionV1",
    "PoolGenerationReservationV1",
    "PoolSupervisor",
    "probe_database_client_capacity",
    "verify_database_contract",
]
