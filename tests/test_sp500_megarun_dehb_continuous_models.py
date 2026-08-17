from __future__ import annotations

import numpy as np
import pytest


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _build_key(**changes):
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationCacheKeyV2

    values = {
        "evaluator_sha256": SHA_A,
        "numeric_profile_sha256": SHA_B,
        "train_manifest_sha256": SHA_C,
        "train_spy_sha256": SHA_D,
        "campaign_contract_sha256": SHA_E,
        "lane_id": "F067",
        "configuration": {"lookback": np.int64(21), "threshold": 0.125},
        "fidelity": 12,
        "fidelity_recipe_sha256": SHA_F,
        "robustness_identity": "base-seed:7",
    }
    values.update(changes)
    return EvaluationCacheKeyV2.build(**values)


def _result_info(**changes):
    values = {
        "validation_opened": False,
        "locked_opened": False,
        "positions_sha256": SHA_B,
    }
    values.update(changes)
    return values


def test_v2_key_is_stable_across_mapping_order_and_numpy_scalars():
    first = _build_key(configuration={"lookback": np.int64(21), "threshold": 0.125})
    reordered = _build_key(configuration={"threshold": 0.125, "lookback": 21})

    assert first.sha256 == reordered.sha256
    assert first.payload == reordered.payload


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("evaluator_sha256", "0" * 64),
        ("numeric_profile_sha256", "1" * 64),
        ("train_manifest_sha256", "2" * 64),
        ("train_spy_sha256", "3" * 64),
        ("campaign_contract_sha256", "4" * 64),
        ("lane_id", "F069"),
        ("configuration", {"lookback": 22, "threshold": 0.125}),
        ("fidelity", 6),
        ("fidelity_recipe_sha256", "5" * 64),
        ("robustness_identity", "base-seed:8"),
    ],
)
def test_v2_key_changes_when_any_scientific_input_changes(field, changed):
    assert _build_key().sha256 != _build_key(**{field: changed}).sha256


def test_v2_key_rejects_non_integral_fidelity():
    from aurora.infra.sp500_megarun.dehb_continuous_models import ContinuousModelError

    with pytest.raises(ContinuousModelError, match="CONTINUOUS_KEY_FIDELITY_INVALID"):
        _build_key(fidelity=6.5)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"validation_opened": True}, "CONTINUOUS_RESULT_OPENED_VALIDATION"),
        ({"locked_opened": True}, "CONTINUOUS_RESULT_OPENED_LOCKED"),
        ({"validation_opened": None}, "CONTINUOUS_RESULT_VALIDATION_FLAG_INVALID"),
        ({"locked_opened": None}, "CONTINUOUS_RESULT_LOCKED_FLAG_INVALID"),
    ],
)
def test_result_rejects_opened_or_ambiguous_later_partitions(changes, message):
    from aurora.infra.sp500_megarun.dehb_continuous_models import (
        ContinuousModelError,
        EvaluationResultV2,
    )

    with pytest.raises(ContinuousModelError, match=message):
        EvaluationResultV2.build(
            key=_build_key(),
            result={"fitness": -1.25, "cost": 0.4, "info": _result_info(**changes)},
        )


def test_result_hash_ignores_runtime_but_preserves_science():
    from aurora.infra.sp500_megarun.dehb_continuous_models import EvaluationResultV2

    first = EvaluationResultV2.build(
        key=_build_key(),
        result={
            "fitness": -1.25,
            "cost": 0.4,
            "info": {**_result_info(), "physical_runtime_seconds": 1.0},
        },
    )
    different_runtime = EvaluationResultV2.build(
        key=_build_key(),
        result={
            "fitness": -1.25,
            "cost": 0.4,
            "info": {**_result_info(), "physical_runtime_seconds": 9.0},
        },
    )
    different_science = EvaluationResultV2.build(
        key=_build_key(),
        result={"fitness": -1.24, "cost": 0.4, "info": _result_info()},
    )

    assert first.result_sha256 == different_runtime.result_sha256
    assert first.result_sha256 != different_science.result_sha256


def test_strategy_key_deduplicates_positions_but_not_fidelity_or_seed():
    from aurora.infra.sp500_megarun.dehb_continuous_models import StrategyEvaluationKeyV1

    base = StrategyEvaluationKeyV1.build(evaluation_key=_build_key(), positions_sha256=SHA_B)
    same_positions_other_config = StrategyEvaluationKeyV1.build(
        evaluation_key=_build_key(configuration={"lookback": 84, "threshold": 0.9}),
        positions_sha256=SHA_B,
    )
    other_fidelity = StrategyEvaluationKeyV1.build(
        evaluation_key=_build_key(fidelity=6), positions_sha256=SHA_B
    )
    other_seed = StrategyEvaluationKeyV1.build(
        evaluation_key=_build_key(robustness_identity="base-seed:8"),
        positions_sha256=SHA_B,
    )

    assert base.sha256 == same_positions_other_config.sha256
    assert base.sha256 != other_fidelity.sha256
    assert base.sha256 != other_seed.sha256
