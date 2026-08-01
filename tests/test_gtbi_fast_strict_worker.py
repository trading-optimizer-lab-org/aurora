# mypy: ignore-errors
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import global_technical_buy_indicator as gtbi


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _data_pack_identity(payload: dict[str, object]) -> str:
    identity_payload = {key: value for key, value in payload.items() if key != "data_pack_identity"}
    return hashlib.sha256(_canonical_json(identity_payload)).hexdigest()


def _worker_fixture(tmp_path: Path) -> dict[str, Path]:
    from scripts import gtbi_fast_strict as strict

    data = tmp_path / "data"
    data.mkdir()
    (data / "prices.csv").write_text("date,close\n2020-12-31,100\n", encoding="utf-8")
    (data / "benchmark.csv").write_text("date,close\n2020-12-31,200\n", encoding="utf-8")
    plan = tmp_path / "plan"
    (plan / "canonical_pack").mkdir(parents=True)
    shard = plan / "canonical_pack" / "strategies_shard_000.jsonl"
    shard.write_text('{"strategy_id":"one","shard_id":0,"slot_in_shard":0}\n', encoding="utf-8")
    worker_manifest = plan / "worker_manifest.csv"
    worker_manifest.write_text(
        "evaluation_hash,canonical_strategy_id,source_shard_id,source_slot_in_shard,global_slot,worker_id,raw_cost_score,scheduling_cost\n"
        "abc,one,0,0,0,0,1.0,1.0\n",
        encoding="utf-8",
    )
    alias_map = plan / "alias_map.csv"
    alias_map.write_text(
        "strategy_id,evaluation_hash,canonical_strategy_id,source_shard_id,source_slot_in_shard,global_slot,worker_id\n"
        "one,abc,one,0,0,0,0\n",
        encoding="utf-8",
    )
    data_manifest = tmp_path / "data_manifest.json"
    data_payload = {
        "source_data_run_id": "1",
        "source_artifact_name": "data",
        "universe_identity": "universe-id",
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "min_market_cap": 2_000_000_000,
        "files": [
            {"path": "benchmark.csv", "sha256": _sha(data / "benchmark.csv"), "size_bytes": (data / "benchmark.csv").stat().st_size},
            {"path": "prices.csv", "sha256": _sha(data / "prices.csv"), "size_bytes": (data / "prices.csv").stat().st_size},
        ],
    }
    data_payload["data_pack_identity"] = _data_pack_identity(data_payload)
    data_manifest.write_text(json.dumps(data_payload), encoding="utf-8")
    inputs = {
        "code_sha": "code-sha",
        "strategy_pack_digest": "strategy-pack-digest",
        "data_run_identity": data_payload["data_pack_identity"],
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "min_market_cap": 2_000_000_000,
        "execution_mode": "optimized_evaluation_v5_event_first",
        "universe_identity": "universe-id",
        "dependency_lock_identity": "dependency-lock-id",
    }
    artifacts = [
        {
            "path": "canonical_pack/strategies_shard_000.jsonl",
            "sha256": _sha(shard),
            "size_bytes": shard.stat().st_size,
        },
        {
            "path": "worker_manifest.csv",
            "sha256": _sha(worker_manifest),
            "size_bytes": worker_manifest.stat().st_size,
        },
        {
            "path": "alias_map.csv",
            "sha256": _sha(alias_map),
            "size_bytes": alias_map.stat().st_size,
        },
    ]
    plan_content = {
        "assignments": {"abc": 0},
        "bundle_assignments": {"signal-abc": 0},
        "counts": {"candidate_count": 1, "unique_economic_groups": 1, "worker_count": 1},
    }
    campaign = plan / "campaign_manifest.json"
    campaign.write_text(
        json.dumps(
            {
                "campaign_fingerprint": strict.campaign_fingerprint(
                    **inputs,
                    artifact_inventory=artifacts,
                    plan_content=plan_content,
                ),
                "inputs": inputs,
                "artifacts": artifacts,
                "plan_content": plan_content,
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
    assert summary["campaign_fingerprint"] == json.loads(paths["campaign"].read_text(encoding="utf-8"))["campaign_fingerprint"]
    assert summary["worker_id"] == 0


def test_worker_output_manifest_satisfies_block_merge_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_block as block
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)

    def run(**kwargs: object) -> dict[str, object]:
        output_dir = Path(str(kwargs["output_dir"]))
        (output_dir / "leaderboard_job_000.csv").write_text(
            "candidate_id,score\none,1.0\n",
            encoding="utf-8",
        )
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

    manifest, canonical_ids = block._verify_worker_manifest(
        worker_root=paths["output"],
        worker_id=0,
        fingerprint=str(summary["campaign_fingerprint"]),
        canonical_count=1,
    )
    assert canonical_ids == ["one"]
    assert manifest["worker_id"] == 0
    assert {record["path"] for record in manifest["files"]} == {
        "campaign_manifest.json",
        "leaderboard_job_000.csv",
        "worker_summary.json",
    }


@pytest.mark.parametrize("tampered_component", ("artifacts", "plan_content"))
def test_worker_rejects_campaign_fingerprint_tampered_plan_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tampered_component: str,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    campaign = json.loads(paths["campaign"].read_text(encoding="utf-8"))
    if tampered_component == "artifacts":
        campaign["artifacts"][0]["sha256"] = "0" * 64
    else:
        campaign["plan_content"]["counts"]["candidate_count"] = 2
    paths["campaign"].write_text(json.dumps(campaign), encoding="utf-8")
    called = False

    def run(**kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    with pytest.raises(ValueError, match="campaign fingerprint"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )
    assert called is False


def test_worker_fails_before_evaluation_on_digest_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    (paths["data"] / "prices.csv").write_text("date,close\n2020-12-31,999\n", encoding="utf-8")
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


@pytest.mark.parametrize("relative_path", ("worker_manifest.csv", "alias_map.csv"))
def test_worker_fails_before_evaluation_on_tampered_plan_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    artifact = paths["plan"] / relative_path
    artifact.write_text(artifact.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
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


def test_worker_recomputes_campaign_fingerprint_before_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    campaign = json.loads(paths["campaign"].read_text(encoding="utf-8"))
    campaign["inputs"]["min_market_cap"] = 1
    paths["campaign"].write_text(json.dumps(campaign), encoding="utf-8")
    called = False

    def run(**kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    with pytest.raises(ValueError, match="campaign fingerprint"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )
    assert called is False


def test_worker_rejects_canonical_shard_inconsistent_with_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    shard = paths["plan"] / "canonical_pack" / "strategies_shard_000.jsonl"
    shard.write_text('{"strategy_id":"tampered","shard_id":0,"slot_in_shard":0}\n', encoding="utf-8")
    campaign = json.loads(paths["campaign"].read_text(encoding="utf-8"))
    campaign["artifacts"][0]["sha256"] = _sha(shard)
    campaign["artifacts"][0]["size_bytes"] = shard.stat().st_size
    campaign["campaign_fingerprint"] = worker.strict.campaign_fingerprint(
        **campaign["inputs"],
        artifact_inventory=campaign["artifacts"],
        plan_content=campaign["plan_content"],
    )
    paths["campaign"].write_text(json.dumps(campaign), encoding="utf-8")
    called = False

    def run(**kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    with pytest.raises(ValueError, match="canonical shard does not match worker manifest"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )
    assert called is False


def test_worker_recomputes_data_pack_identity_before_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    data_manifest = json.loads(paths["data_manifest"].read_text(encoding="utf-8"))
    data_manifest["min_market_cap"] = 1
    paths["data_manifest"].write_text(json.dumps(data_manifest), encoding="utf-8")
    called = False

    def run(**kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    with pytest.raises(ValueError, match="data pack identity"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )
    assert called is False


def test_worker_rejects_prepared_data_at_locked_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import gtbi_fast_strict as strict
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    prices = paths["data"] / "prices.csv"
    prices.write_text("date,close\n2021-01-01,100\n", encoding="utf-8")
    data_manifest = json.loads(paths["data_manifest"].read_text(encoding="utf-8"))
    data_manifest["files"][1] = {
        "path": "prices.csv",
        "sha256": _sha(prices),
        "size_bytes": prices.stat().st_size,
    }
    data_manifest["data_pack_identity"] = _data_pack_identity(data_manifest)
    paths["data_manifest"].write_text(json.dumps(data_manifest), encoding="utf-8")
    campaign = json.loads(paths["campaign"].read_text(encoding="utf-8"))
    campaign["inputs"]["data_run_identity"] = data_manifest["data_pack_identity"]
    campaign["campaign_fingerprint"] = strict.campaign_fingerprint(
        **campaign["inputs"],
        artifact_inventory=campaign["artifacts"],
        plan_content=campaign["plan_content"],
    )
    paths["campaign"].write_text(json.dumps(campaign), encoding="utf-8")
    called = False

    def run(**kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    with pytest.raises(ValueError, match="locked_start"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )
    assert called is False


def test_worker_rejects_non_strict_date_bounds_before_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import gtbi_fast_strict as strict
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    data_manifest = json.loads(paths["data_manifest"].read_text(encoding="utf-8"))
    data_manifest["validation_end"] = "2021-01-01"
    data_manifest["data_pack_identity"] = _data_pack_identity(data_manifest)
    paths["data_manifest"].write_text(json.dumps(data_manifest), encoding="utf-8")
    campaign = json.loads(paths["campaign"].read_text(encoding="utf-8"))
    campaign["inputs"]["validation_end"] = "2021-01-01"
    campaign["inputs"]["data_run_identity"] = data_manifest["data_pack_identity"]
    campaign["campaign_fingerprint"] = strict.campaign_fingerprint(
        **campaign["inputs"],
        artifact_inventory=campaign["artifacts"],
        plan_content=campaign["plan_content"],
    )
    paths["campaign"].write_text(json.dumps(campaign), encoding="utf-8")
    called = False

    def run(**kwargs: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    with pytest.raises(ValueError, match="validation_end"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )
    assert called is False


def test_worker_discards_partial_output_when_strict_count_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)

    def run(**kwargs: object) -> dict[str, object]:
        output_dir = Path(str(kwargs["output_dir"]))
        (output_dir / "partial.json").write_text("partial", encoding="utf-8")
        return {
            "total_strategies_evaluated": 1,
            "total_strategies_early_rejected": 0,
            "total_strategies_timed_out": 1,
            "total_strategies_runtime_error": 0,
            "total_strategies_unsupported": 0,
            "total_strategies_slow_deferred": 0,
        }

    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", run)
    with pytest.raises(ValueError, match="nonzero failure counts"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )
    assert not paths["output"].exists()


def test_worker_rejects_summary_without_all_terminal_and_failure_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    paths = _worker_fixture(tmp_path)
    monkeypatch.setattr(worker.gtbi, "run_external_strategy_pack_shard", lambda **kwargs: {"total_strategies_evaluated": 1})
    with pytest.raises(ValueError, match="missing strict count"):
        worker.run_worker(
            campaign_manifest_path=paths["campaign"],
            data_manifest_path=paths["data_manifest"],
            plan_root=paths["plan"],
            data_pack_root=paths["data"],
            worker_id=0,
            output_dir=paths["output"],
        )


def test_worker_cli_rejects_local_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT", raising=False)
    with pytest.raises(SystemExit, match="GitHub-only"):
        worker.main(
            [
                "run",
                "--campaign-manifest", "campaign.json",
                "--data-manifest", "data.json",
                "--plan-root", "plan",
                "--data-pack-root", "data",
                "--worker-id", "0",
                "--output-dir", "output",
            ]
        )


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


def test_data_manifest_seals_date_bounds_once(tmp_path: Path) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    data = tmp_path / "data"
    data.mkdir()
    (data / "prices.csv").write_text(
        "date,close\n2020-12-30,99\n2020-12-31,100\n",
        encoding="utf-8",
    )

    manifest = worker.create_data_pack_manifest(
        data_pack_root=data,
        output_path=tmp_path / "manifest.json",
        source_data_run_id="run",
        source_artifact_name="artifact",
        universe_identity="universe",
        train_end="2010-12-31",
        validation_start="2011-01-01",
        validation_end="2020-12-31",
        locked_start="2021-01-01",
    )

    assert manifest["date_bounds"] == [
        {
            "column": "date",
            "max": "2020-12-31T00:00:00+00:00",
            "min": "2020-12-30T00:00:00+00:00",
            "non_null_rows": 2,
            "path": "prices.csv",
        }
    ]


def test_data_manifest_rejects_locked_rows_during_single_seal(tmp_path: Path) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    data = tmp_path / "data"
    data.mkdir()
    (data / "prices.csv").write_text("date,close\n2021-01-01,100\n", encoding="utf-8")

    with pytest.raises(ValueError, match="locked_start"):
        worker.create_data_pack_manifest(
            data_pack_root=data,
            output_path=tmp_path / "manifest.json",
            source_data_run_id="run",
            source_artifact_name="artifact",
            universe_identity="universe",
            train_end="2010-12-31",
            validation_start="2011-01-01",
            validation_end="2020-12-31",
            locked_start="2021-01-01",
        )


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
