"""Generate the owner-controlled G1B role registry and closure contract."""

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
from infra.gtbi_v7_readiness.roles import validate_role_registry

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
FIXTURE = (
    ROOT
    / "config/gtbi/fixtures/v7/governance/"
    "role_registry_v1.owner_controlled.json"
)
SCHEMA = ROOT / "config/gtbi/schemas/readiness/role_registry_v1.schema.json"
REGISTRY = ROOT / "config/gtbi/governance/role_registry.json"
RECEIPT = READINESS / "g1b_role_registry_receipt.json"
MANIFEST = READINESS / "transition_manifests/g1b-role-registry-close-v1.json"
OWNER_ACTOR_ID = "github-user:271768688"
RECORDED_AT_UTC = "2026-07-30T18:30:00Z"


def _json_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_payload(path: Path) -> dict[str, Any]:
    payload = _json_payload(path)
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"{path.name} is not canonical JSON")
    return payload


def _expected_result() -> str:
    with (READINESS / "task_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        row = next(
            item
            for item in csv.DictReader(handle)
            if item["id"] == "PREV7-0201"
        )
    return row["expected_result"]


def build_registry() -> dict[str, Any]:
    registry = _json_payload(FIXTURE)
    validate_role_registry(registry, SCHEMA)
    assignments = registry["assignments"]
    if registry["registry_status"] != "active":
        raise ValueError("owner-controlled registry is not active")
    if any(item["status"] != "active" for item in assignments):
        raise ValueError("owner-controlled registry contains vacancies")
    if {item["actor_id"] for item in assignments} != {OWNER_ACTOR_ID}:
        raise ValueError("legacy capability labels are not owner-controlled")
    return registry


def build_receipt(registry: dict[str, Any]) -> dict[str, Any]:
    owner_directive = _canonical_payload(
        READINESS / "owner_simplification_directive.json"
    )
    owner_decisions = _canonical_payload(READINESS / "owner_decisions.json")
    g1a_receipt = _canonical_payload(
        READINESS / "g1a_state_transition_reconciliation_receipt.json"
    )
    if g1a_receipt["post_apply_state"]["g1a_gate_status"] != "green":
        raise ValueError("G1A is not reconciled as green")
    if g1a_receipt["verified_properties"]["locked_data_accessed"]:
        raise ValueError("G1A reconciliation accessed locked data")

    assignments = registry["assignments"]
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g1b_role_registry_receipt_v1",
        "decision_id": "g1b-owner-controlled-role-registry-v1",
        "recorded_at_utc": RECORDED_AT_UTC,
        "owner_actor_id": OWNER_ACTOR_ID,
        "repository": "trading-optimizer-lab-org/aurora",
        "registry": {
            "path": "config/gtbi/governance/role_registry.json",
            "file_sha256": raw_sha256(REGISTRY),
            "role_registry_digest": registry["role_registry_digest"],
            "registry_status": registry["registry_status"],
            "assignment_count": len(assignments),
            "active_assignment_count": sum(
                item["status"] == "active" for item in assignments
            ),
            "vacant_assignment_count": sum(
                item["status"] == "vacant" for item in assignments
            ),
            "unique_actor_ids": sorted(
                {item["actor_id"] for item in assignments}
            ),
        },
        "owner_directive": {
            "path": (
                "docs/readiness/gtbi-v7/"
                "owner_simplification_directive.json"
            ),
            "file_sha256": raw_sha256(
                READINESS / "owner_simplification_directive.json"
            ),
            "schema_version": owner_directive["schema_version"],
            "distinct_people_required": False,
            "external_custodians_required": False,
        },
        "owner_decisions": {
            "path": "docs/readiness/gtbi-v7/owner_decisions.json",
            "file_sha256": raw_sha256(READINESS / "owner_decisions.json"),
            "owner_controlled_model": owner_decisions["decisions"][
                "audits_and_people"
            ]["owner_controlled_model"],
        },
        "g1a_reconciliation": {
            "path": (
                "docs/readiness/gtbi-v7/"
                "g1a_state_transition_reconciliation_receipt.json"
            ),
            "file_sha256": raw_sha256(
                READINESS
                / "g1a_state_transition_reconciliation_receipt.json"
            ),
            "receipt_digest": g1a_receipt["receipt_digest"],
        },
        "verified_properties": {
            "all_legacy_capability_labels_assigned": True,
            "all_assignments_active": True,
            "additional_people_required": False,
            "incompatibility_sets_enforced": False,
            "incompatibility_sets_documentation_only": True,
            "locked_data_accessed": False,
            "owner_controlled": True,
            "scientific_work_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G1B_ROLE_REGISTRY_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def _evidence_set(paths: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {"path": path, "sha256": raw_sha256(ROOT / path)}
        for path in paths
    ]


def build_manifest() -> dict[str, Any]:
    evidence_paths = (
        "docs/readiness/gtbi-v7/g1b_role_registry_receipt.json",
        "docs/readiness/gtbi-v7/owner_simplification_directive.json",
        (
            "docs/readiness/gtbi-v7/"
            "g1a_state_transition_reconciliation_receipt.json"
        ),
    )
    with (READINESS / "gate_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        gate_rows = {
            row["gate_id"]: row
            for row in csv.DictReader(handle)
        }
    inventory_digest = gate_rows["G1A"][
        "inventory_snapshot_digest_or_null"
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g1b-role-registry-close-v1",
        "transaction_id": "G1B_CLOSE-1",
        "requested_at_utc": RECORDED_AT_UTC,
        "actor_id": OWNER_ACTOR_ID,
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0201",
                "target_status": "done",
                "evidence_paths": list(evidence_paths),
                "evidence_sha256": [
                    raw_sha256(ROOT / path) for path in evidence_paths
                ],
                "terminal_reason": (
                    "owner_controlled_role_registry_accepted"
                ),
                "notes": (
                    "Legacy capability labels are assigned to the repository "
                    "owner under the explicit simplification directive; no "
                    "additional people, scientific work or locked access."
                ),
                "files_touched": list(evidence_paths),
                "expected_result": _expected_result(),
                "alternative_completion_receipt_set_digest_or_null": None,
            }
        ],
        "branch_actions": [],
        "gate_actions": [
            {
                "gate_id": "G1B",
                "target_status": "green",
                "selected_branch_id_or_null": None,
                "inventory_snapshot_digest": inventory_digest,
                "evidence_bundle_digest": domain_digest(
                    "GTBI_V7_G1B_EVIDENCE_BUNDLE_V1",
                    _evidence_set(evidence_paths),
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
    registry = build_registry()
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_bytes(canonical_bytes(registry) + b"\n")
    RECEIPT.write_bytes(canonical_bytes(build_receipt(registry)) + b"\n")
    MANIFEST.write_bytes(canonical_bytes(build_manifest()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
