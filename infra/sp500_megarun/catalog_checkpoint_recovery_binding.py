"""Controller-light binding of partial PREPARED plans to authenticated recovery."""
from __future__ import annotations

import json
from pathlib import Path

from ..github_performance.contracts import canonical_sha256
from .catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1
from .catalog_checkpoint_recovery_profile import (
    CheckpointRecoveryProfileV1, canonical_cached_strategy_ids_sha256,
)
from .catalog_sealed_plan import verify_sealed_global_reuse_execution_plan


def build_checkpoint_recovery_binding(
    profile: CheckpointRecoveryProfileV1, proof: CheckpointRecoveryOwnerProofV1,
) -> dict[str, object]:
    if (proof.profile_sha256 != profile.profile_sha256
            or proof.source_request_sha256 != profile.source_request_sha256
            or proof.campaign_key != profile.campaign_key
            or proof.target_generation != profile.target_generation):
        raise ValueError('CATALOG_CHECKPOINT_RECOVERY_BINDING_INVALID')
    return {
        'schema_version': '1', 'profile_sha256': profile.profile_sha256,
        'owner_proof_sha256': proof.evidence_sha256,
        'source_plan_receipt_sha256': profile.source_plan_receipt_sha256,
        'science_sha256': profile.science_sha256,
        'catalog_manifest_sha256': profile.catalog_manifest_sha256,
        'cached_strategy_ids_sha256': profile.cached_strategy_ids_sha256,
        'cached_recipe_count': profile.expected_result_count,
        'total_recipe_count': profile.expected_total_count,
    }


def _read(path: Path) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('CATALOG_CHECKPOINT_RECOVERY_PLAN_INVALID')
            value[key] = item
        return value

    if path.is_symlink() or not path.is_file():
        raise ValueError('CATALOG_CHECKPOINT_RECOVERY_PLAN_INVALID')
    value = json.loads(path.read_bytes(), object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(
                           ValueError('CATALOG_CHECKPOINT_RECOVERY_PLAN_INVALID')))
    if not isinstance(value, dict):
        raise ValueError('CATALOG_CHECKPOINT_RECOVERY_PLAN_INVALID')
    return value


def verify_checkpoint_recovery_plan(
    sealed_plan: Path, profile: CheckpointRecoveryProfileV1,
    proof: CheckpointRecoveryOwnerProofV1,
) -> None:
    """Require a sealed exact partition; this never loads scientific dataframes."""
    receipt = verify_sealed_global_reuse_execution_plan(sealed_plan)
    controller = _read(sealed_plan / 'controller_binding.json')
    envelope = controller.get('binding')
    if (receipt.get('science_sha256') != profile.science_sha256
            or not isinstance(envelope, dict)
            or envelope.get('checkpoint_recovery') != build_checkpoint_recovery_binding(profile, proof)):
        raise ValueError('CATALOG_CHECKPOINT_RECOVERY_BINDING_INVALID')
    work = _read(sealed_plan / 'resume_work_manifest.json')
    run = _read(sealed_plan / 'run_plan.json')
    ids = []
    for name in ('all_strategy_ids', 'cached_strategy_ids', 'pending_strategy_ids'):
        rows = work.get(name)
        if (not isinstance(rows, list) or any(type(row) is not str or not row for row in rows)
                or len(set(rows)) != len(rows)):
            raise ValueError('CATALOG_CHECKPOINT_RECOVERY_PARTITION_INVALID')
        ids.append(rows)
    all_ids, cached, pending = ids
    manifest_hash = canonical_sha256({key: value for key, value in work.items() if key != 'manifest_sha256'})
    if (work.get('schema_version') != '1'
            or work.get('validation_opened') is not False or work.get('locked_opened') is not False
            or work.get('manifest_sha256') != manifest_hash
            or len(all_ids) != profile.expected_total_count
            or len(cached) != profile.expected_result_count
            or set(cached) & set(pending) or set(all_ids) != set(cached) | set(pending)
            or canonical_cached_strategy_ids_sha256(cached) != profile.cached_strategy_ids_sha256
            or run.get('work_manifest_sha256') != manifest_hash
            or run.get('cached_recipe_count') != len(cached)
            or run.get('pending_recipe_count') != len(pending)):
        raise ValueError('CATALOG_CHECKPOINT_RECOVERY_PARTITION_INVALID')
