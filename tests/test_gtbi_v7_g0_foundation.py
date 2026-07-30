from __future__ import annotations

import json

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.g0_foundation import (
    FOUNDATION_REPORT_PATH,
    build_g0_foundation_report,
)


def test_g0_foundation_report_is_deterministic_and_not_green() -> None:
    report = build_g0_foundation_report()
    checked = json.loads(FOUNDATION_REPORT_PATH.read_text(encoding="utf-8"))
    assert checked == report
    assert FOUNDATION_REPORT_PATH.read_bytes() == canonical_bytes(report) + b"\n"
    assert report["report_digest"] == domain_digest(
        "GTBI_V7_G0_OWNER_CONTROLLED_FOUNDATION_REPORT_V1",
        report,
        omit_top_level_fields=("report_digest",),
    )
    assert report["pending_g0_task_ids"] == ["PREV7-0010", "PREV7-0011"]
    assert report["g0_green_claimed"] is False


def test_owner_clarifications_are_closed_not_deferred() -> None:
    report = build_g0_foundation_report()
    assert report["read_packages_scope_present"] is True
    assert report["provider_download_required_now"] is False
    assert report["current_v7_data_input"] == (
        "owner_supplied_frozen_local_data_lake"
    )
    assert report["maximum_incremental_net_spend_usd"] == 0


def test_preservation_is_dual_verified_and_locked_is_contaminated() -> None:
    report = build_g0_foundation_report()
    assert report["private_storage"]["primary"]["private"] is True
    assert report["private_storage"]["mirror"]["private"] is True
    assert report["preservation"] == {
        "v6_primary_clean_restore": True,
        "v6_mirror_clean_restore": True,
        "locked_primary_clean_verification": True,
        "locked_mirror_clean_verification": True,
        "locked_payload_file_count": 343,
        "locked_source_run_count": 17,
        "locked_remote_artifact_count": 15,
    }
    assert report["scientific_boundaries"]["locked_data_opened"] is False
    assert report["scientific_boundaries"][
        "scientific_processing_performed"
    ] is False


def test_foundation_only_claims_tasks_with_checked_evidence() -> None:
    effects = build_g0_foundation_report()["formal_task_effects"]
    assert "PREV7-0010" not in effects
    assert "PREV7-0011" not in effects
    assert set(effects) == {
        "PREV7-0001",
        "PREV7-0002",
        "PREV7-0003",
        "PREV7-0004",
        "PREV7-0005",
        "PREV7-0006",
        "PREV7-0007",
        "PREV7-0008",
        "PREV7-0009",
        "PREV7-0012",
    }
