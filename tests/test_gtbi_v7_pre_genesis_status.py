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


def test_provider_terms_inventory_is_canonical_and_does_not_invent_permission() -> None:
    path = READINESS / "provider_terms_inventory.json"
    inventory = json.loads(path.read_text(encoding="utf-8"))

    assert path.read_bytes() == canonical_bytes(inventory) + b"\n"
    assert inventory["owner_acceptance"] == (
        "accepted_explicitly_subject_to_actual_provider_permission"
    )
    assert inventory["inventory_status"] == (
        "prepared_pending_independent_review"
    )
    assert inventory["v7_full_data_authorization"] == "blocked"

    providers = {
        provider["provider_id"]: provider for provider in inventory["providers"]
    }
    assert providers["yahoo_finance"]["review_status"] == (
        "blocked_permission_or_replacement_required"
    )
    assert providers["yfinance"]["terms"][0]["spdx_id"] == "Apache-2.0"
    assert providers["yfinance"]["review_status"] == (
        "code_licence_identified_data_rights_not_granted"
    )
    assert inventory["findings"]["yfinance_code_licence_scope"] == (
        "client_code_only_not_underlying_yahoo_market_data"
    )


def test_owner_acceptance_does_not_claim_yahoo_data_permission() -> None:
    record = json.loads(
        (READINESS / "owner_decisions.json").read_text(encoding="utf-8")
    )
    licences = record["decisions"]["licences"]

    assert licences["owner_acceptance"] == "accepted_explicitly"
    assert licences["exact_provider_terms_inventory"] == (
        "prepared_pending_independent_review"
    )
    assert licences["independent_review_receipt"] == "pending"
    assert licences["yahoo_data_permission"] == (
        "blocked_permission_or_replacement_required"
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


def test_pre_genesis_status_is_no_go_and_v6_is_verified() -> None:
    status, cancellation = generate()
    assert status["execution_status"] == "NO-GO"
    assert status["formal_genesis_complete"] is False
    assert status["v6_artifact"]["artifact_id"] == 8251391531
    assert status["v6_artifact"]["verified_available"] is True
    blocker_ids = {row["blocker_id"] for row in status["blockers"]}
    assert "PREGENESIS-QUALITY-RECEIPTS" in blocker_ids
    assert "PREGENESIS-INVENTORY-PACKAGES-PERMISSION" in blocker_ids
    assert "PREGENESIS-ESCROW-FOUNDATION" in blocker_ids
    escrow = next(
        row
        for row in status["blockers"]
        if row["blocker_id"] == "PREGENESIS-ESCROW-FOUNDATION"
    )
    assert escrow["facts"]["billing_baseline_status"] == (
        "measured_public_projection"
    )
    assert escrow["facts"]["billing_currency"] == "USD"
    assert escrow["facts"]["maximum_incremental_net_spend_usd"] == 0
    assert escrow["facts"]["discount_change_requires_reauthorization"] is True
    assert cancellation["approval_state"] == "pending_exact_manifest_approval"
    assert cancellation["cancellation_executed"] is False
    assert 29162930823 not in {
        row["run_id"] for row in cancellation["candidates"]
    }
    future_blockers = {
        row["blocker_id"]: row for row in status["future_gate_blockers"]
    }
    yahoo = future_blockers["G2-YAHOO-DATA-PERMISSION"]
    assert yahoo["state"] == "blocked"
    assert yahoo["facts"]["v7_full_data_authorization"] == "blocked"
    assert yahoo["facts"]["owner_acceptance"] == (
        "accepted_explicitly_subject_to_actual_provider_permission"
    )
    lease = status["v6_preservation_lease"]
    assert lease["status"] == "verified"
    assert lease["artifact_id"] == 8728621585
    assert lease["github_only"] is True
    assert lease["requires_local_machine"] is False
    assert lease["formal_g0_effect"] == (
        "none_same_provider_non_independent_lease"
    )


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
