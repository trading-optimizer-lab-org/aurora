from __future__ import annotations

from copy import deepcopy
import json

import pytest

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.locked_evidence import (
    ARCHIVE_SHA256,
    ARTIFACT_RECORDS,
    FAILED_RUNS_WITHOUT_ARTIFACT,
    MIRROR_VERIFICATION_PATH,
    PRESERVATION_REPORT_PATH,
    PRIMARY_VERIFICATION_PATH,
    RUN_RECORDS,
    SOURCE_RUN_IDS,
    LockedEvidenceError,
    build_locked_evidence_preservation_report,
    validate_locked_evidence_verification,
)


def _load(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_two_private_custodies_verified_the_same_archive() -> None:
    primary = _load(PRIMARY_VERIFICATION_PATH)
    mirror = _load(MIRROR_VERIFICATION_PATH)
    validate_locked_evidence_verification(primary, custody="primary")
    validate_locked_evidence_verification(mirror, custody="mirror")
    assert primary["archive_sha256"] == mirror["archive_sha256"]
    assert primary["archive_sha256"] == ARCHIVE_SHA256
    assert primary["private_manifest_sha256"] == (
        mirror["private_manifest_sha256"]
    )
    assert primary["workflow_repository"] != mirror["workflow_repository"]
    assert primary["release_id"] != mirror["release_id"]
    assert primary["workflow_run_id"] != mirror["workflow_run_id"]


def test_verification_receipt_rejects_any_classification_change() -> None:
    primary = _load(PRIMARY_VERIFICATION_PATH)
    tampered = deepcopy(primary)
    tampered["pristine_locked"] = True
    with pytest.raises(
        LockedEvidenceError,
        match="pristine_locked",
    ):
        validate_locked_evidence_verification(
            tampered,
            custody="primary",
        )


def test_public_report_is_deterministic_complete_and_fail_closed() -> None:
    report = build_locked_evidence_preservation_report()
    checked = _load(PRESERVATION_REPORT_PATH)
    assert checked == report
    assert PRESERVATION_REPORT_PATH.read_bytes() == (
        canonical_bytes(report) + b"\n"
    )
    assert report["report_digest"] == domain_digest(
        "GTBI_V7_LOCKED_EVIDENCE_PRESERVATION_REPORT_V1",
        report,
        omit_top_level_fields=("report_digest",),
    )
    assert report["source_run_ids"] == SOURCE_RUN_IDS
    assert report["failed_runs_without_artifact"] == (
        FAILED_RUNS_WITHOUT_ARTIFACT
    )
    assert len(report["runs"]) == 17
    assert len(report["preserved_remote_artifacts"]) == 15
    assert report["archive"]["payload_file_count"] == 343
    assert report["archive"]["payload_bytes"] == 29_347_076
    assert sum(report["preserved_component_counts"].values()) == 343
    assert report["historical_post_validation_contaminated"] is True
    assert report["pristine_locked"] is False
    assert report["locked_data_opened_during_preservation"] is False
    assert report["locked_data_opened_during_verification"] is False
    assert report["scientific_processing_performed"] is False
    assert report["strategy_evaluation_performed"] is False
    assert report["formal_task_effects"] == {
        "PREV7-0004": "evidence_ready"
    }
    assert report["formal_task_completion_claimed"] is False


def test_every_run_and_preserved_artifact_has_exact_public_provenance() -> None:
    assert [row["run_id"] for row in RUN_RECORDS] == SOURCE_RUN_IDS
    run_ids = set(SOURCE_RUN_IDS)
    artifact_run_ids = {row["run_id"] for row in ARTIFACT_RECORDS}
    assert artifact_run_ids == run_ids - set(FAILED_RUNS_WITHOUT_ARTIFACT)
    assert len({row["artifact_id"] for row in ARTIFACT_RECORDS}) == 15
    for run in RUN_RECORDS:
        assert len(run["head_sha"]) == 40
        assert run["workflow_path"].startswith(".github/workflows/")
        assert run["status"] == "completed"
        assert run["conclusion"] in {"success", "failure"}
        assert run["first_observed_at_utc"] == run["created_at_utc"]
    for artifact in ARTIFACT_RECORDS:
        assert artifact["sha256"].startswith("sha256:")
        assert len(artifact["sha256"]) == 71
        assert artifact["size_bytes"] > 0
        assert artifact["preserved_as_exact_zip"] is True


def test_public_report_does_not_publish_local_paths_or_result_metrics() -> None:
    report = build_locked_evidence_preservation_report()
    encoded = canonical_bytes(report)
    lowered = encoded.lower()
    assert b"c:\\" not in lowered
    assert b"e:\\" not in lowered
    assert b"local_survivors/" not in lowered

    keys: set[str] = set()

    def collect_keys(value) -> None:
        if isinstance(value, dict):
            keys.update(str(key) for key in value)
            for child in value.values():
                collect_keys(child)
        elif isinstance(value, list):
            for child in value:
                collect_keys(child)

    collect_keys(report)
    assert keys.isdisjoint(
        {
            "sharpe",
            "profit_factor",
            "trade_return",
            "best_candidate",
        }
    )
