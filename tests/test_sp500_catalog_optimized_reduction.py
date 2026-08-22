from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.shard_planner import sha256_file
from scripts.reduce_sp500_optimized_catalog_group import (
    _checkpoint_receipts,
    _validate_node_checkpoint_bindings,
)


def _write_checkpoint(
    root: Path,
    *,
    worker_id: int,
    slot_index: int,
    slot_count: int,
    strategy_ids: list[str],
    previous_receipt_sha256: str,
) -> str:
    root.mkdir()
    result_path = root / "results.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"strategy_id": strategy_id, "result_json": "{}"}
                for strategy_id in strategy_ids
            ]
        ),
        result_path,
    )
    result_sha256 = sha256_file(result_path)
    receipt = {
        "schema_version": 1,
        "shard_index": worker_id,
        "checkpoint_slot_index": slot_index,
        "checkpoint_slot_count": slot_count,
        "previous_checkpoint_receipt_sha256": previous_receipt_sha256,
        "strategy_count": len(strategy_ids),
        "result_sha256": result_sha256,
        "validation_opened": False,
        "locked_opened": False,
    }
    receipt_path = root / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", "utf-8")
    receipt_sha256 = sha256_file(receipt_path)
    attempt = {
        "schema_version": "1",
        "worker_id": worker_id,
        "checkpoint_slot_index": slot_index,
        "checkpoint_slot_count": slot_count,
        "strategy_ids": strategy_ids,
        "result_sha256": result_sha256,
        "receipt_sha256": receipt_sha256,
        "previous_checkpoint_receipt_sha256": previous_receipt_sha256,
    }
    (root / "shard_attempt_manifest.json").write_text(
        json.dumps(attempt, sort_keys=True) + "\n",
        "utf-8",
    )
    chain = {
        "schema_version": "1",
        "worker_id": worker_id,
        "slot_index": slot_index,
        "slot_count": slot_count,
        "previous_receipt_sha256": previous_receipt_sha256,
        "current_receipt_sha256": receipt_sha256,
        "completed_strategy_ids": strategy_ids,
        "validation_opened": False,
        "locked_opened": False,
    }
    chain["chain_sha256"] = canonical_sha256(chain)
    (root / "checkpoint_chain_manifest.json").write_text(
        json.dumps(chain, sort_keys=True) + "\n",
        "utf-8",
    )
    return receipt_sha256


def test_group_reducer_requires_one_exact_contiguous_checkpoint_chain(
    tmp_path: Path,
) -> None:
    artifacts = [f"checkpoint-{slot}" for slot in range(1, 9)]
    policy = {
        0: {
            "worker_id": 0,
            "checkpoint_slot_count": 2,
            "checkpoint_slot_artifacts": artifacts,
            "checkpoint_slot_manifest_sha256": canonical_sha256(
                {
                    "schema_version": "1",
                    "artifacts": artifacts,
                    "slot_count": 2,
                }
            ),
        }
    }
    assignments = {
        0: {
            "strategy_ids": ["strategy-0", "strategy-1", "strategy-2", "strategy-3"]
        }
    }
    first_sha = _write_checkpoint(
        tmp_path / artifacts[0],
        worker_id=0,
        slot_index=1,
        slot_count=2,
        strategy_ids=["strategy-0", "strategy-1"],
        previous_receipt_sha256="0" * 64,
    )
    _write_checkpoint(
        tmp_path / artifacts[1],
        worker_id=0,
        slot_index=2,
        slot_count=2,
        strategy_ids=["strategy-2", "strategy-3"],
        previous_receipt_sha256=first_sha,
    )

    receipts, manifest = _checkpoint_receipts(
        tmp_path,
        worker_ids=[0],
        checkpoint_rows=policy,
        assignments=assignments,
    )
    assert len(receipts) == 2
    assert [item["slot_index"] for item in manifest] == [1, 2]

    second_receipt_path = tmp_path / artifacts[1] / "receipt.json"
    second_receipt = json.loads(second_receipt_path.read_text("utf-8"))
    second_receipt["previous_checkpoint_receipt_sha256"] = "f" * 64
    second_receipt_path.write_text(
        json.dumps(second_receipt, sort_keys=True) + "\n",
        "utf-8",
    )
    with pytest.raises(SystemExit, match="REDUCTION_CHECKPOINT_CHAIN_INVALID"):
        _checkpoint_receipts(
            tmp_path,
            worker_ids=[0],
            checkpoint_rows=policy,
            assignments=assignments,
        )


def test_reduction_node_binds_exact_checkpoint_policy_hash() -> None:
    artifacts = [f"checkpoint-{slot}" for slot in range(1, 9)]
    descriptor_sha256 = canonical_sha256(
        {
            "schema_version": "1",
            "artifacts": artifacts,
            "slot_count": 2,
        }
    )
    policy = {
        0: {
            "worker_id": 0,
            "checkpoint_slot_count": 2,
            "checkpoint_slot_artifacts": artifacts,
            "checkpoint_slot_manifest_sha256": descriptor_sha256,
        }
    }
    node = {
        "direct_children": [
            {
                "child_id": "worker:000",
                "artifact_ids": artifacts[:2],
                "descriptor_sha256": descriptor_sha256,
            }
        ]
    }

    _validate_node_checkpoint_bindings(
        node,
        worker_ids=[0],
        checkpoint_rows=policy,
    )
    node["direct_children"][0]["descriptor_sha256"] = "f" * 64
    with pytest.raises(
        SystemExit,
        match="REDUCTION_NODE_CHILD_BINDING_INVALID",
    ):
        _validate_node_checkpoint_bindings(
            node,
            worker_ids=[0],
            checkpoint_rows=policy,
        )
