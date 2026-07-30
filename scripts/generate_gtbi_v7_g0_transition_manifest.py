"""Generate the reviewed owner-controlled G0 closure manifest."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
DESTINATION = READINESS / "transition_manifests/g0-owner-close-v1.json"
OWNER_ACTOR_ID = "github-user:271768688"
FOUNDATION = "docs/readiness/gtbi-v7/g0_owner_controlled_foundation_report.json"

TASK_ORDER = (
    "PREV7-0001",
    "PREV7-0002",
    "PREV7-0009",
    "PREV7-0006",
    "PREV7-0010",
    "PREV7-0007",
    "PREV7-0008",
    "PREV7-0003",
    "PREV7-0004",
    "PREV7-0005",
    "PREV7-0012",
    "PREV7-0011",
)
TASK_EVIDENCE = {
    "PREV7-0001": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/inventory_github_actions_attempt_receipt.json",
        "docs/readiness/gtbi-v7/local_data_lake_receipt.json",
    ),
    "PREV7-0002": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/legacy_run_cleanup_receipt.json",
    ),
    "PREV7-0003": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/v6_durable_preservation_receipt.json",
        "docs/readiness/gtbi-v7/v6_final_result_scientific_asset_manifest.json",
    ),
    "PREV7-0004": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/locked_evidence_preservation_report.json",
        "docs/readiness/gtbi-v7/locked_evidence_primary_verification.json",
        "docs/readiness/gtbi-v7/locked_evidence_mirror_verification.json",
    ),
    "PREV7-0005": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/v6_dependency_recovery_report.json",
        "docs/readiness/gtbi-v7/v6_final_result_scientific_asset_manifest.json",
    ),
    "PREV7-0006": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/v6_durable_preservation_receipt.json",
        "docs/readiness/gtbi-v7/owner_decisions.json",
    ),
    "PREV7-0007": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/owner_decisions.json",
        "docs/readiness/gtbi-v7/locked_evidence_primary_verification.json",
    ),
    "PREV7-0008": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/v6_data_pack_primary_verification.json",
        "docs/readiness/gtbi-v7/v6_data_pack_mirror_verification.json",
        "docs/readiness/gtbi-v7/locked_evidence_primary_verification.json",
        "docs/readiness/gtbi-v7/locked_evidence_mirror_verification.json",
    ),
    "PREV7-0009": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/github_packages_inventory_receipt.json",
        "docs/readiness/gtbi-v7/owner_decisions.json",
    ),
    "PREV7-0010": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/state_controller_manifest.json",
        "docs/readiness/gtbi-v7/state_controller_recovery_receipt.json",
        "docs/readiness/gtbi-v7/state_controller_smoke_receipt.json",
    ),
    "PREV7-0011": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/owner_simplification_directive.json",
        "docs/readiness/gtbi-v7/state_controller_recovery_receipt.json",
    ),
    "PREV7-0012": (
        FOUNDATION,
        "docs/readiness/gtbi-v7/v6_preservation_lease_public_receipt.json",
        "docs/readiness/gtbi-v7/locked_evidence_preservation_report.json",
        "docs/readiness/gtbi-v7/locked_evidence_primary_verification.json",
        "docs/readiness/gtbi-v7/locked_evidence_mirror_verification.json",
    ),
}
TERMINAL_REASONS = {
    "PREV7-0001": "github_inventory_and_local_lake_inventoried",
    "PREV7-0002": "legacy_capacity_cleanup_complete",
    "PREV7-0003": "v6_final_result_preserved",
    "PREV7-0004": "locked_evidence_preserved_without_opening",
    "PREV7-0005": "v6_dependency_recovery_classified",
    "PREV7-0006": "owner_controlled_private_storage_verified",
    "PREV7-0007": "ephemeral_github_token_path_verified",
    "PREV7-0008": "preservation_and_restore_workflows_verified",
    "PREV7-0009": "owner_controlled_access_foundation_complete",
    "PREV7-0010": "state_controller_github_smoke_success",
    "PREV7-0011": "normal_g0_path_selected",
    "PREV7-0012": "github_preservation_lease_verified",
}


def _task_expected_results() -> dict[str, str]:
    with (READINESS / "task_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        return {
            row["id"]: row["expected_result"]
            for row in csv.DictReader(handle)
        }


def _evidence_set(paths: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {"path": path, "sha256": raw_sha256(ROOT / path)}
        for path in paths
    ]


def _task_action(
    task_id: str,
    expected_results: dict[str, str],
    alternative_digest: str,
) -> dict[str, Any]:
    paths = TASK_EVIDENCE[task_id]
    return {
        "task_id": task_id,
        "target_status": (
            "cancelled" if task_id == "PREV7-0011" else "done"
        ),
        "evidence_paths": list(paths),
        "evidence_sha256": [raw_sha256(ROOT / path) for path in paths],
        "terminal_reason": TERMINAL_REASONS[task_id],
        "notes": (
            "Owner-controlled completion under "
            "owner_simplification_directive_v1."
        ),
        "files_touched": list(paths),
        "expected_result": expected_results[task_id],
        "alternative_completion_receipt_set_digest_or_null": (
            alternative_digest if task_id == "PREV7-0011" else None
        ),
    }


def _branch_action(
    *,
    branch_id: str,
    task_id: str,
    selected_successor: str,
) -> dict[str, str]:
    evidence_digest = domain_digest(
        "GTBI_V7_BRANCH_PREDICATE_EVIDENCE_V1",
        _evidence_set(TASK_EVIDENCE[task_id]),
    )
    decision_digest = domain_digest(
        "GTBI_V7_BRANCH_DECISION_RECEIPT_V1",
        {
            "branch_id": branch_id,
            "owner_actor_id": OWNER_ACTOR_ID,
            "predicate_evidence_digest": evidence_digest,
            "selected_successor": selected_successor,
            "task_id": task_id,
        },
    )
    return {
        "branch_id": branch_id,
        "task_id": task_id,
        "selected_successor": selected_successor,
        "predicate_evidence_digest": evidence_digest,
        "decision_receipt_digest": decision_digest,
    }


def build_manifest() -> dict[str, Any]:
    expected_results = _task_expected_results()
    all_evidence = sorted(
        {
            path
            for paths in TASK_EVIDENCE.values()
            for path in paths
        }
    )
    alternative_digest = domain_digest(
        "GTBI_V7_G0_READY_EXCEPT_0011_ALTERNATIVE_V1",
        _evidence_set(tuple(all_evidence)),
    )
    inventory = json.loads(
        (
            READINESS / "inventory_github_actions_attempt_receipt.json"
        ).read_text(encoding="utf-8")
    )
    branch_actions = [
        _branch_action(
            branch_id="V6_FINAL_SOURCE",
            task_id="PREV7-0003",
            selected_successor="remote_original_preserved",
        ),
        _branch_action(
            branch_id="EMERGENCY_ESCROW",
            task_id="PREV7-0012",
            selected_successor="normal_preservation_complete",
        ),
        _branch_action(
            branch_id="G0_BOOTSTRAP_DISPOSITION",
            task_id="PREV7-0011",
            selected_successor="g0_ready_alternative_completion",
        ),
    ]
    manifest = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g0-owner-close-v1",
        "transaction_id": "G0_CLOSE-2",
        "requested_at_utc": "2026-07-30T16:00:00Z",
        "actor_id": OWNER_ACTOR_ID,
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            _task_action(task_id, expected_results, alternative_digest)
            for task_id in TASK_ORDER
        ],
        "branch_actions": branch_actions,
        "gate_actions": [
            {
                "gate_id": "G0",
                "target_status": "green",
                "selected_branch_id_or_null": (
                    "G0_BOOTSTRAP_DISPOSITION"
                ),
                "inventory_snapshot_digest": inventory[
                    "inventory_snapshot_digest"
                ],
                "evidence_bundle_digest": domain_digest(
                    "GTBI_V7_G0_EVIDENCE_BUNDLE_V1",
                    _evidence_set(tuple(all_evidence)),
                ),
            }
        ],
        "owner_directive_digest": raw_sha256(
            READINESS / "owner_simplification_directive.json"
        ),
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def main() -> int:
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_bytes(canonical_bytes(build_manifest()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
