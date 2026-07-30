"""Generate durable GTBI V6 preservation and legacy cleanup evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path
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
    seal_asset_manifest,
)
from scripts.generate_gtbi_v7_scientific_asset_contract import (  # noqa: E402
    wrapper_only_fixture,
)

READINESS = ROOT / "docs/readiness/gtbi-v7"
PRESERVATION_PATH = READINESS / "v6_durable_preservation_receipt.json"
SCIENTIFIC_MANIFEST_PATH = (
    READINESS / "v6_final_result_scientific_asset_manifest.json"
)
CLEANUP_PATH = READINESS / "legacy_run_cleanup_receipt.json"

ARCHIVE_NAME = (
    "global-technical-buy-indicator-long-hold-fast-strict-v6-results.zip"
)
ARCHIVE_SHA256 = (
    "sha256:"
    "870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b"
)
ARCHIVE_SIZE = 1_962_204_087
SOURCE_BUNDLE_SHA256 = (
    "sha256:"
    "c0c3a4a7f27339667500dcdc267499c15ac3185992f492614a7587f2f0556417"
)
SOURCE_BUNDLE_SIZE = 11_842_293

SOURCE_BUNDLE_COMMON = {
    "source_repository": "trading-optimizer-lab-org/aurora",
    "source_repository_id": 1_232_647_748,
    "source_tag": "gtbi-v6-fast-strict-run-29162930823",
    "source_tag_object_sha": (
        "a458f1ce0a3d060cf359bfdb7537488771ffd6f7"
    ),
    "source_tag_ruleset_id": 20_042_385,
    "source_commit_sha": "cb80c5065c127322a303d58aea0f6c05337a6c9e",
    "source_tree_sha": "032bcda1035b5ea5f23e940ec5e33d2975ec319b",
    "workflow_git_blob_sha": (
        "5294397f0ce709f6a65c353389e5f40a5a2ca09f"
    ),
    "workflow_sha256": (
        "sha256:"
        "87e98bc51999eaa03aeb402bc98b0438860c224bf49937605a73a16901f0784f"
    ),
    "reachable_commit_count": 451,
    "reachable_object_count": 6_489,
    "submodules": [],
    "lfs_pointers": [],
    "bundle_name": "gtbi-v6-fast-strict-run-29162930823.source.bundle",
    "bundle_size_bytes": SOURCE_BUNDLE_SIZE,
    "bundle_sha256": SOURCE_BUNDLE_SHA256,
    "bundle_restore_verified": True,
    "gitleaks_version": "8.30.1",
    "gitleaks_finding_count": 0,
    "gitleaks_ignored_test_fixture_count": 4,
    "dependency_files": [
        {
            "path": "pyproject.toml",
            "git_blob_sha": "5e31308f4b1c0ba069ddfa1a99db4ed54828eecf",
            "sha256": (
                "sha256:"
                "7e0de45d607ac02430df2e39aa158dffb25c378558cfdb66392bb4ab758a20e6"
            ),
            "size_bytes": 6_249,
        },
        {
            "path": "requirements/gtbi-fast-strict.lock",
            "git_blob_sha": "072e6ee052c14c224d1f4294853d773a4fb730f6",
            "sha256": (
                "sha256:"
                "e0ebac1931c2cb66686b8adbf9262d89c177ad1e75af822f83a323199fa763e6"
            ),
            "size_bytes": 177,
        },
    ],
}

SOURCE_BUNDLE_PRIMARY = {
    "repository": "trading-optimizer-lab-org/aurora-v7-assets",
    "repository_id": 1_317_002_870,
    "release_id": 362_325_816,
    "bundle_asset_id": 495_358_528,
    "bundle_asset_sha256": SOURCE_BUNDLE_SHA256,
    "bundle_asset_size_bytes": SOURCE_BUNDLE_SIZE,
    "manifest_asset_id": 495_358_531,
    "manifest_asset_sha256": (
        "sha256:"
        "e618bc4a5a805bdbb2956d828c4ffb4c394b394d91fc4b5e369bdf88aeca8f56"
    ),
    "manifest_digest": (
        "sha256:"
        "f92070f4fd9ba988d2a930db5b241fe5da5dfe57b4a2f83542a6f38fe8dd1e3d"
    ),
    "verification_run_id": 30_544_068_594,
    "verification_run_url": (
        "https://github.com/trading-optimizer-lab-org/"
        "aurora-v7-assets/actions/runs/30544068594"
    ),
    "verification_workflow_commit_sha": (
        "534e486db17f862d6e8aeddf9a2ba70959297120"
    ),
}

SOURCE_BUNDLE_MIRROR = {
    "repository": "trading-optimizer-lab-org/aurora-v7-assets-mirror",
    "repository_id": 1_317_082_575,
    "release_id": 362_325_841,
    "bundle_asset_id": 495_358_568,
    "bundle_asset_sha256": SOURCE_BUNDLE_SHA256,
    "bundle_asset_size_bytes": SOURCE_BUNDLE_SIZE,
    "manifest_asset_id": 495_358_567,
    "manifest_asset_sha256": (
        "sha256:"
        "9297d5d7880e08db15969c7ce207a93d6c9684a097471b099bc367877f9b8c42"
    ),
    "manifest_digest": (
        "sha256:"
        "699a01a7bfc39c8adbd1e1a0e3b0a1f65ee8dda765036d981be24660987cb3b6"
    ),
    "verification_run_id": 30_544_079_501,
    "verification_run_url": (
        "https://github.com/trading-optimizer-lab-org/"
        "aurora-v7-assets-mirror/actions/runs/30544079501"
    ),
    "verification_workflow_commit_sha": (
        "5b4914e93a499d2e411838170829fa71acb78d93"
    ),
}

PRIMARY = {
    "repository": "trading-optimizer-lab-org/aurora-v7-assets",
    "repository_id": 1_317_002_870,
    "release_id": 362_325_816,
    "release_tag": "gtbi-v6-fast-strict-run-29162930823",
    "release_url": (
        "https://github.com/trading-optimizer-lab-org/aurora-v7-assets/"
        "releases/tag/gtbi-v6-fast-strict-run-29162930823"
    ),
    "published_at_utc": "2026-07-30T12:18:41Z",
    "asset_id": 495_309_998,
    "asset_node_id": "RA_kwDOTn_eds4dhdSu",
    "asset_name": ARCHIVE_NAME,
    "asset_size_bytes": ARCHIVE_SIZE,
    "asset_sha256": ARCHIVE_SHA256,
    "verification_run_id": 30_541_859_386,
    "verification_run_url": (
        "https://github.com/trading-optimizer-lab-org/aurora-v7-assets/"
        "actions/runs/30541859386"
    ),
    "verification_commit_sha": (
        "f284f46599c41caa857dac6edeb627c58024b892"
    ),
    "verification_receipt_asset_id": 495_327_999,
    "verification_receipt_asset_sha256": (
        "sha256:"
        "e3e698b66e4c6bb6fec45b6bce712ee0c4b09e9981ea8ab9450da3ba03e0ada0"
    ),
    "verification_receipt_digest": (
        "sha256:"
        "6e667358ac85011caca0d521e3554297b0829eb93823098ae11dad5148114c55"
    ),
}

MIRROR = {
    "repository": "trading-optimizer-lab-org/aurora-v7-assets-mirror",
    "repository_id": 1_317_082_575,
    "release_id": 362_325_841,
    "release_tag": "gtbi-v6-fast-strict-run-29162930823",
    "release_url": (
        "https://github.com/trading-optimizer-lab-org/"
        "aurora-v7-assets-mirror/releases/tag/"
        "gtbi-v6-fast-strict-run-29162930823"
    ),
    "published_at_utc": "2026-07-30T12:18:43Z",
    "asset_id": 495_309_999,
    "asset_node_id": "RA_kwDOToEVz84dhdSv",
    "asset_name": ARCHIVE_NAME,
    "asset_size_bytes": ARCHIVE_SIZE,
    "asset_sha256": ARCHIVE_SHA256,
    "verification_run_id": 30_541_861_880,
    "verification_run_url": (
        "https://github.com/trading-optimizer-lab-org/"
        "aurora-v7-assets-mirror/actions/runs/30541861880"
    ),
    "verification_commit_sha": (
        "2de9aee59a5d6d0381979447b992f78b14aef3fe"
    ),
    "verification_receipt_asset_id": 495_328_087,
    "verification_receipt_asset_sha256": (
        "sha256:"
        "d41e7c3c0c0da13e2a90819a81c35c3369a83c4d933f0b915267411b394f67f1"
    ),
    "verification_receipt_digest": (
        "sha256:"
        "17f646586db67e8fba8cf1658a7e2812980262328cd7a92674fe04a328057f08"
    ),
}

DELETED_LEGACY_RUN_IDS = [
    28_317_614_762,
    28_317_861_573,
    28_323_484_289,
    28_324_373_509,
    28_324_446_163,
    28_324_498_140,
    28_324_952_288,
    28_328_399_857,
    28_328_870_601,
    28_334_252_075,
    28_355_636_758,
]
ZOMBIE_RUN_ID = 28_391_122_459


def build_preservation_receipt() -> dict[str, Any]:
    """Build the canonical two-copy owner-controlled custody receipt."""

    owner_directive_path = READINESS / "owner_simplification_directive.json"
    payload: dict[str, Any] = {
        "schema_version": "gtbi_v6_durable_preservation_receipt_v1",
        "recorded_at_utc": "2026-07-30T12:18:43Z",
        "source": {
            "repository": "trading-optimizer-lab-org/aurora",
            "run_id": 29_162_930_823,
            "artifact_id": 8_251_391_531,
            "artifact_name": (
                "global-technical-buy-indicator-long-hold-fast-strict-v6-results"
            ),
            "commit_sha": "cb80c5065c127322a303d58aea0f6c05337a6c9e",
            "workflow_path": (
                ".github/workflows/"
                "global-technical-buy-indicator-external-pack-360jobs.yml"
            ),
            "workflow_sha256": (
                "sha256:"
                "87e98bc51999eaa03aeb402bc98b0438860c224bf49937605a73a16901f0784f"
            ),
            "archive_name": ARCHIVE_NAME,
            "archive_size_bytes": ARCHIVE_SIZE,
            "archive_sha256": ARCHIVE_SHA256,
            "archive_member_count": 47,
            "archive_uncompressed_size_bytes": 5_770_916_655,
        },
        "primary": PRIMARY,
        "mirror": MIRROR,
        "source_closure": {
            **SOURCE_BUNDLE_COMMON,
            "primary": SOURCE_BUNDLE_PRIMARY,
            "mirror": SOURCE_BUNDLE_MIRROR,
            "byte_identical_primary_mirror": True,
            "restore_state": "verified_on_two_clean_github_runners",
            "secret_scan_state": "no_actionable_findings",
            "scientific_recalculation_performed": False,
        },
        "custody_model": "owner_controlled_two_private_github_repositories",
        "owner_simplification_directive_sha256": raw_sha256(
            owner_directive_path.read_bytes()
        ),
        "independent_external_copy_required": False,
        "same_provider_mirror_disclosed": True,
        "github_only_restore_verification": True,
        "requires_local_machine": False,
        "scientific_processing_performed": False,
        "locked_data_opened": False,
        "restoration_state": "verified_on_two_clean_github_runners",
        "formal_task_effects": {
            "PREV7-0003": "evidence_ready",
            "PREV7-0012": "evidence_ready",
            "PREV7-0304": "input_ready",
            "PREV7-0305": "input_ready",
        },
        "receipt_digest": "",
    }
    payload["receipt_digest"] = domain_digest(
        "GTBI_V6_DURABLE_PRESERVATION_RECEIPT_V1",
        payload,
        omit_top_level_fields=("receipt_digest",),
    )
    return payload


def _release_part(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "part_index": 0,
        "repository_id": record["repository_id"],
        "release_id": record["release_id"],
        "asset_id": record["asset_id"],
        "asset_name": record["asset_name"],
        "size_bytes": record["asset_size_bytes"],
        "sha256": record["asset_sha256"],
    }


def build_scientific_manifest(
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the truthful archival wrapper to the two verified releases."""

    receipt = receipt or build_preservation_receipt()
    manifest = wrapper_only_fixture()
    manifest.update(
        {
            "workflow_path": receipt["source"]["workflow_path"],
            "workflow_sha256": receipt["source"]["workflow_sha256"],
            "created_at_utc": "2026-07-11T18:09:30Z",
            "retrieval_cutoff_utc": "2026-07-30T11:57:22Z",
            "provider_terms_review_id": (
                "github-private-release-owner-accepted-2026-07-30"
            ),
            "file_count": receipt["source"]["archive_member_count"],
            "compressed_size_bytes": receipt["source"]["archive_size_bytes"],
            "uncompressed_size_bytes": receipt["source"][
                "archive_uncompressed_size_bytes"
            ],
            "source_object_sha256": receipt["source"]["archive_sha256"],
            "primary_release_repository_id": PRIMARY["repository_id"],
            "primary_release_id": PRIMARY["release_id"],
            "primary_release_asset_count": 1,
            "primary_release_parts": [_release_part(PRIMARY)],
            "mirror_release_repository_id": MIRROR["repository_id"],
            "mirror_release_id": MIRROR["release_id"],
            "mirror_release_asset_count": 1,
            "mirror_release_parts": [_release_part(MIRROR)],
            "latest_restore_receipt_digest": receipt["receipt_digest"],
            "attestation_reference": (
                "docs/readiness/gtbi-v7/"
                "v6_durable_preservation_receipt.json"
            ),
        }
    )
    return seal_asset_manifest(manifest)


def build_cleanup_receipt() -> dict[str, Any]:
    """Record exact cleanup observations and quarantine the GitHub zombie."""

    candidate_manifest = json.loads(
        (READINESS / "legacy_run_cancellation_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    payload: dict[str, Any] = {
        "schema_version": "gtbi_v7_legacy_run_cleanup_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "observed_at_utc": "2026-07-30T12:20:56Z",
        "candidate_manifest_payload_sha256": candidate_manifest[
            "manifest_payload_sha256"
        ],
        "approved_by_actor_id": "github-user:271768688",
        "approval_source": (
            "direct owner authorization to complete the full readiness plan"
        ),
        "deleted_run_count": len(DELETED_LEGACY_RUN_IDS),
        "deleted_runs": [
            {
                "run_id": run_id,
                "terminal_readiness_state": "deleted_api_not_found",
                "latest_get_exit_code": 1,
            }
            for run_id in DELETED_LEGACY_RUN_IDS
        ],
        "quarantined_external_zombie": {
            "run_id": ZOMBIE_RUN_ID,
            "github_status": "queued",
            "github_conclusion": None,
            "created_at_utc": "2026-06-29T17:37:20Z",
            "updated_at_utc": "2026-06-29T17:37:20Z",
            "job_count": 0,
            "artifact_count": 0,
            "head_sha": "b245abb9fb6ddec6dfd3089f3194d78672c8d0b2",
            "workflow_id": 301_040_582,
            "cancel_http_status": 500,
            "cancel_request_id": (
                "8E74:1393AA:3411E65:317C68B:6A6B41A7"
            ),
            "force_cancel_http_status": 500,
            "force_cancel_request_id": (
                "8C4D:EA58F:3187448:2EEDC2A:6A6B41A7"
            ),
            "delete_http_status": 403,
            "delete_request_id": (
                "8D94:1208B8:328CCDB:2FE92E8:6A6B41A8"
            ),
            "capacity_effect": "none_zero_jobs",
            "evidence_effect": "none_zero_artifacts",
            "readiness_disposition": (
                "owner_authorized_external_zombie_quarantine"
            ),
        },
        "source_v6_run_excluded_and_preserved": 29_162_930_823,
        "cleanup_complete_for_executable_or_evidentiary_risk": True,
        "github_state_fully_terminal": False,
        "formal_task_effect": (
            "PREV7-0002_alternative_complete_external_zombie_disclosed"
        ),
        "receipt_digest": "",
    }
    payload["receipt_digest"] = domain_digest(
        "GTBI_V7_LEGACY_RUN_CLEANUP_RECEIPT_V1",
        payload,
        omit_top_level_fields=("receipt_digest",),
    )
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def main() -> int:
    preservation = build_preservation_receipt()
    manifest = build_scientific_manifest(preservation)
    cleanup = build_cleanup_receipt()
    _write(PRESERVATION_PATH, preservation)
    _write(SCIENTIFIC_MANIFEST_PATH, manifest)
    _write(CLEANUP_PATH, cleanup)
    print(
        json.dumps(
            {
                "preservation_receipt": str(
                    PRESERVATION_PATH.relative_to(ROOT)
                ),
                "preservation_receipt_digest": preservation[
                    "receipt_digest"
                ],
                "scientific_manifest": str(
                    SCIENTIFIC_MANIFEST_PATH.relative_to(ROOT)
                ),
                "scientific_manifest_digest": manifest[
                    "asset_manifest_digest"
                ],
                "cleanup_receipt": str(CLEANUP_PATH.relative_to(ROOT)),
                "cleanup_receipt_digest": cleanup["receipt_digest"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
