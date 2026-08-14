"""Leader coordinator for independent continuous official-DEHB islands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from aurora.infra.sp500_megarun.dehb_continuous_island import (
    ContinuousIslandState,
    IslandBatchV1,
)
from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationProposalV2


class CoordinatorLeadershipError(RuntimeError):
    """Raised when a non-leader attempts to mutate campaign state."""


ProposalBuilder = Callable[
    [ContinuousIslandState, IslandBatchV1, int, dict], EvaluationProposalV2
]


@dataclass(frozen=True)
class CoordinatorCycleV1:
    batches_created: int
    batches_applied: int
    proposals_registered: int
    physical_work_created: int
    cache_hits: int
    islands_scheduled: tuple[str, ...]
    global_barrier_count: int = 0
    schema_version: int = 1


class ContinuousCampaignCoordinator:
    """Advances ready islands without introducing any global batch barrier."""

    def __init__(
        self,
        *,
        store: object,
        islands: Iterable[ContinuousIslandState],
        proposal_builder: ProposalBuilder,
        owner_token: str,
    ) -> None:
        self.store = store
        self.islands = tuple(sorted(islands, key=lambda island: island.island_id))
        if len({island.island_id for island in self.islands}) != len(self.islands):
            raise ValueError("CONTINUOUS_COORDINATOR_DUPLICATE_ISLAND")
        self._by_id = {island.island_id: island for island in self.islands}
        self.proposal_builder = proposal_builder
        self.owner_token = str(owner_token)
        self._open_batches: dict[str, IslandBatchV1] = {}
        self._stopped: set[str] = set()
        self._round_robin_cursor = 0

    def acquire_leadership(self, *, lease_seconds: int = 60) -> bool:
        return bool(
            self.store.acquire_coordinator_leadership(self.owner_token, lease_seconds)
        )

    def release_leadership(self) -> None:
        self.store.release_coordinator_leadership(self.owner_token)

    def _require_leadership(self) -> None:
        owner = self.store.coordinator_owner()
        if owner is None:
            self.acquire_leadership()
            owner = self.store.coordinator_owner()
        if owner != self.owner_token:
            raise CoordinatorLeadershipError("CONTINUOUS_COORDINATOR_NOT_LEADER")
        self.acquire_leadership()

    def _fair_order(self) -> tuple[ContinuousIslandState, ...]:
        if not self.islands:
            return ()
        cursor = self._round_robin_cursor % len(self.islands)
        ordered = self.islands[cursor:] + self.islands[:cursor]
        self._round_robin_cursor = (cursor + 1) % len(self.islands)
        return ordered

    def run_once(self, *, max_islands: int | None = None) -> CoordinatorCycleV1:
        self._require_leadership()
        applied = 0
        for island_id, batch in tuple(self._open_batches.items()):
            results = self.store.resolved_batch_results(
                island_id=island_id,
                batch_sequence=batch.batch_sequence,
            )
            if results is None:
                continue
            advance = self._by_id[island_id].tell_batch(batch, results)
            self.store.record_island_advance(advance)
            del self._open_batches[island_id]
            applied += 1
            if advance.stopped:
                self._stopped.add(island_id)

        limit = len(self.islands) if max_islands is None else max(0, int(max_islands))
        created = 0
        proposals_registered = 0
        physical_work_created = 0
        cache_hits = 0
        scheduled: list[str] = []
        for island in self._fair_order():
            if created >= limit:
                break
            if island.island_id in self._open_batches or island.island_id in self._stopped:
                continue
            batch = island.ask_batch()
            self.store.open_island_batch(batch)
            for slot, job in enumerate(batch.jobs):
                proposal = self.proposal_builder(island, batch, slot, dict(job))
                registration = self.store.register_proposal(proposal)
                proposals_registered += 1
                physical_work_created += int(registration.physical_work_created)
                cache_hits += int(registration.cache_hit)
            self._open_batches[island.island_id] = batch
            scheduled.append(island.island_id)
            created += 1

        return CoordinatorCycleV1(
            batches_created=created,
            batches_applied=applied,
            proposals_registered=proposals_registered,
            physical_work_created=physical_work_created,
            cache_hits=cache_hits,
            islands_scheduled=tuple(scheduled),
        )


__all__ = [
    "ContinuousCampaignCoordinator",
    "CoordinatorCycleV1",
    "CoordinatorLeadershipError",
    "ProposalBuilder",
]
