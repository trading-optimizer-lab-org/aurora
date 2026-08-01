from __future__ import annotations

from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/gtbi-v7-new-reference.yml")
WORKER_WORKFLOW = Path(".github/workflows/gtbi-v7-new-reference-worker.yml")


def test_workflow_is_manual_github_only_and_locked_has_no_input() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["name"] == "GTBI V7 New Reference Historical Campaign"
    trigger = data.get("on") or data.get(True)
    assert set(trigger) == {"workflow_dispatch"}
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert "locked_start" not in inputs
    assert "validation_end" not in inputs
    assert "train_end" not in inputs
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT" not in text
    assert "runs-on: ubuntu-24.04" in text


def test_workflow_keeps_exact_dates_and_requires_prior_gates() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "2010-12-31" in text
    assert "2011-01-01..2020-12-31" in text
    assert "2021-01-01" in text
    assert "Locked opened: `false`" in text
    assert "inputs.benchmark_run_id != ''" in text
    assert "inputs.smoke_run_id != ''" in text
    assert "inputs.full_authorized" in text


def test_workflow_uses_100_job_smoke_and_dynamic_one_wave_full() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "for i in range(100)" in text
    assert "max-parallel: 100" in text
    assert text.count("max-parallel: 180") == 2
    assert "full_matrix_a" in text
    assert "full_matrix_b" in text
    assert 'len(full_a["include"]) > 180' in text
    assert 'len(full_b["include"]) > 180' in text
    assert "runner_count = logical_workers // processes" in text
    assert "range(runner * processes, (runner + 1) * processes)" in text
    assert "logical_workers = 360" in text
    assert "--logical-workers 360" in text
    assert "--block-size 20" in text
    assert "range(logical_workers // block_size)" in text
    assert "--expected-worker-count 360" in text


def test_workflow_benchmarks_one_two_four_and_pins_actions() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "processes: [1, 2, 4]" in text
    assert "max-parallel: 3" in text
    assert "--processes-per-runner \"${{ matrix.processes }}\"" in text
    assert "gtbi-v7-benchmark-mode-${{ matrix.processes }}" in text
    assert "verify_gtbi_v7_new_reference_evidence" in text
    for workflow in (WORKFLOW, WORKER_WORKFLOW):
        workflow_text = workflow.read_text(encoding="utf-8")
        for action in (
            "actions/checkout@",
            "actions/setup-python@",
            "actions/upload-artifact@",
            "actions/download-artifact@",
        ):
            for line in [line.strip() for line in workflow_text.splitlines() if action in line]:
                revision = line.split("@", 1)[1]
                assert len(revision) == 40
                int(revision, 16)


def test_full_downloads_only_dynamic_aligned_runner_artifacts() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    worker_text = WORKER_WORKFLOW.read_text(encoding="utf-8")
    assert "run-full-a:" in text
    assert "run-full-b:" in text
    assert "needs: [resolve, full-gate, run-full-a, run-full-b]" in text
    assert text.count("uses: ./.github/workflows/gtbi-v7-new-reference-worker.yml") == 2
    assert "RUNNER_COUNT: ${{ matrix.runner_count }}" in text
    assert "seq 0 $((RUNNER_COUNT - 1))" in text
    assert "--batch-worker-ids \"$WORKER_IDS\"" in worker_text
    assert "--processes-per-runner \"$PROCESSES\"" in worker_text
    assert "--expected-block-count 18" in text
    assert "--expected-alias-count 72000" in text
    assert "gtbi-v7-new-reference-historical-results" in text


def test_workflow_materializes_compact_pack_and_preserves_final_release() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("materialize_gtbi_v7_strategy_pack extract") == 2
    assert "strategy_shards.zip" not in text
    assert "preserve-final:" in text
    assert "contents: write" in text
    assert "gtbi-v7-new-reference-results-${GITHUB_RUN_ID}" in text


def test_workflow_binds_every_gate_and_exact_commit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "full-gate:" in text
    assert "--smoke-validation smoke/smoke_validation.json" in text
    assert "--campaign-manifest plan/campaign_manifest.json" in text
    assert "EXPECTED_CPUS" in text
    assert "ACTUAL_CPUS" in text


def test_reusable_worker_is_github_only_and_has_no_manual_trigger() -> None:
    text = WORKER_WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    trigger = data.get("on") or data.get(True)
    assert set(trigger) == {"workflow_call"}
    assert "workflow_dispatch" not in text
    assert "runs-on: ubuntu-24.04" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT" not in text
    assert "timeout-minutes: 720" in text
