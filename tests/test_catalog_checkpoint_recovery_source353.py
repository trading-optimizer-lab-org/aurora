from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import TypedDict, cast

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_source as source
from tests import test_catalog_checkpoint_recovery_source as legacy


class SourceFixture(TypedDict):
    sealed_plan: Path
    checkpoint_root: Path
    bindings: dict[str, str]
    science: str
    catalog: str
    worker_ids: tuple[int, ...]
    strategy_ids: tuple[str, ...]
    plan_receipt: dict[str, object]


def _checkpoint_name(worker_id: int, slot_index: int) -> str:
    return (
        f"catalog-checkpoint-{legacy.EXECUTION_PLAN_SHA256[:16]}-"
        f"g{worker_id // 24:02d}-w{worker_id:03d}-s{slot_index:02d}"
    )


def _bind_constructor_checkpoint_namespace(fixture: SourceFixture) -> None:
    sealed_plan = fixture["sealed_plan"]
    checkpoint_root = fixture["checkpoint_root"]

    for worker_id in legacy.WORKER_IDS:
        for slot_index in range(1, legacy.SLOT_COUNT + 1):
            old_name = f"checkpoint-worker-{worker_id:03d}-slot-{slot_index:02d}"
            old_root = checkpoint_root / old_name
            if old_root.is_dir():
                old_root.rename(checkpoint_root / _checkpoint_name(worker_id, slot_index))

    matrix_path = sealed_plan / "recipe_matrix_a.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    for row in matrix["include"]:
        worker_id = row["worker_id"]
        descriptor_path = (
            sealed_plan
            / "payload_artifacts"
            / f"descriptor-{worker_id:03d}"
            / "recipe"
            / f"worker-{worker_id:03d}.json"
        )
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        artifacts = tuple(_checkpoint_name(worker_id, slot) for slot in range(1, 9))
        descriptor["checkpoint_slot_artifacts"] = artifacts
        descriptor["checkpoint_slot_manifest_sha256"] = canonical_sha256(
            {
                "schema_version": "1",
                "artifacts": artifacts,
                "slot_count": legacy.SLOT_COUNT,
            }
        )
        legacy._write_json(descriptor_path, descriptor)
        row["descriptor_sha256"] = hashlib.sha256(descriptor_path.read_bytes()).hexdigest()
    legacy._write_json(matrix_path, matrix)

    policy_path = sealed_plan / "checkpoint_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    for row in policy["workers"]:
        worker_id = row["worker_id"]
        artifacts = tuple(_checkpoint_name(worker_id, slot) for slot in range(1, 9))
        row["checkpoint_slot_artifacts"] = artifacts
        row["checkpoint_slot_manifest_sha256"] = canonical_sha256(
            {
                "schema_version": "1",
                "artifacts": artifacts,
                "slot_count": legacy.SLOT_COUNT,
            }
        )
    policy_identity = {key: value for key, value in policy.items() if key != "content_sha256"}
    policy["content_sha256"] = canonical_sha256(policy_identity)
    legacy._write_json(policy_path, policy)


def _build_source353_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SourceFixture:
    monkeypatch.setattr(legacy, "RECOVERY_WORKER_IDS", tuple(range(60)))
    monkeypatch.setattr(legacy, "SLOT_COUNT", 2)
    fixture = cast(SourceFixture, legacy._build_fixture(tmp_path, monkeypatch))
    _bind_constructor_checkpoint_namespace(fixture)
    return fixture


def _verify_source353(
    fixture: SourceFixture,
) -> source.ValidatedCheckpointRecoverySource:
    return source.verify_checkpoint_recovery_source(
        fixture["sealed_plan"],
        fixture["checkpoint_root"],
        fixture["bindings"],
        fixture["science"],
        fixture["catalog"],
        fixture["strategy_ids"],
        fixture["worker_ids"],
        checkpoint_slot_count=2,
    )


def test_source353_validates_all_60_workers_with_two_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_source353_fixture(tmp_path, monkeypatch)

    result = _verify_source353(fixture)

    assert result.worker_ids == tuple(range(60))
    assert result.checkpoint_count == 120
    assert result.resume_index.physical_result_count == 240
    assert result.resume_index.duplicate_result_count == 0
    assert len(result.recovery_block_ids) == 120


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "tamper"])
def test_source353_rejects_incomplete_or_untrusted_checkpoint_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    fixture = _build_source353_fixture(tmp_path, monkeypatch)
    checkpoint_root = fixture["checkpoint_root"]
    first = checkpoint_root / _checkpoint_name(0, 1)

    if mutation == "missing":
        shutil.rmtree(checkpoint_root / _checkpoint_name(0, 2))
    elif mutation == "duplicate":
        shutil.copytree(first, checkpoint_root / _checkpoint_name(0, 3))
    elif mutation == "foreign":
        shutil.copytree(
            first,
            checkpoint_root / "catalog-checkpoint-0000000000000000-g00-w000-s01",
        )
    else:
        receipt_path = first / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["checkpoint_slot_count"] = 4
        legacy._write_json(receipt_path, receipt)

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_"):
        _verify_source353(fixture)


def test_default_source_contract_still_validates_30_selected_workers_and_four_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = legacy._build_fixture(tmp_path, monkeypatch)

    result = legacy._verify(fixture)

    assert result.worker_ids == tuple(range(30))
    assert result.checkpoint_count == 120
