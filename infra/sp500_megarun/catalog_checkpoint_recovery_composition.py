"""Revalidate the two immutable checkpoint sources of the closed SP500 successor."""
from __future__ import annotations

from pathlib import Path
import json

from .catalog_checkpoint_recovery_binding import _read, verify_checkpoint_recovery_plan
from .catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1
from .catalog_checkpoint_recovery_profile import (
    CheckpointRecoveryProfileV1,
    canonical_cached_strategy_ids_sha256,
    load_checkpoint_recovery_profile,
)
from .catalog_checkpoint_recovery_source import (
    ValidatedCheckpointRecoverySource,
    _validate_resume_index,
    _validate_run_plan_and_manifest,
    verify_checkpoint_recovery_source,
)
from .catalog_resume import load_resume_index


def _verify_selected_results(repo_root: Path, checkpoint_root: Path, profile: CheckpointRecoveryProfileV1) -> None:
    from .catalog_campaign_registry import resolve_catalog_for_reduction
    from .catalog_selected_results import resolve_registered_selected_result_keys

    catalog = resolve_catalog_for_reduction(repo_root=repo_root,
        scientific_contract_sha256=profile.science_sha256,
        catalog_manifest_sha256=profile.catalog_manifest_sha256)
    expected = resolve_registered_selected_result_keys(repo_root=repo_root,
        scientific_contract_sha256=profile.science_sha256,
        catalog_manifest_sha256=profile.catalog_manifest_sha256, catalog_path=catalog)
    paths = tuple(checkpoint_root.rglob("selected_results.jsonl"))
    if len(paths) != 1 or paths[0].is_symlink():
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
    rows = [json.loads(line) for line in paths[0].read_text("utf-8").splitlines() if line]
    if len(rows) != 13 or tuple(sorted(row["source_strategy_key"] for row in rows)) != expected:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")


def verify_checkpoint_recovery_transport(
    *, repo_root: Path, source_plan_root: Path, checkpoint_root: Path,
    profile: CheckpointRecoveryProfileV1,
) -> ValidatedCheckpointRecoverySource:
    """Check source identities, disjoint partitions and exact physical coverage."""
    from .catalog_checkpoint_recovery_restore import _derive_expected_pending_ids

    current_ids = _derive_expected_pending_ids(source_plan_root, profile)
    if profile.target_generation == 8:
        return verify_checkpoint_recovery_source(
            source_plan_root, checkpoint_root, dict(profile.source_plan_bindings),
            profile.science_sha256, profile.catalog_manifest_sha256,
            current_ids, profile.worker_ids,
        )
    if profile.target_generation != 9:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID")
    inherited = load_checkpoint_recovery_profile(repo_root, profile.campaign_key, 8)
    if inherited is None or inherited.profile_sha256 != profile.inherited_profile_sha256:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_INHERITED_PROFILE_INVALID")
    transport = source_plan_root.parent
    if checkpoint_root != transport / "checkpoints":
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID")
    inherited_plan = transport / "inherited-source-plan"
    for path in (source_plan_root, checkpoint_root, inherited_plan,
                 checkpoint_root / "current", checkpoint_root / "inherited"):
        if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(transport.resolve()):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID")
    if {path.name for path in checkpoint_root.iterdir()} != {"current", "inherited"}:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID")
    proof = CheckpointRecoveryOwnerProofV1(**_read(transport / "inherited-owner-proof.json"))
    if (
        proof.evidence_kind != "failed_owner_without_terminal"
        or proof.profile_sha256 != inherited.profile_sha256
        or proof.source_request_sha256 != inherited.source_request_sha256
        or proof.source_issue_number != inherited.source_issue_number
        or proof.source_run_id != inherited.source_run_id
        or proof.source_run_attempt != inherited.source_run_attempt
        or proof.source_protected_commit_sha != inherited.source_protected_commit_sha
        or proof.source_decision_sha256 != inherited.source_plan_bindings["decision_sha256"]
        or type(proof.source_finalizer_job_id) is not int or proof.source_finalizer_job_id <= 0
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_INHERITED_PROOF_INVALID")
    # Source353's sealed binding already commits to the inherited source339 proof.
    verify_checkpoint_recovery_plan(source_plan_root, inherited, proof)
    inherited_ids = _derive_expected_pending_ids(inherited_plan, inherited)
    old = verify_checkpoint_recovery_source(
        inherited_plan, checkpoint_root / "inherited", dict(inherited.source_plan_bindings),
        inherited.science_sha256, inherited.catalog_manifest_sha256,
        inherited_ids, inherited.worker_ids,
    )
    current = verify_checkpoint_recovery_source(
        source_plan_root, checkpoint_root / "current", dict(profile.source_plan_bindings),
        profile.science_sha256, profile.catalog_manifest_sha256,
        current_ids, profile.worker_ids, checkpoint_slot_count=profile.slot_count,
    )
    _, all_ids, pending, cached = _validate_run_plan_and_manifest(
        source_plan_root, expected_science=profile.science_sha256,
    )
    if (
        old.plan_receipt_sha256 != inherited.source_plan_receipt_sha256
        or current.plan_receipt_sha256 != profile.source_plan_receipt_sha256
        or inherited.science_sha256 != profile.science_sha256
        or inherited.catalog_manifest_sha256 != profile.catalog_manifest_sha256
        or set(inherited_ids) != set(cached) or set(current_ids) != set(pending)
        or set(inherited_ids) & set(current_ids)
        or len(all_ids) != profile.expected_total_count
        or set(all_ids) != set(inherited_ids) | set(current_ids)
        or canonical_cached_strategy_ids_sha256(all_ids) != profile.cached_strategy_ids_sha256
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID")
    index = load_resume_index(
        (checkpoint_root,), expected_science_identity_sha256=profile.science_sha256,
        expected_catalog_manifest_sha256=profile.catalog_manifest_sha256,
    )
    _validate_resume_index(index, expected_science=profile.science_sha256,
                           expected_catalog=profile.catalog_manifest_sha256,
                           expected_strategy_ids=all_ids)
    _verify_selected_results(repo_root, checkpoint_root, profile)
    combined = current.model_copy(update={
        "resume_index": index, "strategy_ids": tuple(sorted(all_ids)),
        **{name: getattr(old, name) + getattr(current, name) for name in (
            "checkpoint_artifact_names", "checkpoint_receipt_sha256s",
            "checkpoint_chain_manifest_sha256s", "recovery_block_ids",
            "source_assignment_manifest_sha256s",
        )},
    })
    if combined.checkpoint_count != profile.total_checkpoint_count:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_COMPOSITION_INVALID")
    return combined
