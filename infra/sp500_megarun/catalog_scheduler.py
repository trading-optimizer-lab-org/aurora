"""Deterministic weighted-LPT planning with component-affinity tie breaks."""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, canonical_sha256
from aurora.infra.sp500_megarun.catalog_cost_model import CatalogCostModelV1


class CatalogShardV1(FrozenModel):
    shard_index: int = Field(ge=0)
    recipe_ids: tuple[str, ...]
    component_ids: tuple[str, ...]
    estimated_seconds: float = Field(ge=0)


class CatalogScheduleV1(FrozenModel):
    schema_version: str = "1"
    shards: tuple[CatalogShardV1, ...]
    tail_ratio: float = Field(ge=1)
    plan_sha256: str


class CatalogComponentShardV1(FrozenModel):
    shard_index: int = Field(ge=0)
    component_ids: tuple[str, ...]
    estimated_seconds: float = Field(ge=0)


class CatalogComponentScheduleV1(FrozenModel):
    schema_version: str = "1"
    shards: tuple[CatalogComponentShardV1, ...]
    tail_ratio: float = Field(ge=1)
    plan_sha256: str


def schedule_components(
    components: Sequence[Mapping[str, object]],
    *,
    model: CatalogCostModelV1,
    workers: int,
) -> CatalogComponentScheduleV1:
    if workers < 1 or workers > min(360, len(components)):
        raise ValueError("CATALOG_COMPONENT_SCHEDULER_WORKER_COUNT_INVALID")
    normalized: list[tuple[str, float]] = []
    seen: set[str] = set()
    for component in components:
        component_id = str(component["configuration_sha256"])
        if component_id in seen:
            raise ValueError("CATALOG_COMPONENT_SCHEDULER_DUPLICATE")
        seen.add(component_id)
        normalized.append((component_id, model.estimate(component_id)))
    assignments: list[list[str]] = [[] for _ in range(workers)]
    loads = [0.0] * workers
    heap = [(0.0, index) for index in range(workers)]
    heapq.heapify(heap)
    for component_id, cost in sorted(normalized, key=lambda item: (-item[1], item[0])):
        load, index = heapq.heappop(heap)
        assignments[index].append(component_id)
        loads[index] = load + cost
        heapq.heappush(heap, (loads[index], index))
    shards = tuple(
        CatalogComponentShardV1(
            shard_index=index,
            component_ids=tuple(sorted(assignments[index])),
            estimated_seconds=loads[index],
        )
        for index in range(workers)
    )
    positive = [load for load in loads if load > 0]
    tail_ratio = max(positive) / min(positive) if positive else 1.0
    identity = {"schema_version": "1", "shards": shards, "tail_ratio": tail_ratio}
    return CatalogComponentScheduleV1(
        **identity,
        plan_sha256=canonical_sha256(identity),
    )


def schedule_components_by_affinity(
    components: Sequence[Mapping[str, object]],
    *,
    model: CatalogCostModelV1,
    workers: int,
    affinity_by_component: Mapping[str, tuple[str, ...]],
) -> CatalogComponentScheduleV1:
    """Schedule components in data-affine groups to avoid repeated downloads.

    Each exact required-dataset set receives at least one worker. Remaining
    workers go to the groups with the largest estimated load per worker, then
    normal weighted scheduling runs inside each group. This preserves one
    physical build per component while keeping each worker's input subset
    small and deterministic.
    """

    if workers < 1 or workers > min(360, len(components)):
        raise ValueError("CATALOG_COMPONENT_SCHEDULER_WORKER_COUNT_INVALID")
    by_id = {str(item["configuration_sha256"]): item for item in components}
    if len(by_id) != len(components):
        raise ValueError("CATALOG_COMPONENT_SCHEDULER_DUPLICATE")
    groups: dict[tuple[str, ...], list[Mapping[str, object]]] = {}
    for component_id in sorted(by_id):
        affinity = tuple(sorted(str(item) for item in affinity_by_component[component_id]))
        groups.setdefault(affinity, []).append(by_id[component_id])
    if len(groups) > workers:
        raise ValueError("CATALOG_COMPONENT_AFFINITY_GROUP_COUNT_INVALID")
    group_costs = {
        affinity: sum(
            model.estimate(str(item["configuration_sha256"]))
            for item in group
        )
        for affinity, group in groups.items()
    }
    allocation = {affinity: 1 for affinity in groups}
    remaining = workers - len(groups)
    while remaining:
        candidates = [
            affinity
            for affinity, group in groups.items()
            if allocation[affinity] < len(group)
        ]
        if not candidates:
            raise ValueError("CATALOG_COMPONENT_AFFINITY_CAPACITY_EXHAUSTED")
        affinity = max(
            candidates,
            key=lambda item: (
                group_costs[item] / allocation[item],
                group_costs[item],
                item,
            ),
        )
        allocation[affinity] += 1
        remaining -= 1
    combined: list[CatalogComponentShardV1] = []
    for affinity in sorted(groups):
        schedule = schedule_components(
            groups[affinity],
            model=model,
            workers=allocation[affinity],
        )
        combined.extend(schedule.shards)
    shards = tuple(
        CatalogComponentShardV1(
            shard_index=index,
            component_ids=shard.component_ids,
            estimated_seconds=shard.estimated_seconds,
        )
        for index, shard in enumerate(combined)
    )
    loads = [float(shard.estimated_seconds) for shard in shards if shard.estimated_seconds > 0]
    tail_ratio = max(loads) / min(loads) if loads else 1.0
    identity = {"schema_version": "1", "shards": shards, "tail_ratio": tail_ratio}
    return CatalogComponentScheduleV1(
        **identity,
        plan_sha256=canonical_sha256(identity),
    )


def schedule_recipes(
    recipes: Sequence[Mapping[str, object]],
    *,
    model: CatalogCostModelV1,
    workers: int,
) -> CatalogScheduleV1:
    if workers < 1 or workers > min(360, len(recipes)):
        raise ValueError("CATALOG_SCHEDULER_WORKER_COUNT_INVALID")
    normalized: list[tuple[str, tuple[str, ...], float]] = []
    seen: set[str] = set()
    for row in recipes:
        recipe_id = str(row["recipe_id"])
        if recipe_id in seen:
            raise ValueError("CATALOG_SCHEDULER_RECIPE_DUPLICATE")
        seen.add(recipe_id)
        components = tuple(sorted({str(value) for value in row["component_ids"]}))
        cost = sum(model.estimate(item) for item in components)
        normalized.append((recipe_id, components, cost))
    assignments: list[list[tuple[str, tuple[str, ...], float]]] = [
        [] for _ in range(workers)
    ]
    component_sets: list[set[str]] = [set() for _ in range(workers)]
    loads = [0.0] * workers
    heap = [(0.0, index) for index in range(workers)]
    heapq.heapify(heap)
    for recipe_id, components, cost in sorted(
        normalized,
        key=lambda item: (-item[2], item[0]),
    ):
        minimum_load = heap[0][0]
        candidates = [
            index
            for load, index in heap
            if abs(load - minimum_load) <= 1e-12
        ]
        index = min(
            candidates,
            key=lambda candidate: (
                -len(component_sets[candidate].intersection(components)),
                candidate,
            ),
        )
        heap.remove((loads[index], index))
        heapq.heapify(heap)
        assignments[index].append((recipe_id, components, cost))
        component_sets[index].update(components)
        loads[index] += cost
        heapq.heappush(heap, (loads[index], index))
    shards = tuple(
        CatalogShardV1(
            shard_index=index,
            recipe_ids=tuple(sorted(item[0] for item in assignment)),
            component_ids=tuple(sorted(component_sets[index])),
            estimated_seconds=loads[index],
        )
        for index, assignment in enumerate(assignments)
    )
    positive = [load for load in loads if load > 0]
    tail_ratio = max(positive) / min(positive) if positive else 1.0
    identity = {"schema_version": "1", "shards": shards, "tail_ratio": tail_ratio}
    return CatalogScheduleV1(**identity, plan_sha256=canonical_sha256(identity))


__all__ = [
    "CatalogComponentScheduleV1",
    "CatalogComponentShardV1",
    "CatalogScheduleV1",
    "CatalogShardV1",
    "schedule_components",
    "schedule_components_by_affinity",
    "schedule_recipes",
]
