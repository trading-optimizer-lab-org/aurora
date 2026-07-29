"""Generate the PREV7-0303 schema and immutable-wrapper fixture."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes  # noqa: E402
from infra.gtbi_v7_readiness.scientific_assets import (  # noqa: E402
    SCIENTIFIC_ASSET_FIELDS,
    scientific_asset_manifest_schema,
    seal_asset_manifest,
)

SCHEMA_PATH = (
    ROOT
    / "config/gtbi/schemas/v7/scientific"
    / "scientific_asset_manifest_v1.schema.json"
)
FIXTURE_PATH = (
    ROOT
    / "config/gtbi/fixtures/v7"
    / "scientific_asset_manifest_v1.wrapper_only.json"
)

ZERO_DIGEST = "sha256:" + ("0" * 64)


def wrapper_only_fixture() -> dict:
    """Build a truthful pre-publication V6 compatibility wrapper."""

    value = {field: None for field in SCIENTIFIC_ASSET_FIELDS}
    value.update(
        {
            "schema_version": "scientific_asset_manifest_v1",
            "asset_type": "v6_final_result_preservation",
            "product": "GTBI Fast Strict V6",
            "campaign_id": "gtbi_long_hold_fast_strict_v6",
            "source_run_id": 29162930823,
            "source_commit_sha": "cb80c5065c127322a303d58aea0f6c05337a6c9e",
            "reconstructed_payload_sha256": (
                "sha256:"
                "870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b"
            ),
            "policy_hash": ZERO_DIGEST,
            "workflow_path": (
                ".github/workflows/"
                "global-technical-buy-indicator-long-hold-fast-strict-v6.yml"
            ),
            "workflow_sha256": ZERO_DIGEST,
            "created_at_utc": "2026-07-02T00:00:00Z",
            "retrieval_cutoff_utc": "2026-07-29T12:41:00Z",
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "historical_exclusion_start": "2021-01-01",
            "historical_post_validation_contaminated": True,
            "pristine_locked": False,
            "new_forward_available": False,
            "provider": "GitHub Actions artifact service",
            "reproducibility_classification": (
                "result_preserved_inputs_incomplete"
            ),
            "min_selection_trades_per_year": 0,
            "reuse_recovered_v6_inputs": False,
            "oracle_b_status": "unavailable_missing_original_inputs",
            "semantic_oracle_effective_branch_coverage_pct": None,
            "semantic_oracle_non_equivalent_mutants_survived": 0,
            "v6_historical_reproduction_confirmed": False,
            "synthetic_engine_equivalence_confirmed": False,
            "engine_equivalence_confirmed": False,
            "optimized_vs_reference_equivalence_confirmed": False,
            "missing_v6_dependency_layers": ["C", "D0", "D1", "D2", "D3", "S"],
            "universe_definition_sha256": ZERO_DIGEST,
            "exact_universe_identity_digest": ZERO_DIGEST,
            "universe_temporal_model": "static_post_period",
            "universe_temporal_coverage_pct": None,
            "universe_point_in_time_claim_allowed": False,
            "observation_timestamp_state": "unknown_unverifiable",
            "source_event_cutoff_utc": "unknown_unverifiable",
            "adjustment_temporal_model": "retrospectively_adjusted_reference",
            "corporate_action_knowledge_coverage_pct": None,
            "historical_adjustment_vintage_contaminated": True,
            "adjustment_point_in_time_claim_allowed": False,
            "adjustment_policy_sha256": ZERO_DIGEST,
            "calendar_policy_sha256": ZERO_DIGEST,
            "currency_policy_sha256": ZERO_DIGEST,
            "decision_time_policy_digest": ZERO_DIGEST,
            "market_observation_availability_policy_digest": ZERO_DIGEST,
            "cross_market_alignment_model": "v6_calendar_date_reference",
            "cross_market_temporal_contaminated": True,
            "causal_cross_market_claim_allowed": False,
            "reference_index_order_confirmed": False,
            "no_lookahead_confirmed": False,
            "historical_causal_claim_allowed": False,
            "reference_engine_code_sha": (
                "cb80c5065c127322a303d58aea0f6c05337a6c9e"
            ),
            "canonical_serialization_profile_digest": ZERO_DIGEST,
            "hash_domain_registry_digest": ZERO_DIGEST,
            "source_object_sha256": (
                "sha256:"
                "870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b"
            ),
            "primary_release_asset_count": 0,
            "primary_release_parts": [],
            "mirror_release_asset_count": 0,
            "mirror_release_parts": [],
            "independent_github_disaster_asset_count": 0,
            "independent_github_disaster_release_parts": [],
            "asset_manifest_digest": ZERO_DIGEST,
        }
    )
    for field in (
        "score_formula_manifest_digest",
        "final_filter_registry_digest",
    ):
        value[field] = ZERO_DIGEST
    return seal_asset_manifest(value)


def main() -> int:
    schema = scientific_asset_manifest_schema()
    fixture = wrapper_only_fixture()
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_bytes(canonical_bytes(schema) + b"\n")
    FIXTURE_PATH.write_bytes(canonical_bytes(fixture) + b"\n")
    print(
        json.dumps(
            {
                "schema_path": str(SCHEMA_PATH.relative_to(ROOT)),
                "fixture_path": str(FIXTURE_PATH.relative_to(ROOT)),
                "field_count": len(SCIENTIFIC_ASSET_FIELDS),
                "asset_manifest_digest": fixture["asset_manifest_digest"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
