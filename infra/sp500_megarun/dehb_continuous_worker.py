"""Four-slot continuous physical evaluation runtime."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
from threading import Lock
import time
from typing import Any, Callable, Mapping

from aurora.infra.sp500_megarun.dehb_continuous_models import (
    EvaluationCacheKeyV2,
    EvaluationResultV2,
    StrategyEvaluationKeyV1,
)


@dataclass(frozen=True)
class PreparedPhysicalEvaluationV1:
    positions_sha256: str
    payload: Any
    schema_version: int = 1


@dataclass(frozen=True)
class ContinuousWorkerSummaryV1:
    worker_session_id: str
    executor_slots: int
    logical_completions: int
    physical_strategy_evaluations: int
    strategy_cache_hits: int
    schema_version: int = 1


PositionBuilder = Callable[[EvaluationCacheKeyV2], PreparedPhysicalEvaluationV1]
PhysicalEvaluator = Callable[
    [PreparedPhysicalEvaluationV1, EvaluationCacheKeyV2], Mapping[str, Any]
]
ResultBinder = Callable[
    [Mapping[str, Any], EvaluationCacheKeyV2, PreparedPhysicalEvaluationV1], Mapping[str, Any]
]


def deterministic_idle_backoff_seconds(
    *,
    worker_session_id: str,
    slot_index: int,
    consecutive_misses: int,
    minimum_seconds: float = 1.0,
    maximum_seconds: float = 30.0,
) -> float:
    """Return a stable jittered backoff so idle workers do not poll in lockstep."""

    misses = max(1, int(consecutive_misses))
    base = min(float(maximum_seconds), float(minimum_seconds) * (2 ** (misses - 1)))
    digest = hashlib.sha256(
        f"{worker_session_id}:{int(slot_index)}:{misses}".encode("utf-8")
    ).digest()
    jitter = 0.75 + (int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)) * 0.5
    return base * jitter


def _default_result_binder(
    result: Mapping[str, Any],
    key: EvaluationCacheKeyV2,
    _prepared: PreparedPhysicalEvaluationV1,
) -> Mapping[str, Any]:
    rebound = dict(result)
    raw_info = result.get("info")
    if isinstance(raw_info, Mapping):
        info = dict(raw_info)
        info["config"] = dict(key.payload["configuration"])
        info["lane_id"] = str(key.payload["lane_id"])
        rebound["info"] = info
    return rebound


class ContinuousWorkerRuntime:
    """Claim and evaluate unique work on four independent local executor slots."""

    def __init__(
        self,
        *,
        store: object,
        pool_generation: str,
        github_run_id: int,
        github_job: str,
        position_builder: PositionBuilder,
        physical_evaluator: PhysicalEvaluator,
        executor_slots: int = 4,
        result_binder: ResultBinder = _default_result_binder,
        strategy_wait_seconds: float = 300.0,
        idle_poll_min_seconds: float = 1.0,
        idle_poll_max_seconds: float = 30.0,
    ) -> None:
        if int(executor_slots) != 4:
            raise ValueError("CONTINUOUS_WORKER_REQUIRES_FOUR_SLOTS")
        self.store = store
        self.pool_generation = str(pool_generation)
        self.github_run_id = int(github_run_id)
        self.github_job = str(github_job)
        self.position_builder = position_builder
        self.physical_evaluator = physical_evaluator
        self.executor_slots = int(executor_slots)
        self.result_binder = result_binder
        self.strategy_wait_seconds = float(strategy_wait_seconds)
        self.idle_poll_min_seconds = float(idle_poll_min_seconds)
        self.idle_poll_max_seconds = float(idle_poll_max_seconds)
        if not 0 < self.idle_poll_min_seconds <= self.idle_poll_max_seconds:
            raise ValueError("CONTINUOUS_WORKER_IDLE_BACKOFF_INVALID")
        self._counter_lock = Lock()
        self._logical_completions = 0
        self._physical_strategy_evaluations = 0
        self._strategy_cache_hits = 0

    def _run_slot(
        self,
        worker_session_id: str,
        slot_index: int,
        *,
        deadline: float | None,
    ) -> None:
        consecutive_misses = 0
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                return
            lease = self.store.claim_evaluation(
                worker_session_id=worker_session_id,
                slot_index=slot_index,
                lease_seconds=900,
            )
            if lease is None:
                if deadline is None:
                    return
                consecutive_misses += 1
                time.sleep(
                    deterministic_idle_backoff_seconds(
                        worker_session_id=worker_session_id,
                        slot_index=slot_index,
                        consecutive_misses=consecutive_misses,
                        minimum_seconds=self.idle_poll_min_seconds,
                        maximum_seconds=self.idle_poll_max_seconds,
                    )
                )
                continue
            consecutive_misses = 0
            prepared = self.position_builder(lease.evaluation_key)
            strategy_key = StrategyEvaluationKeyV1.build(
                evaluation_key=lease.evaluation_key,
                positions_sha256=prepared.positions_sha256,
            )
            claim = self.store.claim_strategy_evaluation(
                evaluation_id=lease.evaluation_id,
                strategy_key=strategy_key,
            )
            if claim.owner:
                raw_result = self.physical_evaluator(prepared, lease.evaluation_key)
                shared_result = self.store.complete_strategy_evaluation(
                    evaluation_id=lease.evaluation_id,
                    strategy_key=strategy_key,
                    result=dict(raw_result),
                )
                with self._counter_lock:
                    self._physical_strategy_evaluations += 1
            elif claim.result is not None:
                shared_result = claim.result
                with self._counter_lock:
                    self._strategy_cache_hits += 1
            else:
                shared_result = self.store.wait_strategy_result(
                    strategy_key=strategy_key,
                    timeout_seconds=self.strategy_wait_seconds,
                )
                with self._counter_lock:
                    self._strategy_cache_hits += 1
            bound = self.result_binder(shared_result, lease.evaluation_key, prepared)
            result = EvaluationResultV2.build(key=lease.evaluation_key, result=bound)
            self.store.complete_evaluation(lease, result)
            with self._counter_lock:
                self._logical_completions += 1

    def _run(self, *, lifetime_seconds: float | None) -> ContinuousWorkerSummaryV1:
        deadline = (
            None if lifetime_seconds is None else time.monotonic() + float(lifetime_seconds)
        )
        session = self.store.claim_worker_session(
            pool_generation=self.pool_generation,
            github_run_id=self.github_run_id,
            github_job=self.github_job,
            lease_seconds=(3_600 if lifetime_seconds is None else int(lifetime_seconds) + 300),
        )
        try:
            with ThreadPoolExecutor(max_workers=self.executor_slots) as executor:
                futures = [
                    executor.submit(
                        self._run_slot,
                        session.worker_session_id,
                        slot,
                        deadline=deadline,
                    )
                    for slot in range(self.executor_slots)
                ]
                for future in futures:
                    future.result()
        finally:
            self.store.close_worker_session(session.worker_session_id)
        return ContinuousWorkerSummaryV1(
            worker_session_id=session.worker_session_id,
            executor_slots=self.executor_slots,
            logical_completions=self._logical_completions,
            physical_strategy_evaluations=self._physical_strategy_evaluations,
            strategy_cache_hits=self._strategy_cache_hits,
        )

    def run_until_idle(self) -> ContinuousWorkerSummaryV1:
        return self._run(lifetime_seconds=None)

    def run_for(self, *, lifetime_seconds: float) -> ContinuousWorkerSummaryV1:
        if float(lifetime_seconds) <= 0:
            raise ValueError("CONTINUOUS_WORKER_LIFETIME_INVALID")
        return self._run(lifetime_seconds=float(lifetime_seconds))


__all__ = [
    "ContinuousWorkerRuntime",
    "ContinuousWorkerSummaryV1",
    "PreparedPhysicalEvaluationV1",
    "deterministic_idle_backoff_seconds",
]
