from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pytest

from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_retention_policy import (
    MANIFEST,
    MIGRATION_EVIDENCE,
    POLICY,
    validate_policy,
    verify_committed,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/aurora-maintenance-retention.yml"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_retention_policy_is_zero_increment_and_exactly_fail_closed() -> None:
    policy = _load(POLICY)
    migration = _load(MIGRATION_EVIDENCE)
    validate_policy(policy, migration)
    assert policy["budget"]["maximum_incremental_net_spend_usd"] == 0
    assert policy["budget"]["new_billable_resources_authorized"] is False
    assert policy["custody_model"]["external_provider_copy_required"] is False
    assert policy["custody_model"]["same_provider_outage_limitation_disclosed"] is True
    assert policy["acceptance_rules"]["missing_or_stale_review_blocks_new_acceptance"]
    assert policy["locked_start"] == "2021-01-01"
    assert policy["locked_data_accessed"] is False
    assert policy["scientific_processing_performed"] is False


def test_retention_policy_enforces_required_rpo_and_rto() -> None:
    policy = _load(POLICY)
    migration = _load(MIGRATION_EVIDENCE)
    classes = {row["asset_class"]: row for row in policy["asset_classes"]}
    assert classes["canonical_final_reference"]["rpo_seconds_or_exact_batch_bound"] == 0
    assert classes["canonical_final_reference"]["rto_seconds"] == 86_400
    assert classes["immutable_audit_log"]["rpo_seconds_or_exact_batch_bound"] == 0
    assert classes["immutable_audit_log"]["rto_seconds"] == 14_400
    assert classes["checkpoint"]["rto_seconds"] == 21_600
    assert classes["emergency_v6_package"]["rto_seconds"] == 86_400
    assert migration["selected_migration_lead_time_days"] >= migration[
        "minimum_required_migration_lead_time_days"
    ]


def test_retention_policy_rejects_budget_or_recovery_weakening() -> None:
    policy = _load(POLICY)
    migration = _load(MIGRATION_EVIDENCE)
    billable = deepcopy(policy)
    billable["budget"]["maximum_incremental_net_spend_usd"] = 1
    with pytest.raises(ValueError, match="exceeds the owner budget"):
        validate_policy(billable, migration)
    weak = deepcopy(policy)
    for row in weak["asset_classes"]:
        if row["asset_class"] == "immutable_audit_log":
            row["rto_seconds"] = 14_401
    with pytest.raises(ValueError, match="audit/log RTO"):
        validate_policy(weak, migration)


def test_committed_policy_verifies_and_expires_fail_closed() -> None:
    valid = verify_committed(now=datetime(2026, 8, 1, tzinfo=timezone.utc))
    expired = verify_committed(now=datetime(2026, 9, 2, tzinfo=timezone.utc))
    assert valid["status"] == "valid"
    assert expired["status"] == "expired_fail_closed"


def test_retention_transition_manifest_is_accepted_by_state_controller() -> None:
    manifest = _load(MANIFEST)
    validate_transition_manifest(manifest)
    assert all(
        path.startswith("docs/readiness/gtbi-v7/")
        for action in manifest["task_actions"]
        for path in action["evidence_paths"]
    )
