from __future__ import annotations

from concurrent.futures import Future
from typing import Any

import pytest


class _ImmediateExecutor:
    def __init__(self, *, max_workers: int) -> None:
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def submit(self, function, *args):
        future: Future[Any] = Future()
        try:
            future.set_result(function(*args))
        except BaseException as exc:  # pragma: no cover - production propagation
            future.set_exception(exc)
        return future


class _DuplicateBatchOptimizer:
    def __init__(self) -> None:
        self.asked = 0
        self.told: list[tuple[int, float]] = []

    def ask(self, n_configs: int = 1):
        assert n_configs == 1
        config_id = self.asked
        self.asked += 1
        return {
            "config": {"window": 63, "direction": "continuation"},
            "fidelity": 27,
            "config_id": config_id,
        }

    def tell(self, job, result) -> None:
        self.told.append((int(job["config_id"]), float(result["fitness"])))


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


def _result(fingerprint: str = "a" * 64) -> dict[str, Any]:
    return {
        "fitness": -0.12,
        "cost": 27.0,
        "info": {
            "archive_key": [0.0, -0.12, -0.55, -0.08],
            "full_fidelity": True,
            "train_feasible": True,
            "strategy_fingerprint": fingerprint,
            "position_fingerprint": "b" * 64,
            "validation_opened": False,
            "locked_opened": False,
        },
    }


def test_cache_key_is_canonical_and_scientifically_bound() -> None:
    import numpy as np
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        EvaluationCacheKeyV1,
    )

    first = EvaluationCacheKeyV1.build(
        scientific_evaluator_sha256="1" * 64,
        train_snapshot_manifest_sha256="2" * 64,
        lane_id="F024",
        configuration={"window": 63, "threshold": 0.5},
        fidelity=27,
    )
    reordered = EvaluationCacheKeyV1.build(
        scientific_evaluator_sha256="1" * 64,
        train_snapshot_manifest_sha256="2" * 64,
        lane_id="F024",
        configuration={"threshold": np.float64(0.5), "window": np.int64(63)},
        fidelity=np.float64(27.0),
    )
    changed_data = EvaluationCacheKeyV1.build(
        scientific_evaluator_sha256="1" * 64,
        train_snapshot_manifest_sha256="3" * 64,
        lane_id="F024",
        configuration={"window": 63, "threshold": 0.5},
        fidelity=27,
    )

    assert first.sha256 == reordered.sha256
    assert first.sha256 != changed_data.sha256
    assert first.configuration == {"threshold": 0.5, "window": 63}
    assert first.fidelity == 27
    changed_config = EvaluationCacheKeyV1.build(
        scientific_evaluator_sha256="1" * 64,
        train_snapshot_manifest_sha256="2" * 64,
        lane_id="F024",
        configuration={"window": 126, "threshold": 0.5},
        fidelity=27,
    )
    changed_fidelity = EvaluationCacheKeyV1.build(
        scientific_evaluator_sha256="1" * 64,
        train_snapshot_manifest_sha256="2" * 64,
        lane_id="F024",
        configuration={"window": 63, "threshold": 0.5},
        fidelity=9,
    )
    changed_code = EvaluationCacheKeyV1.build(
        scientific_evaluator_sha256="4" * 64,
        train_snapshot_manifest_sha256="2" * 64,
        lane_id="F024",
        configuration={"window": 63, "threshold": 0.5},
        fidelity=27,
    )
    assert (
        len(
            {
                first.sha256,
                changed_config.sha256,
                changed_fidelity.sha256,
                changed_code.sha256,
            }
        )
        == 4
    )


def test_scientific_evaluator_binding_changes_with_any_frozen_input() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        scientific_evaluator_binding_sha256,
    )

    baseline = scientific_evaluator_binding_sha256(
        code_commit_sha="a" * 40,
        campaign_contract_sha256="1" * 64,
        runtime_scientific_input_binding_sha256="2" * 64,
        numeric_runtime_profile_sha256="3" * 64,
    )

    assert baseline == scientific_evaluator_binding_sha256(
        code_commit_sha="a" * 40,
        campaign_contract_sha256="1" * 64,
        runtime_scientific_input_binding_sha256="2" * 64,
        numeric_runtime_profile_sha256="3" * 64,
    )
    assert baseline != scientific_evaluator_binding_sha256(
        code_commit_sha="b" * 40,
        campaign_contract_sha256="1" * 64,
        runtime_scientific_input_binding_sha256="2" * 64,
        numeric_runtime_profile_sha256="3" * 64,
    )
    assert baseline != scientific_evaluator_binding_sha256(
        code_commit_sha="a" * 40,
        campaign_contract_sha256="3" * 64,
        runtime_scientific_input_binding_sha256="2" * 64,
        numeric_runtime_profile_sha256="3" * 64,
    )
    assert baseline != scientific_evaluator_binding_sha256(
        code_commit_sha="a" * 40,
        campaign_contract_sha256="1" * 64,
        runtime_scientific_input_binding_sha256="2" * 64,
        numeric_runtime_profile_sha256="4" * 64,
    )


def test_scientific_result_normalization_removes_final_bit_noise_only() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        normalize_scientific_result,
        scientific_result_sha256,
    )

    first = _result()
    second = _result()
    first["fitness"] = 0.123456789012341
    second["fitness"] = 0.123456789012349
    first["info"]["config"] = {"threshold": 0.12345678901234567}
    second["info"]["config"] = {"threshold": 0.12345678901234567}
    first["info"]["objective_runtime_seconds"] = 1.0
    second["info"]["objective_runtime_seconds"] = 99.0

    normalized_first = normalize_scientific_result(first)
    normalized_second = normalize_scientific_result(second)

    assert normalized_first["fitness"] == 0.123456789012
    assert normalized_second["fitness"] == 0.123456789012
    assert normalized_first["info"]["config"]["threshold"] == 0.12345678901234567
    assert normalized_first["info"]["objective_runtime_seconds"] == 1.0
    assert normalized_second["info"]["objective_runtime_seconds"] == 99.0
    assert scientific_result_sha256(normalized_first) == scientific_result_sha256(
        normalized_second
    )


def test_cache_registry_rejects_one_key_with_two_scientific_results() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        EvaluationCacheConflictError,
        EvaluationCacheEntryV1,
        EvaluationCacheKeyV1,
        EvaluationCacheRegistry,
    )

    key = EvaluationCacheKeyV1.build(
        scientific_evaluator_sha256="1" * 64,
        train_snapshot_manifest_sha256="2" * 64,
        lane_id="F067",
        configuration={"bins": 5, "order": 3},
        fidelity=27,
    )
    registry = EvaluationCacheRegistry()
    registry.add(
        EvaluationCacheEntryV1.build(
            key=key,
            result=_result("a" * 64),
            source_run_id=1,
            source_wave=0,
            source_island_id="F067-R1",
            source_evaluation=10,
        )
    )

    with pytest.raises(
        EvaluationCacheConflictError,
        match="EVALUATION_CACHE_RESULT_CONFLICT",
    ):
        registry.add(
            EvaluationCacheEntryV1.build(
                key=key,
                result=_result("c" * 64),
                source_run_id=2,
                source_wave=1,
                source_island_id="F067-R2",
                source_evaluation=20,
            )
        )


def test_ask_tell_slice_coalesces_batch_and_island_duplicates() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        EvaluationCacheKeyV1,
    )
    from aurora.infra.sp500_megarun.dehb_island_runner import run_ask_tell_slice

    optimizer = _DuplicateBatchOptimizer()
    physical_calls = 0

    def objective(_config, _fidelity):
        nonlocal physical_calls
        physical_calls += 1
        return _result()

    def key_for(job):
        return EvaluationCacheKeyV1.build(
            scientific_evaluator_sha256="1" * 64,
            train_snapshot_manifest_sha256="2" * 64,
            lane_id="F024",
            configuration=job["config"],
            fidelity=job["fidelity"],
        )

    result = run_ask_tell_slice(
        optimizer,
        objective,
        n_workers=4,
        full_fidelity=27,
        slice_seconds=10_000,
        plateau_minimum_completed=4,
        plateau_completed_without_improvement=4,
        plateau_seconds_without_improvement=9_000,
        clock=_Clock(),
        executor_factory=_ImmediateExecutor,
        evaluation_key=key_for,
    )

    assert result.evaluations == 8
    assert result.physical_evaluations == 1
    assert result.full_fidelity_physical_evaluations == 1
    assert result.cache_hits == 7
    assert result.cache_hits_by_origin == {"batch_cache": 3, "island_cache": 4}
    assert physical_calls == 1
    assert optimizer.told == [(index, -0.12) for index in range(8)]
    assert [trial["evaluation_origin"] for trial in result.trials] == [
        "physical",
        "batch_cache",
        "batch_cache",
        "batch_cache",
        "island_cache",
        "island_cache",
        "island_cache",
        "island_cache",
    ]
    assert len({trial["cache_key_sha256"] for trial in result.trials}) == 1
    assert result.trials[1]["cache_source_evaluation"] == 1


def test_cache_preserves_exact_dehb_responses_and_stop_trajectory() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        EvaluationCacheKeyV1,
    )
    from aurora.infra.sp500_megarun.dehb_island_runner import run_ask_tell_slice

    def run(*, cached: bool):
        optimizer = _DuplicateBatchOptimizer()
        result = run_ask_tell_slice(
            optimizer,
            lambda _config, _fidelity: _result(),
            n_workers=4,
            full_fidelity=27,
            slice_seconds=10_000,
            plateau_minimum_completed=4,
            plateau_completed_without_improvement=4,
            plateau_seconds_without_improvement=9_000,
            clock=_Clock(),
            executor_factory=_ImmediateExecutor,
            evaluation_key=(
                lambda job: EvaluationCacheKeyV1.build(
                    scientific_evaluator_sha256="1" * 64,
                    train_snapshot_manifest_sha256="2" * 64,
                    lane_id="F024",
                    configuration=job["config"],
                    fidelity=job["fidelity"],
                )
            )
            if cached
            else None,
        )
        return optimizer, result

    uncached_optimizer, uncached = run(cached=False)
    cached_optimizer, cached = run(cached=True)

    assert cached_optimizer.told == uncached_optimizer.told
    assert cached.status == uncached.status
    assert cached.stop_reason == uncached.stop_reason
    assert cached.evaluations == uncached.evaluations
    assert cached.full_fidelity_evaluations == uncached.full_fidelity_evaluations
    assert [trial["fitness"] for trial in cached.trials] == [
        trial["fitness"] for trial in uncached.trials
    ]
    assert [trial["info"] for trial in cached.trials] == [
        trial["info"] for trial in uncached.trials
    ]


def test_ask_tell_slice_reuses_verified_prior_wave_entry() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        EvaluationCacheEntryV1,
        EvaluationCacheKeyV1,
    )
    from aurora.infra.sp500_megarun.dehb_island_runner import run_ask_tell_slice

    key = EvaluationCacheKeyV1.build(
        scientific_evaluator_sha256="1" * 64,
        train_snapshot_manifest_sha256="2" * 64,
        lane_id="F024",
        configuration={"window": 63, "direction": "continuation"},
        fidelity=27,
    )
    entry = EvaluationCacheEntryV1.build(
        key=key,
        result=_result(),
        source_run_id=31673408102,
        source_wave=0,
        source_island_id="F024-R2",
        source_evaluation=77,
    )
    physical_calls = 0

    def objective(_config, _fidelity):
        nonlocal physical_calls
        physical_calls += 1
        return _result()

    result = run_ask_tell_slice(
        _DuplicateBatchOptimizer(),
        objective,
        n_workers=4,
        full_fidelity=27,
        slice_seconds=10_000,
        plateau_minimum_completed=4,
        plateau_completed_without_improvement=4,
        plateau_seconds_without_improvement=9_000,
        clock=_Clock(),
        executor_factory=_ImmediateExecutor,
        initial_evaluation_cache={
            key.sha256: {
                "result": entry.result,
                "result_sha256": entry.result_sha256,
                "source_run_id": entry.source_run_id,
                "source_wave": entry.source_wave,
                "source_island_id": entry.source_island_id,
                "source_evaluation": entry.source_evaluation,
            }
        },
        evaluation_key=lambda _job: key,
    )

    assert physical_calls == 0
    assert result.physical_evaluations == 0
    assert result.cache_hits == 8
    assert result.cache_hits_by_origin == {"prior_wave_cache": 8}
    assert {trial["evaluation_origin"] for trial in result.trials} == {"prior_wave_cache"}
    assert result.trials[0]["cache_source_run_id"] == 31673408102
    assert result.trials[0]["cache_source_island_id"] == "F024-R2"


def test_multiprocess_determinism_audit_rejects_different_results() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        EvaluationCacheConflictError,
        audit_multiprocess_determinism,
    )

    calls = 0

    def unstable(_config, fidelity):
        nonlocal calls
        calls += 1
        return _result(("a" if calls == 1 else "c") * 64) | {"cost": float(fidelity)}

    with pytest.raises(
        EvaluationCacheConflictError,
        match="EVALUATION_DETERMINISM_AUDIT_CONFLICT:F069",
    ):
        audit_multiprocess_determinism(
            unstable,
            lane_id="F069",
            configuration={"window": 252},
            fidelity=27,
            executor_factory=_ImmediateExecutor,
        )


def test_multiprocess_determinism_audit_accepts_exact_scientific_result() -> None:
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        audit_multiprocess_determinism,
    )

    receipt = audit_multiprocess_determinism(
        lambda _config, fidelity: _result() | {"cost": float(fidelity)},
        lane_id="F067",
        configuration={"window": 252},
        fidelity=27,
        executor_factory=_ImmediateExecutor,
    )

    assert receipt["passed"] is True
    assert receipt["independent_process_evaluations"] == 2
    assert receipt["validation_opened"] is False
    assert receipt["locked_opened"] is False
