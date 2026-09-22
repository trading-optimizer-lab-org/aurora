from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from typing import TypedDict

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_composition as composition
from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_restore as restore
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_SOURCE8_EXECUTION_PLAN_SHA256,
    CHECKPOINT_RECOVERY_SOURCE8_ISSUE_NUMBER,
    CHECKPOINT_RECOVERY_SOURCE8_PLAN_RECEIPT_SHA256,
    CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA,
    CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256,
    CheckpointRecoveryProfileV1,
    canonical_cached_strategy_ids_sha256,
    load_checkpoint_recovery_profile,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_source import (
    ValidatedCheckpointRecoverySource,
)
from aurora.infra.sp500_megarun.catalog_resume import (
    CatalogResumeIndexV1,
    load_resume_index,
)


SCIENCE_SHA256 = "a" * 64
CATALOG_SHA256 = "b" * 64
CACHED_IDS = ("cached-1", "cached-2")
PENDING_IDS = ("pending-1", "pending-2")
ALL_IDS = CACHED_IDS + PENDING_IDS


class CompositionFixture(TypedDict):
    repo_root: Path
    source_plan_root: Path
    checkpoint_root: Path
    inherited_plan_root: Path
    profile8: CheckpointRecoveryProfileV1
    profile9: CheckpointRecoveryProfileV1
    proof8: CheckpointRecoveryOwnerProofV1
    inherited_source: ValidatedCheckpointRecoverySource
    current_source: ValidatedCheckpointRecoverySource
    inherited_ids: tuple[str, ...]
    current_ids: tuple[str, ...]
    all_ids: tuple[str, ...]


def _result_json(strategy_id: str) -> str:
    return json.dumps(
        {
            "strategy_id": strategy_id,
            "info": {"locked_opened": False, "validation_opened": False},
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_result_partition(
    root: Path,
    strategy_ids: tuple[str, ...],
    *,
    science_sha256: str,
    catalog_manifest_sha256: str,
) -> None:
    partition = root / "partition"
    partition.mkdir(parents=True, exist_ok=True)
    rows = [
        {"strategy_id": strategy_id, "result_json": _result_json(strategy_id)}
        for strategy_id in strategy_ids
    ]
    result_path = partition / "results.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=pa.schema([("strategy_id", pa.string()), ("result_json", pa.string())]),
        ),
        result_path,
    )
    receipt = {
        "science_identity_sha256": science_sha256,
        "catalog_manifest_sha256": catalog_manifest_sha256,
        "validation_opened": False,
        "locked_opened": False,
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
    }
    (partition / "receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _proof8(profile: CheckpointRecoveryProfileV1) -> CheckpointRecoveryOwnerProofV1:
    proof = CheckpointRecoveryOwnerProofV1(
        profile_sha256=profile.profile_sha256,
        campaign_key=profile.campaign_key,
        target_generation=profile.target_generation,
        source_request_sha256=profile.source_request_sha256,
        source_issue_number=profile.source_issue_number,
        source_run_id=profile.source_run_id,
        source_run_attempt=profile.source_run_attempt,
        source_protected_commit_sha=profile.source_protected_commit_sha,
        source_decision_sha256=profile.source_plan_bindings["decision_sha256"],
        source_finalizer_job_id=123,
    )
    return CheckpointRecoveryOwnerProofV1(**asdict(proof))


def _profile9(
    profile8: CheckpointRecoveryProfileV1,
    *,
    all_ids: tuple[str, ...],
) -> CheckpointRecoveryProfileV1:
    bindings = dict(profile8.source_plan_bindings)
    bindings.update(
        {
            "request_sha256": CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256,
            "protected_commit_sha": CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA,
            "science_sha256": profile8.science_sha256,
            "execution_plan_sha256": CHECKPOINT_RECOVERY_SOURCE8_EXECUTION_PLAN_SHA256,
        }
    )
    return profile8.model_copy(
        update={
            "target_generation": 9,
            "source_generation": 8,
            "source_issue_number": CHECKPOINT_RECOVERY_SOURCE8_ISSUE_NUMBER,
            "source_run_id": 35708742966,
            "source_run_attempt": 1,
            "source_request_sha256": CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256,
            "source_protected_commit_sha": CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA,
            "source_plan_bindings": bindings,
            "source_plan_receipt_sha256": CHECKPOINT_RECOVERY_SOURCE8_PLAN_RECEIPT_SHA256,
            "science_sha256": profile8.science_sha256,
            "catalog_manifest_sha256": profile8.catalog_manifest_sha256,
            "worker_ids": tuple(range(60)),
            "expected_result_count": len(all_ids),
            "expected_total_count": len(all_ids),
            "cached_strategy_ids_sha256": canonical_cached_strategy_ids_sha256(all_ids),
            "inherited_profile_sha256": profile8.profile_sha256,
        }
    )


def _validated_source(
    profile: CheckpointRecoveryProfileV1,
    root: Path,
    *,
    strategy_ids: tuple[str, ...],
    label: str,
) -> ValidatedCheckpointRecoverySource:
    index = load_resume_index(
        (root,),
        expected_science_identity_sha256=profile.science_sha256,
        expected_catalog_manifest_sha256=profile.catalog_manifest_sha256,
    )
    return ValidatedCheckpointRecoverySource(
        resume_index=index,
        plan_receipt={"receipt_sha256": profile.source_plan_receipt_sha256},
        science_identity_sha256=profile.science_sha256,
        catalog_manifest_sha256=profile.catalog_manifest_sha256,
        work_manifest_sha256="c" * 64,
        worker_ids=profile.worker_ids,
        strategy_ids=strategy_ids,
        checkpoint_artifact_names=tuple(f"{label}-checkpoint-{index}" for index in range(120)),
        checkpoint_receipt_sha256s=("1" * 64,) * 120,
        checkpoint_chain_manifest_sha256s=("2" * 64,) * 120,
        recovery_block_ids=tuple(f"{label}-block-{index}" for index in range(120)),
        source_assignment_manifest_sha256s=("3" * 64,) * 120,
    )


def _build_fixture(
    tmp_path: Path,
    *,
    current_ids: tuple[str, ...] = PENDING_IDS,
    duplicate_physical_result: bool = False,
) -> CompositionFixture:
    transport = tmp_path / "transport"
    repo_root = transport / "repo"
    source_plan_root = transport / "source-plan353"
    inherited_plan_root = transport / "inherited-source-plan"
    checkpoint_root = transport / "checkpoints"
    current_root = checkpoint_root / "current"
    inherited_root = checkpoint_root / "inherited"
    for root in (
        repo_root,
        source_plan_root,
        inherited_plan_root,
        current_root,
        inherited_root,
    ):
        root.mkdir(parents=True)

    profile8 = load_checkpoint_recovery_profile(
        Path(__file__).resolve().parents[1], "sp500-optimized-catalog-v1", 8
    )
    assert profile8 is not None
    profile9 = _profile9(profile8, all_ids=ALL_IDS)
    proof8 = _proof8(profile8)
    (transport / "inherited-owner-proof.json").write_text(
        json.dumps(asdict(proof8), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    inherited_result_ids: tuple[str, ...] = CACHED_IDS
    current_result_ids: tuple[str, ...] = current_ids
    if duplicate_physical_result:
        inherited_result_ids += ("physical-duplicate",)
        current_result_ids += ("physical-duplicate",)
    _write_result_partition(
        inherited_root,
        inherited_result_ids,
        science_sha256=profile9.science_sha256,
        catalog_manifest_sha256=profile9.catalog_manifest_sha256,
    )
    _write_result_partition(
        current_root,
        current_result_ids,
        science_sha256=profile9.science_sha256,
        catalog_manifest_sha256=profile9.catalog_manifest_sha256,
    )
    return CompositionFixture(
        repo_root=repo_root,
        source_plan_root=source_plan_root,
        checkpoint_root=checkpoint_root,
        inherited_plan_root=inherited_plan_root,
        profile8=profile8,
        profile9=profile9,
        proof8=proof8,
        inherited_source=_validated_source(
            profile8,
            inherited_root,
            strategy_ids=CACHED_IDS,
            label="inherited",
        ),
        current_source=_validated_source(
            profile9,
            current_root,
            strategy_ids=current_ids,
            label="current",
        ),
        inherited_ids=CACHED_IDS,
        current_ids=current_ids,
        all_ids=ALL_IDS,
    )


def _patch_composition(
    monkeypatch: pytest.MonkeyPatch,
    fixture: CompositionFixture,
    *,
    inherited_profile: CheckpointRecoveryProfileV1 | None = None,
    all_ids: tuple[str, ...] = ALL_IDS,
    pending_ids: tuple[str, ...] = PENDING_IDS,
    cached_ids: tuple[str, ...] = CACHED_IDS,
) -> tuple[
    list[tuple[Path, CheckpointRecoveryProfileV1, CheckpointRecoveryOwnerProofV1]],
    list[tuple[Path, Path, CheckpointRecoveryProfileV1]],
]:
    plan_calls: list[
        tuple[Path, CheckpointRecoveryProfileV1, CheckpointRecoveryOwnerProofV1]
    ] = []
    selected_result_calls: list[tuple[Path, Path, CheckpointRecoveryProfileV1]] = []
    inherited = inherited_profile or fixture["profile8"]

    def load_profile(
        _repo_root: Path, _campaign_key: str, target_generation: int
    ) -> CheckpointRecoveryProfileV1 | None:
        assert target_generation == 8
        return inherited

    def verify_plan(
        plan_root: Path,
        profile: CheckpointRecoveryProfileV1,
        proof: CheckpointRecoveryOwnerProofV1,
    ) -> None:
        plan_calls.append((plan_root, profile, proof))

    def derive_ids(
        plan_root: Path, _profile: CheckpointRecoveryProfileV1
    ) -> tuple[str, ...]:
        if plan_root == fixture["source_plan_root"]:
            return fixture["current_ids"]
        if plan_root == fixture["inherited_plan_root"]:
            return fixture["inherited_ids"]
        raise AssertionError(f"unexpected source plan: {plan_root}")

    def validate_run_manifest(
        _plan_root: Path, *, expected_science: str
    ) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        assert expected_science == fixture["profile9"].science_sha256
        return {}, all_ids, pending_ids, cached_ids

    def validate_source(
        _sealed_plan: Path,
        checkpoint_path: Path,
        *_args: object,
        **kwargs: object,
    ) -> ValidatedCheckpointRecoverySource:
        if checkpoint_path.name == "inherited":
            assert "checkpoint_slot_count" not in kwargs
            return fixture["inherited_source"]
        assert checkpoint_path.name == "current"
        assert kwargs.get("checkpoint_slot_count") == 2
        return fixture["current_source"]

    def verify_selected_results(
        repo_root: Path,
        checkpoint_path: Path,
        profile: CheckpointRecoveryProfileV1,
    ) -> None:
        selected_result_calls.append((repo_root, checkpoint_path, profile))

    monkeypatch.setattr(composition, "load_checkpoint_recovery_profile", load_profile)
    monkeypatch.setattr(composition, "verify_checkpoint_recovery_plan", verify_plan)
    monkeypatch.setattr(composition, "_validate_run_plan_and_manifest", validate_run_manifest)
    monkeypatch.setattr(composition, "verify_checkpoint_recovery_source", validate_source)
    monkeypatch.setattr(composition, "_verify_selected_results", verify_selected_results)
    monkeypatch.setattr(restore, "_derive_expected_pending_ids", derive_ids)
    return plan_calls, selected_result_calls


def _run(
    fixture: CompositionFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    inherited_profile: CheckpointRecoveryProfileV1 | None = None,
    all_ids: tuple[str, ...] = ALL_IDS,
    pending_ids: tuple[str, ...] = PENDING_IDS,
    cached_ids: tuple[str, ...] = CACHED_IDS,
) -> tuple[
    ValidatedCheckpointRecoverySource,
    list[tuple[Path, CheckpointRecoveryProfileV1, CheckpointRecoveryOwnerProofV1]],
    list[tuple[Path, Path, CheckpointRecoveryProfileV1]],
]:
    plan_calls, selected_result_calls = _patch_composition(
        monkeypatch,
        fixture,
        inherited_profile=inherited_profile,
        all_ids=all_ids,
        pending_ids=pending_ids,
        cached_ids=cached_ids,
    )
    return (
        composition.verify_checkpoint_recovery_transport(
            repo_root=fixture["repo_root"],
            source_plan_root=fixture["source_plan_root"],
            checkpoint_root=fixture["checkpoint_root"],
            profile=fixture["profile9"],
        ),
        plan_calls,
        selected_result_calls,
    )


def test_generation9_composes_real_resume_indexes_from_disjoint_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path)

    result, plan_calls, selected_result_calls = _run(fixture, monkeypatch)

    assert isinstance(result.resume_index, CatalogResumeIndexV1)
    assert result.strategy_ids == tuple(sorted(ALL_IDS))
    assert result.resume_index.strategy_ids == tuple(sorted(ALL_IDS))
    assert result.resume_index.physical_result_count == 4
    assert result.resume_index.duplicate_result_count == 0
    assert result.checkpoint_count == 240
    assert plan_calls == [
        (fixture["source_plan_root"], fixture["profile8"], fixture["proof8"])
    ]
    assert selected_result_calls == [
        (fixture["repo_root"], fixture["checkpoint_root"], fixture["profile9"])
    ]


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing", "CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID"),
        ("overlap", "CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID"),
        ("foreign_id", "CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID"),
        ("inherited_profile_hash", "CATALOG_CHECKPOINT_RECOVERY_INHERITED_PROFILE_INVALID"),
        ("proof_binding", "CATALOG_CHECKPOINT_RECOVERY_INHERITED_PROOF_INVALID"),
        ("physical_duplicates", "CATALOG_CHECKPOINT_RECOVERY_STRATEGY_COVERAGE_INVALID"),
    ],
)
def test_generation9_rejects_composition_boundary_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_error: str,
) -> None:
    inherited_profile: CheckpointRecoveryProfileV1 | None = None
    if mutation == "overlap":
        fixture = _build_fixture(tmp_path, current_ids=("cached-1", "pending-2"))
    elif mutation == "foreign_id":
        fixture = _build_fixture(tmp_path, current_ids=("foreign-id", "pending-2"))
    elif mutation == "physical_duplicates":
        fixture = _build_fixture(tmp_path, duplicate_physical_result=True)
    else:
        fixture = _build_fixture(tmp_path)

    if mutation == "missing":
        shutil.rmtree(fixture["checkpoint_root"] / "inherited")
    elif mutation == "inherited_profile_hash":
        wrong_profile = fixture["profile8"].model_copy(
            update={"source_request_sha256": "0" * 64}
        )
        inherited_profile = wrong_profile
    elif mutation == "proof_binding":
        proof_path = fixture["checkpoint_root"].parent / "inherited-owner-proof.json"
        wrong_proof = replace(fixture["proof8"], source_decision_sha256="0" * 64)
        proof_path.write_text(
            json.dumps(asdict(wrong_proof), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match=expected_error):
        _run(fixture, monkeypatch, inherited_profile=inherited_profile)
