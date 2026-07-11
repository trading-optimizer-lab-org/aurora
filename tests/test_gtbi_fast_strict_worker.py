from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import global_technical_buy_indicator as gtbi


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _worker_fixture(tmp_path: Path) -> dict[str, Path]:
    data = tmp_path / "data"
    data.mkdir()
    (data / "prices.parquet").write_bytes(b"prices")
    (data / "benchmark.parquet").write_bytes(b"benchmark")
    plan = tmp_path / "plan"
    (plan / "canonical_pack").mkdir(parents=True)
    shard = plan / "canonical_pack" / "strategies_shard_000.jsonl"
    shard.write_text('{"strategy_id":"one","shard_id":0,"slot_in_shard":0}\n', encoding="utf-8")
    (plan / "worker_manifest.csv").write_text(
        "evaluation_hash,canonical_strategy_id,worker_id\nabc,one,0\n",
        encoding="utf-8",
    )
    data_manifest = tmp_path / "data_manifest.json"
    data_payload = {
        "data_pack_identity": "data-id",
        "source_data_run_id": "1",
        "source_artifact_name": "data",
        "files": [
            {"path": "benchmark.parquet", "sha256": _sha(data / "benchmark.parquet"), "size_bytes": 9},
            {"path": "prices.parquet", "sha256": _sha(data / "prices.parquet"), "size_bytes": 6},
        ],
    }
    data_manifest.write_text(json.dumps(data_payload), encoding="utf-8")
    campaign = plan / "campaign_manifest.json"
    campaign.write_text(
        json.dumps(
            {
                "campaign_fingerprint": "fp",
                "inputs": {
                    "data_run_identity": "data-id",
                    "train_end": "2010-12-31",
                    "validation_start": "2011-01-01",
                    "validation_end": "2020-12-31",
                    "locked_start": "2021-01-01",
                    "min_market_cap": 2_000_000_000,
                    "execution_mode": "optimized_evaluation_v5_event_first",
                },
                "artifacts": [
                    {
                        "path": "canonical_pack/strategies_shard_000.jsonl",
                        "sha256": _sha(shard),
                        "size_bytes": shard.stat().st_size,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return {
        "data": data,
        "data_manifest": data_manifest,
        "plan": plan,
        "campaign": campaign,
        "output": tmp_path / "job-000",
    }


def test_worker_invokes_combined_evaluator_once_with_exact_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    calls: list[dict[str, object]] = []

    def run(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "total_strategies_evaluated": 1,
            "total_strategies_early_rejected": 0,
            "total_strategies_timed_out": 0,
            "total_strategies_runtime_error": 0,
            "total_strategies_unsupported": 0,
            "total_strategies_slow_deferred": 0,
        }

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    summary = worker.run_worker(
        campaign_manifest_path=paths["campaign"],
        data_manifest_path=paths["data_manifest"],
        plan_root=paths["plan"],
        data_pack_root=paths["data"],
        worker_id=0,
        output_dir=paths["output"],
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["signal_first_phase"] == "combined"
    assert call["enable_feature_cache"] is True
    assert call["enable_dedupe"] is True
    assert call["enable_safe_prefilter"] is False
    assert call["enable_early_stopping"] is False
    assert call["candidate_timeout_seconds"] == 0
    assert call["job_wall_clock_seconds"] == 0
    assert call["locked_start"] == "2021-01-01"
    assert summary["campaign_fingerprint"] == "fp"
    assert summary["worker_id"] == 0


def test_worker_fails_before_evaluation_on_digest_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    (paths["data"] / "prices.parquet").write_bytes(b"changed")
    called = False

    def run(**kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    with pytest.raises(ValueError, match="digest mismatch"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )
    assert called is False


@pytest.mark.parametrize(
    "summary",
    [
        {"total_strategies_evaluated": 0, "total_strategies_early_rejected": 0},
        {"total_strategies_evaluated": 1, "total_strategies_timed_out": 1},
        {"total_strategies_evaluated": 1, "total_strategies_runtime_error": 1},
        {"total_strategies_evaluated": 1, "total_strategies_slow_deferred": 1},
    ],
)
def test_worker_rejects_nonterminal_or_failed_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    summary: dict[str, int],
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", lambda **kwargs: summary)
    with pytest.raises(ValueError):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )


def test_data_manifest_is_content_bound_and_deterministic(tmp_path: Path) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    data = tmp_path / "data"
    data.mkdir()
    (data / "z.bin").write_bytes(b"z")
    (data / "a.bin").write_bytes(b"a")
    first = worker.create_data_pack_manifest(
        data_pack_root=data,
        output_path=tmp_path / "first.json",
        source_data_run_id="run",
        source_artifact_name="artifact",
        universe_identity="universe",
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        locked_start="2021-01-01",
    )
    second = worker.create_data_pack_manifest(
        data_pack_root=data,
        output_path=tmp_path / "second.json",
        source_data_run_id="run",
        source_artifact_name="artifact",
        universe_identity="universe",
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        locked_start="2021-01-01",
    )
    assert first == second
    (data / "a.bin").write_bytes(b"changed")
    changed = worker.create_data_pack_manifest(
        data_pack_root=data,
        output_path=tmp_path / "changed.json",
        source_data_run_id="run",
        source_artifact_name="artifact",
        universe_identity="universe",
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        locked_start="2021-01-01",
    )
    assert first["data_pack_identity"] != changed["data_pack_identity"]


def test_exact_float_cache_tokens_do_not_collide() -> None:
    assert gtbi._exact_float_cache_token(0.123456781) != gtbi._exact_float_cache_token(0.123456789)


def test_benchmark_cache_identity_depends_on_content() -> None:
    first = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=2), "close": [1.0, 2.0]})
    second = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=2), "close": [1.0, 3.0]})
    assert gtbi._benchmark_cache_identity(first) != gtbi._benchmark_cache_identity(second)


def test_timing_normalization_never_reports_less_than_components() -> None:
    diagnostic = gtbi._normalize_timing_diagnostic(
        {"seconds_total": 3.0, "seconds_signal": 10.0, "seconds_simulation": 5.0}
    )
    assert diagnostic["seconds_total"] == 15.0
    assert diagnostic["seconds_wall_candidate"] == 3.0
