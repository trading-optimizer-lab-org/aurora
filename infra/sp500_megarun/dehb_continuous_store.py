"""Transactional store contract for continuous SP500 DEHB coordination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
from threading import Condition, RLock
import time
from typing import Callable, Protocol
import uuid
from urllib.parse import parse_qs, urlparse

from aurora.infra.sp500_megarun.dehb_continuous_models import (
    EvaluationCacheKeyV2,
    EvaluationProposalV2,
    EvaluationResultV2,
    StrategyEvaluationKeyV1,
)
from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
    normalize_scientific_result,
    scientific_result_sha256,
)


class ContinuousStoreError(RuntimeError):
    """Base class for continuous campaign persistence failures."""


class LeaseLostError(ContinuousStoreError):
    """Raised when a completion no longer owns the evaluation lease."""


class ResultConflictError(ContinuousStoreError):
    """Raised when one scientific key produces two result hashes."""


class WorkerCapacityError(ContinuousStoreError):
    """Raised when all 360 GitHub worker-session permits are occupied."""


class PostgresStoreConfigurationError(ContinuousStoreError):
    """Raised before connecting when PostgreSQL transport is unsafe or incomplete."""


@dataclass(frozen=True)
class ProposalRegistrationV1:
    proposal_id: int
    evaluation_id: int
    evaluation_key: EvaluationCacheKeyV2
    physical_work_created: bool
    cache_hit: bool


@dataclass(frozen=True)
class WorkerSessionLeaseV1:
    worker_session_id: str
    permit_number: int
    lease_expires_at: datetime


@dataclass(frozen=True)
class EvaluationLeaseV1:
    evaluation_id: int
    cache_key_sha256: str
    evaluation_key: EvaluationCacheKeyV2
    lease_token: str
    worker_session_id: str
    slot_index: int
    lease_expires_at: datetime


@dataclass(frozen=True)
class EvaluationCompletionV1:
    evaluation_id: int
    result_sha256: str
    subscriber_count: int


@dataclass(frozen=True)
class StrategyClaimV1:
    strategy_key_sha256: str
    owner: bool
    result: dict | None


@dataclass(frozen=True)
class StoredIslandV1:
    island_id: str
    lane_id: str
    replica: int
    restart_seed: int
    status: str
    next_batch_sequence: int
    checkpoint_bytes: bytes | None
    checkpoint_sha256: str | None
    runtime_state: dict


@dataclass
class _StrategyRecord:
    owner_evaluation_id: int
    result: dict | None = None
    result_sha256: str | None = None


class ContinuousCampaignStore(Protocol):
    """Behavior required by coordinators and physical workers."""

    def register_proposal(self, proposal: EvaluationProposalV2) -> ProposalRegistrationV1: ...

    def claim_evaluation(
        self, *, worker_session_id: str, slot_index: int, lease_seconds: int
    ) -> EvaluationLeaseV1 | None: ...

    def complete_evaluation(
        self, lease: EvaluationLeaseV1, result: EvaluationResultV2
    ) -> EvaluationCompletionV1: ...


@dataclass
class _EvaluationRecord:
    evaluation_id: int
    key: EvaluationCacheKeyV2
    state: str = "ready"
    lease: EvaluationLeaseV1 | None = None
    result: EvaluationResultV2 | None = None


@dataclass
class _WorkerSession:
    lease: WorkerSessionLeaseV1
    pool_generation: str
    github_run_id: int
    github_job: str
    state: str = "active"


class InMemoryContinuousCampaignStore:
    """Thread-safe executable reference for the PostgreSQL transaction contract."""

    def __init__(
        self,
        *,
        campaign_id: str,
        scientific_contract_sha256: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.campaign_id = str(campaign_id)
        self.scientific_contract_sha256 = str(scientific_contract_sha256)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._strategy_condition = Condition(self._lock)
        self._state = "searching"
        self._next_evaluation_id = 1
        self._next_proposal_id = 1
        self._evaluations_by_key: dict[str, _EvaluationRecord] = {}
        self._evaluations_by_id: dict[int, _EvaluationRecord] = {}
        self._proposals: dict[tuple[str, int, int], tuple[int, int]] = {}
        self._subscribers: dict[int, set[int]] = {}
        self._sessions: dict[str, _WorkerSession] = {}
        self._slots: dict[tuple[str, int], int] = {}
        self._coordinator_owner_token: str | None = None
        self._coordinator_lease_expires_at: datetime | None = None
        self._island_checkpoint_hashes: dict[str, str] = {}
        self._open_island_batches: set[tuple[str, int]] = set()
        self._strategies: dict[str, _StrategyRecord] = {}

    def register_proposal(self, proposal: EvaluationProposalV2) -> ProposalRegistrationV1:
        if proposal.campaign_id != self.campaign_id:
            raise ContinuousStoreError("CONTINUOUS_PROPOSAL_CAMPAIGN_MISMATCH")
        identity = (proposal.island_id, proposal.batch_sequence, proposal.batch_slot)
        with self._lock:
            existing_proposal = self._proposals.get(identity)
            if existing_proposal is not None:
                proposal_id, evaluation_id = existing_proposal
                record = self._evaluations_by_id[evaluation_id]
                if record.key.sha256 != proposal.evaluation_key.sha256:
                    raise ResultConflictError("CONTINUOUS_PROPOSAL_IDENTITY_CONFLICT")
                return ProposalRegistrationV1(
                    proposal_id=proposal_id,
                    evaluation_id=evaluation_id,
                    evaluation_key=record.key,
                    physical_work_created=False,
                    cache_hit=record.state == "completed",
                )

            record = self._evaluations_by_key.get(proposal.evaluation_key.sha256)
            physical_work_created = record is None
            if record is None:
                record = _EvaluationRecord(
                    evaluation_id=self._next_evaluation_id,
                    key=proposal.evaluation_key,
                )
                self._next_evaluation_id += 1
                self._evaluations_by_key[record.key.sha256] = record
                self._evaluations_by_id[record.evaluation_id] = record
                self._subscribers[record.evaluation_id] = set()

            proposal_id = self._next_proposal_id
            self._next_proposal_id += 1
            self._proposals[identity] = (proposal_id, record.evaluation_id)
            self._subscribers[record.evaluation_id].add(proposal_id)
            return ProposalRegistrationV1(
                proposal_id=proposal_id,
                evaluation_id=record.evaluation_id,
                evaluation_key=record.key,
                physical_work_created=physical_work_created,
                cache_hit=record.state == "completed",
            )

    def claim_worker_session(
        self,
        *,
        pool_generation: str,
        github_run_id: int,
        github_job: str,
        lease_seconds: int,
    ) -> WorkerSessionLeaseV1:
        if lease_seconds < 1:
            raise ContinuousStoreError("CONTINUOUS_WORKER_LEASE_SECONDS_INVALID")
        with self._lock:
            used = {
                session.lease.permit_number
                for session in self._sessions.values()
                if session.state != "closed"
            }
            permit = next((number for number in range(1, 361) if number not in used), None)
            if permit is None:
                raise WorkerCapacityError("CONTINUOUS_WORKER_SESSION_CAPACITY")
            session_id = str(uuid.uuid4())
            lease = WorkerSessionLeaseV1(
                worker_session_id=session_id,
                permit_number=permit,
                lease_expires_at=self._clock() + timedelta(seconds=lease_seconds),
            )
            self._sessions[session_id] = _WorkerSession(
                lease=lease,
                pool_generation=str(pool_generation),
                github_run_id=int(github_run_id),
                github_job=str(github_job),
            )
            return lease

    def close_worker_session(self, worker_session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(str(worker_session_id))
            if session is None:
                raise ContinuousStoreError("CONTINUOUS_WORKER_SESSION_UNKNOWN")
            for slot_key, evaluation_id in list(self._slots.items()):
                if slot_key[0] != worker_session_id:
                    continue
                record = self._evaluations_by_id[evaluation_id]
                if record.state == "leased":
                    record.state = "ready"
                    record.lease = None
                del self._slots[slot_key]
            session.state = "closed"

    def claim_evaluation(
        self,
        *,
        worker_session_id: str,
        slot_index: int,
        lease_seconds: int,
    ) -> EvaluationLeaseV1 | None:
        if slot_index not in range(4):
            raise ContinuousStoreError("CONTINUOUS_WORKER_SLOT_INVALID")
        if lease_seconds < 1:
            raise ContinuousStoreError("CONTINUOUS_EVALUATION_LEASE_SECONDS_INVALID")
        with self._lock:
            session = self._sessions.get(str(worker_session_id))
            if session is None or session.state != "active":
                raise ContinuousStoreError("CONTINUOUS_WORKER_SESSION_NOT_ACTIVE")
            slot_key = (str(worker_session_id), slot_index)
            if slot_key in self._slots:
                raise ContinuousStoreError("CONTINUOUS_WORKER_SLOT_OCCUPIED")
            record = next(
                (
                    item
                    for item in sorted(
                        self._evaluations_by_id.values(), key=lambda value: value.evaluation_id
                    )
                    if item.state == "ready"
                ),
                None,
            )
            if record is None:
                return None
            lease = EvaluationLeaseV1(
                evaluation_id=record.evaluation_id,
                cache_key_sha256=record.key.sha256,
                evaluation_key=record.key,
                lease_token=secrets.token_hex(32),
                worker_session_id=str(worker_session_id),
                slot_index=slot_index,
                lease_expires_at=self._clock() + timedelta(seconds=lease_seconds),
            )
            record.state = "leased"
            record.lease = lease
            self._slots[slot_key] = record.evaluation_id
            return lease

    def requeue_expired_leases(self) -> int:
        now = self._clock()
        count = 0
        with self._lock:
            for record in self._evaluations_by_id.values():
                if (
                    record.state == "leased"
                    and record.lease is not None
                    and record.lease.lease_expires_at < now
                ):
                    slot_key = (record.lease.worker_session_id, record.lease.slot_index)
                    self._slots.pop(slot_key, None)
                    record.lease = None
                    record.state = "ready"
                    count += 1
        return count

    def complete_evaluation(
        self,
        lease: EvaluationLeaseV1,
        result: EvaluationResultV2,
    ) -> EvaluationCompletionV1:
        with self._lock:
            record = self._evaluations_by_id.get(lease.evaluation_id)
            if record is None or record.key.sha256 != result.key.sha256:
                raise ContinuousStoreError("CONTINUOUS_EVALUATION_RESULT_KEY_MISMATCH")
            if record.result is not None:
                if record.result.result_sha256 != result.result_sha256:
                    self._state = "halted_conflict"
                    raise ResultConflictError("CONTINUOUS_RESULT_HASH_CONFLICT")
                return EvaluationCompletionV1(
                    evaluation_id=record.evaluation_id,
                    result_sha256=record.result.result_sha256,
                    subscriber_count=len(self._subscribers[record.evaluation_id]),
                )
            if record.lease is None or record.lease.lease_token != lease.lease_token:
                raise LeaseLostError("CONTINUOUS_EVALUATION_LEASE_LOST")
            record.result = result
            record.state = "completed"
            record.lease = None
            self._slots.pop((lease.worker_session_id, lease.slot_index), None)
            return EvaluationCompletionV1(
                evaluation_id=record.evaluation_id,
                result_sha256=result.result_sha256,
                subscriber_count=len(self._subscribers[record.evaluation_id]),
            )

    def claim_strategy_evaluation(
        self,
        *,
        evaluation_id: int,
        strategy_key: StrategyEvaluationKeyV1,
    ) -> StrategyClaimV1:
        with self._strategy_condition:
            record = self._strategies.get(strategy_key.sha256)
            if record is None:
                self._strategies[strategy_key.sha256] = _StrategyRecord(
                    owner_evaluation_id=int(evaluation_id)
                )
                return StrategyClaimV1(strategy_key.sha256, True, None)
            return StrategyClaimV1(
                strategy_key.sha256,
                False,
                None if record.result is None else dict(record.result),
            )

    def complete_strategy_evaluation(
        self,
        *,
        evaluation_id: int,
        strategy_key: StrategyEvaluationKeyV1,
        result: dict,
    ) -> dict:
        normalized = dict(normalize_scientific_result(result))
        result_hash = scientific_result_sha256(normalized)
        with self._strategy_condition:
            record = self._strategies.get(strategy_key.sha256)
            if record is None or record.owner_evaluation_id != int(evaluation_id):
                raise LeaseLostError("CONTINUOUS_STRATEGY_OWNERSHIP_LOST")
            if record.result_sha256 is not None and record.result_sha256 != result_hash:
                self._state = "halted_conflict"
                raise ResultConflictError("CONTINUOUS_STRATEGY_RESULT_HASH_CONFLICT")
            record.result = normalized
            record.result_sha256 = result_hash
            self._strategy_condition.notify_all()
            return dict(normalized)

    def wait_strategy_result(
        self,
        *,
        strategy_key: StrategyEvaluationKeyV1,
        timeout_seconds: float,
    ) -> dict:
        with self._strategy_condition:
            ready = self._strategy_condition.wait_for(
                lambda: (
                    strategy_key.sha256 in self._strategies
                    and self._strategies[strategy_key.sha256].result is not None
                ),
                timeout=float(timeout_seconds),
            )
            if not ready:
                raise ContinuousStoreError("CONTINUOUS_STRATEGY_RESULT_TIMEOUT")
            result = self._strategies[strategy_key.sha256].result
            if result is None:  # pragma: no cover - condition invariant
                raise ContinuousStoreError("CONTINUOUS_STRATEGY_RESULT_MISSING")
            return dict(result)

    def campaign_state(self) -> str:
        with self._lock:
            return self._state

    def acquire_coordinator_leadership(self, owner_token: str, lease_seconds: int) -> bool:
        now = self._clock()
        with self._lock:
            expired = (
                self._coordinator_lease_expires_at is None
                or self._coordinator_lease_expires_at < now
            )
            if (
                self._coordinator_owner_token not in {None, str(owner_token)}
                and not expired
            ):
                return False
            self._coordinator_owner_token = str(owner_token)
            self._coordinator_lease_expires_at = now + timedelta(seconds=lease_seconds)
            return True

    def coordinator_owner(self) -> str | None:
        with self._lock:
            if (
                self._coordinator_lease_expires_at is not None
                and self._coordinator_lease_expires_at < self._clock()
            ):
                self._coordinator_owner_token = None
                self._coordinator_lease_expires_at = None
            return self._coordinator_owner_token

    def release_coordinator_leadership(self, owner_token: str) -> None:
        with self._lock:
            if self._coordinator_owner_token == str(owner_token):
                self._coordinator_owner_token = None
                self._coordinator_lease_expires_at = None

    def resolved_batch_results(
        self,
        *,
        island_id: str,
        batch_sequence: int,
    ) -> dict[int, dict] | None:
        with self._lock:
            resolved: dict[int, dict] = {}
            for slot in range(4):
                proposal_record = self._proposals.get(
                    (str(island_id), int(batch_sequence), slot)
                )
                if proposal_record is None:
                    return None
                evaluation = self._evaluations_by_id[proposal_record[1]]
                if evaluation.result is None:
                    return None
                resolved[slot] = dict(evaluation.result.result)
            return resolved

    def record_island_advance(self, advance: object) -> None:
        island_id = str(getattr(advance, "island_id"))
        prior = getattr(advance, "prior_checkpoint_sha256")
        checkpoint = str(getattr(advance, "checkpoint_sha256"))
        with self._lock:
            if self._island_checkpoint_hashes.get(island_id) != prior:
                raise ResultConflictError("CONTINUOUS_ISLAND_CHECKPOINT_CHAIN_CONFLICT")
            self._island_checkpoint_hashes[island_id] = checkpoint
            self._open_island_batches.discard(
                (island_id, int(getattr(advance, "batch_sequence")))
            )

    def open_island_batch(self, batch: object) -> None:
        identity = (
            str(getattr(batch, "island_id")),
            int(getattr(batch, "batch_sequence")),
        )
        with self._lock:
            self._open_island_batches.add(identity)

    def count_open_island_batches(self) -> int:
        with self._lock:
            return len(self._open_island_batches)

    def count_ready_work_items(self) -> int:
        with self._lock:
            return sum(record.state == "ready" for record in self._evaluations_by_id.values())

    def count_subscribers(self) -> int:
        with self._lock:
            return sum(len(value) for value in self._subscribers.values())

    def count_completed_subscribers(self) -> int:
        with self._lock:
            return sum(
                len(self._subscribers[record.evaluation_id])
                for record in self._evaluations_by_id.values()
                if record.state == "completed"
            )

    def count_physical_completions(self) -> int:
        with self._lock:
            return sum(record.result is not None for record in self._evaluations_by_id.values())

    def maximum_active_leases_per_key(self) -> int:
        with self._lock:
            counts = [1 for record in self._evaluations_by_id.values() if record.state == "leased"]
            return max(counts, default=0)


class PostgresContinuousCampaignStore:
    """Psycopg-backed implementation using short transaction-pooler-safe claims."""

    def __init__(
        self,
        *,
        dsn: str,
        campaign_id: str,
        pool: object | None = None,
        pool_min_size: int = 1,
        pool_max_size: int = 6,
    ) -> None:
        parsed = urlparse(str(dsn))
        sslmode = parse_qs(parsed.query).get("sslmode", [""])[0].lower()
        if parsed.scheme not in {"postgres", "postgresql"} or sslmode not in {
            "require",
            "verify-ca",
            "verify-full",
        }:
            raise PostgresStoreConfigurationError("CONTINUOUS_POSTGRES_TLS_REQUIRED")
        if not str(campaign_id):
            raise PostgresStoreConfigurationError("CONTINUOUS_POSTGRES_CAMPAIGN_ID_REQUIRED")
        self.campaign_id = str(campaign_id)
        if pool is None:
            try:
                from psycopg_pool import ConnectionPool
            except ImportError as exc:  # pragma: no cover - dependency gate
                raise PostgresStoreConfigurationError(
                    "CONTINUOUS_POSTGRES_PSYCOPG_REQUIRED"
                ) from exc
            pool = ConnectionPool(
                conninfo=str(dsn),
                min_size=int(pool_min_size),
                max_size=int(pool_max_size),
                kwargs={"autocommit": False},
                open=True,
            )
        self._pool = pool

    @staticmethod
    def _jsonb(value: object) -> object:
        from psycopg.types.json import Jsonb

        return Jsonb(value)

    def _next_sequence(self, cursor: object) -> int:
        cursor.execute(
            """
            UPDATE campaigns
            SET next_event_sequence = next_event_sequence + 1,
                updated_at = clock_timestamp()
            WHERE campaign_id = %s AND state NOT LIKE 'halted_%%'
            RETURNING next_event_sequence - 1
            """,
            (self.campaign_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ContinuousStoreError("CONTINUOUS_CAMPAIGN_NOT_MUTABLE")
        return int(row[0])

    @staticmethod
    def _serializable(cursor: object) -> None:
        cursor.execute("SET LOCAL TRANSACTION ISOLATION LEVEL SERIALIZABLE")

    def register_proposal(self, proposal: EvaluationProposalV2) -> ProposalRegistrationV1:
        if proposal.campaign_id != self.campaign_id:
            raise ContinuousStoreError("CONTINUOUS_PROPOSAL_CAMPAIGN_MISMATCH")
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                self._serializable(cursor)
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    INSERT INTO evaluations (
                        campaign_id, schema_version, cache_key_sha256, key_payload,
                        state, created_sequence, updated_sequence
                    ) VALUES (%s, 2, %s, %s, 'ready', %s, %s)
                    ON CONFLICT (campaign_id, cache_key_sha256) DO NOTHING
                    RETURNING evaluation_id
                    """,
                    (
                        self.campaign_id,
                        proposal.evaluation_key.sha256,
                        self._jsonb(dict(proposal.evaluation_key.payload)),
                        sequence,
                        sequence,
                    ),
                )
                inserted = cursor.fetchone()
                physical_work_created = inserted is not None
                if inserted is None:
                    cursor.execute(
                        """
                        SELECT evaluation_id, state
                        FROM evaluations
                        WHERE campaign_id = %s AND cache_key_sha256 = %s
                        """,
                        (self.campaign_id, proposal.evaluation_key.sha256),
                    )
                    evaluation_row = cursor.fetchone()
                    if evaluation_row is None:
                        raise ContinuousStoreError("CONTINUOUS_EVALUATION_UPSERT_LOST")
                    evaluation_id, evaluation_state = int(evaluation_row[0]), str(
                        evaluation_row[1]
                    )
                else:
                    evaluation_id, evaluation_state = int(inserted[0]), "ready"
                    cursor.execute(
                        """
                        INSERT INTO work_items (
                            campaign_id, evaluation_id, schema_version, state,
                            created_sequence, updated_sequence
                        ) VALUES (%s, %s, 1, 'ready', %s, %s)
                        """,
                        (self.campaign_id, evaluation_id, sequence, sequence),
                    )
                cursor.execute(
                    """
                    INSERT INTO proposals (
                        campaign_id, island_id, batch_sequence, batch_slot,
                        schema_version, evaluation_id, dehb_job,
                        created_sequence, updated_sequence
                    ) VALUES (%s, %s, %s, %s, 2, %s, %s, %s, %s)
                    ON CONFLICT (campaign_id, island_id, batch_sequence, batch_slot)
                    DO NOTHING
                    RETURNING proposal_id
                    """,
                    (
                        self.campaign_id,
                        proposal.island_id,
                        proposal.batch_sequence,
                        proposal.batch_slot,
                        evaluation_id,
                        self._jsonb(dict(proposal.dehb_job)),
                        sequence,
                        sequence,
                    ),
                )
                proposal_row = cursor.fetchone()
                if proposal_row is None:
                    cursor.execute(
                        """
                        SELECT proposal_id, evaluation_id
                        FROM proposals
                        WHERE campaign_id = %s AND island_id = %s
                          AND batch_sequence = %s AND batch_slot = %s
                        """,
                        (
                            self.campaign_id,
                            proposal.island_id,
                            proposal.batch_sequence,
                            proposal.batch_slot,
                        ),
                    )
                    existing = cursor.fetchone()
                    if existing is None or int(existing[1]) != evaluation_id:
                        raise ResultConflictError("CONTINUOUS_PROPOSAL_IDENTITY_CONFLICT")
                    proposal_id = int(existing[0])
                else:
                    proposal_id = int(proposal_row[0])
                cursor.execute(
                    """
                    INSERT INTO evaluation_subscribers (
                        campaign_id, evaluation_id, proposal_id, schema_version,
                        created_sequence, updated_sequence
                    ) VALUES (%s, %s, %s, 1, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        self.campaign_id,
                        evaluation_id,
                        proposal_id,
                        sequence,
                        sequence,
                    ),
                )
        return ProposalRegistrationV1(
            proposal_id=proposal_id,
            evaluation_id=evaluation_id,
            evaluation_key=proposal.evaluation_key,
            physical_work_created=physical_work_created,
            cache_hit=evaluation_state == "completed",
        )

    def claim_worker_session(
        self,
        *,
        pool_generation: str,
        github_run_id: int,
        github_job: str,
        lease_seconds: int,
    ) -> WorkerSessionLeaseV1:
        if lease_seconds < 1:
            raise ContinuousStoreError("CONTINUOUS_WORKER_LEASE_SECONDS_INVALID")
        session_id = str(uuid.uuid4())
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                self._serializable(cursor)
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 360))",
                    (self.campaign_id,),
                )
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    UPDATE worker_sessions
                    SET state = 'closed', updated_sequence = %s,
                        updated_at = clock_timestamp()
                    WHERE campaign_id = %s AND state <> 'closed'
                      AND lease_expires_at < clock_timestamp()
                    """,
                    (sequence, self.campaign_id),
                )
                cursor.execute(
                    """
                    SELECT permit
                    FROM generate_series(1, 360) AS permit
                    WHERE NOT EXISTS (
                        SELECT 1 FROM worker_sessions
                        WHERE campaign_id = %s AND permit_number = permit
                          AND state <> 'closed'
                    )
                    ORDER BY permit
                    LIMIT 1
                    """,
                    (self.campaign_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise WorkerCapacityError("CONTINUOUS_WORKER_SESSION_CAPACITY")
                permit = int(row[0])
                cursor.execute(
                    """
                    INSERT INTO worker_sessions (
                        worker_session_id, campaign_id, schema_version,
                        pool_generation, github_run_id, github_job, permit_number,
                        state, lease_expires_at, created_sequence, updated_sequence
                    ) VALUES (
                        %s, %s, 1, %s, %s, %s, %s, 'active',
                        clock_timestamp() + make_interval(secs => %s), %s, %s
                    ) RETURNING lease_expires_at
                    """,
                    (
                        session_id,
                        self.campaign_id,
                        str(pool_generation),
                        int(github_run_id),
                        str(github_job),
                        permit,
                        int(lease_seconds),
                        sequence,
                        sequence,
                    ),
                )
                expires = cursor.fetchone()[0]
        return WorkerSessionLeaseV1(session_id, permit, expires)

    def claim_evaluation(
        self,
        *,
        worker_session_id: str,
        slot_index: int,
        lease_seconds: int,
    ) -> EvaluationLeaseV1 | None:
        if slot_index not in range(4):
            raise ContinuousStoreError("CONTINUOUS_WORKER_SLOT_INVALID")
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    SELECT 1 FROM worker_sessions
                    WHERE worker_session_id = %s AND campaign_id = %s
                      AND state = 'active' AND lease_expires_at >= clock_timestamp()
                    FOR UPDATE
                    """,
                    (worker_session_id, self.campaign_id),
                )
                if cursor.fetchone() is None:
                    raise ContinuousStoreError("CONTINUOUS_WORKER_SESSION_NOT_ACTIVE")
                cursor.execute(
                    """
                    SELECT w.work_item_id, w.evaluation_id, e.cache_key_sha256,
                           e.key_payload
                    FROM work_items w
                    JOIN evaluations e ON e.evaluation_id = w.evaluation_id
                    WHERE w.campaign_id = %s AND w.state = 'ready'
                    ORDER BY w.priority DESC, w.work_item_id
                    FOR UPDATE OF w SKIP LOCKED
                    LIMIT 1
                    """,
                    (self.campaign_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                work_item_id, evaluation_id, key_sha256, key_payload = row
                token = secrets.token_hex(32)
                cursor.execute(
                    """
                    INSERT INTO worker_slot_leases (
                        campaign_id, worker_session_id, slot_index, schema_version,
                        lease_token, lease_expires_at, created_sequence, updated_sequence
                    ) VALUES (
                        %s, %s, %s, 1, %s,
                        clock_timestamp() + make_interval(secs => %s), %s, %s
                    )
                    """,
                    (
                        self.campaign_id,
                        worker_session_id,
                        slot_index,
                        token,
                        int(lease_seconds),
                        sequence,
                        sequence,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE work_items SET state = 'leased', lease_token = %s,
                        leased_by_session_id = %s, leased_by_slot = %s,
                        lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                        attempt_count = attempt_count + 1, updated_sequence = %s,
                        updated_at = clock_timestamp()
                    WHERE work_item_id = %s
                    RETURNING lease_expires_at
                    """,
                    (
                        token,
                        worker_session_id,
                        slot_index,
                        int(lease_seconds),
                        sequence,
                        int(work_item_id),
                    ),
                )
                expires = cursor.fetchone()[0]
                cursor.execute(
                    """
                    UPDATE evaluations SET state = 'leased', updated_sequence = %s,
                        updated_at = clock_timestamp() WHERE evaluation_id = %s
                    """,
                    (sequence, int(evaluation_id)),
                )
        key = EvaluationCacheKeyV2(sha256=str(key_sha256), payload=dict(key_payload))
        return EvaluationLeaseV1(
            evaluation_id=int(evaluation_id),
            cache_key_sha256=str(key_sha256),
            evaluation_key=key,
            lease_token=token,
            worker_session_id=str(worker_session_id),
            slot_index=int(slot_index),
            lease_expires_at=expires,
        )

    def complete_evaluation(
        self,
        lease: EvaluationLeaseV1,
        result: EvaluationResultV2,
    ) -> EvaluationCompletionV1:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                self._serializable(cursor)
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    SELECT w.lease_token, w.state, r.result_sha256
                    FROM work_items w
                    LEFT JOIN results r ON r.evaluation_id = w.evaluation_id
                    WHERE w.campaign_id = %s AND w.evaluation_id = %s
                    FOR UPDATE OF w
                    """,
                    (self.campaign_id, lease.evaluation_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ContinuousStoreError("CONTINUOUS_EVALUATION_UNKNOWN")
                active_token, state, existing_hash = row
                if existing_hash is not None:
                    if str(existing_hash) != result.result_sha256:
                        cursor.execute(
                            "UPDATE campaigns SET state = 'halted_conflict' WHERE campaign_id = %s",
                            (self.campaign_id,),
                        )
                        raise ResultConflictError("CONTINUOUS_RESULT_HASH_CONFLICT")
                elif str(active_token) != lease.lease_token or state != "leased":
                    raise LeaseLostError("CONTINUOUS_EVALUATION_LEASE_LOST")
                else:
                    if result.key.sha256 != lease.cache_key_sha256:
                        raise ContinuousStoreError("CONTINUOUS_EVALUATION_RESULT_KEY_MISMATCH")
                    cursor.execute(
                        """
                        INSERT INTO results (
                            campaign_id, schema_version, evaluation_id, result_sha256,
                            result_payload, evaluation_origin, physical_runtime_seconds,
                            validation_opened, locked_opened,
                            created_sequence, updated_sequence
                        ) VALUES (%s, 2, %s, %s, %s, 'physical', 0, false, false, %s, %s)
                        """,
                        (
                            self.campaign_id,
                            lease.evaluation_id,
                            result.result_sha256,
                            self._jsonb(dict(result.result)),
                            sequence,
                            sequence,
                        ),
                    )
                    cursor.execute(
                        """
                        UPDATE evaluations SET state = 'completed', updated_sequence = %s,
                            updated_at = clock_timestamp() WHERE evaluation_id = %s
                        """,
                        (sequence, lease.evaluation_id),
                    )
                    cursor.execute(
                        """
                        UPDATE work_items SET state = 'completed', lease_token = NULL,
                            leased_by_session_id = NULL, leased_by_slot = NULL,
                            lease_expires_at = NULL, updated_sequence = %s,
                            updated_at = clock_timestamp() WHERE evaluation_id = %s
                        """,
                        (sequence, lease.evaluation_id),
                    )
                    cursor.execute(
                        """
                        DELETE FROM worker_slot_leases
                        WHERE campaign_id = %s AND worker_session_id = %s
                          AND slot_index = %s AND lease_token = %s
                        """,
                        (
                            self.campaign_id,
                            lease.worker_session_id,
                            lease.slot_index,
                            lease.lease_token,
                        ),
                    )
                cursor.execute(
                    """
                    SELECT count(*) FROM evaluation_subscribers
                    WHERE campaign_id = %s AND evaluation_id = %s
                    """,
                    (self.campaign_id, lease.evaluation_id),
                )
                subscriber_count = int(cursor.fetchone()[0])
        return EvaluationCompletionV1(
            evaluation_id=lease.evaluation_id,
            result_sha256=result.result_sha256,
            subscriber_count=subscriber_count,
        )

    def requeue_expired_leases(self) -> int:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    WITH expired AS (
                        UPDATE work_items
                        SET state = 'ready', lease_token = NULL,
                            leased_by_session_id = NULL, leased_by_slot = NULL,
                            lease_expires_at = NULL, updated_sequence = %s,
                            updated_at = clock_timestamp()
                        WHERE campaign_id = %s AND state = 'leased'
                          AND lease_expires_at < clock_timestamp()
                        RETURNING evaluation_id
                    )
                    UPDATE evaluations SET state = 'ready', updated_sequence = %s,
                        updated_at = clock_timestamp()
                    WHERE evaluation_id IN (SELECT evaluation_id FROM expired)
                    RETURNING evaluation_id
                    """,
                    (sequence, self.campaign_id, sequence),
                )
                rows = cursor.fetchall()
                cursor.execute(
                    """
                    DELETE FROM worker_slot_leases
                    WHERE campaign_id = %s AND lease_expires_at < clock_timestamp()
                    """,
                    (self.campaign_id,),
                )
        return len(rows)

    def close_worker_session(self, worker_session_id: str) -> None:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    UPDATE work_items SET state = 'ready', lease_token = NULL,
                        leased_by_session_id = NULL, leased_by_slot = NULL,
                        lease_expires_at = NULL, updated_sequence = %s,
                        updated_at = clock_timestamp()
                    WHERE campaign_id = %s AND leased_by_session_id = %s
                      AND state = 'leased' RETURNING evaluation_id
                    """,
                    (sequence, self.campaign_id, worker_session_id),
                )
                evaluation_ids = [int(row[0]) for row in cursor.fetchall()]
                if evaluation_ids:
                    cursor.execute(
                        """
                        UPDATE evaluations SET state = 'ready', updated_sequence = %s,
                            updated_at = clock_timestamp()
                        WHERE campaign_id = %s AND evaluation_id = ANY(%s)
                        """,
                        (sequence, self.campaign_id, evaluation_ids),
                    )
                cursor.execute(
                    "DELETE FROM worker_slot_leases WHERE worker_session_id = %s",
                    (worker_session_id,),
                )
                cursor.execute(
                    """
                    UPDATE worker_sessions SET state = 'closed', updated_sequence = %s,
                        updated_at = clock_timestamp()
                    WHERE worker_session_id = %s AND campaign_id = %s
                    """,
                    (sequence, worker_session_id, self.campaign_id),
                )

    def acquire_coordinator_leadership(self, owner_token: str, lease_seconds: int) -> bool:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 720))",
                    (self.campaign_id,),
                )
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    INSERT INTO campaign_leases (
                        campaign_id, schema_version, owner_token, lease_expires_at,
                        created_sequence, updated_sequence
                    ) VALUES (
                        %s, 1, %s, clock_timestamp() + make_interval(secs => %s), %s, %s
                    )
                    ON CONFLICT (campaign_id) DO UPDATE SET
                        owner_token = EXCLUDED.owner_token,
                        lease_expires_at = EXCLUDED.lease_expires_at,
                        updated_sequence = EXCLUDED.updated_sequence,
                        updated_at = clock_timestamp()
                    WHERE campaign_leases.lease_expires_at < clock_timestamp()
                       OR campaign_leases.owner_token = EXCLUDED.owner_token
                    RETURNING owner_token
                    """,
                    (
                        self.campaign_id,
                        str(owner_token),
                        int(lease_seconds),
                        sequence,
                        sequence,
                    ),
                )
                row = cursor.fetchone()
        return row is not None and str(row[0]) == str(owner_token)

    def coordinator_owner(self) -> str | None:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT owner_token FROM campaign_leases
                    WHERE campaign_id = %s AND lease_expires_at >= clock_timestamp()
                    """,
                    (self.campaign_id,),
                )
                row = cursor.fetchone()
        return None if row is None else str(row[0])

    def release_coordinator_leadership(self, owner_token: str) -> None:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM campaign_leases WHERE campaign_id = %s AND owner_token = %s",
                    (self.campaign_id, str(owner_token)),
                )

    def open_island_batch(self, batch: object) -> None:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    INSERT INTO island_batches (
                        campaign_id, island_id, batch_sequence, schema_version,
                        status, batch_sha256, checkpoint_before_sha256,
                        created_sequence, updated_sequence
                    )
                    SELECT %s, %s, %s, 1, 'open', %s, checkpoint_sha256, %s, %s
                    FROM islands WHERE campaign_id = %s AND island_id = %s
                    ON CONFLICT (campaign_id, island_id, batch_sequence) DO NOTHING
                    RETURNING batch_sequence
                    """,
                    (
                        self.campaign_id,
                        str(getattr(batch, "island_id")),
                        int(getattr(batch, "batch_sequence")),
                        str(getattr(batch, "batch_sha256")),
                        sequence,
                        sequence,
                        self.campaign_id,
                        str(getattr(batch, "island_id")),
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    cursor.execute(
                        """
                        SELECT status FROM island_batches
                        WHERE campaign_id = %s AND island_id = %s AND batch_sequence = %s
                        """,
                        (
                            self.campaign_id,
                            str(getattr(batch, "island_id")),
                            int(getattr(batch, "batch_sequence")),
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None or str(row[0]) != "open":
                        raise ResultConflictError("CONTINUOUS_ISLAND_BATCH_IDENTITY_CONFLICT")

    def resolved_batch_results(
        self,
        *,
        island_id: str,
        batch_sequence: int,
    ) -> dict[int, dict] | None:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.batch_slot, r.result_payload
                    FROM proposals p
                    JOIN results r ON r.evaluation_id = p.evaluation_id
                    WHERE p.campaign_id = %s AND p.island_id = %s
                      AND p.batch_sequence = %s
                    ORDER BY p.batch_slot
                    """,
                    (self.campaign_id, str(island_id), int(batch_sequence)),
                )
                rows = cursor.fetchall()
        if len(rows) != 4 or {int(row[0]) for row in rows} != {0, 1, 2, 3}:
            return None
        return {int(slot): dict(payload) for slot, payload in rows}

    def record_island_advance(self, advance: object) -> None:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                self._serializable(cursor)
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    UPDATE islands SET checkpoint_bytes = %s, checkpoint_sha256 = %s,
                        prior_checkpoint_sha256 = %s, next_batch_sequence = %s,
                        status = %s, runtime_state = %s, updated_sequence = %s,
                        updated_at = clock_timestamp()
                    WHERE campaign_id = %s AND island_id = %s
                      AND checkpoint_sha256 IS NOT DISTINCT FROM %s
                    RETURNING island_id
                    """,
                    (
                        bytes(getattr(advance, "checkpoint_bytes")),
                        str(getattr(advance, "checkpoint_sha256")),
                        getattr(advance, "prior_checkpoint_sha256"),
                        int(getattr(advance, "batch_sequence")) + 1,
                        "plateau" if bool(getattr(advance, "stopped")) else "runnable",
                        self._jsonb(
                            {
                                "evaluations": int(getattr(advance, "evaluations")),
                                "full_fidelity_evaluations": int(
                                    getattr(advance, "full_fidelity_evaluations")
                                ),
                                "completed_since_improvement": int(
                                    getattr(advance, "completed_since_improvement")
                                ),
                                "best_archive_key": getattr(advance, "best_archive_key"),
                            }
                        ),
                        sequence,
                        self.campaign_id,
                        str(getattr(advance, "island_id")),
                        getattr(advance, "prior_checkpoint_sha256"),
                    ),
                )
                if cursor.fetchone() is None:
                    raise ResultConflictError("CONTINUOUS_ISLAND_CHECKPOINT_CHAIN_CONFLICT")
                cursor.execute(
                    """
                    UPDATE island_batches SET status = 'applied', checkpoint_after_sha256 = %s,
                        updated_sequence = %s, updated_at = clock_timestamp()
                    WHERE campaign_id = %s AND island_id = %s AND batch_sequence = %s
                      AND status = 'open'
                    """,
                    (
                        str(getattr(advance, "checkpoint_sha256")),
                        sequence,
                        self.campaign_id,
                        str(getattr(advance, "island_id")),
                        int(getattr(advance, "batch_sequence")),
                    ),
                )

    def claim_strategy_evaluation(
        self,
        *,
        evaluation_id: int,
        strategy_key: StrategyEvaluationKeyV1,
    ) -> StrategyClaimV1:
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    INSERT INTO strategy_evaluations (
                        campaign_id, schema_version, strategy_key_sha256, key_payload,
                        owner_evaluation_id, state, created_sequence, updated_sequence
                    ) VALUES (%s, 1, %s, %s, %s, 'owned', %s, %s)
                    ON CONFLICT (campaign_id, strategy_key_sha256) DO NOTHING
                    RETURNING strategy_evaluation_id
                    """,
                    (
                        self.campaign_id,
                        strategy_key.sha256,
                        self._jsonb(dict(strategy_key.payload)),
                        int(evaluation_id),
                        sequence,
                        sequence,
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is not None:
                    return StrategyClaimV1(strategy_key.sha256, True, None)
                cursor.execute(
                    """
                    SELECT state, result_payload FROM strategy_evaluations
                    WHERE campaign_id = %s AND strategy_key_sha256 = %s
                    """,
                    (self.campaign_id, strategy_key.sha256),
                )
                row = cursor.fetchone()
                if row is None or str(row[0]) == "conflict":
                    raise ResultConflictError("CONTINUOUS_STRATEGY_REGISTRY_CONFLICT")
                payload = None if row[1] is None else dict(row[1])
                return StrategyClaimV1(strategy_key.sha256, False, payload)

    def complete_strategy_evaluation(
        self,
        *,
        evaluation_id: int,
        strategy_key: StrategyEvaluationKeyV1,
        result: dict,
    ) -> dict:
        normalized = dict(normalize_scientific_result(result))
        result_hash = scientific_result_sha256(normalized)
        with self._pool.connection() as connection, connection.transaction():
            with connection.cursor() as cursor:
                self._serializable(cursor)
                sequence = self._next_sequence(cursor)
                cursor.execute(
                    """
                    SELECT owner_evaluation_id, state, result_sha256
                    FROM strategy_evaluations
                    WHERE campaign_id = %s AND strategy_key_sha256 = %s
                    FOR UPDATE
                    """,
                    (self.campaign_id, strategy_key.sha256),
                )
                row = cursor.fetchone()
                if row is None or int(row[0]) != int(evaluation_id):
                    raise LeaseLostError("CONTINUOUS_STRATEGY_OWNERSHIP_LOST")
                if row[2] is not None and str(row[2]) != result_hash:
                    cursor.execute(
                        """
                        UPDATE strategy_evaluations SET state = 'conflict',
                            updated_sequence = %s WHERE campaign_id = %s
                            AND strategy_key_sha256 = %s
                        """,
                        (sequence, self.campaign_id, strategy_key.sha256),
                    )
                    cursor.execute(
                        "UPDATE campaigns SET state = 'halted_conflict' WHERE campaign_id = %s",
                        (self.campaign_id,),
                    )
                    raise ResultConflictError("CONTINUOUS_STRATEGY_RESULT_HASH_CONFLICT")
                if row[2] is None:
                    cursor.execute(
                        """
                        UPDATE strategy_evaluations
                        SET state = 'completed', result_sha256 = %s, result_payload = %s,
                            updated_sequence = %s, updated_at = clock_timestamp()
                        WHERE campaign_id = %s AND strategy_key_sha256 = %s
                        """,
                        (
                            result_hash,
                            self._jsonb(normalized),
                            sequence,
                            self.campaign_id,
                            strategy_key.sha256,
                        ),
                    )
        return normalized

    def wait_strategy_result(
        self,
        *,
        strategy_key: StrategyEvaluationKeyV1,
        timeout_seconds: float,
    ) -> dict:
        deadline = time.monotonic() + float(timeout_seconds)
        while time.monotonic() < deadline:
            with self._pool.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT state, result_payload FROM strategy_evaluations
                        WHERE campaign_id = %s AND strategy_key_sha256 = %s
                        """,
                        (self.campaign_id, strategy_key.sha256),
                    )
                    row = cursor.fetchone()
            if row is not None and str(row[0]) == "completed" and row[1] is not None:
                return dict(row[1])
            if row is not None and str(row[0]) == "conflict":
                raise ResultConflictError("CONTINUOUS_STRATEGY_REGISTRY_CONFLICT")
            time.sleep(0.2)
        raise ContinuousStoreError("CONTINUOUS_STRATEGY_RESULT_TIMEOUT")

    def load_island_records(self) -> tuple[StoredIslandV1, ...]:
        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT island_id, lane_id, replica, restart_seed, status,
                           next_batch_sequence, checkpoint_bytes, checkpoint_sha256,
                           runtime_state
                    FROM islands WHERE campaign_id = %s ORDER BY island_id
                    """,
                    (self.campaign_id,),
                )
                rows = cursor.fetchall()
        records = tuple(
            StoredIslandV1(
                island_id=str(row[0]),
                lane_id=str(row[1]),
                replica=int(row[2]),
                restart_seed=int(row[3]),
                status=str(row[4]),
                next_batch_sequence=int(row[5]),
                checkpoint_bytes=None if row[6] is None else bytes(row[6]),
                checkpoint_sha256=None if row[7] is None else str(row[7]),
                runtime_state=dict(row[8]),
            )
            for row in rows
        )
        if len(records) != 720:
            raise ContinuousStoreError("CONTINUOUS_ISLAND_INVENTORY_INCOMPLETE")
        return records

    def load_open_batches(self) -> dict[str, object]:
        from aurora.infra.sp500_megarun.dehb_continuous_island import IslandBatchV1

        with self._pool.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT b.island_id, b.batch_sequence, b.batch_sha256,
                           p.batch_slot, p.dehb_job
                    FROM island_batches b
                    JOIN proposals p ON p.campaign_id = b.campaign_id
                      AND p.island_id = b.island_id
                      AND p.batch_sequence = b.batch_sequence
                    WHERE b.campaign_id = %s AND b.status = 'open'
                    ORDER BY b.island_id, b.batch_sequence, p.batch_slot
                    """,
                    (self.campaign_id,),
                )
                rows = cursor.fetchall()
        grouped: dict[tuple[str, int, str], list[tuple[int, dict]]] = {}
        for island_id, sequence, batch_hash, slot, job in rows:
            grouped.setdefault(
                (str(island_id), int(sequence), str(batch_hash)), []
            ).append((int(slot), dict(job)))
        batches: dict[str, object] = {}
        for (island_id, sequence, batch_hash), items in grouped.items():
            if [slot for slot, _job in items] != [0, 1, 2, 3]:
                raise ContinuousStoreError("CONTINUOUS_OPEN_BATCH_INCOMPLETE")
            batches[island_id] = IslandBatchV1(
                island_id=island_id,
                batch_sequence=sequence,
                jobs=tuple(job for _slot, job in items),
                batch_sha256=batch_hash,
            )
        return batches


__all__ = [
    "ContinuousCampaignStore",
    "ContinuousStoreError",
    "EvaluationCompletionV1",
    "EvaluationLeaseV1",
    "InMemoryContinuousCampaignStore",
    "LeaseLostError",
    "PostgresContinuousCampaignStore",
    "PostgresStoreConfigurationError",
    "ProposalRegistrationV1",
    "ResultConflictError",
    "StrategyClaimV1",
    "StoredIslandV1",
    "WorkerCapacityError",
    "WorkerSessionLeaseV1",
]
