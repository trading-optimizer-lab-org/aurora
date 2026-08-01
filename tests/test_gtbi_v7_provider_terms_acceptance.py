from __future__ import annotations

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from scripts.generate_gtbi_v7_provider_terms_acceptance import (
    MANIFEST,
    RECEIPT,
    build_manifest,
    build_receipt,
    verify_committed,
)


def test_provider_terms_acceptance_uses_frozen_input_without_new_download() -> None:
    verify_committed()
    receipt = build_receipt()
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["decision"] == "accepted_for_frozen_input_only"
    assert receipt["current_provider_download_required"] is False
    assert receipt["new_yahoo_or_yfinance_collection_authorized"] is False
    assert receipt["future_refresh_provider"] == "tiingo_daily"
    assert receipt["future_refresh_authorized_now"] is False
    assert receipt["maximum_incremental_net_spend_usd"] == 0
    assert receipt["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "provider_download_performed": False,
    }


def test_provider_terms_transition_is_owner_controlled_and_task_scoped() -> None:
    receipt = build_receipt()
    manifest = build_manifest(receipt)
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert manifest["actor_role"] == "repository_owner"
    assert manifest["gate_actions"] == []
    assert manifest["branch_actions"] == []
    assert manifest["task_actions"][0]["task_id"] == "PREV7-0302"
    assert manifest["task_actions"][0]["target_status"] == "done"
