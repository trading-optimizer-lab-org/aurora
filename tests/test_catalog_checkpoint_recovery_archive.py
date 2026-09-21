from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import (
    CheckpointRecoveryOwnerAuthenticationV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_binding import (
    build_checkpoint_recovery_binding,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    load_checkpoint_recovery_profile,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_source import (
    ValidatedCheckpointRecoverySource,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastLaunchDecisionV1,
    CatalogPreparationIdentityV1,
    CatalogPreparedReceiptV1,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence
from aurora.infra.sp500_megarun.catalog_prepared_artifact import (
    PreparedArtifactRestoreError,
    PreparedArtifactRestoreResult,
)
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    CatalogPreparedBundleManifestV1,
)
from aurora.infra.sp500_megarun.catalog_resume import (
    CatalogResumeIndexV1,
    ResumeResultV1,
)
from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_archive as archive


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "trading-optimizer-lab-org/aurora"
HISTORICAL_COMMIT = "d90ab8b63492c69a9727d9ce558a678907c15621"
PROTECTED_COMMIT = "3" * 40
ARCHIVE_CONFIG = ROOT / "config/catalog_checkpoint_recovery_archives_v1.json"


def _profile_root(tmp_path: Path) -> Path:
    config = tmp_path / "config"
    config.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "config/catalog_checkpoint_recovery_profiles_v1.json",
        config / "catalog_checkpoint_recovery_profiles_v1.json",
    )
    return tmp_path


def _identity() -> CatalogPreparationIdentityV1:
    return CatalogPreparationIdentityV1(
        schema_version="1",
        campaign_key="sp500-optimized-catalog-v1",
        engine_id="optimized_catalog_v1",
        protected_commit_sha=HISTORICAL_COMMIT,
        campaign_definition_sha256="1" * 64,
        scientific_contract_sha256="2" * 64,
        dependency_lock_sha256="3" * 64,
        optimization_policy_sha256="4" * 64,
        data_contract_sha256="5" * 64,
        feature_contract_sha256="6" * 64,
        catalog_manifest_sha256="7" * 64,
        selected_config_sha256="8" * 64,
    )


def _authenticated(profile) -> CheckpointRecoveryOwnerAuthenticationV1:
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED",
        reason_code="LAUNCH_REQUIRED",
        request_sha256=profile.source_request_sha256,
        submission_key_sha256="a" * 64,
        campaign_key=profile.campaign_key,
        prepared_receipt_sha256=None,
        selected_workers=30,
        launch_required=True,
        existing_run_id=None,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    job_id = 123456
    step_names = {
        "Fetch one bounded timing snapshot": "failure",
        "Create exactly one terminal receipt": "skipped",
        "Publish the terminal receipt before changing the issue": "skipped",
        "Write current authority edition": "skipped",
        "Publish current authority edition": "skipped",
        "Verify the terminal publication before releasing the campaign": "skipped",
        "Publish the terminal state and release the reservation": "skipped",
    }
    job = {
        "id": job_id,
        "run_id": profile.source_run_id,
        "run_attempt": profile.source_run_attempt,
        "head_sha": profile.source_protected_commit_sha,
        "status": "completed",
        "conclusion": "failure",
        "name": "finalize",
        "steps": tuple(
            {
                "name": name,
                "status": "completed",
                "conclusion": conclusion,
            }
            for name, conclusion in step_names.items()
        ),
    }
    owner = FastGateOwnerEvidence(
        run={
            "id": profile.source_run_id,
            "run_attempt": profile.source_run_attempt,
            "head_sha": profile.source_protected_commit_sha,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "failure",
        },
        run_id=profile.source_run_id,
        decision=decision,
        jobs=(job,),
    )
    proof = CheckpointRecoveryOwnerProofV1(
        profile_sha256=profile.profile_sha256,
        campaign_key=profile.campaign_key,
        target_generation=profile.target_generation,
        source_request_sha256=profile.source_request_sha256,
        source_issue_number=profile.source_issue_number,
        source_run_id=profile.source_run_id,
        source_run_attempt=profile.source_run_attempt,
        source_protected_commit_sha=profile.source_protected_commit_sha,
        source_decision_sha256=decision.decision_sha256,
        source_finalizer_job_id=job_id,
    )
    return CheckpointRecoveryOwnerAuthenticationV1(owner=owner, proof=proof)


def _prepared(identity: CatalogPreparationIdentityV1, raw: bytes) -> PreparedArtifactRestoreResult:
    receipt = CatalogPreparedReceiptV1.create(
        identity=identity,
        generated_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        runtime_identity_sha256="9" * 64,
        prepared_input_identity_sha256="a" * 64,
        component_store_manifest_sha256="b" * 64,
        execution_plan_template_sha256="c" * 64,
        required_cache_keys=("test-cache",),
        logical_recipe_count=37258,
        unique_component_count=1,
        qualified_worker_ceiling=30,
        production_dependency_smoke_passed=True,
        recipe_worker_build_allowed=False,
    )
    manifest = CatalogPreparedBundleManifestV1.create(
        preparation_key_sha256=identity.preparation_key_sha256,
        prepared_receipt_sha256=receipt.receipt_sha256,
        files=[
            {
                "path": "prepared-receipt.json",
                "sha256": hashlib.sha256(b"receipt").hexdigest(),
                "size_bytes": 7,
            }
        ],
    )
    return PreparedArtifactRestoreResult(
        receipt=receipt,
        manifest=manifest,
        artifact_id=10608043279,
        run_id=35519707067,
        run_attempt=1,
        digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        source_commit=identity.protected_commit_sha,
        campaign_key=identity.campaign_key,
        preparation_key_sha256=identity.preparation_key_sha256,
    )


def _source_validation(
    profile,
    recovery_root: Path,
    *,
    strategy_ids: tuple[str, ...] = ("cached-0",),
) -> ValidatedCheckpointRecoverySource:
    result = ResumeResultV1(
        strategy_id="cached-0",
        result_json='{"info":{"locked_opened":false,"validation_opened":false}}',
        scientific_result_sha256="d" * 64,
        source_path=str(recovery_root / "checkpoints/cached-0/results.parquet"),
    )
    index = CatalogResumeIndexV1(
        science_identity_sha256=profile.science_sha256,
        catalog_manifest_sha256=profile.catalog_manifest_sha256,
        results=(result,),
        strategy_ids=strategy_ids,
        physical_result_count=profile.expected_result_count,
        duplicate_result_count=0,
        index_sha256="e" * 64,
    )
    return ValidatedCheckpointRecoverySource(
        resume_index=index,
        plan_receipt={"receipt_sha256": profile.source_plan_receipt_sha256},
        science_identity_sha256=profile.science_sha256,
        catalog_manifest_sha256=profile.catalog_manifest_sha256,
        work_manifest_sha256="f" * 64,
        worker_ids=profile.worker_ids,
        strategy_ids=strategy_ids,
        checkpoint_artifact_names=tuple(f"checkpoint-{i}" for i in range(120)),
        checkpoint_receipt_sha256s=("1" * 64,),
        checkpoint_chain_manifest_sha256s=("2" * 64,),
        recovery_block_ids=("block-0",),
        source_assignment_manifest_sha256s=("3" * 64,),
    )


class _Source:
    repository = REPOSITORY

    def __init__(self, *, lineage_ok: bool = True) -> None:
        self.lineage_ok = lineage_ok
        self.calls: list[str] = []

    def get_json(self, path: str) -> tuple[object, object]:
        self.calls.append(path)
        historical = HISTORICAL_COMMIT if self.lineage_ok else "0" * 40
        return (
            {
                "status": "ahead" if self.lineage_ok else "diverged",
                "base_commit": {"sha": historical},
                "merge_base_commit": {"sha": historical},
            },
            None,
        )


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    large_seed: bool = False,
):
    root = _profile_root(tmp_path / "repo")
    profile = load_checkpoint_recovery_profile(
        root, "sp500-optimized-catalog-v1", 8
    )
    assert profile is not None
    assert profile.profile_sha256 == "fc3aff1e9ccfc0e4608e510a538f8ce839c371669585b8b680a658e54d7e81b7"
    identity = _identity()
    raw = b"prepared archive"
    prepared = _prepared(identity, raw)
    expected_ids = (
        tuple(f"SCV1-{index:064x}" for index in range(18_630))
        if large_seed
        else ("cached-0",)
    )
    record = {
        "profile_sha256": profile.profile_sha256,
        "identity": identity.model_dump(mode="json"),
        "run_id": prepared.run_id,
        "run_attempt": prepared.run_attempt,
        "artifact_id": prepared.artifact_id,
        "artifact_digest": prepared.digest,
        "size_bytes": len(raw),
        "prepared_receipt_sha256": prepared.receipt.receipt_sha256,
        "bundle_manifest_sha256": prepared.manifest.manifest_sha256,
    }
    config = root / "config/catalog_checkpoint_recovery_archives_v1.json"
    config.write_text(
        json.dumps({"schema_version": "1", "archives": [record]}, sort_keys=True),
        encoding="utf-8",
    )
    auth = _authenticated(profile)
    auth = CheckpointRecoveryOwnerAuthenticationV1(
        owner=auth.owner,
        proof=replace(
            auth.proof,
            source_decision_sha256=profile.source_plan_bindings["decision_sha256"],
        ),
    )
    monkeypatch.setattr(
        archive,
        "verify_checkpoint_failure_owner",
        lambda **kwargs: auth.proof,
    )
    source = _Source()
    calls: list[CatalogPreparationIdentityV1] = []
    source_result: dict[str, ValidatedCheckpointRecoverySource] = {}

    def restore_prepared(*, client, expected_identity, destination, download_archive):
        assert client is source
        calls.append(expected_identity)
        assert download_archive(prepared.artifact_id) == raw
        recovery = destination / "checkpoint-recovery"
        (recovery / "source-plan").mkdir(parents=True)
        (recovery / "checkpoints").mkdir()
        (destination / "evidence").mkdir()
        (destination / "templates/workers-030").mkdir(parents=True)
        document = {
            "schema_version": "1",
            "profile": profile.model_dump(mode="json"),
            "owner_proof": asdict(auth.proof),
            "binding": build_checkpoint_recovery_binding(profile, auth.proof),
            "cached_strategy_ids": list(expected_ids),
            "cached_strategy_ids_sha256": profile.cached_strategy_ids_sha256,
            # This is the historical digest, before source paths are relocated
            # into the fresh staging directory.  It must not be compared with
            # the relocated resume-index digest.
            "resume_index_sha256": "a" * 64,
            "source_plan_receipt_sha256": profile.source_plan_receipt_sha256,
            "source_plan_relative": "source-plan",
            "checkpoint_relative": "checkpoints",
        }
        if large_seed:
            document["files"] = [
                {
                    "path": f"checkpoint-recovery/checkpoints/checkpoint-{index:03d}.json",
                    "sha256": "0" * 64,
                    "size_bytes": index + 1,
                }
                for index in range(120)
            ]
        seed_path = destination / "evidence/preparation-seed.json"
        seed_path.write_text(
            json.dumps({"checkpoint_recovery": document}), encoding="utf-8"
        )
        if large_seed:
            assert seed_path.stat().st_size > 256 * 1024
        source_result["value"] = _source_validation(
            profile, recovery, strategy_ids=expected_ids
        )
        return prepared

    monkeypatch.setattr(archive, "restore_prepared_artifact", restore_prepared)
    monkeypatch.setattr(archive, "verify_checkpoint_recovery_plan", lambda *args: None)
    monkeypatch.setattr(archive, "_derive_expected_pending_ids", lambda *args: expected_ids)
    monkeypatch.setattr(
        archive,
        "canonical_cached_strategy_ids_sha256",
        lambda values: profile.cached_strategy_ids_sha256,
    )
    monkeypatch.setattr(
        archive,
        "verify_checkpoint_recovery_source",
        lambda *args: source_result["value"],
    )
    return root, profile, identity, record, auth, source, calls, prepared


def _run(fixture, *, profile=None, auth=None, source=None, record=None):
    root, original_profile, identity, original_record, original_auth, original_source, calls, prepared = fixture
    root_record = original_record if record is None else record
    (root / "config/catalog_checkpoint_recovery_archives_v1.json").write_text(
        json.dumps({"schema_version": "1", "archives": [root_record]}, sort_keys=True),
        encoding="utf-8",
    )
    target = root / "output"
    result = archive.restore_archived_checkpoint_recovery(
        root,
        REPOSITORY,
        PROTECTED_COMMIT,
        original_profile if profile is None else profile,
        original_auth if auth is None else auth,
        target,
        original_source if source is None else source,
        lambda artifact_id: b"prepared archive",
    )
    return result, target


def test_archive_restore_accepts_relocated_bundle_and_rebases_index_paths(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    result, target = _run(fixture)

    assert isinstance(result, archive.CheckpointRecoveryRestoreResultV1)
    assert target.is_dir()
    assert result.checkpoint_root == target / "checkpoints"
    assert result.source_plan_root == target / "source-plan"
    assert result.source_validation.resume_index.results[0].source_path == str(
        target / "checkpoints/cached-0/results.parquet"
    )
    assert fixture[6] == [fixture[2]]
    assert fixture[5].calls == [
        f"/repos/{REPOSITORY}/compare/{HISTORICAL_COMMIT}...{PROTECTED_COMMIT}"
    ]


def test_archive_restore_accepts_relocated_real_sized_seed(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch, large_seed=True)
    result, target = _run(fixture)

    assert isinstance(result, archive.CheckpointRecoveryRestoreResultV1)
    assert target.is_dir()
    assert result.source_validation.resume_index.strategy_ids == tuple(
        f"SCV1-{index:064x}" for index in range(18_630)
    )


def test_archive_altered_result_fails_closed_without_publishing(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    root, profile, identity, record, auth, source, calls, prepared = fixture
    valid_validator = archive.verify_checkpoint_recovery_source

    def altered_result(*args):
        validated = valid_validator(*args)
        altered_index = validated.resume_index.model_copy(
            update={"physical_result_count": profile.expected_result_count - 1}
        )
        return validated.model_copy(update={"resume_index": altered_index})

    monkeypatch.setattr(archive, "verify_checkpoint_recovery_source", altered_result)
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SOURCE_INVALID"):
        _run(fixture)
    assert not (root / "output").exists()


@pytest.mark.parametrize("mutation", ["pin", "profile", "proof", "archive", "lineage", "expiredprepared"])
def test_archive_mutations_fail_closed_without_publishing(tmp_path, monkeypatch, mutation):
    fixture = _fixture(tmp_path, monkeypatch)
    root, profile, identity, record, auth, source, calls, prepared = fixture
    changed_record = dict(record)
    changed_profile = profile
    changed_auth = auth
    changed_source = source
    if mutation == "pin":
        changed_record["artifact_id"] = record["artifact_id"] + 1
    elif mutation == "profile":
        changed_profile = profile.model_copy(update={"expected_total_count": 37257})
    elif mutation == "proof":
        changed_auth = CheckpointRecoveryOwnerAuthenticationV1(
            owner=auth.owner,
            proof=replace(auth.proof, source_run_id=auth.proof.source_run_id + 1),
        )
    elif mutation == "archive":
        changed_record["bundle_manifest_sha256"] = "0" * 64
    elif mutation == "lineage":
        changed_source = _Source(lineage_ok=False)
    else:
        def expired(**kwargs):
            raise PreparedArtifactRestoreError("CATALOG_PREPARED_ARTIFACT_EXPIRED")

        monkeypatch.setattr(archive, "restore_prepared_artifact", expired)

    with pytest.raises(ValueError):
        _run(
            fixture,
            profile=changed_profile,
            auth=changed_auth,
            source=changed_source,
            record=changed_record,
        )
    assert not (root / "output").exists()


def test_archive_config_absence_and_nonmatching_profile_keep_legacy_fallback(tmp_path, monkeypatch):
    root = _profile_root(tmp_path / "repo")
    profile = load_checkpoint_recovery_profile(root, "sp500-optimized-catalog-v1", 8)
    assert profile is not None
    auth = _authenticated(profile)
    output = root / "output"
    source = _Source()
    assert archive.restore_archived_checkpoint_recovery(
        root, REPOSITORY, PROTECTED_COMMIT, profile, auth, output, source, lambda _: b"x"
    ) is None
    config = root / "config/catalog_checkpoint_recovery_archives_v1.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "archives": [
                    {
                        "profile_sha256": "0" * 64,
                        "identity": _identity().model_dump(mode="json"),
                        "run_id": 1,
                        "run_attempt": 1,
                        "artifact_id": 1,
                        "artifact_digest": "sha256:" + "1" * 64,
                        "size_bytes": 1,
                        "prepared_receipt_sha256": "2" * 64,
                        "bundle_manifest_sha256": "3" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert archive.restore_archived_checkpoint_recovery(
        root, REPOSITORY, PROTECTED_COMMIT, profile, auth, output, source, lambda _: b"x"
    ) is None
    assert not output.exists()


def test_archive_config_is_closed_and_symlink_safe(tmp_path):
    root = _profile_root(tmp_path / "repo")
    config = root / "config/catalog_checkpoint_recovery_archives_v1.json"
    config.write_text('{"schema_version":"1","archives":[],"extra":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID"):
        archive._load_archive_records(root)
    config.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text('{"schema_version":"1","archives":[]}', encoding="utf-8")
    try:
        config.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID"):
        archive._load_archive_records(root)
