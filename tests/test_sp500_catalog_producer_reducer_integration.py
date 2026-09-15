from __future__ import annotations

import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.sp500_megarun.catalog_admission import CatalogRunPlanV1
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_recovery_blocks import (
    resolve_recovery_block,
)
from aurora.infra.sp500_megarun.catalog_resume import build_resume_work_manifest
from scripts import reduce_sp500_optimized_catalog_group as reducer
from scripts.reduce_sp500_optimized_catalog_group import (
    _checkpoint_receipts,
    _checkpoint_rows,
    _group_row,
    _load_assignment_documents,
    _node_row,
    _validate_node_checkpoint_bindings,
    _verify_plan_document,
)
from tests.test_catalog_prepared_materialization import prepared_transport_fixture
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    materialize_prepared_catalog_plan,
)


_STAGE_NAMES = (
    "component_load",
    "composition",
    "objective",
    "serialization",
    "write",
)
_WALL_STAGE_NAMES = (
    "initialization",
    "evaluation",
    "write",
    "selected_verification",
)


def _write_json(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _write_synthetic_checkpoint(
    root: Path,
    *,
    policy: dict[str, object],
    worker_id: int,
    strategy_ids: list[str],
    science_identity_sha256: str,
    catalog_manifest_sha256: str,
    block_size: int,
) -> None:
    artifact = policy["workers"][worker_id]["checkpoint_slot_artifacts"][0]  # type: ignore[index]
    checkpoint = root / str(artifact)
    checkpoint.mkdir()
    rows = [
        {
            "strategy_id": strategy_id,
            "result_json": json.dumps(
                {"fixture": True, "strategy_id": strategy_id},
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for strategy_id in strategy_ids
    ]
    result_path = checkpoint / "results.parquet"
    pq.write_table(
        pa.Table.from_pylist(rows, schema=reducer._RESULT_SCHEMA),
        result_path,
        compression="zstd",
        use_dictionary=True,
        row_group_size=4096,
    )
    result_sha256 = sha256_file(result_path)
    recovery_block_id = resolve_recovery_block(
        policy,
        science_sha256=str(policy["science_sha256"]),
        worker_id=worker_id,
        slot_index=1,
        strategy_ids=strategy_ids,
    )
    attempt_id = (
        f"{policy['authority_id']}:worker:{worker_id:03d}:attempt:1"
    )
    receipt = {
        "schema_version": "1",
        "attempt_id": attempt_id,
        "science_identity_sha256": science_identity_sha256,
        "catalog_manifest_sha256": catalog_manifest_sha256,
        "shard_index": worker_id,
        "checkpoint_slot_index": 1,
        "checkpoint_slot_count": 1,
        "previous_checkpoint_receipt_sha256": "0" * 64,
        "result_sha256": result_sha256,
        "strategy_count": len(strategy_ids),
        "validation_opened": False,
        "locked_opened": False,
        "recovery_block_id": recovery_block_id,
        "processes_per_worker": 2,
        "block_size": block_size,
        "available_memory_bytes": 1,
        "peak_memory_bytes": 1,
        "peak_memory_fraction": 1.0,
        "cpu_seconds": 0.01,
        "scientific_attribution_difference_ratio": 0.0,
        "scientific_stage_seconds": {name: 0.0 for name in _STAGE_NAMES},
        "scientific_wall_stage_seconds": {
            name: (0.01 if name == "evaluation" else 0.0)
            for name in _WALL_STAGE_NAMES
        },
    }
    receipt_path = checkpoint / "receipt.json"
    _write_json(receipt_path, receipt)
    receipt_sha256 = sha256_file(receipt_path)
    attempt = {
        "schema_version": "1",
        "worker_id": worker_id,
        "checkpoint_slot_index": 1,
        "checkpoint_slot_count": 1,
        "strategy_ids": strategy_ids,
        "attempt_id": attempt_id,
        "result_sha256": result_sha256,
        "receipt_sha256": receipt_sha256,
        "previous_checkpoint_receipt_sha256": "0" * 64,
        "recovery_block_id": recovery_block_id,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write_json(checkpoint / "shard_attempt_manifest.json", attempt)
    chain_identity = {
        "schema_version": "1",
        "worker_id": worker_id,
        "slot_index": 1,
        "slot_count": 1,
        "previous_receipt_sha256": "0" * 64,
        "current_receipt_sha256": receipt_sha256,
        "completed_strategy_ids": strategy_ids,
        "attempt_id": attempt_id,
        "recovery_block_id": recovery_block_id,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write_json(
        checkpoint / "checkpoint_chain_manifest.json",
        {**chain_identity, "chain_sha256": canonical_sha256(chain_identity)},
    )


def test_real_producer_materialization_reaches_verified_synthetic_reducer_output(
    tmp_path: Path, monkeypatch,
) -> None:
    """Exercise the full document boundary with explicitly non-scientific rows."""
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
    node = _node_row(reduction_plan, group=group)
    checkpoint_rows = _checkpoint_rows(policy, worker_ids=worker_ids)
    _validate_node_checkpoint_bindings(
        node,
        worker_ids=worker_ids,
        checkpoint_rows=checkpoint_rows,
    )
    assert [
        artifact
        for worker_id in worker_ids
        for artifact in checkpoint_rows[worker_id]["checkpoint_slot_artifacts"][
            : checkpoint_rows[worker_id]["checkpoint_slot_count"]
        ]
    ] == group["checkpoint_artifacts"]

    contract = RunOptimizationContractV1.model_validate_json(
        (sealed / "resolved_contract.json").read_text("utf-8")
    )
    expected_science_identity_sha256 = canonical_sha256(contract.science)
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
            science_identity_sha256=expected_science_identity_sha256,
            catalog_manifest_sha256=contract.science.catalog_manifest_sha256,
            block_size=contract.execution.block_size,
        )
    receipts, receipt_manifest = _checkpoint_receipts(
        checkpoint_input,
        worker_ids=worker_ids,
        checkpoint_rows=checkpoint_rows,
        assignments=assignments,
        recovery_policy=policy,
    )
    assert len(receipts) == len(worker_ids) == 7
    assert len(receipt_manifest) == len(worker_ids)
    assert all(
        item["recovery_block_id"] for item in receipt_manifest
    )
    assert all(
        receipt["validation_opened"] is False and receipt["locked_opened"] is False
        for receipt in receipts
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
    run_plan_path.write_text(run_plan.model_dump_json() + "\n", encoding="utf-8")

    output_dir = tmp_path / "reduction-output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reduce_sp500_optimized_catalog_group.py",
            "--input-root",
            str(checkpoint_input),
            "--resolved-contract",
            str(sealed / "resolved_contract.json"),
            "--resume-work-manifest",
            str(work_manifest_path),
            "--run-plan",
            str(run_plan_path),
            "--admission-token",
            "e" * 64,
            "--checkpoint-policy",
            str(sealed / "checkpoint_policy.json"),
            "--reduction-plan",
            str(sealed / "reduction_plan.json"),
            "--recipe-assignments",
            str(sealed / "recipe_assignment_bundle.zip"),
            "--group-id",
            "0",
            "--output-dir",
            str(output_dir),
        ],
    )
    assert reducer.main() == 0

    table = pq.read_table(output_dir / "results.parquet")
    output_rows = table.to_pylist()
    assert [row["strategy_id"] for row in output_rows] == sorted(strategy_ids)
    assert len(output_rows) == 24
    assert all(json.loads(row["result_json"])["fixture"] is True for row in output_rows)

    group_manifest = json.loads(
        (output_dir / "reduction_group_manifest.json").read_text("utf-8")
    )
    output_receipt = json.loads((output_dir / "receipt.json").read_text("utf-8"))
    assert group_manifest["validation_opened"] is False
    assert group_manifest["locked_opened"] is False
    assert group_manifest["worker_ids"] == worker_ids
    assert group_manifest["result_sha256"] == sha256_file(
        output_dir / "results.parquet"
    )
    assert output_receipt["validation_opened"] is False
    assert output_receipt["locked_opened"] is False
    assert output_receipt["strategy_count"] == len(strategy_ids)
    assert output_receipt["selected_strategy_count"] == 0
    assert output_receipt["science_identity_sha256"] == expected_science_identity_sha256
    assert output_receipt["catalog_manifest_sha256"] == contract.science.catalog_manifest_sha256
    receipt_identity = {
        key: value for key, value in output_receipt.items() if key != "receipt_sha256"
    }
    assert output_receipt["receipt_sha256"] == canonical_sha256(receipt_identity)
