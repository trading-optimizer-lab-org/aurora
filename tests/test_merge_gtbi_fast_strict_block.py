from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pandas as pd
import pytest


def _campaign(label: str) -> dict[str, object]:
    from scripts.gtbi_fast_strict import campaign_fingerprint

    inputs = {
        "code_sha": f"sha-{label}",
        "strategy_pack_digest": "strategy-pack",
        "data_run_identity": "data-run",
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "min_market_cap": 2_000_000_000,
        "execution_mode": "optimized_evaluation_v5_event_first",
        "universe_identity": "universe",
        "dependency_lock_identity": "lock",
    }
    return {
        "campaign_fingerprint": campaign_fingerprint(**inputs),
        "inputs": inputs,
    }


def _file_record(path: Path, root: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _write_worker_manifest(worker: Path, worker_id: int, fingerprint: str, canonical_ids: list[str]) -> None:
    records = [
        _file_record(path, worker)
        for path in sorted(worker.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.name != "worker_manifest.json"
    ]
    (worker / "worker_manifest.json").write_text(
        json.dumps(
            {
                "campaign_fingerprint": fingerprint,
                "worker_id": worker_id,
                "canonical_ids": canonical_ids,
                "files": records,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _worker(
    root: Path,
    worker_id: int,
    *,
    fingerprint: str = "fp",
    candidate_id: str | None = None,
    failure: bool = False,
) -> None:
    worker = root / f"gtbi-v6-block-00-worker-{worker_id:03d}"
    worker.mkdir(parents=True)
    candidate = candidate_id or f"candidate-{worker_id}"
    campaign = _campaign(fingerprint)
    campaign_fingerprint = str(campaign["campaign_fingerprint"])
    pd.DataFrame(
        [{"candidate_id": candidate, "score": float(worker_id)}]
    ).to_csv(worker / f"leaderboard_job_{worker_id:03d}.csv", index=False)
    pd.DataFrame(columns=["strategy_id", "reason"]).to_csv(
        worker / f"early_rejected_strategies_job_{worker_id:03d}.csv",
        index=False,
    )
    timeout = (
        pd.DataFrame([{"strategy_id": candidate, "reason": "timeout"}])
        if failure
        else pd.DataFrame(columns=["strategy_id", "reason"])
    )
    timeout.to_csv(worker / f"timeout_strategies_job_{worker_id:03d}.csv", index=False)
    (worker / "worker_summary.json").write_text(
        json.dumps(
            {
                "campaign_fingerprint": campaign_fingerprint,
                "worker_id": worker_id,
                "canonical_group_count": 1,
                "total_strategies_evaluated": 1,
                "total_strategies_early_rejected": 0,
                "total_strategies_timed_out": int(failure),
                "total_strategies_runtime_error": 0,
                "total_strategies_unsupported": 0,
                "total_strategies_slow_deferred": 0,
            }
        ),
        encoding="utf-8",
    )
    (worker / "campaign_manifest.json").write_text(
        json.dumps(campaign),
        encoding="utf-8",
    )
    _write_worker_manifest(worker, worker_id, campaign_fingerprint, [candidate])


def test_block_merge_accepts_parquet_input_with_verified_worker_manifest(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    _worker(inputs, 1)
    for worker_id in (0, 1):
        worker = inputs / f"gtbi-v6-block-00-worker-{worker_id:03d}"
        csv_path = worker / f"leaderboard_job_{worker_id:03d}.csv"
        frame = pd.read_csv(csv_path)
        csv_path.unlink()
        frame.to_parquet(worker / f"leaderboard_job_{worker_id:03d}.parquet", index=False)
        _write_worker_manifest(
            worker,
            worker_id,
            str(_campaign("fp")["campaign_fingerprint"]),
            [f"candidate-{worker_id}"],
        )

    block.merge_block(
        input_root=inputs,
        output_dir=tmp_path / "output",
        block_id=0,
        expected_worker_ids=[0, 1],
    )

    merged = pd.read_csv(tmp_path / "output" / "leaderboard_job_block_00.csv")
    assert merged["candidate_id"].tolist() == ["candidate-0", "candidate-1"]


def test_block_merge_preserves_rows_and_writes_manifest(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    _worker(inputs, 1)
    output = tmp_path / "output"

    summary = block.merge_block(
        input_root=inputs,
        output_dir=output,
        block_id=0,
        expected_worker_ids=[0, 1],
    )

    leaderboard = pd.read_csv(output / "leaderboard_job_block_00.csv")
    manifest = json.loads((output / "block_manifest.json").read_text(encoding="utf-8"))
    assert leaderboard["candidate_id"].tolist() == ["candidate-0", "candidate-1"]
    assert summary["total_strategies_evaluated"] == 2
    assert summary["total_jobs_completed"] == 2
    assert manifest["worker_ids"] == [0, 1]
    assert manifest["campaign_fingerprint"] == _campaign("fp")["campaign_fingerprint"]
    assert manifest["files"]


def test_block_merge_is_byte_deterministic(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 1)
    _worker(inputs, 0)
    first = tmp_path / "first"
    second = tmp_path / "second"
    block.merge_block(input_root=inputs, output_dir=first, block_id=0, expected_worker_ids=[0, 1])
    block.merge_block(input_root=inputs, output_dir=second, block_id=0, expected_worker_ids=[0, 1])
    assert (first / "leaderboard_job_block_00.csv").read_bytes() == (
        second / "leaderboard_job_block_00.csv"
    ).read_bytes()


def test_block_merge_preserves_json_artifacts(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    _worker(inputs, 1)
    for worker_id in (0, 1):
        worker = inputs / f"gtbi-v6-block-00-worker-{worker_id:03d}"
        (worker / f"diagnostics_job_{worker_id:03d}.json").write_text(
            json.dumps({"worker_id": worker_id, "labels": ["one", "two"]}),
            encoding="utf-8",
        )
        (worker / f"events_job_{worker_id:03d}.jsonl").write_text(
            json.dumps({"worker_id": worker_id, "event": "completed"}) + "\n",
            encoding="utf-8",
        )
        _write_worker_manifest(
            worker,
            worker_id,
            str(_campaign("fp")["campaign_fingerprint"]),
            [f"candidate-{worker_id}"],
        )

    block.merge_block(
        input_root=inputs,
        output_dir=tmp_path / "output",
        block_id=0,
        expected_worker_ids=[0, 1],
    )

    assert json.loads((tmp_path / "output" / "diagnostics_job_block_00.json").read_text()) == [
        {"labels": ["one", "two"], "worker_id": 0},
        {"labels": ["one", "two"], "worker_id": 1},
    ]
    assert [
        json.loads(line)
        for line in (tmp_path / "output" / "events_job_block_00.jsonl").read_text().splitlines()
    ] == [
        {"event": "completed", "worker_id": 0},
        {"event": "completed", "worker_id": 1},
    ]


def test_block_merge_recomputes_campaign_fingerprint(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    campaign_path = inputs / "gtbi-v6-block-00-worker-000" / "campaign_manifest.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    campaign["campaign_fingerprint"] = "tampered"
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match inputs"):
        block.merge_block(
            input_root=inputs,
            output_dir=tmp_path / "output",
            block_id=0,
            expected_worker_ids=[0],
        )


def test_block_merge_accepts_planner_campaign_fingerprint_with_artifacts_and_plan_content(
    tmp_path: Path,
) -> None:
    from scripts import merge_gtbi_fast_strict_block as block
    from scripts.gtbi_fast_strict import campaign_fingerprint

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    worker = inputs / "gtbi-v6-block-00-worker-000"
    campaign_path = worker / "campaign_manifest.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    campaign["artifacts"] = [
        {
            "path": "canonical_pack/strategies_shard_000.jsonl",
            "sha256": "a" * 64,
            "size_bytes": 42,
        }
    ]
    campaign["plan_content"] = {
        "assignments": {"economic-hash": 0},
        "bundle_assignments": {"signal-hash": 0},
        "counts": {"worker_count": 1, "unique_signal_bundles": 1},
    }
    campaign["campaign_fingerprint"] = campaign_fingerprint(
        **campaign["inputs"],
        artifact_inventory=campaign["artifacts"],
        plan_content=campaign["plan_content"],
    )
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
    summary_path = worker / "worker_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["campaign_fingerprint"] = campaign["campaign_fingerprint"]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    _write_worker_manifest(worker, 0, str(campaign["campaign_fingerprint"]), ["candidate-0"])

    result = block.merge_block(
        input_root=inputs,
        output_dir=tmp_path / "output",
        block_id=0,
        expected_worker_ids=[0],
    )

    assert result["campaign_fingerprint"] == campaign["campaign_fingerprint"]


def test_block_merge_rejects_tampered_worker_file_digest_atomically(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    worker = inputs / "gtbi-v6-block-00-worker-000"
    (worker / "leaderboard_job_000.csv").write_text("candidate_id,score\ntampered,0\n", encoding="utf-8")
    output = tmp_path / "output"

    with pytest.raises(ValueError, match="digest mismatch"):
        block.merge_block(
            input_root=inputs,
            output_dir=output,
            block_id=0,
            expected_worker_ids=[0],
        )

    assert not output.exists()


def test_block_merge_publishes_nothing_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    output = tmp_path / "output"

    def fail_replace(_: Path, __: Path) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr(block.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated publish failure"):
        block.merge_block(
            input_root=inputs,
            output_dir=output,
            block_id=0,
            expected_worker_ids=[0],
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".output.merge-*"))


def test_block_merge_uses_parquet_intermediate_for_large_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    written: list[Path] = []
    original_to_parquet = pd.DataFrame.to_parquet

    def record_parquet(self: pd.DataFrame, path: Path, *args: object, **kwargs: object) -> None:
        written.append(Path(path))
        original_to_parquet(self, path, *args, **kwargs)

    monkeypatch.setattr(block, "PARQUET_INTERMEDIATE_ROWS", 1, raising=False)
    monkeypatch.setattr(pd.DataFrame, "to_parquet", record_parquet)
    block.merge_block(
        input_root=inputs,
        output_dir=tmp_path / "output",
        block_id=0,
        expected_worker_ids=[0],
    )

    assert written
    assert not list((tmp_path / "output").glob(".intermediate/*"))


def test_block_merge_rejects_missing_worker(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0)
    with pytest.raises(ValueError, match="worker membership mismatch"):
        block.merge_block(
            input_root=inputs,
            output_dir=tmp_path / "output",
            block_id=0,
            expected_worker_ids=[0, 1],
        )


def test_block_merge_rejects_campaign_mismatch(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0, fingerprint="one")
    _worker(inputs, 1, fingerprint="two")
    with pytest.raises(ValueError, match="campaign fingerprint"):
        block.merge_block(
            input_root=inputs,
            output_dir=tmp_path / "output",
            block_id=0,
            expected_worker_ids=[0, 1],
        )


def test_block_merge_rejects_duplicate_canonical_id(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0, candidate_id="duplicate")
    _worker(inputs, 1, candidate_id="duplicate")
    with pytest.raises(ValueError, match="duplicate canonical"):
        block.merge_block(
            input_root=inputs,
            output_dir=tmp_path / "output",
            block_id=0,
            expected_worker_ids=[0, 1],
        )


def test_block_merge_rejects_failure_rows(tmp_path: Path) -> None:
    from scripts import merge_gtbi_fast_strict_block as block

    inputs = tmp_path / "inputs"
    _worker(inputs, 0, failure=True)
    with pytest.raises(ValueError, match="failure"):
        block.merge_block(
            input_root=inputs,
            output_dir=tmp_path / "output",
            block_id=0,
            expected_worker_ids=[0],
        )
