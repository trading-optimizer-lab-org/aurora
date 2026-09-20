#!/usr/bin/env python3
"""Restore the opt-in authenticated SP500 checkpoint recovery source."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_binding import (
    verify_checkpoint_recovery_plan, build_checkpoint_recovery_binding, _read as _strict_json,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
    CHECKPOINT_RECOVERY_TARGET_GENERATION,
    load_checkpoint_recovery_profile,
    validate_exact_checkpoint_profile,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_source import (
    _validate_contract_science, verify_checkpoint_recovery_source,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_restore import _derive_expected_pending_ids
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry, resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import build_catalog_preparation_identity
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    verify_prepared_catalog_bundle,
)
from aurora.infra.sp500_megarun.catalog_sealed_plan import (
    verify_sealed_global_reuse_execution_plan,
)


REPOSITORY = "trading-optimizer-lab-org/aurora"


def _load_checkpoint_recovery_seed(root, seed, campaign_key, context, *, sealed_plan):
    """Validate source bytes already bound by the authenticated PREPARED manifest."""
    document = context.get("checkpoint_recovery")
    if not isinstance(document, dict) or document.get("schema_version") != "1":
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SEED_INVALID")
    profile = validate_exact_checkpoint_profile(root, document.get("profile"))
    if profile.campaign_key != campaign_key:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_MISMATCH")
    proof = CheckpointRecoveryOwnerProofV1(**document["owner_proof"])
    if (
        document.get("binding") != build_checkpoint_recovery_binding(profile, proof)
        or proof.source_issue_number != profile.source_issue_number
        or proof.source_run_id != profile.source_run_id
        or proof.source_run_attempt != profile.source_run_attempt
        or proof.source_protected_commit_sha != profile.source_protected_commit_sha
        or proof.source_decision_sha256 != profile.source_plan_bindings["decision_sha256"]
        or proof.evidence_kind != "failed_owner_without_terminal"
        or type(proof.source_finalizer_job_id) is not int or proof.source_finalizer_job_id <= 0
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_OWNER_PROOF_INVALID")
    transport = seed / "checkpoint-recovery"
    paths = []
    for key, expected in (("source_plan_relative", "source-plan"), ("checkpoint_relative", "checkpoints")):
        if document.get(key) != expected:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_TRANSPORT_INVALID")
        path = transport / expected
        if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(seed.resolve()):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_TRANSPORT_INVALID")
        paths.append(path)
    verify_checkpoint_recovery_plan(sealed_plan, profile, proof)
    expected_ids = _derive_expected_pending_ids(paths[0], profile)
    source = verify_checkpoint_recovery_source(
        paths[0], paths[1], dict(profile.source_plan_bindings), profile.science_sha256,
        profile.catalog_manifest_sha256, expected_ids, profile.worker_ids,
    )
    if (
        source.plan_receipt_sha256 != profile.source_plan_receipt_sha256
        or source.checkpoint_count != 120
        or source.resume_index.physical_result_count != profile.expected_result_count
        or source.resume_index.duplicate_result_count != 0
        or tuple(sorted(source.resume_index.strategy_ids)) != tuple(sorted(expected_ids))
        or document.get("source_plan_receipt_sha256") != profile.source_plan_receipt_sha256
        or document.get("cached_strategy_ids_sha256") != profile.cached_strategy_ids_sha256
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_INVALID")
    return dict(profile=profile, proof=proof, source_plan_relative="source-plan",
                checkpoint_relative="checkpoints", source_plan_receipt_sha256=source.plan_receipt_sha256,
                resume_index_sha256=source.resume_index_sha256)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore the authenticated source-7 checkpoint resume root."
    )
    parser.add_argument("--sealed-plan", required=True, type=Path)
    parser.add_argument("--prepared-bundle", required=True, type=Path)
    return parser


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"CATALOG_CHECKPOINT_RECOVERY_ENV_INVALID:{name}")
    return value


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repository = _required_environment("GITHUB_REPOSITORY")
        protected_commit_sha = _required_environment("CATALOG_PROTECTED_COMMIT_SHA")
        if repository != REPOSITORY or re.fullmatch(r"[0-9a-f]{40}", protected_commit_sha) is None:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_AUTH_IDENTITY_INVALID")
        checked_out = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if checked_out != protected_commit_sha:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_COMMIT_MISMATCH")

        profile = load_checkpoint_recovery_profile(
            REPOSITORY_ROOT,
            CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
            CHECKPOINT_RECOVERY_TARGET_GENERATION,
        )
        if profile is None:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_REQUIRED")

        registry = load_catalog_campaign_registry(
            REPOSITORY_ROOT / "config/catalog_campaign_registry_v1.json"
        )
        entry = resolve_catalog_campaign(registry, CHECKPOINT_RECOVERY_CAMPAIGN_KEY, REPOSITORY_ROOT)
        identity = build_catalog_preparation_identity(
            repo_root=REPOSITORY_ROOT,
            registry_entry=entry,
            protected_commit_sha=protected_commit_sha,
        )
        verify_sealed_global_reuse_execution_plan(
            args.sealed_plan, expected_bindings={"protected_commit_sha": protected_commit_sha},
        )
        controller = _strict_json(args.sealed_plan / "controller_binding.json")
        binding = controller.get("binding") if isinstance(controller, dict) else None
        if not isinstance(binding, dict) or "checkpoint_recovery" not in binding:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_BINDING_INVALID")
        receipt, manifest = verify_prepared_catalog_bundle(
            bundle_dir=args.prepared_bundle, expected_identity=identity,
        )
        if binding.get("checkpoint_recovery_prepared_bundle_manifest_sha256") != manifest.manifest_sha256:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_TRANSPORT_INVALID")
        if binding.get("prepared_receipt_sha256") != receipt.receipt_sha256:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PREPARED_RECEIPT_MISMATCH")
        bundle = args.prepared_bundle.resolve(strict=True)
        context = _strict_json(bundle / "evidence/preparation-seed.json")
        if not isinstance(context, dict):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SEED_INVALID")
        state = _load_checkpoint_recovery_seed(
            REPOSITORY_ROOT, bundle, CHECKPOINT_RECOVERY_CAMPAIGN_KEY, context,
            sealed_plan=bundle / f"templates/workers-{receipt.qualified_worker_ceiling:03d}",
        )
        if state is None or state["profile"] != profile:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_REQUIRED")
        proof = state["proof"]
        verify_checkpoint_recovery_plan(args.sealed_plan, profile, proof)
        _validate_contract_science(
            args.sealed_plan,
            expected_science=profile.science_sha256,
            expected_catalog=profile.catalog_manifest_sha256,
        )

        payload = {
            "checkpoint_root": str(bundle / "checkpoint-recovery" / state["checkpoint_relative"]),
            "source_plan_root": str(bundle / "checkpoint-recovery" / state["source_plan_relative"]),
            "profile_sha256": profile.profile_sha256,
            "owner_proof_sha256": proof.evidence_sha256,
            "source_plan_receipt_sha256": state["source_plan_receipt_sha256"],
            "resume_index_sha256": state["resume_index_sha256"],
            "cached_strategy_ids_sha256": profile.cached_strategy_ids_sha256,
            "cached_recipe_count": profile.expected_result_count,
            "total_recipe_count": profile.expected_total_count,
        }
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
