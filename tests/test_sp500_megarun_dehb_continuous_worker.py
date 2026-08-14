from __future__ import annotations

from collections import Counter
from threading import Lock


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def key(lookback, *, robustness="base-seed:7"):
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
        robustness_identity=robustness,
    )


def registry_with(keys):
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationProposalV2
    from aurora.infra.sp500_megarun.dehb_continuous_store import (
        InMemoryContinuousCampaignStore,
    )

    registry = InMemoryContinuousCampaignStore(
        campaign_id="campaign-1",
        scientific_contract_sha256=SHA_E,
    )
    for slot, item in enumerate(keys):
        registry.register_proposal(
            EvaluationProposalV2.build(
                campaign_id="campaign-1",
                island_id=f"F067-R{slot // 4}",
                batch_sequence=1,
                batch_slot=slot % 4,
                evaluation_key=item,
                dehb_job={"config_id": slot, "fidelity": 12},
            )
        )
    return registry


def scientific_result(key_value):
    return {
        "fitness": -1.0,
        "cost": 12.0,
        "info": {
            "config": dict(key_value.payload["configuration"]),
            "lane_id": key_value.payload["lane_id"],
            "archive_key": [0.0, -0.2, -0.6, -0.1],
            "position_fingerprint": SHA_B,
            "validation_opened": False,
            "locked_opened": False,
        },
    }


def test_same_positions_from_different_configurations_are_scored_once():
    from aurora.infra.sp500_megarun.dehb_continuous_worker import (
        ContinuousWorkerRuntime,
        PreparedPhysicalEvaluationV1,
    )

    keys = [key(21), key(84)]
    registry = registry_with(keys)
    calls = Counter()
    lock = Lock()

    def prepare(key_value):
        return PreparedPhysicalEvaluationV1(
            positions_sha256=SHA_B,
            payload={"configuration": key_value.payload["configuration"]},
        )

    def evaluate(prepared, key_value):
        with lock:
            calls["expensive"] += 1
        return scientific_result(key_value)

    runtime = ContinuousWorkerRuntime(
        store=registry,
        pool_generation="test",
        github_run_id=1,
        github_job="worker",
        position_builder=prepare,
        physical_evaluator=evaluate,
        executor_slots=4,
    )
    summary = runtime.run_until_idle()

    assert summary.logical_completions == 2
    assert summary.physical_strategy_evaluations == 1
    assert summary.strategy_cache_hits == 1
    assert calls["expensive"] == 1
    assert registry.count_physical_completions() == 2


def test_different_robustness_seeds_are_never_position_deduplicated():
    from aurora.infra.sp500_megarun.dehb_continuous_worker import (
        ContinuousWorkerRuntime,
        PreparedPhysicalEvaluationV1,
    )

    registry = registry_with([key(21, robustness="seed:7"), key(21, robustness="seed:8")])
    calls = Counter()

    def prepare(_key_value):
        return PreparedPhysicalEvaluationV1(positions_sha256=SHA_B, payload={})

    def evaluate(_prepared, key_value):
        calls["expensive"] += 1
        return scientific_result(key_value)

    summary = ContinuousWorkerRuntime(
        store=registry,
        pool_generation="test",
        github_run_id=1,
        github_job="worker",
        position_builder=prepare,
        physical_evaluator=evaluate,
        executor_slots=4,
    ).run_until_idle()

    assert summary.logical_completions == 2
    assert summary.physical_strategy_evaluations == 2
    assert summary.strategy_cache_hits == 0
    assert calls["expensive"] == 2


def test_four_executor_slots_drain_more_than_one_round_without_duplicate_leases():
    from aurora.infra.sp500_megarun.dehb_continuous_worker import (
        ContinuousWorkerRuntime,
        PreparedPhysicalEvaluationV1,
    )

    registry = registry_with([key(20 + index) for index in range(8)])

    summary = ContinuousWorkerRuntime(
        store=registry,
        pool_generation="test",
        github_run_id=1,
        github_job="worker",
        position_builder=lambda key_value: PreparedPhysicalEvaluationV1(
            positions_sha256=f"{int(key_value.payload['configuration']['lookback']):064x}",
            payload={},
        ),
        physical_evaluator=lambda _prepared, key_value: scientific_result(key_value),
        executor_slots=4,
    ).run_until_idle()

    assert summary.logical_completions == 8
    assert summary.executor_slots == 4
    assert registry.maximum_active_leases_per_key() <= 1
