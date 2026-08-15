from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.dehb_numeric_runtime import DEHB_NUMERIC_ENV


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


def test_continuous_smoke_uses_exact_commit_and_postgres_16_without_later_data() -> None:
    workflow = _load(CONTINUOUS_SMOKE)
    text = CONTINUOUS_SMOKE.read_text(encoding="utf-8")

    job = workflow["jobs"]["postgres_contract"]
    assert job["services"]["postgres"]["image"] == "postgres:16.4-alpine"
    assert job["steps"][0]["with"]["ref"] == "${{ inputs.commit_sha }}"
    assert "test_sp500_megarun_dehb_continuous_postgres.py" in text
    assert "validation_2011_2020" not in text
    assert "2021" not in text


def test_registered_smoke_can_bridge_continuous_postgres_on_feature_branch() -> None:
    workflow = _load(REGISTERED_SMOKE_BRIDGE)
    text = REGISTERED_SMOKE_BRIDGE.read_text(encoding="utf-8")

    dispatch = workflow["on"]["workflow_dispatch"]["inputs"]
    assert dispatch["mode"]["default"] == "official"
    assert "continuous_postgres" in dispatch["mode"]["options"]
    job = workflow["jobs"]["continuous_postgres"]
    assert job["if"] == "${{ inputs.mode == 'continuous_postgres' }}"
    assert job["services"]["postgres"]["image"] == "postgres:16.4-alpine"
    assert "test_sp500_megarun_dehb_continuous_postgres.py" in text
    assert "validation_2011_2020" not in text
    assert "locked_2021" not in text


def test_registered_bridge_can_clone_and_verify_coordinator_database() -> None:
    workflow = _load(REGISTERED_SMOKE_BRIDGE)
    text = REGISTERED_SMOKE_BRIDGE.read_text(encoding="utf-8")

    dispatch = workflow["on"]["workflow_dispatch"]["inputs"]
    assert "continuous_migrate" in dispatch["mode"]["options"]
    migration = workflow["jobs"]["continuous_migrate"]
    assert migration["if"] == "${{ inputs.mode == 'continuous_migrate' }}"
    assert migration["env"]["SP500_DEHB_COORDINATOR_DATABASE_URL"] == (
        "${{ secrets.SP500_DEHB_COORDINATOR_DATABASE_URL_DIRECT }}"
    )
    assert migration["env"]["SP500_DEHB_COORDINATOR_DATABASE_URL_NEXT"] == (
        "${{ secrets.SP500_DEHB_COORDINATOR_DATABASE_URL_NEXT_DIRECT }}"
    )
    assert "pg_dump" in text
    assert "pg_restore" in text
    assert "assert_sp500_dehb_database_quiescent.py" in text
    assert "verify_sp500_dehb_database_clone.py" in text
    assert "validation_2011_2020" not in text
    assert "locked_2021" not in text


def test_registered_bridge_can_allocate_an_encrypted_reserve_database() -> None:
    workflow = _load(REGISTERED_SMOKE_BRIDGE)
    text = REGISTERED_SMOKE_BRIDGE.read_text(encoding="utf-8")

    dispatch = workflow["on"]["workflow_dispatch"]["inputs"]
    assert "continuous_allocate" in dispatch["mode"]["options"]
    allocation = workflow["jobs"]["continuous_allocate"]
    assert allocation["if"] == "${{ inputs.mode == 'continuous_allocate' }}"
    assert allocation["runs-on"] == "macos-15"
    assert "allocation_public_key_b64" in dispatch
    assert "openssl pkeyutl -encrypt" in text
    assert "rsa_padding_mode:oaep" in text
    assert "connection-string.enc" in text
    assert "claim-url.enc" in text


def test_registered_bridge_can_start_and_continue_production_autonomously() -> None:
    workflow = _load(REGISTERED_SMOKE_BRIDGE)
    text = REGISTERED_SMOKE_BRIDGE.read_text(encoding="utf-8")

    dispatch = workflow["on"]["workflow_dispatch"]["inputs"]
    assert {"continuous_start", "continuous_continue"}.issubset(
        dispatch["mode"]["options"]
    )
    assert workflow["permissions"] == {"actions": "write", "contents": "read"}
    assert workflow["jobs"]["continuous_bootstrap"]["uses"] == (
        "./.github/workflows/sp500-dehb-continuous-bootstrap-v2.yml"
    )
    assert workflow["jobs"]["continuous_coordinator"]["uses"] == (
        "./.github/workflows/sp500-dehb-continuous-coordinator-v2.yml"
    )
    assert workflow["jobs"]["continuous_pool"]["uses"] == (
        "./.github/workflows/sp500-dehb-continuous-worker-pool-v2.yml"
    )
    assert workflow["jobs"]["continuous_reducer"]["uses"] == (
        "./.github/workflows/sp500-dehb-continuous-reducer-v2.yml"
    )
    continuation = workflow["jobs"]["continuous_continue"]
    assert continuation["needs"] == [
        "continuous_bootstrap",
        "continuous_coordinator",
        "continuous_pool",
        "continuous_reducer",
    ]
    assert "gh workflow run sp500-megarun-dehb-official-smoke.yml" in text
    assert "continuous_continue" in text
    assert "halt_conflict" in text
    assert "halt_boundary" in text
    assert "sp500-dehb-mega-controller-v1.yml" not in text
    assert "validation_2011_2020" not in text
    assert "locked_2021" not in text


def test_continuous_children_are_reusable_and_cover_full_pool_generation() -> None:
    coordinator = _load(CONTINUOUS_COORDINATOR)
    reducer = _load(CONTINUOUS_REDUCER)

    for path in (
        CONTINUOUS_BOOTSTRAP,
        CONTINUOUS_COORDINATOR,
        CONTINUOUS_POOL,
        CONTINUOUS_REDUCER,
        CONTINUOUS_SUPERVISOR,
    ):
        assert "workflow_call" in _load(path)["on"]

    coordinator_job = coordinator["jobs"]["coordinator"]
    assert coordinator_job["strategy"]["max-parallel"] == 1
    assert coordinator_job["strategy"]["matrix"]["lifetime_ordinal"] == [0, 1]
    reducer_job = reducer["jobs"]["reduce"]
    assert reducer_job["strategy"]["max-parallel"] == 1
    assert reducer_job["strategy"]["matrix"]["reducer_ordinal"] == [0, 1, 2, 3]
    assert "--delay-minutes" in CONTINUOUS_REDUCER.read_text(encoding="utf-8")


def test_continuous_pool_has_three_120_parallel_shards_and_four_slots() -> None:
    workflow = _load(CONTINUOUS_POOL)
    action = _load(CONTINUOUS_WORKER_ACTION)

    for shard in "abc":
        job = workflow["jobs"][f"shard_{shard}"]
        assert job["strategy"]["max-parallel"] == 120
        assert job["strategy"]["fail-fast"] is False
        assert job["runs-on"] == "ubuntu-24.04"
        assert job["steps"][1]["uses"] == "./.github/actions/sp500-dehb-continuous-worker"
    assert "run_sp500_dehb_continuous_worker.py" in CONTINUOUS_WORKER_ACTION.read_text(
        encoding="utf-8"
    )
    assert "--executor-slots 4" in CONTINUOUS_WORKER_ACTION.read_text(encoding="utf-8")
    assert action["runs"]["using"] == "composite"
    worker_script = (ROOT / "scripts/run_sp500_dehb_continuous_worker.py").read_text(
        encoding="utf-8"
    )
    assert "pool_min_size=0" in worker_script
    assert "pool_max_size=1" in worker_script
    bootstrap_script = (
        ROOT / "scripts/init_sp500_dehb_continuous_campaign.py"
    ).read_text(encoding="utf-8")
    assert "probe_database_client_capacity" in bootstrap_script
    assert "required_connections=400" in bootstrap_script


def test_every_scientific_continuous_job_exports_the_frozen_numeric_runtime() -> None:
    coordinator = _load(CONTINUOUS_COORDINATOR)["jobs"]["coordinator"]
    reducer = _load(CONTINUOUS_REDUCER)["jobs"]["reduce"]
    pool_jobs = _load(CONTINUOUS_POOL)["jobs"]

    scientific_jobs = [
        coordinator,
        reducer,
        *(pool_jobs[f"shard_{shard}"] for shard in "abc"),
    ]
    for job in scientific_jobs:
        assert {
            name: str(job["env"].get(name, "")) for name in DEHB_NUMERIC_ENV
        } == dict(DEHB_NUMERIC_ENV)


def test_continuous_reducer_reads_nested_technical_evidence_run_reference() -> None:
    reducer = _load(CONTINUOUS_REDUCER)["jobs"]["reduce"]
    download_step = next(
        step
        for step in reducer["steps"]
        if step["name"] == "Download exact technical evidence named by launch contract"
    )

    command = download_step["run"]
    assert ".technical_evidence.workflow_run_id" in command
    assert ".technical_evidence.artifact_name" in command
    assert 'gh run download "$technical_run_id"' in command
    assert '--name "$technical_artifact_name"' in command


def test_continuous_workflows_are_exact_commit_train_only_and_never_call_v1() -> None:
    paths = (
        CONTINUOUS_BOOTSTRAP,
        CONTINUOUS_COORDINATOR,
        CONTINUOUS_POOL,
        CONTINUOUS_REDUCER,
        CONTINUOUS_SUPERVISOR,
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for path in paths:
        assert path.exists()
        assert "commit_sha" in path.read_text(encoding="utf-8")
    assert "SP500_DEHB_COORDINATOR_DATABASE_URL" in combined
    assert "sp500-dehb-mega-controller-v1.yml" not in combined
    assert "validation_2011_2020" not in combined
    assert "locked_2021" not in combined
    assert "2021" not in combined


def test_three_shards_request_360_jobs_and_skip_inside_called_worker() -> None:
    controller = _load(CONTROLLER)
    worker = _load(WORKER_ACTION)

    jobs = controller["jobs"]
    assert "preflight" in jobs
    assert jobs["framework_contract"]["uses"] == ("./.github/workflows/_aurora-future-run-v3.yml")
    assert jobs["preflight"]["needs"] == "framework_contract"
    assert jobs["plan"]["needs"] == "preflight"
    for shard_id in "abc":
        job = jobs[f"shard_{shard_id}"]
        assert job["needs"] == ["preflight", "plan"]
        assert job["strategy"]["max-parallel"] == 120
        assert job["strategy"]["fail-fast"] is False
        assert job["timeout-minutes"] == 330
        assert job["continue-on-error"] is True
        assert job["steps"][1]["uses"] == ("./.github/actions/sp500-dehb-mega-worker")
        assert job["steps"][1]["if"] == ("${{ !startsWith(matrix.job_id, 'SKIP-') }}")
        assert job["steps"][1]["with"]["evaluation-cache-run-ids"] == (
            "${{ inputs.evaluation_cache_run_ids }}"
        )
    assert worker["runs"]["using"] == "composite"
    assert all(
        jobs["shard_a"]["env"][name] == "1"
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        )
    )
    for shard_id in "abc":
        env = jobs[f"shard_{shard_id}"]["env"]
        assert env["OPENBLAS_CORETYPE"] == "NEHALEM"
        assert "AVX" in env["NPY_DISABLE_CPU_FEATURES"].split(",")
        assert env["VECLIB_MAXIMUM_THREADS"] == "1"
        assert env["BLIS_NUM_THREADS"] == "1"


def test_controller_is_indefinite_train_only_and_retries_exact_jobs() -> None:
    workflow = _load(CONTROLLER)
    text = CONTROLLER.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"actions": "write", "contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["jobs"]["reduce"]["timeout-minutes"] == 360
    assert "retry_jobs" in text
    assert "dispatch_next_wave" in text
    assert "gh workflow run sp500-dehb-mega-controller-v1.yml" in text
    assert "build_sp500_megarun_dehb_launch_contract.py" in text
    assert "--launch-contract" in text
    assert "sp500-dehb-launch-contract" in text
    assert workflow["jobs"]["plan"]["if"] == "${{ !inputs.launch_only }}"
    assert "validation_2011_2020" not in text
    assert "2021" not in text
    assert "timeout-hours" not in text
    assert "evaluation_cache_run_ids" in text
    assert '-f evaluation_cache_run_ids="$cache_ids"' in text


def test_worker_downloads_only_three_peer_artifacts_per_cache_run() -> None:
    text = WORKER_ACTION.read_text(encoding="utf-8")

    assert "list_sp500_megarun_dehb_cache_peer_jobs.py" in text
    assert 'test "${#peer_jobs[@]}" -eq 3' in text
    assert '--name "sp500-dehb-worker-$peer_job"' in text
    assert "--evaluation-cache-root" in text


def test_controller_normalizes_outputs_without_python_one_liner_syntax_hazard() -> None:
    text = CONTROLLER.read_text(encoding="utf-8")

    normalize_start = text.index("      - name: Normalize controller outputs")
    normalize_end = text.index("      - name: Upload controller decision", normalize_start)
    block = text[normalize_start:normalize_end]

    assert "python -c" not in block
    assert "printf 'action=%s\\n'" in block
    assert "printf 'next_wave=%s\\n'" in block
    assert "printf 'next_restart_ordinal=%s\\n'" in block


def test_controller_continuation_reads_decision_artifact_after_reduce() -> None:
    workflow = _load(CONTROLLER)
    text = CONTROLLER.read_text(encoding="utf-8")
    continuation = workflow["jobs"]["continue"]
    block = text[text.index("  continue:") :]

    assert "always()" in continuation["if"]
    assert "needs.reduce.result == 'success'" in continuation["if"]
    assert "sp500-dehb-controller-decision" in block
    assert "controller_decision.json" in block
    assert "steps.decision.outputs.action" in block
    assert "needs.reduce.outputs.action" not in block


def test_reducer_validates_exact_wave_plan_instead_of_reconstructing_it() -> None:
    text = CONTROLLER.read_text(encoding="utf-8")
    reduce_block = text[text.index("  reduce:") : text.index("  continue:")]

    assert "Download exact wave plan" in reduce_block
    assert "name: sp500-dehb-wave-plan" in reduce_block
    assert '--wave-plan "$RUNNER_TEMP/dehb_wave_plan"' in reduce_block


def test_cross_runner_probe_replays_all_material_conflicts_on_six_hosts() -> None:
    workflow = _load(CROSS_RUNNER)
    text = CROSS_RUNNER.read_text(encoding="utf-8")

    assert "push:" not in text
    assert "framework_contract:" in text
    assert "needs: framework_contract" in text
    assert "replica: [1, 2, 3, 4, 5, 6]" in text
    assert "Replay all 35 material conflicts" in text
    assert "--expected-replicas 6" in text
    assert 'run-id: "31418682679"' in text
    assert 'run-id: "31774646675"' in text
    env = workflow["jobs"]["probe"]["env"]
    assert env["OPENBLAS_CORETYPE"] == "NEHALEM"
    assert "AVX" in env["NPY_DISABLE_CPU_FEATURES"].split(",")
    assert env["VECLIB_MAXIMUM_THREADS"] == "1"
    assert env["BLIS_NUM_THREADS"] == "1"


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


def test_cache_conflict_diagnostic_is_github_only_and_train_evidence_only() -> None:
    workflow = _load(CONFLICT_DIAGNOSTIC)
    text = CONFLICT_DIAGNOSTIC.read_text(encoding="utf-8")

    assert set(workflow["on"]) == {"push", "workflow_dispatch"}
    assert workflow["on"]["push"]["branches"] == [
        "codex/sp500-search-method-benchmark-short"
    ]
    assert workflow["on"]["push"]["paths"] == [
        ".github/workflows/sp500-dehb-cache-conflict-diagnostic.yml",
        "infra/sp500_megarun/dehb_global_merge.py",
        "scripts/diagnose_sp500_megarun_dehb_cache_conflicts.py",
    ]
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert "source_run_id" in workflow["on"]["workflow_dispatch"]["inputs"]
    assert 'gh run download "$SOURCE_RUN_ID"' in text
    assert '--pattern "sp500-dehb-worker-*"' in text
    assert "diagnose_sp500_megarun_dehb_cache_conflicts.py" in text
    assert "95c8068e41e8e508ec57b44ae456cda790ab8af56a39e293a72296f7e1995232" not in text
    assert "validation_2011_2020" not in text
    assert "locked_2021" not in text
