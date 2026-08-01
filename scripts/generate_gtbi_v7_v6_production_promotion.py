"""Freeze PREV7-0304/0305 V6 production promotion and restore evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import (  # noqa: E402
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.scientific_assets import (  # noqa: E402
    validate_scientific_asset_manifest,
)

READINESS = ROOT / "docs/readiness/gtbi-v7"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
PROVIDER_TERMS = READINESS / "g2_provider_terms_acceptance_receipt.json"
RETENTION = READINESS / "g2_retention_policy_receipt.json"
DURABLE = READINESS / "v6_durable_preservation_receipt.json"
ASSET_MANIFEST = READINESS / "v6_final_result_scientific_asset_manifest.json"
RECEIPT = READINESS / "g2_v6_production_promotion_restore_receipt.json"
TRANSITION = (
    READINESS / "transition_manifests/g2-v6-production-promotion-restore-v1.json"
)
RECORDED_AT_UTC = "2026-07-31T19:50:00Z"
ARCHIVE_SHA256 = (
    "sha256:870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b"
)
SOURCE_BUNDLE_SHA256 = (
    "sha256:c0c3a4a7f27339667500dcdc267499c15ac3185992f492614a7587f2f0556417"
)


def _load_canonical(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(value) + b"\n":
        raise ValueError(f"non-canonical evidence: {path.relative_to(ROOT)}")
    return value


def _expected_result(task_id: str) -> str:
    with (READINESS / "task_status.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    return next(row["expected_result"] for row in rows if row["id"] == task_id)


def build_receipt() -> dict[str, Any]:
    owner = _load_canonical(OWNER_DIRECTIVE)
    provider = _load_canonical(PROVIDER_TERMS)
    retention = _load_canonical(RETENTION)
    durable = _load_canonical(DURABLE)
    asset = _load_canonical(ASSET_MANIFEST)
    validate_scientific_asset_manifest(asset)

    if not owner["accepted"]:
        raise ValueError("owner simplification directive is not accepted")
    if provider["decision"] != "accepted_for_frozen_input_only":
        raise ValueError("provider terms decision is not accepted")
    if retention["maximum_incremental_net_spend_usd"] != 0:
        raise ValueError("retention policy exceeds the owner budget")
    if retention["external_provider_copy_required"]:
        raise ValueError("retention receipt conflicts with owner custody model")
    if durable["restoration_state"] != "verified_on_two_clean_github_runners":
        raise ValueError("V6 package lacks two clean-runner verifications")
    if durable["requires_local_machine"]:
        raise ValueError("V6 restoration depends on a local machine")
    if durable["scientific_processing_performed"] or durable["locked_data_opened"]:
        raise ValueError("V6 preservation crossed a scientific boundary")
    if asset["asset_manifest_digest"] != (
        "sha256:e581450d23b2f480b27b14c1e2f20f6ce3867c3e5e26efd203ba3d118ef12bfe"
    ):
        raise ValueError("unexpected V6 scientific asset manifest")
    if asset["last_date"] != "2020-12-31" or asset["locked_start"] != "2021-01-01":
        raise ValueError("V6 scientific boundaries changed")
    if not asset["pristine_locked"] or asset["historical_post_validation_contaminated"]:
        raise ValueError("V6 manifest does not preserve the locked boundary")

    primary = durable["primary"]
    mirror = durable["mirror"]
    if {primary["asset_sha256"], mirror["asset_sha256"]} != {ARCHIVE_SHA256}:
        raise ValueError("primary and mirror archive digests differ")
    if primary["asset_size_bytes"] != mirror["asset_size_bytes"]:
        raise ValueError("primary and mirror archive sizes differ")
    source = durable["source_closure"]
    if not source["byte_identical_primary_mirror"]:
        raise ValueError("source closure is not byte-identical")
    if source["bundle_sha256"] != SOURCE_BUNDLE_SHA256:
        raise ValueError("unexpected source bundle digest")
    if source["restore_state"] != "verified_on_two_clean_github_runners":
        raise ValueError("source closure was not clean-runner verified twice")

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_v6_production_promotion_restore_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "task_ids": ["PREV7-0304", "PREV7-0305"],
        "recorded_at_utc": RECORDED_AT_UTC,
        "promotion": {
            "previous_registry_status": "emergency",
            "production_registry_status": "canonical",
            "republish_performed": False,
            "reason_not_republished": "existing_package_meets_owner_production_policy",
            "archive_sha256": ARCHIVE_SHA256,
            "archive_size_bytes": primary["asset_size_bytes"],
            "scientific_asset_manifest_digest": asset["asset_manifest_digest"],
            "reproducibility_classification": asset[
                "reproducibility_classification"
            ],
        },
        "custody": {
            "model": durable["custody_model"],
            "same_provider_mirror_disclosed": durable[
                "same_provider_mirror_disclosed"
            ],
            "external_provider_copy_required": False,
            "primary_repository_id": primary["repository_id"],
            "primary_release_id": primary["release_id"],
            "mirror_repository_id": mirror["repository_id"],
            "mirror_release_id": mirror["release_id"],
        },
        "clean_runner_restores": [
            {
                "source": "primary",
                "repository": primary["repository"],
                "run_id": primary["verification_run_id"],
                "run_url": primary["verification_run_url"],
                "workflow_commit_sha": primary["verification_commit_sha"],
                "conclusion": "success",
                "duration_seconds": 33,
                "rto_seconds": 86400,
                "archive_sha256": primary["asset_sha256"],
                "repository_scoped_source_only": True,
            },
            {
                "source": "mirror",
                "repository": mirror["repository"],
                "run_id": mirror["verification_run_id"],
                "run_url": mirror["verification_run_url"],
                "workflow_commit_sha": mirror["verification_commit_sha"],
                "conclusion": "success",
                "duration_seconds": 37,
                "rto_seconds": 86400,
                "archive_sha256": mirror["asset_sha256"],
                "repository_scoped_source_only": True,
            },
        ],
        "source_closure": {
            "bundle_sha256": source["bundle_sha256"],
            "bundle_restore_verified": source["bundle_restore_verified"],
            "byte_identical_primary_mirror": source[
                "byte_identical_primary_mirror"
            ],
            "primary_verification_run_id": source["primary"]["verification_run_id"],
            "mirror_verification_run_id": source["mirror"]["verification_run_id"],
            "secret_scan_state": source["secret_scan_state"],
        },
        "bound_evidence": {
            "provider_terms_receipt_digest": provider["receipt_digest"],
            "retention_policy_receipt_digest": retention["receipt_digest"],
            "durable_preservation_receipt_digest": durable["receipt_digest"],
            "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        },
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "validation_end": "2020-12-31",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "strategy_evaluation_performed": False,
            "provider_download_performed": False,
        },
        "requires_local_machine": False,
        "maximum_incremental_net_spend_usd": 0,
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_V6_PRODUCTION_PROMOTION_RESTORE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def build_transition_manifest(receipt: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = [
        RECEIPT.relative_to(ROOT).as_posix(),
        DURABLE.relative_to(ROOT).as_posix(),
        ASSET_MANIFEST.relative_to(ROOT).as_posix(),
        RETENTION.relative_to(ROOT).as_posix(),
        PROVIDER_TERMS.relative_to(ROOT).as_posix(),
        OWNER_DIRECTIVE.relative_to(ROOT).as_posix(),
    ]
    common = {
        "target_status": "done",
        "evidence_paths": evidence_paths,
        "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
        "files_touched": evidence_paths,
        "alternative_completion_receipt_set_digest_or_null": receipt[
            "receipt_digest"
        ],
    }
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g2-v6-production-promotion-restore-v1",
        "transaction_id": "G2_CLOSE-5",
        "requested_at_utc": RECORDED_AT_UTC,
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0304",
                "terminal_reason": "v6_archive_promoted_without_reupload",
                "notes": (
                    "The byte-identical primary and owner mirror package is promoted "
                    "under the active zero-incremental-spend production policy."
                ),
                "expected_result": _expected_result("PREV7-0304"),
                **common,
            },
            {
                "task_id": "PREV7-0305",
                "terminal_reason": "two_clean_github_runner_restores_verified",
                "notes": (
                    "Primary and mirror restore independently on clean GitHub runners, "
                    "match the same archive and source bundle, and stay inside RTO."
                ),
                "expected_result": _expected_result("PREV7-0305"),
                **common,
            },
        ],
        "branch_actions": [],
        "gate_actions": [],
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def main() -> int:
    receipt = build_receipt()
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    transition = build_transition_manifest(receipt)
    TRANSITION.parent.mkdir(parents=True, exist_ok=True)
    TRANSITION.write_bytes(canonical_bytes(transition) + b"\n")
    print(json.dumps({"receipt_digest": receipt["receipt_digest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
