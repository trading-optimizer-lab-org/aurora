from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aurora.infra.github_performance.preflight import load_github_yaml


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / ".github/workflows/sp500-dehb-mega-controller-v1.yml"
WORKER_ACTION = ROOT / ".github/actions/sp500-dehb-mega-worker/action.yml"
CONFLICT_DIAGNOSTIC = ROOT / ".github/workflows/sp500-dehb-cache-conflict-diagnostic.yml"
CROSS_RUNNER = ROOT / ".github/workflows/sp500-dehb-cross-runner-determinism.yml"
CONTINUOUS_SMOKE = ROOT / ".github/workflows/sp500-dehb-continuous-smoke-v2.yml"
REGISTERED_SMOKE_BRIDGE = ROOT / ".github/workflows/sp500-megarun-dehb-official-smoke.yml"
CONTINUOUS_BOOTSTRAP = ROOT / ".github/workflows/sp500-dehb-continuous-bootstrap-v2.yml"
CONTINUOUS_COORDINATOR = ROOT / ".github/workflows/sp500-dehb-continuous-coordinator-v2.yml"
CONTINUOUS_POOL = ROOT / ".github/workflows/sp500-dehb-continuous-worker-pool-v2.yml"
CONTINUOUS_REDUCER = ROOT / ".github/workflows/sp500-dehb-continuous-reducer-v2.yml"
CONTINUOUS_SUPERVISOR = ROOT / ".github/workflows/sp500-dehb-continuous-supervisor-v2.yml"
CONTINUOUS_WORKER_ACTION = ROOT / ".github/actions/sp500-dehb-continuous-worker/action.yml"


def _load(path: Path) -> dict[str, Any]:
    return dict(load_github_yaml(path))


def test_worker_downloads_only_three_peer_artifacts_per_cache_run() -> None:
    text = WORKER_ACTION.read_text(encoding="utf-8")

    assert "list_sp500_megarun_dehb_cache_peer_jobs.py" in text
    assert 'test "${#peer_jobs[@]}" -eq 3' in text
    assert '--name "sp500-dehb-worker-$peer_job"' in text
    assert "--evaluation-cache-root" in text


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
        json.dumps(matrices[shard], ensure_ascii=True, separators=(",", ":")) for shard in "ABC"
    ]
    estimated_utf16_bytes = sum(len(value) * 2 for value in encoded)

    assert [len(matrices[shard]["include"]) for shard in "ABC"] == [120, 120, 120]
    assert estimated_utf16_bytes < 1_000_000
