from __future__ import annotations

from concurrent.futures import Future
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
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
        except BaseException as exc:  # pragma: no cover - exercised by production recovery
            future.set_exception(exc)
        return future


class _FakeOptimizer:
    def __init__(self) -> None:
        self.asked = 0
        self.told: list[int] = []

    def ask(self, n_configs: int = 1):
        jobs = []
        for _ in range(n_configs):
            index = self.asked
            self.asked += 1
            jobs.append(
                {
                    "config": {"index": index},
                    "fidelity": 27,
                    "config_id": index,
                }
            )
        return jobs[0] if n_configs == 1 else jobs

    def tell(self, job, _result) -> None:
        self.told.append(int(job["config_id"]))


_ForbiddenValueError = type(
    "ForbiddenValueError",
    (ValueError,),
    {"__module__": "ConfigSpace.exceptions"},
)


class _ForbiddenOnceOptimizer(_FakeOptimizer):
    def __init__(self) -> None:
        super().__init__()
        self.request_sizes: list[int] = []
        self.rejected = False

    def ask(self, n_configs: int = 1):
        self.request_sizes.append(n_configs)
        if n_configs != 1:
            raise AssertionError("runner must not lose partial DEHB batches")
        if not self.rejected:
            self.rejected = True
            raise _ForbiddenValueError("forbidden synthetic vector")
        return super().ask(n_configs=n_configs)


class _AlwaysForbiddenOptimizer:
    def ask(self, n_configs: int = 1):
        assert n_configs == 1
        raise _ForbiddenValueError("always forbidden synthetic vector")


class _BrokenOptimizer:
    def ask(self, n_configs: int = 1):
        assert n_configs == 1
        raise RuntimeError("unrelated optimizer failure")


class _FakeConfigRepository:
    def __init__(self) -> None:
        self.configs = [SimpleNamespace(config={"initial": index}) for index in range(4)]

    def announce_config(self, config, _fidelity) -> int:
        config_id = len(self.configs)
        self.configs.append(SimpleNamespace(config=config))
        return config_id


class _ReplaySubpopulation:
    def __init__(self) -> None:
        self.calls = 0

    def vector_to_configspace(self, vector):
        self.calls += 1
        if self.calls == 1:
            raise _ForbiddenValueError("forbidden checkpoint replay vector")
        return {"vector": vector}


class _BatchedCheckpointReplayOptimizer:
    def __init__(self, *, resume: bool) -> None:
        self.ask_calls = 0
        self.events: list[str] = []
        self.cs = SimpleNamespace(get_default_configuration=lambda: {"default": True})
        self.de = {1: _ReplaySubpopulation()}
        self.config_repository = _FakeConfigRepository()
        if resume:
            self._load_checkpoint("checkpoint")

    def _load_checkpoint(self, _run_dir: str) -> bool:
        for index, config_id in enumerate((4, 6, 7, 9)):
            self.tell(
                {"config": {"index": index}, "fidelity": 27, "config_id": config_id},
                {"fitness": float(index), "cost": 1.0, "info": {}},
                replay=True,
            )
        return True

    def ask(self, n_configs: int = 1):
        assert n_configs == 1
        self.ask_calls += 1
        self.events.append("ask")
        configuration = self.de[1].vector_to_configspace(self.ask_calls)
        index = self.config_repository.announce_config(configuration, 1)
        return {
            "config": configuration,
            "fidelity": 1,
            "config_id": index,
            "parent_id": index,
            "bracket_id": 0,
        }

    def tell(self, job_info, _result, replay: bool = False) -> None:
        if replay:
            job_info = self.ask()
        self.events.append("tell")


class _Clock:
    def __init__(self, values: list[float]) -> None:
        self.values = list(values)
        self.last = values[-1]

    def __call__(self) -> float:
        if self.values:
            self.last = self.values.pop(0)
        else:
            self.last += 1.0
        return self.last


def _objective(config, fidelity):
    index = int(config["index"])
    return {
        "fitness": float(index),
        "cost": float(fidelity),
        "info": {
            "archive_key": [0.0, -0.20, -0.60, -0.10],
            "full_fidelity": True,
            "train_feasible": True,
            "validation_opened": False,
            "locked_opened": False,
            "strategy_fingerprint": f"fingerprint-{index}",
            "position_fingerprint": f"positions-{index}",
        },
    }


def _determinism_audit(lane_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "lane_id": lane_id,
        "fidelity": 27,
        "configuration_sha256": "1" * 64,
        "result_sha256": "2" * 64,
        "independent_process_evaluations": 2,
        "passed": True,
        "validation_opened": False,
        "locked_opened": False,
    }


def test_official_ask_tell_slice_uses_four_parallel_slots_and_stops_on_plateau() -> None:
    from aurora.infra.sp500_megarun.dehb_island_runner import run_ask_tell_slice

    optimizer = _FakeOptimizer()
    result = run_ask_tell_slice(
        optimizer,
        _objective,
        n_workers=4,
        full_fidelity=27,
        slice_seconds=10_000,
        plateau_minimum_completed=4,
        plateau_completed_without_improvement=4,
        plateau_seconds_without_improvement=9_000,
        clock=_Clock([0.0, 1.0, 2.0, 3.0, 4.0]),
        executor_factory=_ImmediateExecutor,
    )

    assert result.status == "completed"
    assert result.stop_reason == "plateau_completed_evaluations"
    assert result.evaluations == 8
    assert result.full_fidelity_evaluations == 8
    assert optimizer.told == list(range(8))
    assert len(result.trials) == 8


def test_official_ask_tell_slice_pauses_at_runner_boundary_for_exact_resume() -> None:
    from aurora.infra.sp500_megarun.dehb_island_runner import run_ask_tell_slice

    optimizer = _FakeOptimizer()
    result = run_ask_tell_slice(
        optimizer,
        _objective,
        n_workers=4,
        full_fidelity=27,
        slice_seconds=10,
        plateau_minimum_completed=128,
        plateau_completed_without_improvement=512,
        plateau_seconds_without_improvement=120,
        clock=_Clock([0.0, 1.0, 11.0]),
        executor_factory=_ImmediateExecutor,
    )

    assert result.status == "paused_at_runner_slice"
    assert result.stop_reason == "runner_slice_elapsed"
    assert result.evaluations == 4
    assert optimizer.told == [0, 1, 2, 3]


def test_official_ask_tell_slice_rejects_only_forbidden_configspace_vectors() -> None:
    from aurora.infra.sp500_megarun.dehb_island_runner import run_ask_tell_slice

    optimizer = _ForbiddenOnceOptimizer()
    result = run_ask_tell_slice(
        optimizer,
        _objective,
        n_workers=4,
        full_fidelity=27,
        slice_seconds=10,
        plateau_minimum_completed=128,
        plateau_completed_without_improvement=512,
        plateau_seconds_without_improvement=120,
        clock=_Clock([0.0, 1.0, 11.0]),
        executor_factory=_ImmediateExecutor,
    )

    assert result.evaluations == 4
    assert result.invalid_config_rejections == 1
    assert optimizer.told == [0, 1, 2, 3]
    assert optimizer.request_sizes == [1, 1, 1, 1, 1]


def test_official_ask_tell_slice_fails_closed_after_forbidden_rejection_limit() -> None:
    from aurora.infra.sp500_megarun.dehb_island_runner import (
        IslandRunnerError,
        run_ask_tell_slice,
    )

    with pytest.raises(
        IslandRunnerError,
        match="OFFICIAL_DEHB_FORBIDDEN_REJECTION_LIMIT",
    ):
        run_ask_tell_slice(
            _AlwaysForbiddenOptimizer(),
            _objective,
            n_workers=4,
            full_fidelity=27,
            slice_seconds=10,
            plateau_minimum_completed=128,
            plateau_completed_without_improvement=512,
            plateau_seconds_without_improvement=120,
            max_invalid_config_rejections_per_slice=2,
            clock=_Clock([0.0, 1.0]),
            executor_factory=_ImmediateExecutor,
        )


def test_official_ask_tell_slice_does_not_mask_unrelated_optimizer_errors() -> None:
    from aurora.infra.sp500_megarun.dehb_island_runner import run_ask_tell_slice

    with pytest.raises(RuntimeError, match="unrelated optimizer failure"):
        run_ask_tell_slice(
            _BrokenOptimizer(),
            _objective,
            n_workers=4,
            full_fidelity=27,
            slice_seconds=10,
            plateau_minimum_completed=128,
            plateau_completed_without_improvement=512,
            plateau_seconds_without_improvement=120,
            clock=_Clock([0.0, 1.0]),
            executor_factory=_ImmediateExecutor,
        )


def test_official_checkpoint_resume_replays_original_four_job_batches() -> None:
    from aurora.infra.sp500_megarun.dehb_island_runner import (
        _resume_safe_dehb_class,
    )

    guarded = _resume_safe_dehb_class(_BatchedCheckpointReplayOptimizer)
    optimizer = guarded(resume=True)

    assert optimizer.events == ["ask"] * 4 + ["tell"] * 4
    assert optimizer.ask_calls == 4
    assert optimizer.resume_forbidden_rejections == 1
    assert len(optimizer.config_repository.configs) == 10
    assert optimizer.config_repository.configs[9].config == {"index": 3}
    assert optimizer.de[1].vector_to_configspace.__self__ is optimizer.de[1]


def test_island_bundle_contains_native_checkpoint_ledgers_and_closed_audits(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_job_payload
    from aurora.infra.sp500_megarun.dehb_island_runner import (
        run_ask_tell_slice,
        verify_island_bundle,
        write_island_bundle,
    )

    repo = Path(__file__).resolve().parents[1]
    campaign = load_and_validate_campaign_contract(
        repo / "config" / "sp500_megarun_dehb_campaign_v1.json"
    )
    assignment = build_job_payload(campaign, job_index=0, wave=0, restart_ordinal=0)["islands"][0]
    search = run_ask_tell_slice(
        _FakeOptimizer(),
        _objective,
        n_workers=4,
        full_fidelity=27,
        slice_seconds=10,
        plateau_minimum_completed=128,
        plateau_completed_without_improvement=512,
        plateau_seconds_without_improvement=120,
        clock=_Clock([0.0, 1.0, 11.0]),
        executor_factory=_ImmediateExecutor,
    )
    bundle = tmp_path / "F001-R1"
    native = bundle / "native_checkpoint"
    native.mkdir(parents=True)
    (native / "dehb_state.json").write_text('{"state":"official"}', "utf-8")
    (native / "history.parquet.gzip").write_bytes(b"official-history")

    result = write_island_bundle(
        campaign,
        assignment=assignment,
        wave=0,
        search=search,
        output_dir=bundle,
        data_access_audit={
            "train_partition": "train_snapshot_1993_2010",
            "validation_opened": False,
            "locked_opened": False,
        },
        determinism_audit=_determinism_audit(str(assignment["lane_id"])),
    )

    required = {
        "island_manifest.json",
        "checkpoint_envelope.json",
        "trial_ledger.parquet",
        "full_fidelity_candidates.parquet",
        "pareto_front.parquet",
        "annual_metrics.parquet",
        "failure_ledger.jsonl",
        "runtime_audit.json",
        "evaluation_cache_manifest.json",
        "determinism_audit.json",
        "data_access_audit.json",
        "checksums.sha256",
    }
    assert required <= {path.name for path in bundle.iterdir() if path.is_file()}
    assert result["status"] == "paused_at_runner_slice"
    assert result["validation_opened"] is False
    assert result["locked_opened"] is False
    manifest = json.loads((bundle / "island_manifest.json").read_text("utf-8"))
    assert manifest["official_dehb_native_checkpoint"] is True
    assert manifest["invalid_config_rejections"] == 0
    assert manifest["champion"]["robustness_passed"] is False
    runtime_audit = json.loads((bundle / "runtime_audit.json").read_text("utf-8"))
    assert runtime_audit["invalid_config_rejections"] == 0
    assert runtime_audit["physical_evaluations"] == 4
    assert runtime_audit["full_fidelity_physical_evaluations"] == 4
    assert runtime_audit["cache_hits"] == 0
    assert runtime_audit["cache_hits_by_origin"] == {}
    assert runtime_audit["unique_strategies"] == 4
    trial_ledger = pd.read_parquet(bundle / "trial_ledger.parquet")
    assert {
        "cache_key_sha256",
        "run_id",
        "wave",
        "island_id",
        "evaluation_origin",
        "cache_result_sha256",
        "cache_source_run_id",
        "cache_source_wave",
        "cache_source_island_id",
        "cache_source_evaluation",
        "physical_runtime_seconds",
    } <= set(trial_ledger.columns)
    assert set(trial_ledger["evaluation_origin"]) == {"physical"}
    assert manifest["physical_evaluations"] == 4
    assert manifest["cache_hits"] == 0
    assert (
        verify_island_bundle(campaign, bundle, expected_island_id=str(assignment["island_id"]))[
            "verified"
        ]
        is True
    )

    (bundle / "runtime_audit.json").write_text("{}", "utf-8")
    try:
        verify_island_bundle(campaign, bundle, expected_island_id=str(assignment["island_id"]))
    except ValueError as exc:
        assert "BUNDLE_CHECKSUM_MISMATCH" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("tampered bundle was accepted")


def test_verified_cache_round_trip_rejects_incompatible_evaluator(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_job_payload
    from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
        EvaluationCacheKeyV1,
    )
    from aurora.infra.sp500_megarun.dehb_island_runner import (
        IslandRunnerError,
        load_verified_evaluation_cache,
        run_ask_tell_slice,
        write_island_bundle,
    )

    repo = Path(__file__).resolve().parents[1]
    campaign = load_and_validate_campaign_contract(
        repo / "config" / "sp500_megarun_dehb_campaign_v1.json"
    )
    assignment = build_job_payload(campaign, job_index=0, wave=0, restart_ordinal=0)["islands"][0]
    evaluator_sha = "7" * 64
    search = run_ask_tell_slice(
        _FakeOptimizer(),
        _objective,
        n_workers=4,
        full_fidelity=27,
        slice_seconds=10,
        plateau_minimum_completed=128,
        plateau_completed_without_improvement=512,
        plateau_seconds_without_improvement=120,
        clock=_Clock([0.0, 1.0, 11.0]),
        executor_factory=_ImmediateExecutor,
        evaluation_key=lambda job: EvaluationCacheKeyV1.build(
            scientific_evaluator_sha256=evaluator_sha,
            train_snapshot_manifest_sha256=(campaign.train_snapshot_manifest_sha256),
            lane_id=str(assignment["lane_id"]),
            configuration=job["config"],
            fidelity=job["fidelity"],
        ),
        source_run_id=123,
        source_wave=0,
        source_island_id=str(assignment["island_id"]),
    )
    bundle = tmp_path / str(assignment["island_id"])
    native = bundle / "native_checkpoint"
    native.mkdir(parents=True)
    (native / "dehb_state.json").write_text("{}", encoding="utf-8")
    write_island_bundle(
        campaign,
        assignment=assignment,
        wave=0,
        search=search,
        output_dir=bundle,
        data_access_audit={
            "validation_opened": False,
            "locked_opened": False,
        },
        launch_contract_sha256="8" * 64,
        scientific_evaluator_sha256=evaluator_sha,
        source_run_id=123,
        determinism_audit=_determinism_audit(str(assignment["lane_id"])),
    )

    cache = load_verified_evaluation_cache(
        campaign,
        bundle_sources=((bundle, 123, "prior_wave_cache"),),
        lane_id=str(assignment["lane_id"]),
        scientific_evaluator_sha256=evaluator_sha,
        expected_launch_contract_sha256="8" * 64,
    )

    assert len(cache) == 4
    assert {entry["source_run_id"] for entry in cache.values()} == {123}
    with pytest.raises(IslandRunnerError, match="CACHE_MANIFEST_MISMATCH"):
        load_verified_evaluation_cache(
            campaign,
            bundle_sources=((bundle, 123, "prior_wave_cache"),),
            lane_id=str(assignment["lane_id"]),
            scientific_evaluator_sha256="9" * 64,
            expected_launch_contract_sha256="8" * 64,
        )
