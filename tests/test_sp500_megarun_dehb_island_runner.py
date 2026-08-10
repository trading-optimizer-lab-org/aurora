from __future__ import annotations

from concurrent.futures import Future
import json
from pathlib import Path
from typing import Any


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

    def ask(self, n_configs: int):
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
        return jobs

    def tell(self, job, _result) -> None:
        self.told.append(int(job["config_id"]))


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
            "strategy_fingerprint": f"fingerprint-{index}",
        },
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
    assignment = build_job_payload(
        campaign, job_index=0, wave=0, restart_ordinal=0
    )["islands"][0]
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
        "data_access_audit.json",
        "checksums.sha256",
    }
    assert required <= {path.name for path in bundle.iterdir() if path.is_file()}
    assert result["status"] == "paused_at_runner_slice"
    assert result["validation_opened"] is False
    assert result["locked_opened"] is False
    manifest = json.loads((bundle / "island_manifest.json").read_text("utf-8"))
    assert manifest["official_dehb_native_checkpoint"] is True
    assert manifest["champion"]["robustness_passed"] is False
    assert verify_island_bundle(
        campaign, bundle, expected_island_id=str(assignment["island_id"])
    )["verified"] is True

    (bundle / "runtime_audit.json").write_text("{}", "utf-8")
    try:
        verify_island_bundle(
            campaign, bundle, expected_island_id=str(assignment["island_id"])
        )
    except ValueError as exc:
        assert "BUNDLE_CHECKSUM_MISMATCH" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("tampered bundle was accepted")
