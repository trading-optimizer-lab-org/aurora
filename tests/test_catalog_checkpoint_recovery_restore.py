from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    canonical_cached_strategy_ids_sha256,
    load_checkpoint_recovery_profile,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import (
    CheckpointRecoveryOwnerAuthenticationV1,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubCollection,
    CatalogStableInventory,
)
from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_restore as restore
from tests.test_catalog_checkpoint_recovery_profile import _root_with_profile


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "trading-optimizer-lab-org/aurora"


def _artifact_row(artifact_id: int, name: str) -> dict[str, object]:
    return {
        "id": artifact_id,
        "name": name,
        "expired": False,
        "size_in_bytes": 4,
        "digest": "sha256:" + "a" * 64,
        "workflow_run": {"id": 17},
    }


class _InventoryClient:
    repository = REPOSITORY

    def __init__(self, inventory: object) -> None:
        self.inventory = inventory
        self.calls: list[str] = []

    def stable_paginated(self, path: str, *, root: str) -> object:
        self.calls.append(path)
        assert root == "artifacts"
        return self.inventory

    def get_json(self, path: str) -> tuple[object, object]:
        raise AssertionError(f"Unexpected GET: {path}")


@pytest.mark.parametrize("missing", ["get_json", "stable_paginated", "repository"])
def test_source_protocol_rejects_missing_members(missing: str) -> None:
    members = dict(repository=REPOSITORY, get_json=lambda path: ({}, None),
                   stable_paginated=lambda path, *, root: object())
    del members[missing]
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_FETCH_INVALID"):
        restore._resolve_source(REPOSITORY, SimpleNamespace(**members))


def test_source_protocol_and_delegation_preserve_evidence() -> None:
    evidence = object()
    client = _InventoryClient(evidence)
    assert restore._resolve_source(REPOSITORY, client) is client
    adapter = restore.RunArtifactInventorySubsetClient(client, owner_run_id=17)
    assert adapter.stable_paginated("/another-run/artifacts", root="artifacts") is evidence
    assert adapter.inventory_calls == 0


def test_name_subsets_share_one_complete_authentic_inventory() -> None:
    collection = CatalogGitHubCollection(
        rows=(
            _artifact_row(1, "plan"),
            _artifact_row(2, "checkpoint-a"),
            _artifact_row(3, "checkpoint-b"),
        ),
        ordered_ids=(1, 2, 3),
        pages=(),
        complete=True,
        collection_sha256="c" * 64,
    )
    inventory = CatalogStableInventory(
        collection=collection,
        attempt=2,
        stable=True,
        observed_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        snapshot_sha256="s" * 64,
    )
    client = _InventoryClient(inventory)
    adapter = restore.RunArtifactInventorySubsetClient(client, owner_run_id=17)

    first = adapter.stable_paginated(
        "/repos/trading-optimizer-lab-org/aurora/actions/runs/17/artifacts?name=plan",
        root="artifacts",
    )
    second = adapter.stable_paginated(
        "/repos/trading-optimizer-lab-org/aurora/actions/runs/17/artifacts?name=checkpoint-a",
        root="artifacts",
    )

    assert len(client.calls) == 1
    assert isinstance(first, restore.ArtifactInventorySubsetEvidence)
    assert isinstance(second, restore.ArtifactInventorySubsetEvidence)
    assert isinstance(first.collection, CatalogGitHubCollection)
    assert isinstance(second.collection, CatalogGitHubCollection)
    assert first.source_inventory is inventory
    assert first.source_collection_sha256 == collection.collection_sha256
    assert first.collection.collection_sha256 == collection.collection_sha256
    assert [row["name"] for row in first.collection.rows] == ["plan"]
    assert [row["name"] for row in second.collection.rows] == ["checkpoint-a"]
    assert adapter.inventory_calls == 1


def test_incomplete_global_inventory_is_not_hidden_by_a_name_filter() -> None:
    collection = SimpleNamespace(rows=(_artifact_row(1, "plan"),), complete=False)
    client = _InventoryClient(SimpleNamespace(stable=True, collection=collection))
    adapter = restore.RunArtifactInventorySubsetClient(client, owner_run_id=17)

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_INVENTORY_INCOMPLETE"):
        adapter.stable_paginated(
            "/repos/trading-optimizer-lab-org/aurora/actions/runs/17/artifacts?name=plan",
            root="artifacts",
        )
    assert len(client.calls) == 1


@pytest.mark.parametrize("kind", ["missing", "extra"])
def test_profile_pin_cardinality_fails_closed_before_authentication(
    tmp_path: Path, kind: str
) -> None:
    profile = load_checkpoint_recovery_profile(
        _root_with_profile(tmp_path), "sp500-optimized-catalog-v1", 8
    )
    assert profile is not None
    artifacts = profile.artifacts[:-1] if kind == "missing" else profile.artifacts + (profile.artifacts[-1],)
    candidate = profile.model_copy(update={"artifacts": artifacts})

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_PROFILE_ARTIFACTS_INVALID"):
        restore._profile_artifacts(candidate)


def test_profile_artifact_digest_size_and_metadata_pin_are_exact(tmp_path: Path) -> None:
    profile = load_checkpoint_recovery_profile(
        _root_with_profile(tmp_path), "sp500-optimized-catalog-v1", 8
    )
    assert profile is not None
    artifact = profile.artifacts[0]

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_PROFILE_MISMATCH"):
        restore._profile_artifact_metadata(
            {
                "id": artifact.artifact_id,
                "name": artifact.artifact_name,
                "size_in_bytes": artifact.size_bytes,
            },
            artifact,
        )
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_PROFILE_MISMATCH"):
        restore._profile_artifact_metadata(
            {
                "id": artifact.artifact_id,
                "name": artifact.artifact_name,
                "digest": "sha256:" + "0" * 64,
                "size_in_bytes": artifact.size_bytes + 1,
            },
            artifact,
        )
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_PROFILE_MISMATCH"):
        restore._profile_artifact_metadata(
            {
                "id": artifact.artifact_id,
                "name": artifact.artifact_name,
                "digest": artifact.digest,
                "size_in_bytes": artifact.size_bytes,
                "publisher_job_name": "wrong-publisher",
            },
            artifact,
        )


def test_publisher_job_and_step_must_be_unique_completed_success() -> None:
    owner = SimpleNamespace(
        jobs=(
            {
                "name": "publisher",
                "steps": ({"name": "publish", "status": "completed", "conclusion": "failure"},),
            },
        )
    )
    artifact = SimpleNamespace(publisher_job_name="publisher", publish_step_name="publish")

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_PUBLISHER_INVALID"):
        restore._validate_publisher(owner, artifact)


def test_cached_partition_hash_and_counts_are_bound_to_the_source_plan(tmp_path: Path, monkeypatch) -> None:
    from tests.test_catalog_checkpoint_recovery_source import _build_fixture

    fixture = _build_fixture(tmp_path, monkeypatch)
    plan = fixture["sealed_plan"]
    profile = SimpleNamespace(
        science_sha256=fixture["science"], worker_ids=fixture["worker_ids"],
        expected_total_count=240, expected_result_count=120,
        cached_strategy_ids_sha256=canonical_cached_strategy_ids_sha256(fixture["strategy_ids"]),
    )
    work = json.loads((plan / "resume_work_manifest.json").read_text())
    assert work["cached_strategy_ids"] == []
    assert len(work["pending_strategy_ids"]) == 240
    assert restore._derive_expected_pending_ids(plan, profile) == fixture["strategy_ids"]
    for field, value in (("expected_total_count", 241), ("expected_result_count", 119),
                         ("cached_strategy_ids_sha256", "0" * 64)):
        changed = SimpleNamespace(**{**vars(profile), field: value})
        with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_PARTITION_INVALID"):
            restore._derive_expected_pending_ids(plan, changed)




def _zip_bytes(member: str, payload: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, payload)
    return stream.getvalue()


def test_restore_uses_injected_transport_and_publishes_only_after_local_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restore, "CHECKPOINT_RECOVERY_WORKER_COUNT", 1)
    monkeypatch.setattr(restore, "CHECKPOINT_RECOVERY_CHECKPOINT_COUNT", 1)
    monkeypatch.setattr(restore, "CHECKPOINT_RECOVERY_SLOT_COUNT", 1)

    plan_raw = _zip_bytes("plan.json", b"plan")
    checkpoint_raw = _zip_bytes("checkpoint.json", b"checkpoint")

    plan = SimpleNamespace(
        role="plan",
        artifact_id=101,
        artifact_name="plan",
        digest="sha256:" + hashlib.sha256(plan_raw).hexdigest(),
        size_bytes=len(plan_raw),
        publisher_job_name="plan-publisher",
        publish_step_name="Publish plan",
        worker_id=None,
        slot_index=None,
    )
    checkpoint = SimpleNamespace(
        role="checkpoint",
        artifact_id=102,
        artifact_name="checkpoint",
        digest="sha256:" + hashlib.sha256(checkpoint_raw).hexdigest(),
        size_bytes=len(checkpoint_raw),
        publisher_job_name="checkpoint-publisher",
        publish_step_name="Publish checkpoint",
        worker_id=0,
        slot_index=1,
    )
    profile = SimpleNamespace(
        profile_sha256="p" * 64,
        campaign_key="sp500-optimized-catalog-v1",
        target_generation=8,
        source_run_id=17,
        source_run_attempt=1,
        source_protected_commit_sha="c" * 40,
        source_plan_bindings={"authority_id": "a", "campaign_id": "c"},
        source_plan_receipt_sha256="r" * 64,
        science_sha256="s" * 64,
        catalog_manifest_sha256="m" * 64,
        worker_ids=(0,),
        expected_total_count=3,
        expected_result_count=1,
        cached_strategy_ids_sha256="h" * 64,
        artifacts=(plan, checkpoint),
    )
    proof = CheckpointRecoveryOwnerProofV1(
        profile_sha256=profile.profile_sha256,
        campaign_key=profile.campaign_key,
        target_generation=8,
        source_request_sha256="q" * 64,
        source_issue_number=339,
        source_run_id=17,
        source_run_attempt=1,
        source_protected_commit_sha=profile.source_protected_commit_sha,
        source_decision_sha256="d" * 64,
        source_finalizer_job_id=9001,
    )
    owner = FastGateOwnerEvidence(
        run_id=17,
        run={"id": 17, "run_attempt": 1, "head_sha": profile.source_protected_commit_sha},
        decision=SimpleNamespace(),
        jobs=(
            {"name": "plan-publisher", "steps": ({"name": "Publish plan", "status": "completed", "conclusion": "success"},)},
            {"name": "checkpoint-publisher", "steps": ({"name": "Publish checkpoint", "status": "completed", "conclusion": "success"},)},
        ),
    )
    auth_result = CheckpointRecoveryOwnerAuthenticationV1(owner=owner, proof=proof)

    class Fetch:
        repository = REPOSITORY

        def get_json(self, path: str) -> tuple[object, object]:
            raise AssertionError(f"unexpected injected GET: {path}")

        def stable_paginated(self, path: str, *, root: str) -> object:
            raise AssertionError(f"unexpected injected inventory: {path}")

    def read_archive(*, artifact_name: str, **_: object) -> tuple[bytes, Mapping[str, object]]:
        raw = plan_raw if artifact_name == "plan" else checkpoint_raw
        artifact = plan if artifact_name == "plan" else checkpoint
        return raw, {
            "id": artifact.artifact_id,
            "name": artifact.artifact_name,
            "digest": artifact.digest,
            "size_in_bytes": artifact.size_bytes,
        }

    monkeypatch.setattr(restore, "validate_exact_checkpoint_profile", lambda root, value: profile)
    monkeypatch.setattr(restore, "authenticate_checkpoint_recovery_owner", lambda **_: auth_result)
    monkeypatch.setattr(restore, "verify_sealed_global_reuse_execution_plan",
                        lambda *args, **kwargs: {"receipt_sha256": profile.source_plan_receipt_sha256})
    monkeypatch.setattr(restore, "_derive_expected_pending_ids", lambda *args: ("pending",))
    monkeypatch.setattr(
        restore,
        "verify_checkpoint_recovery_source",
        lambda *args: SimpleNamespace(plan_receipt_sha256=profile.source_plan_receipt_sha256),
    )
    monkeypatch.setattr(restore, "read_owner_artifact_archive", read_archive)

    result = restore.restore_catalog_checkpoint_recovery(
        repo_root=tmp_path,
        repository=REPOSITORY,
        protected_commit_sha="e" * 40,
        profile=profile,
        output_dir=tmp_path / "restored",
        fetch_json=Fetch(),
        download_artifact=lambda _: b"unused",
    )

    assert result.profile is profile
    assert result.proof is proof
    assert result.source_plan_root.is_dir()
    assert result.checkpoint_root.is_dir()
    assert (result.source_plan_root / "plan.json").is_file()
    assert (result.checkpoint_root / "checkpoint" / "checkpoint.json").is_file()


@pytest.mark.parametrize("defect", [None, "missing", "duplicate", "digest", "size", "publisher", "expired"])
def test_real_owner_reader_shares_inventory_and_rejects_transport_defects(defect):
    from tests.test_catalog_reduction_recovery_artifact import _fixture
    raw, artifact, job, owner, _, inventory = _fixture()
    rows = [{**artifact, "id": i + 1, "name": f"checkpoint-{i}"} for i in range(121)]
    if defect == "missing":
        rows.pop()
    elif defect == "duplicate":
        rows.append({**rows[-1], "id": 999})
    elif defect == "digest":
        rows[-1]["digest"] = "sha256:" + "0" * 64
    elif defect == "size":
        rows[-1]["size_in_bytes"] += 1
    elif defect == "publisher":
        job["conclusion"] = "failure"
    elif defect == "expired":
        rows[-1]["expired"] = True
    inventory.collection.rows = tuple(rows)
    client = _InventoryClient(inventory)
    adapter = restore.RunArtifactInventorySubsetClient(client, owner_run_id=17)

    def read_all():
        for i in range(121):
            restore.read_owner_artifact_archive(
                client=adapter, owner=owner, artifact_name=f"checkpoint-{i}",
                publisher_job_name=job["name"], publish_step_name=job["steps"][0]["name"],
                download_archive=lambda _: raw,
            )
    if defect:
        with pytest.raises(ValueError, match="CATALOG_RECOVERY_ARTIFACT"):
            read_all()
    else:
        read_all()
    assert len(client.calls) == 1


def test_restore_real_source_full_plan_and_120_checkpoint_archives(tmp_path, monkeypatch):
    from tests.test_catalog_checkpoint_recovery_source import _build_fixture
    from tests.test_catalog_reduction_recovery_artifact import _fixture
    fixture = _build_fixture(tmp_path, monkeypatch)
    _, metadata, job, owner, _, inventory = _fixture()
    checkpoints = tuple(sorted(fixture["checkpoint_root"].iterdir()))
    artifacts, downloads, rows = [], {}, []
    for ordinal, tree in enumerate((fixture["sealed_plan"], *checkpoints), 1):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(tree.rglob("*")):
                if path.is_file():
                    archive.writestr(path.relative_to(tree).as_posix(), path.read_bytes())
        raw = stream.getvalue()
        pin = SimpleNamespace(
            role="plan" if ordinal == 1 else "checkpoint", artifact_id=ordinal,
            artifact_name=tree.name, digest="sha256:" + hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw), publisher_job_name=job["name"],
            publish_step_name=job["steps"][0]["name"],
            worker_id=None if ordinal == 1 else (ordinal - 2) // 4,
            slot_index=None if ordinal == 1 else (ordinal - 2) % 4 + 1,
        )
        artifacts.append(pin)
        downloads[ordinal] = raw
        rows.append({**metadata, "id": ordinal, "name": pin.artifact_name,
                     "size_in_bytes": len(raw), "digest": pin.digest})
    profile = SimpleNamespace(
        profile_sha256="a" * 64, source_run_id=17, source_run_attempt=1,
        target_generation=8,
        source_protected_commit_sha=owner.run["head_sha"],
        source_plan_bindings=fixture["bindings"],
        source_plan_receipt_sha256=fixture["plan_receipt"]["receipt_sha256"],
        science_sha256=fixture["science"], catalog_manifest_sha256=fixture["catalog"],
        worker_ids=fixture["worker_ids"], expected_total_count=240, expected_result_count=120,
        cached_strategy_ids_sha256=canonical_cached_strategy_ids_sha256(fixture["strategy_ids"]),
        artifacts=tuple(artifacts),
    )
    proof = CheckpointRecoveryOwnerProofV1(
        profile_sha256=profile.profile_sha256, campaign_key="sp500-optimized-catalog-v1",
        target_generation=8, source_request_sha256="a" * 64, source_issue_number=339,
        source_run_id=17, source_run_attempt=1,
        source_protected_commit_sha=owner.run["head_sha"],
        source_decision_sha256="b" * 64, source_finalizer_job_id=5,
    )
    inventory.collection.rows = tuple(rows)
    client = _InventoryClient(inventory)
    client.get_json = lambda _: pytest.fail("unexpected network")
    monkeypatch.setattr(restore, "validate_exact_checkpoint_profile", lambda *args: profile)
    monkeypatch.setattr(restore, "authenticate_checkpoint_recovery_owner",
                        lambda **kwargs: CheckpointRecoveryOwnerAuthenticationV1(owner, proof))
    def sealed(root, *, expected_bindings):
        assert expected_bindings == fixture["bindings"]
        assert json.loads((root / "resume_work_manifest.json").read_text())["cached_strategy_ids"] == []
        return fixture["plan_receipt"]
    monkeypatch.setattr(restore, "verify_sealed_global_reuse_execution_plan", sealed)
    result = restore.restore_catalog_checkpoint_recovery(
        repo_root=tmp_path, repository=REPOSITORY, protected_commit_sha="e" * 40,
        profile=profile, output_dir=tmp_path / "restored", fetch_json=client,
        download_artifact=downloads.__getitem__,
    )
    assert result.source_validation.checkpoint_count == 120
    assert result.source_validation.strategy_ids == tuple(sorted(fixture["strategy_ids"]))
    assert all(Path(item.source_path).is_file() for item in result.source_validation.resume_index.results)
    assert len(client.calls) == 1
    assert fixture["sealed_plan"].is_dir()
