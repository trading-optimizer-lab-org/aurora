from __future__ import annotations

import hashlib
import io
import json
import tarfile
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from infra.gtbi_v7_new_reference import campaign, release, runner
from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.frozen_data_lake import MANIFEST_DOMAIN, MANIFEST_MEMBER, RECEIPT_DOMAIN
from scripts import gtbi_fast_strict as strict
from scripts.summarize_gtbi_v7_new_reference_benchmark import summarize
from scripts.validate_gtbi_v7_new_reference_smoke import validate_smoke


BENCHMARK_RELATIVE_PATH = "benchmarks/SPY.parquet"


def _canonical(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _scientific_output(root: Path, worker_id: int, *, profit_factor: float = 1.5, seconds: float = 1.0) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for kind in sorted(runner.REQUIRED_SCIENTIFIC_KINDS):
        suffix = f"{kind}_shard_{worker_id:03d}"
        if kind == "top_indicator_rules":
            (root / f"{suffix}.jsonl").write_text("", encoding="utf-8")
        elif kind == "leaderboard":
            pd.DataFrame(
                [
                    {
                        "candidate_id": f"c{worker_id}",
                        "validation_profit_factor": profit_factor,
                        "seconds_total": seconds,
                    }
                ]
            ).to_csv(root / f"{suffix}.csv", index=False)
        elif kind == "yearly_trade_performance":
            pd.DataFrame(
                [{"candidate_id": f"c{worker_id}", "split": "validation", "year": 2020}]
            ).to_csv(root / f"{suffix}.csv", index=False)
        else:
            pd.DataFrame(columns=["candidate_id"]).to_csv(root / f"{suffix}.csv", index=False)


def _release_verification(root: Path) -> None:
    payload = {
        "verified": True,
        "verification_digest": "sha256:test-release",
        "manifest_digest": "sha256:test-manifest",
    }
    _canonical(root / "release_verification.json", payload)


def _receipt(path: Path, value: dict) -> dict:
    payload = dict(value)
    payload["receipt_digest"] = campaign._receipt_digest(payload)
    _canonical(path, payload)
    return payload


def test_release_stream_is_verified_once_and_extracts_only_required_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "release"
    root.mkdir()
    file_bytes = {path: f"bytes:{path}".encode() for path in release.REQUIRED_SOURCE_PATHS}
    file_bytes["unused/raw.parquet"] = b"unused"
    rows = [
        {
            "path": path,
            "size_bytes": len(value),
            "sha256": "sha256:" + hashlib.sha256(value).hexdigest(),
        }
        for path, value in sorted(file_bytes.items())
    ]
    manifest = {
        "schema_version": "gtbi_v7_frozen_data_lake_manifest_v1",
        "source_file_count": len(rows),
        "locked_start": "2021-01-01",
        "scientific_cutoff": "2020-12-31",
        "files": rows,
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        MANIFEST_DOMAIN, manifest, omit_top_level_fields=("manifest_digest",)
    )
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path, value in sorted(file_bytes.items()):
            info = tarfile.TarInfo(path)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
        encoded = canonical_bytes(manifest) + b"\n"
        info = tarfile.TarInfo(MANIFEST_MEMBER)
        info.size = len(encoded)
        archive.addfile(info, io.BytesIO(encoded))
    archive_bytes = stream.getvalue()
    midpoint = len(archive_bytes) // 2
    part_values = (archive_bytes[:midpoint], archive_bytes[midpoint:])
    parts = []
    for index, value in enumerate(part_values, start=1):
        name = f"test.tar.part-{index:04d}"
        (root / name).write_bytes(value)
        parts.append(
            {
                "index": index,
                "name": name,
                "size_bytes": len(value),
                "sha256": "sha256:" + hashlib.sha256(value).hexdigest(),
            }
        )
    archive_digest = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()
    monkeypatch.setattr(release, "ARCHIVE_SHA256", archive_digest)
    monkeypatch.setattr(release, "ARCHIVE_SIZE_BYTES", len(archive_bytes))
    receipt = {
        "release_tag": release.RELEASE_TAG,
        "archive_sha256": archive_digest,
        "archive_size_bytes": len(archive_bytes),
        "part_count": len(parts),
        "parts": parts,
        "manifest_digest": manifest["manifest_digest"],
        "locked_start": "2021-01-01",
        "scientific_cutoff": "2020-12-31",
        "provider_download_performed": False,
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        RECEIPT_DOMAIN, receipt, omit_top_level_fields=("receipt_digest",)
    )
    _canonical(root / release.MANIFEST_FILENAME, manifest)
    _canonical(root / release.RECEIPT_FILENAME, receipt)

    output = tmp_path / "selected"
    result = release.verify_and_extract_required_release_files(release_root=root, output_dir=output)
    assert result["verified"] is True
    for path, value in file_bytes.items():
        if path in release.REQUIRED_SOURCE_PATHS:
            assert (output / path).read_bytes() == value
        else:
            assert not (output / path).exists()


def test_historical_pack_physically_excludes_locked_rows(tmp_path: Path) -> None:
    from scripts import run_gtbi_fast_strict_worker as worker

    source = tmp_path / "source"
    _release_verification(source)
    prices = pd.DataFrame(
        {
            "date": list(pd.date_range("2019-01-01", periods=300, freq="D").date)
            + list(pd.date_range("2021-01-01", periods=10, freq="D").date),
            "symbol": ["AAA"] * 310,
            "open": [10.0] * 310,
            "high": [11.0] * 310,
            "low": [9.0] * 310,
            "close": [10.5] * 310,
            "adj_close": [10.5] * 310,
            "volume": [1000.0] * 310,
            "dividends": [0.0] * 310,
            "stock_splits": [0.0] * 310,
            "source": ["test"] * 310,
            "retrieved_at": ["2026-01-01"] * 310,
        }
    )
    benchmark = prices.drop(columns="symbol").copy()
    metadata = pd.DataFrame({"symbol": ["AAA"], "market_cap": [3_000_000_000]})
    universe = pd.DataFrame({"symbol": ["AAA"]})
    for relative, frame in (
        ("exports/all_prices.parquet", prices),
        (BENCHMARK_RELATIVE_PATH, benchmark),
        ("metadata/company_metadata.parquet", metadata),
        ("universe/us_stock_like_universe.parquet", universe),
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)

    output = tmp_path / "historical"
    result = release.build_historical_execution_pack(extracted_root=source, output_root=output)

    stored = pd.read_parquet(output / "data-pack/prices.parquet")
    assert stored["date"].max().isoformat() <= "2020-12-31"
    assert len(stored) == 300
    manifest = json.loads((output / "data_manifest.json").read_text(encoding="utf-8"))
    assert manifest["locked_start"] == "2021-01-01"
    assert manifest["v7_data_contract"]["locked_rows_in_execution_pack"] is False
    assert manifest["v7_data_contract"]["retained_symbol_count"] == 1
    assert result["data_pack_identity"] == manifest["data_pack_identity"]
    assert worker._verify_data_manifest(manifest, output / "data-pack") == result[
        "data_pack_identity"
    ]


def test_historical_pack_rejects_symbol_below_market_cap(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _release_verification(source)
    dates = list(pd.date_range("2019-01-01", periods=300, freq="D").date)
    prices = pd.DataFrame(
        {
            "date": dates,
            "symbol": ["AAA"] * 300,
            "open": [10.0] * 300,
            "high": [11.0] * 300,
            "low": [9.0] * 300,
            "close": [10.5] * 300,
            "volume": [1000.0] * 300,
        }
    )
    benchmark = prices.drop(columns="symbol")
    files = {
        "exports/all_prices.parquet": prices,
        BENCHMARK_RELATIVE_PATH: benchmark,
        "metadata/company_metadata.parquet": pd.DataFrame({"symbol": ["AAA"], "market_cap": [1_000]}),
        "universe/us_stock_like_universe.parquet": pd.DataFrame({"symbol": ["AAA"]}),
    }
    for relative, frame in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    with pytest.raises(release.FrozenReleaseError, match="historical price view is empty"):
        release.build_historical_execution_pack(extracted_root=source, output_root=tmp_path / "out")


def test_v7_contract_digest_rejects_locked_authorization(tmp_path: Path) -> None:
    authorization = {
        "campaign_id": campaign.CAMPAIGN_ID,
        "separate_from_v6": True,
        "scientific_boundaries": {
            "train_end": campaign.TRAIN_END,
            "validation_start": campaign.VALIDATION_START,
            "validation_end": campaign.VALIDATION_END,
            "historical_exclusion_start": campaign.HISTORICAL_EXCLUSION_START,
            "locked_authorized": True,
            "locked_data_accessed": False,
            "provider_download_performed": False,
        },
        "execution_policy": {
            "github_actions_only": True,
            "local_scientific_runs_allowed": False,
            "maximum_incremental_net_spend_usd": 0,
        },
    }
    path = tmp_path / "authorization.json"
    _canonical(path, authorization)
    with pytest.raises(campaign.V7CampaignError, match="locked_authorized"):
        campaign._validated_authorization(path)


def test_scientific_equivalence_ignores_runtime_only_columns(tmp_path: Path) -> None:
    outputs = []
    for index, seconds in enumerate((1.0, 9.0)):
        output = tmp_path / f"mode-{index}"
        _scientific_output(output, 0, profit_factor=1.5, seconds=seconds)
        outputs.append(output)
    digest = runner.assert_scientific_outputs_equal(outputs)
    assert digest.startswith("sha256:")


def test_scientific_equivalence_detects_metric_change(tmp_path: Path) -> None:
    outputs = []
    for index, value in enumerate((1.5, 1.6)):
        output = tmp_path / f"mode-{index}"
        _scientific_output(output, 0, profit_factor=value)
        outputs.append(output)
    with pytest.raises(runner.V7RunnerError, match="scientific outputs differ"):
        runner.assert_scientific_outputs_equal(outputs)


def test_scientific_digest_rejects_incomplete_output(tmp_path: Path) -> None:
    pd.DataFrame([{"candidate_id": "x"}]).to_csv(tmp_path / "leaderboard_shard_000.csv", index=False)
    with pytest.raises(runner.V7RunnerError, match="scientific output is incomplete"):
        runner.scientific_output_digest(tmp_path)


def test_effective_cpu_count_is_positive() -> None:
    assert runner.effective_cpu_count() >= 1


def test_v7_manifest_rewrite_preserves_strict_float_fingerprint(tmp_path: Path) -> None:
    inputs: dict[str, str | float] = {
        "code_sha": "abc",
        "strategy_pack_digest": "pack",
        "data_run_identity": "data",
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "min_market_cap": 2_000_000_000.0,
        "execution_mode": "optimized_evaluation_v5_event_first",
        "universe_identity": "universe",
        "dependency_lock_identity": "lock",
    }
    plan_content: dict[str, Any] = {"assignments": {}, "bundle_assignments": {}, "counts": {}}
    fingerprint = strict.campaign_fingerprint(
        code_sha=str(inputs["code_sha"]),
        strategy_pack_digest=str(inputs["strategy_pack_digest"]),
        data_run_identity=str(inputs["data_run_identity"]),
        train_end=str(inputs["train_end"]),
        validation_start=str(inputs["validation_start"]),
        validation_end=str(inputs["validation_end"]),
        locked_start=str(inputs["locked_start"]),
        min_market_cap=float(inputs["min_market_cap"]),
        execution_mode=str(inputs["execution_mode"]),
        universe_identity=str(inputs["universe_identity"]),
        dependency_lock_identity=str(inputs["dependency_lock_identity"]),
        artifact_inventory=[],
        plan_content=plan_content,
    )
    manifest = {
        "campaign_fingerprint": fingerprint,
        "inputs": inputs,
        "plan_content": plan_content,
        "artifacts": [],
        "v7_campaign_contract": {"campaign_fingerprint": fingerprint},
    }
    campaign._write_strict_campaign_manifest(tmp_path / "campaign_manifest.json", manifest)
    strict.verify_campaign_artifacts(tmp_path)
    reloaded = json.loads((tmp_path / "campaign_manifest.json").read_text(encoding="utf-8"))
    assert isinstance(reloaded["inputs"]["min_market_cap"], float)


def test_batch_reuses_one_runner_and_covers_every_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(runner, "effective_cpu_count", lambda: 4)

    def fake_run(kwargs: dict) -> dict:
        output = Path(kwargs["output_dir"])
        _scientific_output(output, kwargs["worker_id"])
        receipt = {
            "campaign_fingerprint": "fp",
            "worker_id": kwargs["worker_id"],
            "cpu_seconds": 1.0,
            "peak_rss_kib": 10,
            "scientific_output_digest": runner.scientific_output_digest(output),
        }
        return {"v7_worker_receipt": receipt}

    executor_sizes: list[int] = []

    class InlineExecutor:
        def __init__(self, *, max_workers: int, mp_context: Any) -> None:
            del mp_context
            executor_sizes.append(max_workers)

        def __enter__(self) -> InlineExecutor:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def submit(self, function: Any, argument: dict) -> Future:
            future: Future = Future()
            future.set_result(function(argument))
            return future

    monkeypatch.setattr(runner, "_run_v7_worker_process", fake_run)
    monkeypatch.setattr(runner, "ProcessPoolExecutor", InlineExecutor)
    monkeypatch.setattr(runner, "as_completed", lambda futures: list(futures))
    output = tmp_path / "batch"
    result = runner.run_v7_batch(
        campaign_manifest_path=tmp_path / "campaign.json",
        data_manifest_path=tmp_path / "data.json",
        plan_root=tmp_path,
        data_pack_root=tmp_path,
        authorization_path=tmp_path / "authorization.json",
        worker_ids=[4, 5, 6, 7],
        output_root=output,
        processes_per_runner=1,
    )
    assert result["worker_ids"] == [4, 5, 6, 7]
    assert result["symbol_workers_per_process"] == 1
    assert executor_sizes == [1]
    assert {path.name for path in output.glob("worker-*")} == {
        "worker-004",
        "worker-005",
        "worker-006",
        "worker-007",
    }


def test_batch_equivalence_compares_each_logical_worker(tmp_path: Path) -> None:
    roots = []
    for mode in (1, 4):
        root = tmp_path / f"mode-{mode}"
        roots.append(root)
        for worker_id in (0, 1):
            output = root / f"worker-{worker_id:03d}"
            _scientific_output(output, worker_id)
    result = runner.assert_batch_outputs_equal(roots)
    assert result["equivalent"] is True
    assert set(result["worker_scientific_digests"]) == {"worker-000", "worker-001"}


def test_benchmark_selects_fastest_only_after_equivalence(tmp_path: Path) -> None:
    roots = {}
    for mode, seconds in ((1, 30.0), (2, 18.0), (4, 12.0)):
        root = tmp_path / f"mode-{mode}"
        roots[mode] = root
        for worker_id in (0, 1):
            output = root / f"worker-{worker_id:03d}"
            _scientific_output(output, worker_id)
        _canonical(
            root / "v7_batch_receipt.json",
            {
                "campaign_fingerprint": "fp",
                "worker_ids": [0, 1],
                "processes_per_runner": mode,
                "symbol_workers_per_process": 1,
                "effective_cpu_count": 4,
                "wall_seconds": seconds,
                "locked_data_accessed": False,
            },
        )
    result = summarize(roots, tmp_path / "benchmark.json")
    assert result["selected_processes_per_runner"] == 4
    assert result["selected_symbol_workers_per_process"] == 1
    assert result["effective_cpu_count"] == 4
    assert result["equal_workload_runtime_reduction_pct"] == pytest.approx(60.0)


def test_prior_evidence_is_bound_to_exact_campaign(tmp_path: Path) -> None:
    campaign_path = tmp_path / "campaign.json"
    _canonical(campaign_path, {"campaign_fingerprint": "fp"})
    benchmark_path = tmp_path / "benchmark.json"
    benchmark = _receipt(
        benchmark_path,
        {
            "campaign_id": campaign.CAMPAIGN_ID,
            "campaign_fingerprint": "fp",
            "equivalent": True,
            "worker_ids": [0, 1, 2, 3],
            "selected_processes_per_runner": 4,
            "selected_symbol_workers_per_process": 1,
            "effective_cpu_count": 4,
            "locked_authorized": False,
            "locked_data_accessed": False,
            "github_only_run": True,
            "queue_time_included": False,
        },
    )
    smoke_path = tmp_path / "smoke.json"
    _receipt(
        smoke_path,
        {
            "campaign_id": campaign.CAMPAIGN_ID,
            "campaign_fingerprint": "fp",
            "valid": True,
            "worker_count": 100,
            "worker_ids": list(range(100)),
            "strategies_timed_out": 0,
            "strategies_runtime_error": 0,
            "strategies_unsupported": 0,
            "strategies_slow_deferred": 0,
            "historical_exclusion_start": campaign.HISTORICAL_EXCLUSION_START,
            "locked_authorized": False,
            "locked_data_accessed": False,
            "github_only_run": True,
        },
    )
    assert campaign.validate_benchmark_evidence(
        campaign_manifest_path=campaign_path, benchmark_path=benchmark_path
    )["receipt_digest"] == benchmark["receipt_digest"]
    assert campaign.validate_smoke_evidence(
        campaign_manifest_path=campaign_path, smoke_validation_path=smoke_path
    )["worker_count"] == 100


def test_prior_evidence_rejects_other_campaign(tmp_path: Path) -> None:
    campaign_path = tmp_path / "campaign.json"
    _canonical(campaign_path, {"campaign_fingerprint": "expected"})
    benchmark_path = tmp_path / "benchmark.json"
    _receipt(
        benchmark_path,
        {
            "campaign_id": campaign.CAMPAIGN_ID,
            "campaign_fingerprint": "other",
            "equivalent": True,
            "worker_ids": [0, 1, 2, 3],
            "selected_processes_per_runner": 4,
            "selected_symbol_workers_per_process": 1,
            "effective_cpu_count": 4,
            "locked_authorized": False,
            "locked_data_accessed": False,
            "github_only_run": True,
            "queue_time_included": False,
        },
    )
    with pytest.raises(campaign.V7CampaignError, match="campaign_fingerprint"):
        campaign.validate_benchmark_evidence(
            campaign_manifest_path=campaign_path, benchmark_path=benchmark_path
        )


def test_smoke_validator_reconciles_real_output_rows(tmp_path: Path) -> None:
    root = tmp_path / "smoke"
    for worker_id in (0, 1):
        output = root / f"artifact-{worker_id}" / f"worker-{worker_id:03d}"
        _scientific_output(output, worker_id)
        _canonical(
            output / "worker_summary.json",
            {
                "canonical_group_count": 1,
                "total_strategies_evaluated": 1,
                "total_strategies_early_rejected": 0,
                "total_strategies_timed_out": 0,
                "total_strategies_runtime_error": 0,
                "total_strategies_unsupported": 0,
                "total_strategies_slow_deferred": 0,
            },
        )
        _canonical(
            output / "v7_worker_receipt.json",
            {
                "worker_id": worker_id,
                "campaign_fingerprint": "fp",
                "locked_authorized": False,
                "locked_data_accessed": False,
                "scientific_output_digest": runner.scientific_output_digest(output),
            },
        )
    result = validate_smoke(root, tmp_path / "smoke.json", expected_workers=2)
    assert result["valid"] is True
    assert result["canonical_terminal_count"] == 2


def test_worker_requires_github_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(runner.V7RunnerError, match="GitHub Actions only"):
        runner.run_v7_worker(
            campaign_manifest_path=tmp_path / "campaign.json",
            data_manifest_path=tmp_path / "data.json",
            plan_root=tmp_path,
            data_pack_root=tmp_path,
            authorization_path=tmp_path / "auth.json",
            worker_id=0,
            output_dir=tmp_path / "out",
            symbol_workers=1,
        )


def test_campaign_source_contains_no_locked_escape() -> None:
    workflow_root = Path(".github/workflows")
    sources = [
        Path("infra/gtbi_v7_new_reference/campaign.py"),
        Path("infra/gtbi_v7_new_reference/release.py"),
        Path("infra/gtbi_v7_new_reference/runner.py"),
        Path("scripts/prepare_gtbi_v7_new_reference_data.py"),
        Path("scripts/run_gtbi_v7_new_reference_worker.py"),
    ]
    sources.extend(workflow_root.glob("*gtbi-v7-new-reference*.yml"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources if path.exists())
    assert "self-hosted" not in combined
    assert "C:\\" not in combined
    assert "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT" not in combined
