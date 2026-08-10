from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aurora.infra.github_performance.preflight import load_github_yaml


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / ".github/workflows/sp500-dehb-mega-controller-v1.yml"
SHARD = ROOT / ".github/workflows/_sp500-dehb-mega-shard-v1.yml"
WORKER = ROOT / ".github/workflows/_sp500-dehb-mega-worker-v1.yml"


def _load(path: Path) -> dict[str, Any]:
    return dict(load_github_yaml(path))


def test_three_shards_request_360_jobs_and_skip_inside_called_worker() -> None:
    controller = _load(CONTROLLER)
    shard = _load(SHARD)
    worker = _load(WORKER)

    jobs = controller["jobs"]
    for shard_id in "abc":
        job = jobs[f"shard_{shard_id}"]
        assert job["needs"] == "plan"
        assert job["uses"] == "./.github/workflows/_sp500-dehb-mega-shard-v1.yml"
    shard_job = shard["jobs"]["worker"]
    assert shard_job["strategy"]["max-parallel"] == 120
    assert shard_job["strategy"]["fail-fast"] is False
    assert "if" not in shard_job
    assert shard_job["uses"] == "./.github/workflows/_sp500-dehb-mega-worker-v1.yml"
    worker_job = worker["jobs"]["worker"]
    assert worker_job["if"] == "${{ !startsWith(inputs.job_id, 'SKIP-') }}"
    assert worker_job["timeout-minutes"] == 330
    assert worker_job["continue-on-error"] is True
    assert all(worker_job["env"][name] == "1" for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ))


def test_controller_is_indefinite_train_only_and_retries_exact_jobs() -> None:
    workflow = _load(CONTROLLER)
    text = CONTROLLER.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"actions": "write", "contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["jobs"]["reduce"]["timeout-minutes"] == 360
    assert "retry_jobs" in text
    assert "dispatch_next_wave" in text
    assert "gh workflow run sp500-dehb-mega-controller-v1.yml" in text
    assert "validation_2011_2020" not in text
    assert "2021" not in text
    assert "timeout-hours" not in text


def test_initial_matrix_outputs_fit_below_github_job_output_limit() -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_shard_matrices

    campaign = load_and_validate_campaign_contract(
        ROOT / "config/sp500_megarun_dehb_campaign_v1.json"
    )
    matrices = build_shard_matrices(campaign)
    encoded = [
        json.dumps(matrices[shard], ensure_ascii=True, separators=(",", ":"))
        for shard in "ABC"
    ]
    estimated_utf16_bytes = sum(len(value) * 2 for value in encoded)

    assert [len(matrices[shard]["include"]) for shard in "ABC"] == [120, 120, 120]
    assert estimated_utf16_bytes < 1_000_000
