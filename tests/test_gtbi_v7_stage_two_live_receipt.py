from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_stage_two_live_receipt import MANIFEST, RECEIPT


def test_live_receipt_is_canonical_ready_and_digest_bound() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_OWNER_CONTROLLED_STAGE_TWO_LIVE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["evaluation"] == {"ready": True, "blockers": []}
    assert receipt["required_check"]["conclusion"] == "success"
    assert receipt["required_check"]["head_sha"] == receipt["main_sha"]
    assert receipt["codeowners_valid"] is True
    assert receipt["external_reviewers_required"] is False
    assert receipt["incremental_net_spend_usd"] == 0


def test_live_receipt_preserves_owner_and_locked_boundaries() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    branch = receipt["branch_protection"]
    assert branch["required_approving_review_count"] == 0
    assert branch["require_code_owner_reviews"] is False
    assert branch["enforce_admins"] is True
    assert branch["allow_force_pushes"] is False
    assert branch["allow_deletions"] is False
    assert receipt["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "local_research_run_performed": False,
    }


def test_transition_closes_only_prev7_0207() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    validate_transition_manifest(manifest)
    assert [item["task_id"] for item in manifest["task_actions"]] == ["PREV7-0207"]
    assert manifest["branch_actions"] == []
    assert manifest["gate_actions"] == []
