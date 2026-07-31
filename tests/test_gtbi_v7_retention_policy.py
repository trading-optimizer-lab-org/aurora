from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
import yaml

from scripts.generate_gtbi_v7_retention_policy import (
    MIGRATION_EVIDENCE,
    POLICY,
    validate_policy,
    verify_committed,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/aurora-maintenance-retention.yml"


def _load(path: Path) -> dict[str, object]:
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


def test_maintenance_workflow_is_pinned_github_only_and_non_scientific() -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = payload["jobs"]["verify-retention-policy"]
    text = WORKFLOW.read_text(encoding="utf-8")
    assert job["runs-on"] == "ubuntu-24.04"
    assert payload["permissions"] == {"contents": "read"}
    assert "workflow_dispatch" in payload[True]
    assert "schedule" in payload[True]
    assert "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803" in text
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "locked" not in text.lower()
