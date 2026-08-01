from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from scripts.generate_gtbi_v7_new_reference_campaign import (
    AUTHORIZATION,
    CAMPAIGN_ID,
    PLAN,
    build_authorization,
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_new_reference_authorization_is_canonical_and_reproducible() -> None:
    receipt = _load(AUTHORIZATION)
    assert AUTHORIZATION.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt == build_authorization()
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_NEW_REFERENCE_CAMPAIGN_AUTHORIZATION_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )


def test_new_campaign_is_separate_from_closed_v6() -> None:
    receipt = _load(AUTHORIZATION)
    assert receipt["campaign_id"] == CAMPAIGN_ID
    assert receipt["separate_from_v6"] is True
    assert receipt["v6_reproduction_claim_allowed"] is False
    assert receipt["v6_terminal_closure"]["state"] == "NO_GO_CLOSED"
    assert receipt["v6_terminal_closure"]["close_id"] == "NO_GO_CLOSE-1"
    assert "v6_equivalence_claim" in receipt["prohibited_scope"]


def test_locked_remains_closed_and_historical_dates_are_frozen() -> None:
    receipt = _load(AUTHORIZATION)
    boundaries = receipt["scientific_boundaries"]
    assert boundaries == {
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "historical_exclusion_start": "2021-01-01",
        "locked_authorized": False,
        "locked_data_accessed": False,
        "provider_download_performed": False,
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
    }
    assert receipt["execution_policy"]["locked_requires_new_owner_authorization"] is True
    assert "locked_access" in receipt["prohibited_scope"]
    assert "forward_evaluation" in receipt["prohibited_scope"]


def test_data_limitations_and_github_only_policy_are_explicit() -> None:
    receipt = _load(AUTHORIZATION)
    limitations = receipt["accepted_limitations"]
    assert limitations["survivorship_biased_reference"] is True
    assert limitations["point_in_time_universe"] is False
    assert limitations["historical_knowability_confirmed"] is False
    assert receipt["execution_policy"]["github_actions_only"] is True
    assert receipt["execution_policy"]["local_scientific_runs_allowed"] is False
    assert receipt["execution_policy"]["runs_on"] == "ubuntu-24.04"
    assert receipt["execution_policy"]["maximum_incremental_net_spend_usd"] == 0
    assert receipt["frozen_data_release"]["scientific_cutoff"] == "2020-12-31"


def test_campaign_plan_has_no_local_or_locked_execution_escape() -> None:
    text = PLAN.read_text(encoding="utf-8")
    assert "C:\\" not in text
    assert "self-hosted" not in text
    assert "locked_authorized=false" in text
    assert "GitHub Actions only" in text
    assert "exactly 72,000 terminal strategy identities" in text
