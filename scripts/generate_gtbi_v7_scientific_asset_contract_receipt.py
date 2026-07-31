"""Freeze PREV7-0303 scientific-asset contract evidence."""

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
    DOMAIN,
    SCIENTIFIC_ASSET_FIELDS,
    lifecycle_state,
    validate_scientific_asset_manifest,
)
from scripts.generate_gtbi_v7_scientific_asset_contract import (  # noqa: E402
    FIXTURE_PATH,
    SCHEMA_PATH,
    wrapper_only_fixture,
)

READINESS = ROOT / "docs/readiness/gtbi-v7"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
HASH_REGISTRY = ROOT / "config/gtbi/contracts/hash_domain_registry_v1.json"
VALIDATOR = ROOT / "infra/gtbi_v7_readiness/scientific_assets.py"
RECEIPT = READINESS / "g2_scientific_asset_contract_receipt.json"
MANIFEST = READINESS / "transition_manifests/g2-scientific-asset-contract-v1.json"
RECORDED_AT_UTC = "2026-07-31T18:50:00Z"


def _task_expected_result() -> str:
    with (READINESS / "task_status.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return next(row["expected_result"] for row in rows if row["id"] == "PREV7-0303")


def _load_canonical(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(value) + b"\n":
        raise ValueError(f"non-canonical contract file: {path.relative_to(ROOT)}")
    return value


def build_receipt() -> dict[str, Any]:
    schema = _load_canonical(SCHEMA_PATH)
    fixture = _load_canonical(FIXTURE_PATH)
    registry = _load_canonical(HASH_REGISTRY)
    expected_fixture = wrapper_only_fixture()
    if fixture != expected_fixture:
        raise ValueError("scientific asset wrapper fixture drift")
    validate_scientific_asset_manifest(fixture)
    bindings = [
        row
        for row in registry["ordered_schema_bindings"]
        if row["logical_schema_id"] == "scientific_asset_manifest_v1"
    ]
    expected_binding = {
        "logical_schema_id": "scientific_asset_manifest_v1",
        "hash_domain_id": DOMAIN,
        "digest_result_name": "asset_manifest_digest",
    }
    if bindings != [expected_binding]:
        raise ValueError("scientific asset hash-domain binding mismatch")
    if schema["x-gtbi-hash-domain-id"] != DOMAIN:
        raise ValueError("scientific asset schema hash domain mismatch")

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_scientific_asset_contract_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "task_id": "PREV7-0303",
        "recorded_at_utc": RECORDED_AT_UTC,
        "logical_schema_id": "scientific_asset_manifest_v1",
        "schema_path": SCHEMA_PATH.relative_to(ROOT).as_posix(),
        "schema_sha256": raw_sha256(SCHEMA_PATH),
        "schema_field_count": len(SCIENTIFIC_ASSET_FIELDS),
        "closed_schema": schema["additionalProperties"] is False,
        "all_fields_required": set(schema["required"]) == set(SCIENTIFIC_ASSET_FIELDS),
        "hash_domain_id": DOMAIN,
        "hash_domain_registry_path": HASH_REGISTRY.relative_to(ROOT).as_posix(),
        "hash_domain_registry_sha256": raw_sha256(HASH_REGISTRY),
        "hash_domain_binding": expected_binding,
        "validator_path": VALIDATOR.relative_to(ROOT).as_posix(),
        "validator_sha256": raw_sha256(VALIDATOR),
        "lifecycle_states": [
            "wrapper_only",
            "custody_incomplete",
            "stored_not_restore_verified",
            "restore_verified_owner_controlled",
            "restore_verified_with_disaster_copy",
        ],
        "fixture_path": FIXTURE_PATH.relative_to(ROOT).as_posix(),
        "fixture_sha256": raw_sha256(FIXTURE_PATH),
        "fixture_asset_manifest_digest": fixture["asset_manifest_digest"],
        "fixture_lifecycle_state": lifecycle_state(fixture),
        "transport_classification": {
            "raw_data_visibility": "private",
            "normalized_data_visibility": "private",
            "derived_data_visibility": "private",
            "trade_detail_visibility": "private",
            "aggregate_result_visibility": "private",
            "permission_source": "provider_terms_acceptance_before_execution",
        },
        "nullability_validated": True,
        "immutable_wrapper_validated": True,
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "strategy_evaluation_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_SCIENTIFIC_ASSET_CONTRACT_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def build_transition_manifest(receipt: dict[str, Any]) -> dict[str, Any]:
    evidence_paths = [
        RECEIPT.relative_to(ROOT).as_posix(),
        OWNER_DIRECTIVE.relative_to(ROOT).as_posix(),
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g2-scientific-asset-contract-v1",
        "transaction_id": "G2_CLOSE-3",
        "requested_at_utc": RECORDED_AT_UTC,
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0303",
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
                "terminal_reason": "scientific_asset_contract_frozen",
                "notes": (
                    "The closed schema, registered hash domain, lifecycle/nullability "
                    "validator and immutable wrapper are frozen without scientific or "
                    "locked-data execution."
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


def main() -> int:
    receipt = build_receipt()
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    manifest = build_transition_manifest(receipt)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(canonical_bytes(manifest) + b"\n")
    print(json.dumps({"receipt_digest": receipt["receipt_digest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
