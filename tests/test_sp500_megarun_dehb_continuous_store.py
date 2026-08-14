from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


class ManualClock:
    def __init__(self):
        self.now = datetime(2026, 8, 14, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def evaluation_key(*, lookback=21):
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationCacheKeyV2

    return EvaluationCacheKeyV2.build(
        evaluator_sha256=SHA_A,
        numeric_profile_sha256=SHA_B,
        train_manifest_sha256=SHA_C,
        train_spy_sha256=SHA_D,
        campaign_contract_sha256=SHA_E,
        lane_id="F067",
        configuration={"lookback": lookback},
        fidelity=12,
        fidelity_recipe_sha256=SHA_F,
        robustness_identity="base-seed:7",
    )


def proposal(*, island="F067-R0", sequence=1, slot=0, lookback=21):
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationProposalV2

    return EvaluationProposalV2.build(
        campaign_id="campaign-1",
        island_id=island,
        batch_sequence=sequence,
        batch_slot=slot,
        evaluation_key=evaluation_key(lookback=lookback),
        dehb_job={"config_id": sequence * 10 + slot, "fidelity": 12},
    )


def result_for(key, *, fitness=-1.25):
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationResultV2

    return EvaluationResultV2.build(
        key=key,
        result={
            "fitness": fitness,
            "cost": 0.4,
            "info": {
                "validation_opened": False,
                "locked_opened": False,
                "positions_sha256": SHA_B,
            },
        },
    )


def store(clock=None):
    from aurora.infra.sp500_megarun.dehb_continuous_store import (
        InMemoryContinuousCampaignStore,
    )

    return InMemoryContinuousCampaignStore(
        campaign_id="campaign-1",
        scientific_contract_sha256=SHA_E,
        clock=clock,
    )


def worker_session(registry, *, job="job-1"):
    return registry.claim_worker_session(
        pool_generation="pool-1",
        github_run_id=123,
        github_job=job,
        lease_seconds=60,
    )


def test_500_concurrent_proposals_create_one_physical_work_item():
    registry = store()
    proposals = [
        proposal(island=f"F067-R{i % 3}", sequence=i // 12 + 1, slot=i % 4)
        for i in range(500)
    ]

    with ThreadPoolExecutor(max_workers=32) as executor:
        rows = list(executor.map(registry.register_proposal, proposals))

    assert len({row.evaluation_id for row in rows}) == 1
    assert sum(row.physical_work_created for row in rows) == 1
    assert registry.count_ready_work_items() == 1
    assert registry.count_subscribers() == 500


def test_four_slots_claim_four_distinct_scientific_keys():
    registry = store()
    for slot in range(4):
        registry.register_proposal(proposal(slot=slot, lookback=21 + slot))
    session = worker_session(registry)

    leases = [
        registry.claim_evaluation(
            worker_session_id=session.worker_session_id,
            slot_index=slot,
            lease_seconds=30,
        )
        for slot in range(4)
    ]

    assert all(lease is not None for lease in leases)
    assert len({lease.cache_key_sha256 for lease in leases if lease is not None}) == 4
    assert registry.count_ready_work_items() == 0
    assert registry.maximum_active_leases_per_key() == 1


def test_expired_lease_is_requeued_and_old_token_cannot_complete():
    from aurora.infra.sp500_megarun.dehb_continuous_store import LeaseLostError

    clock = ManualClock()
    registry = store(clock=clock)
    registration = registry.register_proposal(proposal())
    first_session = worker_session(registry, job="job-1")
    first = registry.claim_evaluation(
        worker_session_id=first_session.worker_session_id,
        slot_index=0,
        lease_seconds=10,
    )
    clock.advance(11)

    assert registry.requeue_expired_leases() == 1
    second_session = worker_session(registry, job="job-2")
    second = registry.claim_evaluation(
        worker_session_id=second_session.worker_session_id,
        slot_index=0,
        lease_seconds=10,
    )

    assert first is not None and second is not None
    assert first.lease_token != second.lease_token
    with pytest.raises(LeaseLostError, match="CONTINUOUS_EVALUATION_LEASE_LOST"):
        registry.complete_evaluation(first, result_for(registration.evaluation_key))


def test_completion_fans_one_result_to_every_subscriber():
    registry = store()
    first = registry.register_proposal(proposal(island="F067-R0"))
    registry.register_proposal(proposal(island="F067-R1"))
    session = worker_session(registry)
    lease = registry.claim_evaluation(
        worker_session_id=session.worker_session_id,
        slot_index=0,
        lease_seconds=30,
    )

    assert lease is not None
    completion = registry.complete_evaluation(lease, result_for(first.evaluation_key))

    assert completion.subscriber_count == 2
    assert registry.count_completed_subscribers() == 2
    assert registry.count_physical_completions() == 1


def test_same_hash_completion_is_idempotent_but_conflict_halts_campaign():
    from aurora.infra.sp500_megarun.dehb_continuous_store import ResultConflictError

    registry = store()
    registration = registry.register_proposal(proposal())
    session = worker_session(registry)
    lease = registry.claim_evaluation(
        worker_session_id=session.worker_session_id,
        slot_index=0,
        lease_seconds=30,
    )
    accepted = result_for(registration.evaluation_key)

    assert lease is not None
    first = registry.complete_evaluation(lease, accepted)
    second = registry.complete_evaluation(lease, accepted)
    assert first.result_sha256 == second.result_sha256

    with pytest.raises(ResultConflictError, match="CONTINUOUS_RESULT_HASH_CONFLICT"):
        registry.complete_evaluation(
            lease,
            result_for(registration.evaluation_key, fitness=-1.24),
        )
    assert registry.campaign_state() == "halted_conflict"


def test_worker_session_permits_stop_at_360_and_reuse_only_after_close():
    from aurora.infra.sp500_megarun.dehb_continuous_store import WorkerCapacityError

    registry = store()
    sessions = [worker_session(registry, job=f"job-{index}") for index in range(360)]

    assert {session.permit_number for session in sessions} == set(range(1, 361))
    with pytest.raises(WorkerCapacityError, match="CONTINUOUS_WORKER_SESSION_CAPACITY"):
        worker_session(registry, job="job-overflow")

    registry.close_worker_session(sessions[99].worker_session_id)
    replacement = worker_session(registry, job="job-replacement")
    assert replacement.permit_number == 100


def test_postgres_store_rejects_non_tls_database_urls_before_connecting():
    from aurora.infra.sp500_megarun.dehb_continuous_store import (
        PostgresContinuousCampaignStore,
        PostgresStoreConfigurationError,
    )

    with pytest.raises(PostgresStoreConfigurationError, match="CONTINUOUS_POSTGRES_TLS_REQUIRED"):
        PostgresContinuousCampaignStore(
            dsn="postgresql://user:secret@db.example/aurora",
            campaign_id="campaign-1",
        )


def test_postgres_store_exposes_the_same_transactional_operations():
    from aurora.infra.sp500_megarun.dehb_continuous_store import (
        PostgresContinuousCampaignStore,
    )

    class Pool:
        pass

    registry = PostgresContinuousCampaignStore(
        dsn="postgresql://user:secret@db.example/aurora?sslmode=require",
        campaign_id="campaign-1",
        pool=Pool(),
    )

    for method in (
        "register_proposal",
        "claim_worker_session",
        "claim_evaluation",
        "complete_evaluation",
        "requeue_expired_leases",
        "close_worker_session",
    ):
        assert callable(getattr(registry, method))
