from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.generate_gtbi_v7_canonical_successor_authorization import (
    DESTINATION,
    PLAN,
    build_authorization,
)


def test_canonical_successor_authorization_is_reproducible() -> None:
    actual = json.loads(DESTINATION.read_text(encoding="utf-8"))
    assert DESTINATION.read_bytes() == canonical_bytes(actual) + b"\n"
    assert actual == build_authorization()
    assert actual["receipt_digest"] == domain_digest(
        "GTBI_V7_CANONICAL_SUCCESSOR_AUTHORIZATION_V1",
        actual,
        omit_top_level_fields=("receipt_digest",),
    )


def test_canonical_successor_amendment_uses_valid_heading_level() -> None:
    plan_text = PLAN.read_text(encoding="utf-8")
    assert "## Canonical Successor Amendment" in plan_text
    assert "### Canonical Successor Amendment" not in plan_text


def test_successor_does_not_reopen_or_relabel_v6() -> None:
    receipt = build_authorization()
    historical = receipt["historical_v6_lineage"]
    assert historical == {
        "classification": "historical_reference_only",
        "terminal_state": "NO_GO_CLOSED",
        "receipt_digest": historical["receipt_digest"],
        "reopened": False,
        "equivalence_claim_allowed": False,
    }
    assert receipt["canonical_successor"]["terminal_strategy_identities"] == 72_000
    assert receipt["canonical_successor"]["passing_candidate_count"] == 0


def test_successor_preserves_scientific_boundaries() -> None:
    boundaries = build_authorization()["scientific_boundaries"]
    assert boundaries["validation_end"] == "2020-12-31"
    assert boundaries["locked_start"] == "2021-01-01"
    assert boundaries["locked_authorized"] is False
    assert boundaries["locked_data_accessed"] is False
    assert boundaries["github_only"] is True
    assert boundaries["requires_local_machine"] is False
    assert boundaries["maximum_incremental_net_spend_usd"] == 0
    assert boundaries["v6_equivalence_claim_allowed"] is False


def test_adoption_does_not_select_a_favourable_result() -> None:
    adoption = build_authorization()["adoption_safety"]
    assert adoption["campaign_pre_authorized_before_execution"] is True
    assert adoption["all_requested_strategy_identities_terminal"] is True
    assert adoption["passing_candidate_selection_used_for_adoption"] is False
    assert adoption["scientific_outputs_rewritten"] is False
    assert adoption["rerun_required_for_identity_promotion"] is False
