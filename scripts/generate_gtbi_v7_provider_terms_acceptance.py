"""Freeze the repository-owner provider/data terms decision for PREV7-0302."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
INVENTORY = READINESS / "provider_terms_inventory.json"
REVIEW = READINESS / "provider_terms_review.md"
OWNER_DECISIONS = READINESS / "owner_decisions.json"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
LOCAL_DATA = READINESS / "local_data_lake_receipt.json"
GITHUB_DATA = READINESS / "frozen_data_lake_github_release_receipt.json"
RECEIPT = READINESS / "g2_provider_terms_acceptance_receipt.json"
MANIFEST = READINESS / "transition_manifests/g2-provider-terms-acceptance-v1.json"
RECORDED_AT_UTC = "2026-07-31T18:35:00Z"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_expected_result() -> str:
    with (READINESS / "task_status.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return next(row["expected_result"] for row in rows if row["id"] == "PREV7-0302")


def build_receipt() -> dict[str, Any]:
    inventory = _load(INVENTORY)
    decisions = _load(OWNER_DECISIONS)
    directive = _load(OWNER_DIRECTIVE)
    if inventory["inventory_status"] != "owner_reviewed":
        raise ValueError("provider terms inventory is not owner reviewed")
    if inventory["owner_acceptance"] != "accepted_explicitly":
        raise ValueError("provider terms are not explicitly accepted")
    if inventory["current_v7_data_input"] != "owner_supplied_frozen_local_data_lake":
        raise ValueError("current V7 input changed")
    if inventory["findings"]["current_provider_download_required"]:
        raise ValueError("current V7 input unexpectedly requires a provider download")
    if inventory["findings"]["yahoo_automated_collection_permission"] != (
        "not_evidenced_no_new_collection_authorized"
    ):
        raise ValueError("Yahoo no-new-collection boundary changed")
    if inventory["future_refresh_authorization"] != "deferred_until_owner_requests_refresh":
        raise ValueError("future refresh was authorized implicitly")
    if decisions["decisions"]["licences"]["independent_review_receipt"] != "not_required":
        raise ValueError("owner-controlled terms model changed")
    if decisions["decisions"]["budget"]["maximum_incremental_net_spend_usd"] != 0:
        raise ValueError("provider decision exceeds the owner budget")
    if "remove_three_independent_audit_requirement" not in directive["authorization_scope"]:
        raise ValueError("owner simplification directive is incomplete")

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g2_provider_terms_acceptance_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "task_id": "PREV7-0302",
        "recorded_at_utc": RECORDED_AT_UTC,
        "owner_actor_id": "github-user:271768688",
        "decision": "accepted_for_frozen_input_only",
        "current_v7_data_input": "owner_supplied_frozen_local_data_lake",
        "current_provider_download_required": False,
        "new_yahoo_or_yfinance_collection_authorized": False,
        "future_refresh_provider": "tiingo_daily",
        "future_refresh_authorized_now": False,
        "future_refresh_requires_new_owner_instruction": True,
        "independent_terms_reviewer_required": False,
        "maximum_incremental_net_spend_usd": 0,
        "evidence": {
            "provider_terms_inventory_sha256": raw_sha256(INVENTORY),
            "provider_terms_review_sha256": raw_sha256(REVIEW),
            "owner_decisions_sha256": raw_sha256(OWNER_DECISIONS),
            "owner_directive_sha256": raw_sha256(OWNER_DIRECTIVE),
            "local_data_lake_receipt_sha256": raw_sha256(LOCAL_DATA),
            "github_data_lake_receipt_sha256": raw_sha256(GITHUB_DATA),
        },
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "provider_download_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G2_PROVIDER_TERMS_ACCEPTANCE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def build_manifest(receipt: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = [
        RECEIPT.relative_to(ROOT).as_posix(),
        INVENTORY.relative_to(ROOT).as_posix(),
        REVIEW.relative_to(ROOT).as_posix(),
        OWNER_DECISIONS.relative_to(ROOT).as_posix(),
        OWNER_DIRECTIVE.relative_to(ROOT).as_posix(),
        LOCAL_DATA.relative_to(ROOT).as_posix(),
        GITHUB_DATA.relative_to(ROOT).as_posix(),
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g2-provider-terms-acceptance-v1",
        "transaction_id": "G2_CLOSE-4",
        "requested_at_utc": RECORDED_AT_UTC,
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0302",
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
                "terminal_reason": "owner_accepted_versioned_provider_terms_for_frozen_input",
                "notes": (
                    "The current input is the already frozen data lake. No provider "
                    "download or new Yahoo collection is authorized. Tiingo remains an "
                    "optional future refresh source requiring a new owner instruction."
                ),
                "files_touched": evidence_paths,
                "expected_result": _task_expected_result(),
                "alternative_completion_receipt_set_digest_or_null": receipt[
                    "receipt_digest"
                ],
            }
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


def verify_committed() -> None:
    receipt = _load(RECEIPT)
    manifest = _load(MANIFEST)
    if RECEIPT.read_bytes() != canonical_bytes(receipt) + b"\n":
        raise ValueError("provider terms receipt is not canonical")
    if MANIFEST.read_bytes() != canonical_bytes(manifest) + b"\n":
        raise ValueError("provider terms manifest is not canonical")
    if receipt != build_receipt():
        raise ValueError("provider terms receipt drift")
    if manifest != build_manifest(receipt):
        raise ValueError("provider terms manifest drift")


def main() -> int:
    receipt = build_receipt()
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(canonical_bytes(build_manifest(receipt)) + b"\n")
    verify_committed()
    print(receipt["receipt_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
