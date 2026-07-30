"""GTBI V7 scientific-asset compatibility manifests.

This module implements the post-retrieval V6 compatibility wrapper described
by PREV7-0303. It does not authorize an asset or make missing provenance true.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema

from infra.gtbi_v7_readiness.canonical import domain_digest

DOMAIN = "GTBI_SCIENTIFIC_ASSET_MANIFEST_V1"
SCHEMA_VERSION = "scientific_asset_manifest_v1"
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z$"
)
COMMIT_PATTERN = r"^[0-9a-f]{40}$"

SCIENTIFIC_ASSET_FIELDS = (
    "schema_version",
    "asset_type",
    "product",
    "campaign_id",
    "source_run_id",
    "source_commit_sha",
    "reconstructed_payload_sha256",
    "policy_hash",
    "workflow_path",
    "workflow_sha256",
    "created_at_utc",
    "retrieval_cutoff_utc",
    "train_end",
    "validation_start",
    "validation_end",
    "locked_start",
    "historical_exclusion_start",
    "historical_post_validation_contaminated",
    "pristine_locked",
    "new_forward_available",
    "first_market_session_locked",
    "first_market_session_locked_by_market_digest_or_null",
    "forward_lock_calendar_manifest_digest_or_null",
    "later_required_approval_utc_or_null",
    "provider",
    "provider_terms_review_id",
    "reproducibility_classification",
    "evaluation_identity",
    "selection_split",
    "scoring_profile",
    "min_selection_trades_per_year",
    "score_formula_manifest_digest",
    "final_filter_registry_digest",
    "reuse_recovered_v6_inputs",
    "oracle_b_status",
    "semantic_oracle_coverage_manifest_digest",
    "semantic_oracle_effective_branch_coverage_pct",
    "semantic_oracle_non_equivalent_mutants_survived",
    "v6_historical_reproduction_confirmed",
    "synthetic_engine_equivalence_confirmed",
    "engine_equivalence_confirmed",
    "optimized_vs_reference_equivalence_confirmed",
    "missing_v6_dependency_layers",
    "universe_definition_sha256",
    "exact_universe_identity_digest",
    "universe_temporal_model",
    "universe_temporal_manifest_digest",
    "universe_temporal_coverage_pct",
    "universe_point_in_time_claim_allowed",
    "observation_timestamp_state",
    "price_data_vintage_utc",
    "source_event_cutoff_utc",
    "adjustment_temporal_model",
    "corporate_action_knowledge_manifest_digest",
    "corporate_action_knowledge_coverage_pct",
    "historical_adjustment_vintage_contaminated",
    "adjustment_point_in_time_claim_allowed",
    "adjustment_policy_sha256",
    "calendar_policy_sha256",
    "currency_policy_sha256",
    "decision_time_policy_digest",
    "market_observation_availability_policy_digest",
    "cross_market_alignment_model",
    "cross_market_temporal_contaminated",
    "causal_cross_market_claim_allowed",
    "reference_index_order_confirmed",
    "no_lookahead_confirmed",
    "historical_causal_claim_allowed",
    "data_digest",
    "data_manifest_digest",
    "historical_execution_pack_digest",
    "reference_engine_code_sha",
    "reference_engine_tree_digest",
    "reference_entrypoint_digest",
    "reference_dependency_lock_digest",
    "reference_runtime_digest",
    "reference_engine_isolation_policy_digest",
    "numerical_environment_digest",
    "scientific_numerical_semantics_digest",
    "approved_numerical_execution_profile_registry_digest",
    "approved_hardware_profile_registry_digest",
    "canonical_serialization_profile_digest",
    "hash_domain_registry_digest",
    "file_count",
    "row_count",
    "first_date",
    "last_date",
    "symbol_source_end_manifest_digest",
    "artificial_truncation_manifest_digest",
    "compressed_size_bytes",
    "uncompressed_size_bytes",
    "source_object_sha256",
    "primary_release_repository_id",
    "primary_release_id",
    "primary_release_asset_count",
    "primary_release_parts",
    "mirror_release_repository_id",
    "mirror_release_id",
    "mirror_release_asset_count",
    "mirror_release_parts",
    "independent_github_disaster_repository_id",
    "independent_github_disaster_release_id",
    "independent_github_disaster_asset_count",
    "independent_github_disaster_release_parts",
    "platform_outage_archive_provider",
    "platform_outage_archive_object_version",
    "platform_outage_archive_manifest_digest",
    "platform_outage_archive_server_side_encryption_mode",
    "platform_outage_archive_kms_provider_account_key_version_or_null",
    "platform_outage_archive_kms_administrator_identity_or_null",
    "platform_outage_archive_kms_retain_until_utc_or_null",
    "platform_outage_archive_kms_deletion_protection_receipt_digest_or_null",
    "platform_outage_archive_kms_admin_negative_test_receipt_digest_or_null",
    "platform_outage_archive_lock_mode",
    "platform_outage_archive_object_lock_until_utc",
    "platform_outage_archive_legal_hold_state",
    "platform_outage_archive_retention_policy_digest",
    "platform_outage_archive_admin_negative_test_receipt_digest",
    "retention_funding_manifest_digest",
    "recovery_objective_policy_digest",
    "latest_restore_receipt_digest",
    "attestation_reference",
    "asset_manifest_digest",
)

BOOLEAN_FIELDS = {
    "historical_post_validation_contaminated",
    "pristine_locked",
    "new_forward_available",
    "reuse_recovered_v6_inputs",
    "v6_historical_reproduction_confirmed",
    "synthetic_engine_equivalence_confirmed",
    "engine_equivalence_confirmed",
    "optimized_vs_reference_equivalence_confirmed",
    "universe_point_in_time_claim_allowed",
    "historical_adjustment_vintage_contaminated",
    "adjustment_point_in_time_claim_allowed",
    "cross_market_temporal_contaminated",
    "causal_cross_market_claim_allowed",
    "reference_index_order_confirmed",
    "no_lookahead_confirmed",
    "historical_causal_claim_allowed",
}

NULLABLE_DIGEST_FIELDS = {
    "first_market_session_locked_by_market_digest_or_null",
    "forward_lock_calendar_manifest_digest_or_null",
    "semantic_oracle_coverage_manifest_digest",
    "universe_temporal_manifest_digest",
    "corporate_action_knowledge_manifest_digest",
    "data_digest",
    "data_manifest_digest",
    "historical_execution_pack_digest",
    "reference_engine_tree_digest",
    "reference_entrypoint_digest",
    "reference_dependency_lock_digest",
    "reference_runtime_digest",
    "reference_engine_isolation_policy_digest",
    "numerical_environment_digest",
    "scientific_numerical_semantics_digest",
    "approved_numerical_execution_profile_registry_digest",
    "approved_hardware_profile_registry_digest",
    "symbol_source_end_manifest_digest",
    "artificial_truncation_manifest_digest",
    "platform_outage_archive_manifest_digest",
    "platform_outage_archive_kms_deletion_protection_receipt_digest_or_null",
    "platform_outage_archive_kms_admin_negative_test_receipt_digest_or_null",
    "platform_outage_archive_retention_policy_digest",
    "platform_outage_archive_admin_negative_test_receipt_digest",
    "retention_funding_manifest_digest",
    "recovery_objective_policy_digest",
    "latest_restore_receipt_digest",
}

NULLABLE_TIMESTAMP_FIELDS = {
    "first_market_session_locked",
    "later_required_approval_utc_or_null",
    "price_data_vintage_utc",
    "platform_outage_archive_kms_retain_until_utc_or_null",
    "platform_outage_archive_object_lock_until_utc",
}

NULLABLE_COUNT_FIELDS = {
    "file_count",
    "row_count",
    "compressed_size_bytes",
    "uncompressed_size_bytes",
}

PERCENT_FIELDS = {
    "semantic_oracle_effective_branch_coverage_pct",
    "universe_temporal_coverage_pct",
    "corporate_action_knowledge_coverage_pct",
}

NULLABLE_STRING_FIELDS = {
    "provider_terms_review_id",
    "evaluation_identity",
    "selection_split",
    "scoring_profile",
    "platform_outage_archive_provider",
    "platform_outage_archive_object_version",
    "platform_outage_archive_server_side_encryption_mode",
    "platform_outage_archive_kms_provider_account_key_version_or_null",
    "platform_outage_archive_kms_administrator_identity_or_null",
    "platform_outage_archive_lock_mode",
    "platform_outage_archive_legal_hold_state",
    "attestation_reference",
}


class ScientificAssetManifestError(ValueError):
    """Raised when a manifest makes an invalid or contradictory claim."""


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _part_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "part_index": {"type": "integer", "minimum": 0},
            "repository_id": {"type": "integer", "minimum": 1},
            "release_id": {"type": "integer", "minimum": 1},
            "asset_id": {"type": "integer", "minimum": 1},
            "asset_name": {
                "type": "string",
                "minLength": 1,
                "pattern": r"^[A-Za-z0-9._-]+$",
            },
            "size_bytes": {"type": "integer", "minimum": 1},
            "sha256": {"type": "string", "pattern": DIGEST_PATTERN},
        },
        "required": [
            "part_index",
            "repository_id",
            "release_id",
            "asset_id",
            "asset_name",
            "size_bytes",
            "sha256",
        ],
    }


def _field_schema(name: str) -> dict[str, Any]:
    if name == "schema_version":
        return {"const": SCHEMA_VERSION}
    if name == "source_run_id":
        return {"type": "integer", "minimum": 1}
    if name in {"source_commit_sha", "reference_engine_code_sha"}:
        schema = {"type": "string", "pattern": COMMIT_PATTERN}
        return _nullable(schema) if name == "reference_engine_code_sha" else schema
    if name in BOOLEAN_FIELDS:
        return {"type": "boolean"}
    if name in NULLABLE_DIGEST_FIELDS:
        return _nullable({"type": "string", "pattern": DIGEST_PATTERN})
    if (
        name.endswith("_digest")
        or name.endswith("_sha256")
        or name == "policy_hash"
    ):
        return {"type": "string", "pattern": DIGEST_PATTERN}
    if name in NULLABLE_TIMESTAMP_FIELDS:
        return _nullable({"type": "string", "pattern": TIMESTAMP_PATTERN})
    if name in {"created_at_utc", "retrieval_cutoff_utc"}:
        return {"type": "string", "pattern": TIMESTAMP_PATTERN}
    if name in {
        "train_end",
        "validation_start",
        "validation_end",
        "locked_start",
        "historical_exclusion_start",
    }:
        constants = {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "historical_exclusion_start": "2021-01-01",
        }
        return {"const": constants[name]}
    if name in {"first_date", "last_date"}:
        return _nullable(
            {
                "type": "string",
                "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
            }
        )
    if name == "source_event_cutoff_utc":
        return {
            "anyOf": [
                {"type": "string", "pattern": TIMESTAMP_PATTERN},
                {"const": "unknown_unverifiable"},
            ]
        }
    if name == "observation_timestamp_state":
        return {
            "enum": [
                "authenticated",
                "unknown_unverifiable",
            ]
        }
    if name == "reproducibility_classification":
        return {
            "enum": [
                "fully_reproducible",
                "result_preserved_inputs_incomplete",
                "historical_reference_only",
            ]
        }
    if name == "oracle_b_status":
        return {
            "enum": [
                "exact_match",
                "mismatch",
                "unavailable_missing_original_inputs",
            ]
        }
    if name == "universe_temporal_model":
        return {"enum": ["point_in_time", "static_post_period"]}
    if name == "adjustment_temporal_model":
        return {
            "enum": [
                "as_known_each_session",
                "retrospectively_adjusted_reference",
            ]
        }
    if name == "cross_market_alignment_model":
        return {"enum": ["v6_calendar_date_reference", "causal_asof_utc"]}
    if name == "missing_v6_dependency_layers":
        return {
            "type": "array",
            "items": {"enum": ["C", "D0", "D1", "D2", "D3", "S", "R"]},
            "uniqueItems": True,
        }
    if name in {
        "primary_release_parts",
        "mirror_release_parts",
        "independent_github_disaster_release_parts",
    }:
        return {"type": "array", "items": _part_schema()}
    if name in {
        "semantic_oracle_non_equivalent_mutants_survived",
        "min_selection_trades_per_year",
        "primary_release_asset_count",
        "mirror_release_asset_count",
        "independent_github_disaster_asset_count",
    }:
        return {"type": "integer", "minimum": 0}
    if name in NULLABLE_COUNT_FIELDS:
        return _nullable({"type": "integer", "minimum": 0})
    if name in PERCENT_FIELDS:
        return _nullable(
            {"type": "number", "minimum": 0.0, "maximum": 100.0}
        )
    if name in {
        "primary_release_repository_id",
        "primary_release_id",
        "mirror_release_repository_id",
        "mirror_release_id",
        "independent_github_disaster_repository_id",
        "independent_github_disaster_release_id",
    }:
        return _nullable({"type": "integer", "minimum": 1})
    if name in NULLABLE_STRING_FIELDS:
        return _nullable({"type": "string", "minLength": 1})
    if name == "workflow_path":
        return {
            "type": "string",
            "pattern": r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$",
        }
    return {"type": "string", "minLength": 1}


def scientific_asset_manifest_schema() -> dict[str, Any]:
    """Return the closed JSON Schema for the compatibility wrapper."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://aurora.local/schemas/gtbi/v7/scientific/"
            "scientific_asset_manifest_v1.schema.json"
        ),
        "title": "GTBI V7 scientific asset compatibility manifest",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            name: _field_schema(name) for name in SCIENTIFIC_ASSET_FIELDS
        },
        "required": list(SCIENTIFIC_ASSET_FIELDS),
        "x-gtbi-logical-schema-id": SCHEMA_VERSION,
        "x-gtbi-hash-domain-id": DOMAIN,
        "x-gtbi-digest-storage": "self_field",
        "x-gtbi-digest-result-name": "asset_manifest_digest",
    }


def compute_asset_manifest_digest(manifest: dict[str, Any]) -> str:
    """Compute the self-field digest for an asset manifest."""

    return domain_digest(
        DOMAIN,
        manifest,
        omit_top_level_fields=("asset_manifest_digest",),
    )


def _validate_parts(
    manifest: dict[str, Any],
    *,
    label: str,
    parts_field: str,
    count_field: str,
    repository_field: str,
    release_field: str,
) -> None:
    parts = manifest[parts_field]
    count = manifest[count_field]
    repository_id = manifest[repository_field]
    release_id = manifest[release_field]
    if len(parts) != count:
        raise ScientificAssetManifestError(
            f"{label} part count does not match declared asset count"
        )
    if [part["part_index"] for part in parts] != list(range(count)):
        raise ScientificAssetManifestError(
            f"{label} part indices must be contiguous from zero"
        )
    if count == 0:
        if repository_id is not None or release_id is not None:
            raise ScientificAssetManifestError(
                f"{label} empty custody must not claim repository or release"
            )
        return
    if repository_id is None or release_id is None:
        raise ScientificAssetManifestError(
            f"{label} custody is missing repository or release identity"
        )
    for part in parts:
        if part["repository_id"] != repository_id:
            raise ScientificAssetManifestError(
                f"{label} part repository identity mismatch"
            )
        if part["release_id"] != release_id:
            raise ScientificAssetManifestError(
                f"{label} part release identity mismatch"
            )


def validate_scientific_asset_manifest(
    manifest: dict[str, Any],
) -> None:
    """Validate schema, lifecycle claims, custody arrays and self digest."""

    jsonschema.Draft202012Validator(
        scientific_asset_manifest_schema()
    ).validate(manifest)

    if manifest["asset_manifest_digest"] != compute_asset_manifest_digest(
        manifest
    ):
        raise ScientificAssetManifestError("asset manifest digest mismatch")

    if manifest["locked_start"] != manifest["historical_exclusion_start"]:
        raise ScientificAssetManifestError(
            "locked_start must equal historical_exclusion_start"
        )
    if manifest["first_date"] and manifest["last_date"]:
        if manifest["first_date"] > manifest["last_date"]:
            raise ScientificAssetManifestError("first_date is after last_date")
    if (
        manifest["last_date"]
        and manifest["last_date"] > manifest["validation_end"]
    ):
        raise ScientificAssetManifestError(
            "scientific asset includes data after validation_end"
        )

    missing = manifest["missing_v6_dependency_layers"]
    if missing != sorted(missing):
        raise ScientificAssetManifestError(
            "missing V6 dependency layers must use canonical sorted order"
        )

    classification = manifest["reproducibility_classification"]
    if classification == "fully_reproducible":
        if (
            missing
            or not manifest["reuse_recovered_v6_inputs"]
            or manifest["oracle_b_status"] != "exact_match"
            or not manifest["v6_historical_reproduction_confirmed"]
        ):
            raise ScientificAssetManifestError(
                "fully reproducible classification lacks required evidence"
            )
    elif classification == "result_preserved_inputs_incomplete":
        if (
            not missing
            or manifest["oracle_b_status"]
            != "unavailable_missing_original_inputs"
            or manifest["v6_historical_reproduction_confirmed"]
        ):
            raise ScientificAssetManifestError(
                "incomplete-input classification is contradictory"
            )

    if manifest["oracle_b_status"] == "mismatch":
        if manifest["v6_historical_reproduction_confirmed"]:
            raise ScientificAssetManifestError(
                "Oracle B mismatch cannot confirm V6 reproduction"
            )
    if any(
        manifest[field]
        for field in (
            "v6_historical_reproduction_confirmed",
            "synthetic_engine_equivalence_confirmed",
            "engine_equivalence_confirmed",
            "optimized_vs_reference_equivalence_confirmed",
        )
    ) and manifest["asset_type"] == "v6_final_result_preservation":
        raise ScientificAssetManifestError(
            "archival preservation cannot assert engine equivalence"
        )

    if manifest["universe_temporal_model"] == "static_post_period":
        if (
            manifest["observation_timestamp_state"]
            != "unknown_unverifiable"
            or manifest["universe_point_in_time_claim_allowed"]
            or manifest["historical_causal_claim_allowed"]
        ):
            raise ScientificAssetManifestError(
                "static post-period universe makes an invalid causal claim"
            )

    if (
        manifest["adjustment_temporal_model"]
        == "retrospectively_adjusted_reference"
    ):
        if (
            not manifest["historical_adjustment_vintage_contaminated"]
            or manifest["adjustment_point_in_time_claim_allowed"]
        ):
            raise ScientificAssetManifestError(
                "retrospective adjustments make an invalid point-in-time claim"
            )

    _validate_parts(
        manifest,
        label="primary release",
        parts_field="primary_release_parts",
        count_field="primary_release_asset_count",
        repository_field="primary_release_repository_id",
        release_field="primary_release_id",
    )
    _validate_parts(
        manifest,
        label="mirror release",
        parts_field="mirror_release_parts",
        count_field="mirror_release_asset_count",
        repository_field="mirror_release_repository_id",
        release_field="mirror_release_id",
    )
    _validate_parts(
        manifest,
        label="independent GitHub disaster release",
        parts_field="independent_github_disaster_release_parts",
        count_field="independent_github_disaster_asset_count",
        repository_field="independent_github_disaster_repository_id",
        release_field="independent_github_disaster_release_id",
    )


def lifecycle_state(manifest: dict[str, Any]) -> str:
    """Return an informational lifecycle state without changing the wrapper."""

    validate_scientific_asset_manifest(manifest)
    primary = manifest["primary_release_asset_count"]
    mirror = manifest["mirror_release_asset_count"]
    disaster = manifest["independent_github_disaster_asset_count"]
    if (primary, mirror, disaster) == (0, 0, 0):
        return "wrapper_only"
    if primary == 0 or mirror == 0:
        return "custody_incomplete"
    if manifest["latest_restore_receipt_digest"] is None:
        return "stored_not_restore_verified"
    if disaster == 0:
        return "restore_verified_owner_controlled"
    return "restore_verified_with_disaster_copy"


def seal_asset_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with its computed digest and validate it."""

    sealed = deepcopy(manifest)
    sealed["asset_manifest_digest"] = compute_asset_manifest_digest(sealed)
    validate_scientific_asset_manifest(sealed)
    return sealed


def load_and_validate_asset_manifest(path: Path) -> dict[str, Any]:
    """Load a canonical JSON object and validate every manifest invariant."""

    import json

    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_scientific_asset_manifest(manifest)
    return manifest
