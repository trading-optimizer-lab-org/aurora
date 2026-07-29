from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_gtbi_v7_pre_genesis_status import generate

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"


def test_owner_decisions_match_explicit_instruction() -> None:
    record = json.loads(
        (READINESS / "owner_decisions.json").read_text(encoding="utf-8")
    )
    decisions = record["decisions"]
    assert decisions["personal_action_items_1_and_2"] == {
        "formal_gate_effect": "none",
        "status": "removed_from_immediate_owner_queue",
    }
    assert (
        decisions["budget"]["authorization"]
        == "no_increase_from_current_baseline"
    )
    assert decisions["licences"]["owner_acceptance"] == "accepted_explicitly"
    assert (
        decisions["private_resources"]["owner_authorization"]
        == "authorized_explicitly"
    )
    assert (
        decisions["remaining_owner_decisions"]["status"]
        == "deferred_until_actionable"
    )


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
    assert cancellation["approval_state"] == "pending_exact_manifest_approval"
    assert cancellation["cancellation_executed"] is False
    assert 29162930823 not in {
        row["run_id"] for row in cancellation["candidates"]
    }


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
