"""Cloud-entry consumer checks that are not covered by the existing contracts.

P25, P27, and P35 already have focused coverage in the existing payload,
checkpoint-policy, producer/reducer, and canary-scope tests.  This module owns
the remaining P32 boundary: a reducer failure must leave durable checkpoints
available for recovery and must not create a fresh evaluation output.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_admission import CatalogRunPlanV1
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    materialize_prepared_catalog_plan,
)
from aurora.infra.sp500_megarun.catalog_resume import build_resume_work_manifest
from scripts import reduce_sp500_optimized_catalog_group as reducer
from scripts.reduce_sp500_optimized_catalog_group import (
    _checkpoint_rows,
    _group_row,
    _load_assignment_documents,
    _verify_plan_document,
)
from tests.test_sp500_catalog_producer_reducer_integration import (
    _write_synthetic_checkpoint,
)
from tests.test_catalog_prepared_materialization import prepared_transport_fixture


def _file_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _reduction_case(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Build the real sealed producer documents consumed by the reducer CLI."""
    bundle, _template, _plan, identity, _prepared = prepared_transport_fixture(
        tmp_path / "prepared"
    )
    sealed = tmp_path / "sealed"
    materialize_prepared_catalog_plan(
        bundle_dir=bundle,
        expected_identity=identity,
        request_sha256="1" * 64,
        decision_sha256="2" * 64,
        output_dir=sealed,
    )

    policy = _verify_plan_document(sealed / "checkpoint_policy.json", "checkpoint_policy")
    reduction_plan = _verify_plan_document(sealed / "reduction_plan.json", "reduction_plan")
    assignments = _load_assignment_documents(sealed / "recipe_assignment_bundle.zip")
    group = _group_row(reduction_plan, 0)
    worker_ids = list(group["worker_ids"])
    checkpoint_rows = _checkpoint_rows(policy, worker_ids=worker_ids)
    contract = RunOptimizationContractV1.model_validate_json(
        (sealed / "resolved_contract.json").read_text("utf-8")
    )
    strategy_ids = [
        strategy_id
        for worker_id in worker_ids
        for strategy_id in assignments[worker_id]["strategy_ids"]
    ]

    checkpoint_input = tmp_path / "checkpoint-input"
    checkpoint_input.mkdir()
    for worker_id in worker_ids:
        _write_synthetic_checkpoint(
            checkpoint_input,
            policy=policy,
            worker_id=worker_id,
            strategy_ids=list(assignments[worker_id]["strategy_ids"]),
            science_identity_sha256=canonical_sha256(contract.science),
            catalog_manifest_sha256=contract.science.catalog_manifest_sha256,
            block_size=contract.execution.block_size,
        )

    work_manifest = build_resume_work_manifest(
        strategy_ids,
        cached_strategy_ids=(),
        maximum_workers=len(worker_ids),
    )
    work_manifest_path = tmp_path / "cli-resume-work-manifest.json"
    work_manifest_path.write_text(
        work_manifest.model_dump_json() + "\n", encoding="utf-8"
    )
    run_plan = CatalogRunPlanV1(
        contract_sha256=contract.contract_sha256,
        evidence_sha256="f" * 64,
        admission_token_sha256="e" * 64,
        workers=contract.execution.workers,
        active_workers=len(worker_ids),
        component_workers=contract.execution.component_workers,
        component_processes_per_worker=contract.execution.component_processes_per_worker,
        processes_per_worker=2,
        block_size=contract.execution.block_size,
        matrices=(tuple(worker_ids),),
        work_manifest_sha256=work_manifest.manifest_sha256,
        pending_recipe_count=len(strategy_ids),
        cached_recipe_count=0,
        expected_physical_component_builds=12,
    )
    run_plan_path = tmp_path / "cli-run-plan.json"
    run_plan_path.write_text(
        run_plan.model_dump_json() + "\n", encoding="utf-8"
    )
    return (
        checkpoint_input,
        sealed / "resolved_contract.json",
        work_manifest_path,
        run_plan_path,
    )


def test_reduction_failure_preserves_checkpoints_without_reevaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_input, resolved_contract, work_manifest, run_plan = _reduction_case(
        tmp_path
    )
    policy = json.loads(
        (tmp_path / "sealed" / "checkpoint_policy.json").read_text("utf-8")
    )
    reduction_plan = json.loads(
        (tmp_path / "sealed" / "reduction_plan.json").read_text("utf-8")
    )
    worker_ids = list(_group_row(reduction_plan, 0)["worker_ids"])
    checkpoint_rows = _checkpoint_rows(policy, worker_ids=worker_ids)
    first_artifact = checkpoint_rows[worker_ids[0]]["checkpoint_slot_artifacts"][0]
    result_path = checkpoint_input / first_artifact / "results.parquet"
    table = pq.read_table(result_path)
    rows = table.to_pylist()
    rows[0]["result_json"] = json.dumps(
        {"fixture": True, "tampered": True},
        sort_keys=True,
        separators=(",", ":"),
    )
    pq.write_table(
        pa.Table.from_pylist(rows, schema=reducer._RESULT_SCHEMA),
        result_path,
        compression="zstd",
        use_dictionary=True,
        row_group_size=4096,
    )
    before = _file_snapshot(checkpoint_input)
    output_dir = tmp_path / "reduction-output"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reduce_sp500_optimized_catalog_group.py",
            "--input-root",
            str(checkpoint_input),
            "--resolved-contract",
            str(resolved_contract),
            "--resume-work-manifest",
            str(work_manifest),
            "--run-plan",
            str(run_plan),
            "--admission-token",
            "e" * 64,
            "--checkpoint-policy",
            str(tmp_path / "sealed" / "checkpoint_policy.json"),
            "--reduction-plan",
            str(tmp_path / "sealed" / "reduction_plan.json"),
            "--recipe-assignments",
            str(tmp_path / "sealed" / "recipe_assignment_bundle.zip"),
            "--group-id",
            "0",
            "--output-dir",
            str(output_dir),
        ],
    )

    with pytest.raises(SystemExit, match="REDUCTION_CHECKPOINT_CHAIN_INVALID"):
        reducer.main()

    assert not output_dir.exists()
    assert _file_snapshot(checkpoint_input) == before
