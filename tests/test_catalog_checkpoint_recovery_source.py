from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_recovery_blocks import build_recovery_blocks
from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_source as source


WORKER_IDS = tuple(range(60))
RECOVERY_WORKER_IDS = tuple(range(30))
SLOT_COUNT = 4
CATALOG_SHA256 = "b" * 64
SCIENCE_DOCUMENT = {
    "catalog_manifest_sha256": CATALOG_SHA256,
    "data_snapshot_sha256": "c" * 64,
    "evaluator_sha256": "d" * 64,
    "locked_opened": False,
    "numeric_profile": "e" * 64,
    "train_end": "2010-12-31",
    "validation_opened": False,
}
SCIENCE_SHA256 = canonical_sha256(SCIENCE_DOCUMENT)
AUTHORITY_ID = "authority-1"
CAMPAIGN_ID = "campaign-1"
EXECUTION_PLAN_SHA256 = "f" * 64


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(payload))


def _slot_artifacts(worker_id: int) -> tuple[str, ...]:
    return tuple(f"checkpoint-worker-{worker_id:03d}-slot-{slot:02d}" for slot in range(1, 9))


def _strategy_ids(worker_id: int) -> tuple[str, ...]:
    return tuple(f"strategy-{worker_id:03d}-{index:02d}" for index in range(4))


def _slot_partition(ids: tuple[str, ...], slot_index: int) -> tuple[str, ...]:
    return ids[len(ids) * (slot_index - 1) // SLOT_COUNT : len(ids) * slot_index // SLOT_COUNT]


def _build_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    sealed_plan = tmp_path / "sealed-plan"
    checkpoint_root = tmp_path / "checkpoints"
    sealed_plan.mkdir()
    checkpoint_root.mkdir()

    assignments = {worker_id: _strategy_ids(worker_id) for worker_id in WORKER_IDS}
    all_strategy_ids = tuple(strategy_id for ids in assignments.values() for strategy_id in ids)
    work_manifest_identity = {
        "schema_version": "1",
        "all_strategy_ids": all_strategy_ids,
        "cached_strategy_ids": (),
        "pending_strategy_ids": all_strategy_ids,
        "active_workers": 60,
        "validation_opened": False,
        "locked_opened": False,
    }
    work_manifest = {
        **work_manifest_identity,
        "manifest_sha256": canonical_sha256(work_manifest_identity),
    }
    _write_json(sealed_plan / "resume_work_manifest.json", work_manifest)
    _write_json(
        sealed_plan / "resolved_contract.json",
        {"schema_version": "1", "science": SCIENCE_DOCUMENT},
    )
    run_plan = {
        "schema_version": "1",
        "workers": 60,
        "active_workers": 60,
        "component_workers": 60,
        "component_processes_per_worker": 4,
        "processes_per_worker": 1,
        "matrices": [list(WORKER_IDS)],
        "work_manifest_sha256": work_manifest["manifest_sha256"],
        "pending_recipe_count": len(all_strategy_ids),
        "cached_recipe_count": 0,
        "validation_opened": False,
        "locked_opened": False,
    }
    _write_json(sealed_plan / "run_plan.json", run_plan)

    worker_policy_rows: list[dict[str, object]] = []
    recovery_assignments: list[dict[str, object]] = []
    descriptor_rows: list[dict[str, object]] = []
    for worker_id in WORKER_IDS:
        ids = assignments[worker_id]
        artifacts = _slot_artifacts(worker_id)
        checkpoint_manifest_sha256 = canonical_sha256(
            {"schema_version": "1", "artifacts": artifacts, "slot_count": SLOT_COUNT}
        )
        worker_policy_rows.append(
            {
                "worker_id": worker_id,
                "checkpoint_slot_count": SLOT_COUNT,
                "checkpoint_slot_artifacts": artifacts,
                "checkpoint_slot_manifest_sha256": checkpoint_manifest_sha256,
            }
        )
        recovery_assignments.append(
            {"worker_id": worker_id, "checkpoint_slot_count": SLOT_COUNT, "strategy_ids": ids}
        )

        assignment_artifact = f"assignment-{worker_id:03d}"
        assignment_member = f"recipe/worker-{worker_id:03d}.json"
        assignment_identity = {
            "schema_version": "1",
            "worker_id": worker_id,
            "strategy_ids": ids,
        }
        assignment = {
            **assignment_identity,
            "expected_strategy_manifest_sha256": canonical_sha256(assignment_identity),
        }
        assignment_path = sealed_plan / "payload_artifacts" / assignment_artifact / assignment_member
        _write_json(assignment_path, assignment)
        descriptor = {
            "worker_id": worker_id,
            "attempt_id": f"{AUTHORITY_ID}:worker:{worker_id:03d}:attempt:1",
            "assignment_artifact": assignment_artifact,
            "assignment_member": assignment_member,
            "assignment_sha256": hashlib.sha256(assignment_path.read_bytes()).hexdigest(),
            "data_partition_artifacts": ("data",),
            "data_partition_manifest_sha256": "1" * 64,
            "component_bundle_artifacts": ("components",),
            "component_bundle_manifest_sha256": "2" * 64,
            "prior_checkpoint_chain_artifact": "",
            "checkpoint_slot_artifacts": artifacts,
            "checkpoint_slot_manifest_sha256": checkpoint_manifest_sha256,
            "checkpoint_slot_count": SLOT_COUNT,
            "expected_strategy_count": len(ids),
            "expected_strategy_manifest_sha256": assignment["expected_strategy_manifest_sha256"],
        }
        descriptor_path = (
            sealed_plan
            / "payload_artifacts"
            / f"descriptor-{worker_id:03d}"
            / f"recipe/worker-{worker_id:03d}.json"
        )
        _write_json(descriptor_path, descriptor)
        descriptor_rows.append(
            {
                "worker_id": worker_id,
                "descriptor_bundle_artifact": f"descriptor-{worker_id:03d}",
                "descriptor_member": f"recipe/worker-{worker_id:03d}.json",
                "descriptor_sha256": hashlib.sha256(descriptor_path.read_bytes()).hexdigest(),
            }
        )

    blocks = build_recovery_blocks(
        science_sha256=SCIENCE_SHA256,
        runtime_identity_sha256="3" * 64,
        prepared_input_identity_sha256="4" * 64,
        assignments=recovery_assignments,
    )
    policy_identity = {
        "schema_version": "1",
        "document_type": "checkpoint_policy",
        "authority_id": AUTHORITY_ID,
        "campaign_id": CAMPAIGN_ID,
        "science_sha256": SCIENCE_SHA256,
        "execution_plan_sha256": EXECUTION_PLAN_SHA256,
        "workers": worker_policy_rows,
        "recovery_blocks_v1": blocks,
    }
    policy = {**policy_identity, "content_sha256": canonical_sha256(policy_identity)}
    _write_json(sealed_plan / "checkpoint_policy.json", policy)

    for worker_id in RECOVERY_WORKER_IDS:
        ids = assignments[worker_id]
        previous_receipt_sha256 = "0" * 64
        for slot_index in range(1, SLOT_COUNT + 1):
            artifact_name = _slot_artifacts(worker_id)[slot_index - 1]
            artifact_root = checkpoint_root / artifact_name
            artifact_root.mkdir()
            slot_ids = _slot_partition(ids, slot_index)
            result_rows = [
                {
                    "strategy_id": strategy_id,
                    "result_json": json.dumps(
                        {
                            "fitness": 1.0,
                            "info": {"validation_opened": False, "locked_opened": False},
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
                for strategy_id in slot_ids
            ]
            pq.write_table(
                pa.Table.from_pylist(
                    result_rows,
                    schema=pa.schema([("strategy_id", pa.string()), ("result_json", pa.string())]),
                ),
                artifact_root / "results.parquet",
            )
            result_sha256 = hashlib.sha256((artifact_root / "results.parquet").read_bytes()).hexdigest()
            block = next(
                item
                for item in blocks["blocks"]
                if item["worker_id"] == worker_id and item["slot_index"] == slot_index
            )
            attempt_id = f"{AUTHORITY_ID}:worker:{worker_id:03d}:attempt:1"
            receipt = {
                "schema_version": 1,
                "attempt_id": attempt_id,
                "science_identity_sha256": SCIENCE_SHA256,
                "catalog_manifest_sha256": CATALOG_SHA256,
                "work_manifest_sha256": work_manifest["manifest_sha256"],
                "shard_index": worker_id,
                "total_shards": 60,
                "checkpoint_slot_count": SLOT_COUNT,
                "checkpoint_slot_index": slot_index,
                "strategy_count": len(slot_ids),
                "result_sha256": result_sha256,
                "recovery_block_id": block["block_id"],
                "previous_checkpoint_receipt_sha256": previous_receipt_sha256,
                "validation_opened": False,
                "locked_opened": False,
            }
            _write_json(artifact_root / "receipt.json", receipt)
            receipt_sha256 = hashlib.sha256((artifact_root / "receipt.json").read_bytes()).hexdigest()
            attempt = {
                "schema_version": "1",
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "checkpoint_slot_count": SLOT_COUNT,
                "checkpoint_slot_index": slot_index,
                "strategy_ids": slot_ids,
                "previous_checkpoint_receipt_sha256": previous_receipt_sha256,
                "result_sha256": result_sha256,
                "receipt_sha256": receipt_sha256,
                "recovery_block_id": block["block_id"],
                "validation_opened": False,
                "locked_opened": False,
            }
            _write_json(artifact_root / "shard_attempt_manifest.json", attempt)
            chain_identity = {
                "schema_version": "1",
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "slot_count": SLOT_COUNT,
                "slot_index": slot_index,
                "completed_strategy_ids": slot_ids,
                "previous_receipt_sha256": previous_receipt_sha256,
                "current_receipt_sha256": receipt_sha256,
                "recovery_block_id": block["block_id"],
                "validation_opened": False,
                "locked_opened": False,
            }
            _write_json(
                artifact_root / "checkpoint_chain_manifest.json",
                {**chain_identity, "chain_sha256": canonical_sha256(chain_identity)},
            )
            previous_receipt_sha256 = receipt_sha256

    _write_json(sealed_plan / "recipe_matrix_a.json", {"include": descriptor_rows})
    _write_json(sealed_plan / "recipe_matrix_b.json", {"include": []})
    _write_json(sealed_plan / "recipe_matrix_c.json", {"include": []})

    bindings = {
        "request_sha256": "a" * 64,
        "decision_sha256": "b" * 64,
        "protected_commit_sha": "c" * 40,
        "authority_id": AUTHORITY_ID,
        "campaign_id": CAMPAIGN_ID,
        "execution_plan_sha256": EXECUTION_PLAN_SHA256,
    }
    plan_receipt_identity = {
        **bindings,
        "schema_version": "1",
        "science_sha256": SCIENCE_SHA256,
        "active_recipe_workers": 60,
        "content_manifest": [],
        "content_manifest_sha256": "6" * 64,
        "validation_opened": False,
        "locked_opened": False,
    }
    plan_receipt = {
        **plan_receipt_identity,
        "receipt_sha256": canonical_sha256(plan_receipt_identity),
    }
    monkeypatch.setattr(
        source,
        "verify_sealed_global_reuse_execution_plan",
        lambda root, *, expected_bindings: plan_receipt,
    )
    return {
        "sealed_plan": sealed_plan,
        "checkpoint_root": checkpoint_root,
        "bindings": bindings,
        "science": SCIENCE_SHA256,
        "catalog": CATALOG_SHA256,
        "worker_ids": RECOVERY_WORKER_IDS,
        "strategy_ids": tuple(
            strategy_id
            for worker_id in RECOVERY_WORKER_IDS
            for strategy_id in assignments[worker_id]
        ),
        "plan_receipt": plan_receipt,
    }


def _verify(fixture: dict[str, Any]) -> source.ValidatedCheckpointRecoverySource:
    return source.verify_checkpoint_recovery_source(
        fixture["sealed_plan"],
        fixture["checkpoint_root"],
        fixture["bindings"],
        fixture["science"],
        fixture["catalog"],
        fixture["strategy_ids"],
        fixture["worker_ids"],
    )


def test_valid_source_returns_immutable_exact_resume_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)

    result = _verify(fixture)

    assert isinstance(result, source.ValidatedCheckpointRecoverySource)
    assert result.worker_ids == fixture["worker_ids"]
    assert result.strategy_ids == tuple(sorted(fixture["strategy_ids"]))
    assert result.checkpoint_count == 120
    assert result.resume_index.physical_result_count == 120
    assert result.resume_index.duplicate_result_count == 0
    assert result.plan_receipt["receipt_sha256"] == fixture["plan_receipt"]["receipt_sha256"]
    assert len(result.recovery_block_ids) == 120
    with pytest.raises((TypeError, ValueError)):
        result.worker_ids = ()
    with pytest.raises(TypeError):
        result.plan_receipt["receipt_sha256"] = "0" * 64


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_checkpoint_inventory_is_exact_and_never_accepts_a_partial_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    target = fixture["checkpoint_root"] / "checkpoint-worker-000-slot-04"
    if mutation == "missing":
        shutil.rmtree(target)
    else:
        (fixture["checkpoint_root"] / "unexpected-checkpoint").mkdir()

    with pytest.raises(ValueError, match="ARTIFACT_SET_INVALID"):
        _verify(fixture)


@pytest.mark.parametrize("filename,field", [
    ("shard_attempt_manifest.json", "strategy_ids"),
    ("checkpoint_chain_manifest.json", "completed_strategy_ids"),
])
def test_checkpoint_strategy_ids_require_a_json_array(tmp_path, monkeypatch, filename, field):
    fixture = _build_fixture(tmp_path, monkeypatch)
    path = fixture["checkpoint_root"] / "checkpoint-worker-000-slot-01" / filename
    document = json.loads(path.read_text(encoding="utf-8"))
    document[field] = 1
    _write_json(path, document)
    with pytest.raises(ValueError, match="SLOT_ASSIGNMENT_INVALID"):
        _verify(fixture)


def test_descriptor_artifact_must_be_a_single_safe_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    matrix_path = fixture["sealed_plan"] / "recipe_matrix_a.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["include"][0]["descriptor_bundle_artifact"] = "../descriptor-000"
    _write_json(matrix_path, matrix)

    with pytest.raises(ValueError, match="DESCRIPTOR_INVALID"):
        _verify(fixture)


def test_assignment_artifact_must_be_a_single_safe_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    descriptor_path = (
        fixture["sealed_plan"]
        / "payload_artifacts"
        / "descriptor-000"
        / "recipe"
        / "worker-000.json"
    )
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["assignment_artifact"] = "../assignment-000"
    _write_json(descriptor_path, descriptor)
    matrix_path = fixture["sealed_plan"] / "recipe_matrix_a.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["include"][0]["descriptor_sha256"] = hashlib.sha256(
        descriptor_path.read_bytes()
    ).hexdigest()
    _write_json(matrix_path, matrix)

    with pytest.raises(ValueError, match="ASSIGNMENT_INVALID"):
        _verify(fixture)


def test_descriptor_artifact_symlink_ancestor_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    descriptor_root = (
        fixture["sealed_plan"] / "payload_artifacts" / "descriptor-000"
    )
    symlink_target = tmp_path / "outside-descriptor-000"
    shutil.copytree(descriptor_root, symlink_target)
    shutil.rmtree(descriptor_root)
    try:
        descriptor_root.symlink_to(symlink_target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink no disponible en este entorno: {exc}")

    with pytest.raises(ValueError, match="DESCRIPTOR_INVALID"):
        _verify(fixture)


def test_source_assignment_ids_must_match_each_checkpoint_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    attempt_path = (
        fixture["checkpoint_root"] / "checkpoint-worker-000-slot-01" / "shard_attempt_manifest.json"
    )
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    attempt["strategy_ids"] = ["strategy-001-00"]
    attempt_path.write_bytes(_json_bytes(attempt))

    with pytest.raises(ValueError, match="SLOT_ASSIGNMENT_INVALID"):
        _verify(fixture)


def test_result_info_boundaries_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path, monkeypatch)
    artifact_root = fixture["checkpoint_root"] / "checkpoint-worker-000-slot-01"
    result_path = artifact_root / "results.parquet"
    table = pq.read_table(result_path)
    row = table.to_pylist()[0]
    result_payload = json.loads(row["result_json"])
    result_payload["info"]["validation_opened"] = True
    row["result_json"] = json.dumps(result_payload, sort_keys=True, separators=(",", ":"))
    pq.write_table(
        pa.Table.from_pylist([row], schema=table.schema),
        result_path,
    )
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    receipt_path = artifact_root / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["result_sha256"] = result_sha256
    _write_json(receipt_path, receipt)
    receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    attempt_path = artifact_root / "shard_attempt_manifest.json"
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    attempt["result_sha256"] = result_sha256
    attempt["receipt_sha256"] = receipt_sha256
    _write_json(attempt_path, attempt)
    chain_path = artifact_root / "checkpoint_chain_manifest.json"
    chain = json.loads(chain_path.read_text(encoding="utf-8"))
    chain["current_receipt_sha256"] = receipt_sha256
    chain_identity = {key: value for key, value in chain.items() if key != "chain_sha256"}
    chain["chain_sha256"] = canonical_sha256(chain_identity)
    _write_json(chain_path, chain)
    previous_receipt_sha256 = receipt_sha256
    for slot_index in range(2, SLOT_COUNT + 1):
        next_root = fixture["checkpoint_root"] / f"checkpoint-worker-000-slot-{slot_index:02d}"
        next_receipt_path = next_root / "receipt.json"
        next_receipt = json.loads(next_receipt_path.read_text(encoding="utf-8"))
        next_receipt["previous_checkpoint_receipt_sha256"] = previous_receipt_sha256
        _write_json(next_receipt_path, next_receipt)
        next_receipt_sha256 = hashlib.sha256(next_receipt_path.read_bytes()).hexdigest()
        next_attempt_path = next_root / "shard_attempt_manifest.json"
        next_attempt = json.loads(next_attempt_path.read_text(encoding="utf-8"))
        next_attempt["previous_checkpoint_receipt_sha256"] = previous_receipt_sha256
        next_attempt["receipt_sha256"] = next_receipt_sha256
        _write_json(next_attempt_path, next_attempt)
        next_chain_path = next_root / "checkpoint_chain_manifest.json"
        next_chain = json.loads(next_chain_path.read_text(encoding="utf-8"))
        next_chain["previous_receipt_sha256"] = previous_receipt_sha256
        next_chain["current_receipt_sha256"] = next_receipt_sha256
        next_chain_identity = {key: value for key, value in next_chain.items() if key != "chain_sha256"}
        next_chain["chain_sha256"] = canonical_sha256(next_chain_identity)
        _write_json(next_chain_path, next_chain)
        previous_receipt_sha256 = next_receipt_sha256

    with pytest.raises(ValueError, match="RESULT_BOUNDARY_INVALID"):
        _verify(fixture)
