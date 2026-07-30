"""Generate the reviewed dry-run manifest for the controller smoke test."""

from __future__ import annotations

from pathlib import Path

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
DESTINATION = READINESS / "transition_manifests/state-controller-smoke-v1.json"


def build_manifest() -> dict:
    evidence_path = (
        "docs/readiness/gtbi-v7/"
        "inventory_github_actions_attempt_receipt.json"
    )
    owner_decisions = READINESS / "owner_decisions.json"
    manifest = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "state-controller-smoke-v1",
        "transaction_id": "G0_CLOSE-1",
        "requested_at_utc": "2026-07-30T15:00:00Z",
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0001",
                "target_status": "done",
                "evidence_paths": [evidence_path],
                "evidence_sha256": [raw_sha256(ROOT / evidence_path)],
                "terminal_reason": "github_inventory_verified",
                "notes": (
                    "Dry-run-only smoke projection over reviewed G0 evidence."
                ),
                "files_touched": [
                    evidence_path,
                    "docs/readiness/gtbi-v7/"
                    "g0_owner_controlled_foundation_report.json",
                ],
                "expected_result": "inventory_evidence_complete",
                "alternative_completion_receipt_set_digest_or_null": None,
            }
        ],
        "branch_actions": [],
        "gate_actions": [],
        "owner_directive_digest": raw_sha256(owner_decisions),
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def main() -> int:
    manifest = build_manifest()
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_bytes(canonical_bytes(manifest) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
