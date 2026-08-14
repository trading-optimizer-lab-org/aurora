from __future__ import annotations

from collections import Counter

import pytest


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


class FakeOptimizer:
    def __init__(self, offset):
        self.offset = offset
        self.asked = 0
        self.told = []

    def ask(self, n_configs=1):
        assert n_configs == 1
        index = self.asked
        self.asked += 1
        return {
            "config": {"index": index, "offset": self.offset},
            "fidelity": 27,
            "config_id": index,
        }

    def tell(self, job, result):
        self.told.append((job["config_id"], result["fitness"]))


def make_island(island_id, offset):
    from aurora.infra.sp500_megarun.dehb_continuous_island import ContinuousIslandState

    return ContinuousIslandState(
        island_id=island_id,
        optimizer=FakeOptimizer(offset),
        full_fidelity=27,
        plateau_minimum_completed=1_000,
        plateau_completed_without_improvement=2_000,
        checkpoint_serializer=lambda optimizer: str(optimizer.told).encode("utf-8"),
    )


def make_store():
    from aurora.infra.sp500_megarun.dehb_continuous_store import (
        InMemoryContinuousCampaignStore,
    )

    return InMemoryContinuousCampaignStore(
        campaign_id="campaign-1",
        scientific_contract_sha256=SHA_E,
    )


def proposal_builder(island, batch, slot, job):
    from aurora.infra.sp500_megarun.dehb_continuous_models import (
        EvaluationCacheKeyV2,
        EvaluationProposalV2,
    )

    key = EvaluationCacheKeyV2.build(
        evaluator_sha256=SHA_A,
        numeric_profile_sha256=SHA_B,
        train_manifest_sha256=SHA_C,
        train_spy_sha256=SHA_D,
        campaign_contract_sha256=SHA_E,
        lane_id=island.island_id[:4],
        configuration=job["config"],
        fidelity=job["fidelity"],
        fidelity_recipe_sha256=SHA_F,
        robustness_identity="base-seed:7",
    )
    return EvaluationProposalV2.build(
        campaign_id="campaign-1",
        island_id=island.island_id,
        batch_sequence=batch.batch_sequence,
        batch_slot=slot,
        evaluation_key=key,
        dehb_job=job,
    )


def result_for(key):
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationResultV2

    index = int(key.payload["configuration"]["index"])
    return EvaluationResultV2.build(
        key=key,
        result={
            "fitness": float(index),
            "cost": 1.0,
            "info": {
                "archive_key": [0.0, -0.2, -0.6, -0.1 + index / 1000],
                "validation_opened": False,
                "locked_opened": False,
                "positions_sha256": SHA_B,
            },
        },
    )


def drain_ready(store):
    session = store.claim_worker_session(
        pool_generation="test",
        github_run_id=1,
        github_job="drain",
        lease_seconds=300,
    )
    completed = 0
    while True:
        lease = store.claim_evaluation(
            worker_session_id=session.worker_session_id,
            slot_index=0,
            lease_seconds=60,
        )
        if lease is None:
            break
        store.complete_evaluation(lease, result_for(lease.evaluation_key))
        completed += 1
    store.close_worker_session(session.worker_session_id)
    return completed


def test_one_island_advances_without_waiting_for_other_islands():
    from aurora.infra.sp500_megarun.dehb_continuous_coordinator import (
        ContinuousCampaignCoordinator,
    )

    registry = make_store()
    islands = [make_island("F001-R0", 1), make_island("F002-R0", 2)]
    coordinator = ContinuousCampaignCoordinator(
        store=registry,
        islands=islands,
        proposal_builder=proposal_builder,
        owner_token="leader-1",
    )

    first = coordinator.run_once()
    assert first.batches_created == 2
    one_session = registry.claim_worker_session(
        pool_generation="test",
        github_run_id=1,
        github_job="one",
        lease_seconds=60,
    )
    one_lease = registry.claim_evaluation(
        worker_session_id=one_session.worker_session_id,
        slot_index=0,
        lease_seconds=60,
    )
    assert one_lease is not None
    registry.complete_evaluation(one_lease, result_for(one_lease.evaluation_key))
    registry.close_worker_session(one_session.worker_session_id)
    second = coordinator.run_once()

    assert second.batches_applied == 0
    assert islands[0].evaluations == 0
    assert islands[1].evaluations == 0

    drain_ready(registry)
    third = coordinator.run_once()
    assert third.batches_applied == 2
    assert third.batches_created == 2
    assert all(island.evaluations == 4 for island in islands)


def test_duplicate_batches_fan_out_to_independent_islands():
    from aurora.infra.sp500_megarun.dehb_continuous_coordinator import (
        ContinuousCampaignCoordinator,
    )

    registry = make_store()
    islands = [make_island("F067-R0", 7), make_island("F067-R1", 7)]
    coordinator = ContinuousCampaignCoordinator(
        store=registry,
        islands=islands,
        proposal_builder=proposal_builder,
        owner_token="leader-1",
    )

    cycle = coordinator.run_once()
    assert cycle.proposals_registered == 8
    assert registry.count_open_island_batches() == 2
    assert registry.count_ready_work_items() == 4
    assert drain_ready(registry) == 4
    cycle = coordinator.run_once()

    assert cycle.batches_applied == 2
    assert islands[0].optimizer.told == islands[1].optimizer.told
    assert registry.count_physical_completions() == 4
    assert registry.count_completed_subscribers() == 8


def test_weighted_round_robin_gives_every_lane_equal_first_turn():
    from aurora.infra.sp500_megarun.dehb_continuous_coordinator import (
        ContinuousCampaignCoordinator,
    )

    registry = make_store()
    islands = [make_island(f"F{lane:03d}-R0", lane) for lane in range(1, 241)]
    coordinator = ContinuousCampaignCoordinator(
        store=registry,
        islands=islands,
        proposal_builder=proposal_builder,
        owner_token="leader-1",
    )

    cycle = coordinator.run_once(max_islands=240)
    counts = Counter(identity[:4] for identity in cycle.islands_scheduled)

    assert len(counts) == 240
    assert set(counts.values()) == {1}
    assert cycle.global_barrier_count == 0


def test_second_coordinator_cannot_mutate_until_leader_releases():
    from aurora.infra.sp500_megarun.dehb_continuous_coordinator import (
        ContinuousCampaignCoordinator,
        CoordinatorLeadershipError,
    )

    registry = make_store()
    first = ContinuousCampaignCoordinator(
        store=registry,
        islands=[make_island("F001-R0", 1)],
        proposal_builder=proposal_builder,
        owner_token="leader-1",
    )
    second = ContinuousCampaignCoordinator(
        store=registry,
        islands=[make_island("F001-R0", 1)],
        proposal_builder=proposal_builder,
        owner_token="leader-2",
    )

    assert first.acquire_leadership(lease_seconds=60) is True
    with pytest.raises(CoordinatorLeadershipError, match="CONTINUOUS_COORDINATOR_NOT_LEADER"):
        second.run_once()
    first.release_leadership()
    assert second.acquire_leadership(lease_seconds=60) is True
