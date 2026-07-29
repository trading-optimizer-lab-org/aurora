from __future__ import annotations

import json
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from scripts.generate_gtbi_v7_pre_genesis_status import generate

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"


def test_owner_decisions_match_explicit_instruction() -> None:
    path = READINESS / "owner_decisions.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert path.read_bytes() == canonical_bytes(record) + b"\n"
    decisions = record["decisions"]
    assert decisions["personal_action_items_1_and_2"] == {
        "formal_gate_effect": "none",
        "status": "removed_from_immediate_owner_queue",
    }
    assert (
        decisions["budget"]["authorization"]
        == "no_increase_from_current_baseline"
    )
    assert decisions["budget"]["currency"] == "USD"
    assert decisions["budget"]["maximum_incremental_net_spend_usd"] == 0
    assert decisions["budget"]["discount_change_requires_reauthorization"] is True
    assert decisions["licences"]["owner_acceptance"] == "accepted_explicitly"
    assert decisions["licences"]["selected_future_v7_provider"] == "tiingo_daily"
    assert decisions["audits_and_people"]["external_audits_required"] == 0
    assert decisions["audits_and_people"]["distinct_people_required"] is False
    assert decisions["preservation"]["github_v6_preservation_lease"] == (
        "accepted_as_sufficient"
    )
    assert (
        decisions["private_resources"]["owner_authorization"]
        == "authorized_explicitly"
    )
    assert (
        decisions["remaining_owner_decisions"]["status"]
        == "deferred_until_actionable"
    )


def test_public_billing_baseline_is_bounded_and_canonical() -> None:
    path = READINESS / "billing_baseline_public_receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["currency"] == "USD"
    assert receipt["current_actions_net_amount_usd"] == 0
    assert (
        receipt["current_enterprise_cloud_full_month_unit_amount_usd"]
        == 21
    )
    assert receipt["maximum_incremental_net_spend_usd"] == 0
    assert receipt["new_billable_resources_authorized"] is False
    assert (
        receipt["discount_dependency_requires_reauthorization_on_change"]
        is True
    )
    assert receipt["gross_usage_publication"] == (
        "withheld_private_billing_evidence"
    )
    assert "gross_amount" not in receipt


def test_provider_terms_inventory_selects_tiingo_and_retires_yahoo() -> None:
    path = READINESS / "provider_terms_inventory.json"
    inventory = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(inventory) + b"\n"
    assert inventory["owner_acceptance"] == "accepted_explicitly"
    assert inventory["inventory_status"] == "owner_reviewed"
    assert inventory["v7_full_data_authorization"] == (
        "conditional_on_token_and_capacity_plan"
    )
    assert inventory["selected_future_v7_provider"] == "tiingo_daily"

    providers = {
        provider["provider_id"]: provider for provider in inventory["providers"]
    }
    assert providers["tiingo"]["review_status"] == (
        "selected_zero_cost_internal_research_source"
    )
    assert providers["yahoo_finance"]["review_status"] == (
        "historical_evidence_only_not_future_v7_input"
    )
    assert providers["yfinance"]["terms"][0]["spdx_id"] == "Apache-2.0"
    assert providers["yfinance"]["review_status"] == (
        "legacy_client_not_selected_for_future_v7"
    )
    assert inventory["findings"]["yfinance_code_licence_scope"] == (
        "client_code_only_not_underlying_yahoo_market_data"
    )


def test_v7_data_source_selection_is_canonical_and_preserves_boundaries() -> None:
    path = ROOT / "config/gtbi/v7/data_source_selection.json"
    selection = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(selection) + b"\n"
    assert selection["primary_provider"] == "tiingo_daily"
    assert selection["pricing_tier"] == "Starter_0_USD_per_month"
    assert selection["monthly_unique_symbol_limit"] == 500
    assert selection["zero_incremental_spend_cap_preserved"] is True
    assert selection["train_end"] == "2010-12-31"
    assert selection["validation_start"] == "2011-01-01"
    assert selection["validation_end"] == "2020-12-31"
    assert selection["locked_start"] == "2021-01-01"


def test_owner_acceptance_selects_replacement_without_claiming_yahoo_permission() -> None:
    record = json.loads(
        (READINESS / "owner_decisions.json").read_text(encoding="utf-8")
    )
    licences = record["decisions"]["licences"]

    assert licences["owner_acceptance"] == "accepted_explicitly"
    assert licences["exact_provider_terms_inventory"] == "owner_reviewed"
    assert licences["independent_review_receipt"] == "not_required"
    assert licences["selected_future_v7_provider"] == "tiingo_daily"
    assert licences["yahoo_data_permission"] == (
        "historical_evidence_only_not_future_v7_input"
    )


def test_v6_preservation_lease_is_canonical_verified_and_non_independent() -> None:
    path = READINESS / "v6_preservation_lease_public_receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["status"] == "verified"
    assert receipt["github_only"] is True
    assert receipt["requires_local_machine"] is False
    assert receipt["locked_or_scientific_processing_performed"] is False
    assert receipt["preservation_result"] == {
        "member_count": 47,
        "part_count": 1,
        "source_archive_digest": (
            "sha256:"
            "870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b"
        ),
        "source_size_bytes": 1962204087,
    }
    assert receipt["lease_artifact"]["id"] == 8728621585
    assert receipt["lease_artifact"]["expires_at_utc"] == (
        "2026-10-27T14:57:48Z"
    )
    assert receipt["formal_g0_effect"] == (
        "none_same_provider_non_independent_lease"
    )
    assert set(receipt["scientific_jobs"].values()) == {"skipped"}


def test_inventory_github_actions_attempt_is_canonical_and_fail_closed() -> None:
    path = READINESS / "inventory_github_actions_attempt_receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["run_id"] == 30464201570
    assert receipt["commit_sha"] == (
        "0a1046a805f2ce3c817f1d3f0bb16c60fd6fc4e6"
    )
    assert receipt["github_only"] is True
    assert receipt["requires_local_machine"] is False
    assert receipt["status"] == "blocked_missing_permissions"
    assert receipt["packages"]["overall_status"] == "unavailable"
    assert receipt["packages"]["container"]["http_status"] == 400
    assert receipt["branch_protection"]["http_status"] == 403
    assert receipt["formal_effect"] == "none_inventory_still_incomplete"
    assert set(receipt["scientific_jobs"].values()) == {"skipped"}


def test_pre_genesis_status_allows_preparation_and_v6_is_verified() -> None:
    status, cancellation = generate()
    assert status["execution_status"] == "TECHNICAL_PREPARATION_ALLOWED"
    assert status["formal_genesis_complete"] is False
    assert status["v6_artifact"]["artifact_id"] == 8251391531
    assert status["v6_artifact"]["verified_available"] is True
    assert status["blockers"] == []
    assert cancellation["approval_state"] == "pending_exact_manifest_approval"
    assert cancellation["cancellation_executed"] is False
    assert 29162930823 not in {
        row["run_id"] for row in cancellation["candidates"]
    }
    future_prerequisites = {
        row["prerequisite_id"]: row
        for row in status["future_gate_prerequisites"]
    }
    tiingo = future_prerequisites["G2-TIINGO-CREDENTIAL-AND-CAPACITY"]
    assert tiingo["state"] == "pending_before_scientific_execution"
    assert tiingo["facts"]["selected_provider"] == "tiingo_daily"
    assert tiingo["facts"]["monthly_unique_symbol_limit"] == 500
    lease = status["v6_preservation_lease"]
    assert lease["status"] == "verified"
    assert lease["artifact_id"] == 8728621585
    assert lease["github_only"] is True
    assert lease["requires_local_machine"] is False
    assert lease["formal_g0_effect"] == "accepted_by_owner_as_sufficient"
    packages = status["packages_inventory"]
    assert packages["status"] == "owner_waived_pending_interactive_oauth"
    assert packages["read_packages_authorized_by_owner"] is True
    assert packages["gate_effect"] == "non_blocking"


def test_pre_genesis_generated_files_match_generator() -> None:
    status, cancellation = generate()
    checked_status = json.loads(
        (READINESS / "pre_genesis_status.json").read_text(encoding="utf-8")
    )
    checked_cancellation = json.loads(
        (READINESS / "legacy_run_cancellation_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    assert checked_status == status
    assert checked_cancellation == cancellation
