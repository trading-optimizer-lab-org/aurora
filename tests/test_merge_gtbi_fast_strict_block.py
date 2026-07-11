from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


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
                "campaign_fingerprint": fingerprint,
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
        json.dumps({"campaign_fingerprint": fingerprint}),
        encoding="utf-8",
    )


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
    assert manifest["campaign_fingerprint"] == "fp"
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
