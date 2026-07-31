"""Generate the deterministic owner-auth completion and G3A transition."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.g3a_governance import (
    REPOSITORY_OWNER_ACTOR_ID,
)
from infra.gtbi_v7_readiness.g3a_owner_auth import (
    G3A_OWNER_AUTH_TASK_IDS,
    build_owner_auth_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
RECEIPT = READINESS / "g3a_owner_auth_completion_receipt.json"
MANIFEST = (
    READINESS
    / "transition_manifests/g3a-owner-auth-close-v1.json"
)

SOURCE_PATHS = {
    "owner_simplification_directive.json": (
        READINESS / "owner_simplification_directive.json"
    ),
    "owner_decisions.json": READINESS / "owner_decisions.json",
    "g0_owner_controlled_foundation_report.json": (
        READINESS / "g0_owner_controlled_foundation_report.json"
    ),
    "g3a_github_live_receipt.json": (
        READINESS / "g3a_github_live_receipt.json"
    ),
    "frozen_data_lake_github_release_receipt.json": (
        READINESS / "frozen_data_lake_github_release_receipt.json"
    ),
    "github_packages_inventory_receipt.json": (
        READINESS / "github_packages_inventory_receipt.json"
    ),
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _task_rows() -> list[dict[str, str]]:
    with (READINESS / "task_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        return list(csv.DictReader(handle))


def _expected_results(rows: list[dict[str, str]]) -> dict[str, str]:
    return {
        row["id"]: row["expected_result"]
        for row in rows
        if row["id"] in G3A_OWNER_AUTH_TASK_IDS
    }


def build_receipt(*, recorded_at_utc: str) -> dict[str, Any]:
    evidence_sha256 = {
        name: raw_sha256(path) for name, path in SOURCE_PATHS.items()
    }
    return build_owner_auth_receipt(
        owner_directive=_read_json(
            SOURCE_PATHS["owner_simplification_directive.json"]
        ),
        owner_decisions=_read_json(SOURCE_PATHS["owner_decisions.json"]),
        foundation=_read_json(
            SOURCE_PATHS["g0_owner_controlled_foundation_report.json"]
        ),
        live_baseline=_read_json(
            SOURCE_PATHS["g3a_github_live_receipt.json"]
        ),
        frozen_data_release=_read_json(
            SOURCE_PATHS["frozen_data_lake_github_release_receipt.json"]
        ),
        packages_inventory=_read_json(
            SOURCE_PATHS["github_packages_inventory_receipt.json"]
        ),
        task_rows=_task_rows(),
        evidence_file_sha256=evidence_sha256,
        recorded_at_utc=recorded_at_utc,
    )


def _repo_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def build_transition_manifest(
    receipt: dict[str, Any],
    *,
    requested_at_utc: str,
) -> dict[str, Any]:
    rows = _task_rows()
    expected_results = _expected_results(rows)
    receipt_path = _repo_path(RECEIPT)
    evidence_paths = [
        receipt_path,
        *(_repo_path(path) for path in SOURCE_PATHS.values()),
    ]
    evidence_sha256 = [raw_sha256(ROOT / path) for path in evidence_paths]
    alternative_digest = receipt["receipt_digest"]
    owner_directive_digest = raw_sha256(
        SOURCE_PATHS["owner_simplification_directive.json"]
    )
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g3a-owner-auth-close-v1",
        "transaction_id": "G3A_CLOSE-2",
        "requested_at_utc": requested_at_utc,
        "actor_id": REPOSITORY_OWNER_ACTOR_ID,
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": task_id,
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": evidence_sha256,
                "terminal_reason": {
                    "PREV7-0204": (
                        "owner_controlled_ephemeral_auth_alternative_verified"
                    ),
                    "PREV7-0210": (
                        "owner_controlled_environments_and_auth_verified"
                    ),
                }[task_id],
                "notes": (
                    "Owner-authorized alternative completion uses GitHub's "
                    "repository-scoped ephemeral token, no permanent App key, "
                    "no external broker, no incremental spend, no scientific "
                    "processing and no locked-data access."
                ),
                "files_touched": evidence_paths,
                "expected_result": expected_results[task_id],
                "alternative_completion_receipt_set_digest_or_null": (
                    alternative_digest
                ),
            }
            for task_id in G3A_OWNER_AUTH_TASK_IDS
        ],
        "branch_actions": [
            {
                "branch_id": "APP_PRIVATE_KEY_IMPORT",
                "task_id": "PREV7-0204",
                "selected_successor": (
                    "owner_controlled_ephemeral_github_token"
                ),
                "predicate_evidence_digest": alternative_digest,
                "decision_receipt_digest": alternative_digest,
            }
        ],
        "gate_actions": [
            {
                "gate_id": "G3A",
                "target_status": "green",
                "selected_branch_id_or_null": "APP_PRIVATE_KEY_IMPORT",
                "inventory_snapshot_digest": raw_sha256(
                    SOURCE_PATHS["g3a_github_live_receipt.json"]
                ),
                "evidence_bundle_digest": alternative_digest,
            }
        ],
        "owner_directive_digest": owner_directive_digest,
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recorded-at-utc",
        required=True,
        help="Stable UTC timestamp used for deterministic regeneration.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = build_receipt(recorded_at_utc=args.recorded_at_utc)
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    manifest = build_transition_manifest(
        receipt,
        requested_at_utc=args.recorded_at_utc,
    )
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(canonical_bytes(manifest) + b"\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
