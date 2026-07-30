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
    assert decisions["licences"]["current_v7_data_input"] == (
        "owner_supplied_frozen_local_data_lake"
    )
    assert decisions["licences"]["future_refresh_provider"] == "tiingo_daily"
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


def test_provider_terms_inventory_keeps_tiingo_as_optional_refresh() -> None:
    path = READINESS / "provider_terms_inventory.json"
    inventory = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(inventory) + b"\n"
    assert inventory["owner_acceptance"] == "accepted_explicitly"
    assert inventory["inventory_status"] == "owner_reviewed"
    assert inventory["current_v7_data_input"] == (
        "owner_supplied_frozen_local_data_lake"
    )
    assert inventory["future_refresh_authorization"] == (
        "deferred_until_owner_requests_refresh"
    )
    assert inventory["selected_future_v7_provider"] == "tiingo_daily"

    providers = {
        provider["provider_id"]: provider for provider in inventory["providers"]
    }
    assert providers["tiingo"]["review_status"] == "optional_future_refresh_source"
    assert providers["yahoo_finance"]["review_status"] == (
        "frozen_existing_dataset_no_new_collection"
    )
    assert providers["yfinance"]["terms"][0]["spdx_id"] == "Apache-2.0"
    assert providers["yfinance"]["review_status"] == (
        "legacy_provenance_no_new_collection"
    )
    assert inventory["findings"]["yfinance_code_licence_scope"] == (
        "client_code_only_not_underlying_yahoo_market_data"
    )


def test_local_data_lake_receipt_is_canonical_and_requires_only_github_transfer() -> None:
    path = READINESS / "local_data_lake_receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["universe_symbols"] == 4693
    assert receipt["downloaded_ok"] == 4400
    assert receipt["normalized_parquet_files"] == 5332
    assert receipt["provider_download_required_now"] is False
    assert receipt["github_transfer_required_before_execution"] is True
    assert receipt["scientific_cutoff_required"] == "2020-12-31"
    assert receipt["locked_start"] == "2021-01-01"
    assert receipt["locked_rows_present"] is True
    assert receipt["original_github_artifact"]["expired"] is True


def test_github_packages_inventory_receipt_is_canonical_and_empty() -> None:
    path = READINESS / "github_packages_inventory_receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["account"] == "gomez5757"
    assert receipt["active_account"] is True
    assert receipt["read_packages_scope_present"] is True
    assert "read:packages" in receipt["token_scopes"]
    assert receipt["organization"] == "trading-optimizer-lab-org"
    assert receipt["package_types_checked"] == [
        "container",
        "maven",
        "npm",
        "nuget",
        "rubygems",
    ]
    assert receipt["package_counts"] == {
        "container": 0,
        "maven": 0,
        "npm": 0,
        "nuget": 0,
        "rubygems": 0,
    }


def test_v7_data_source_selection_uses_frozen_local_data_and_preserves_boundaries() -> None:
    path = ROOT / "config/gtbi/v7/data_source_selection.json"
    selection = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(selection) + b"\n"
    assert selection["current_input"] == "owner_supplied_frozen_local_data_lake"
    assert selection["provider_download_required_now"] is False
    assert selection["github_transfer_required_before_execution"] is True
    assert selection["optional_future_refresh_provider"] == "tiingo_daily"
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
    assert licences["current_v7_data_input"] == (
        "owner_supplied_frozen_local_data_lake"
    )
    assert licences["future_refresh_provider"] == "tiingo_daily"


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


def test_inventory_github_actions_attempt_is_canonical_and_complete() -> None:
    path = READINESS / "inventory_github_actions_attempt_receipt.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["run_id"] == 30523390257
    assert receipt["commit_sha"] == (
        "d7489dc64756274f981f2600b2e50de8404e44d0"
    )
    assert receipt["github_only"] is True
    assert receipt["requires_local_machine"] is False
    assert receipt["status"] == "success"
    assert receipt["packages"]["overall_status"] == "complete"
    assert receipt["packages"]["container"]["row_count"] == 0
    assert receipt["branch_protection"]["http_status"] == 200
    assert receipt["formal_effect"] == (
        "PREV7-0001_evidence_ready_dependency_PREV7-0000_pending"
    )
    assert set(receipt["scientific_jobs"].values()) == {"skipped"}


def test_pre_genesis_status_allows_preparation_and_v6_is_verified() -> None:
    status, cancellation = generate()
    assert status["execution_status"] == "TECHNICAL_PREPARATION_ALLOWED"
    assert status["formal_genesis_complete"] is False
    assert status["v6_artifact"]["artifact_id"] == 8251391531
    assert status["v6_artifact"]["verified_available"] is True
    assert status["blockers"] == []
    assert status["initial_readiness_records"] == {
        "status": "provisional_fail_closed",
        "formal_genesis_effect": "none_until_merged_and_reconciled",
        "task_rows": 110,
        "gate_rows": 15,
        "task_attempt_rows": 0,
        "all_tasks_blocked": True,
        "all_gates_red": True,
        "validated": True,
    }
    assert cancellation["approval_state"] == "pending_exact_manifest_approval"
    assert cancellation["cancellation_executed"] is False
    assert 29162930823 not in {
        row["run_id"] for row in cancellation["candidates"]
    }
    future_prerequisites = {
        row["prerequisite_id"]: row
        for row in status["future_gate_prerequisites"]
    }
    frozen = future_prerequisites["G2-FROZEN-DATA-LAKE-GITHUB-TRANSFER"]
    assert frozen["state"] == "pending_before_github_only_execution"
    assert frozen["facts"]["provider_token_required_now"] is False
    assert frozen["facts"]["universe_symbols"] == 4693
    tiingo = future_prerequisites["G2-TIINGO-OPTIONAL-FUTURE-REFRESH"]
    assert tiingo["state"] == (
        "deferred_not_required_for_current_frozen_dataset"
    )
    lease = status["v6_preservation_lease"]
    assert lease["status"] == "verified"
    assert lease["artifact_id"] == 8728621585
    assert lease["github_only"] is True
    assert lease["requires_local_machine"] is False
    assert lease["formal_g0_effect"] == "accepted_by_owner_as_sufficient"
    packages = status["packages_inventory"]
    assert packages["status"] == "complete_verified_empty"
    assert packages["read_packages_authorized_by_owner"] is True
    assert packages["oauth_grant_status"] == "granted_verified"
    assert packages["private_packages_verified"] is True
    assert packages["organization_packages_observed"] == 0
    assert packages["verification_receipt"] == (
        "docs/readiness/gtbi-v7/github_packages_inventory_receipt.json"
    )
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
