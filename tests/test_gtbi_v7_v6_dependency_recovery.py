from __future__ import annotations

from copy import deepcopy
import json

import pytest

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.scientific_assets import (
    validate_scientific_asset_manifest,
)
from infra.gtbi_v7_readiness.v6_dependency_recovery import (
    CALCULATION_COMMIT_SHA,
    DATA_PACK_IDENTITY,
    DEPENDENCY_LOCK_SHA256,
    MIRROR_VERIFICATION_PATH,
    PRIMARY_VERIFICATION_PATH,
    RECOVERY_REPORT_PATH,
    STRATEGY_PACK_DIGEST,
    V6DependencyRecoveryError,
    apply_recovery_to_scientific_manifest,
    build_dependency_recovery_report,
    validate_data_pack_verification,
)
from scripts.generate_gtbi_v7_scientific_asset_contract import (
    wrapper_only_fixture,
)


def _load(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_two_clean_runner_receipts_bind_exact_v6_inputs() -> None:
    primary = _load(PRIMARY_VERIFICATION_PATH)
    mirror = _load(MIRROR_VERIFICATION_PATH)
    validate_data_pack_verification(primary, custody="primary")
    validate_data_pack_verification(mirror, custody="mirror")
    assert primary["data_pack_manifest"] == mirror["data_pack_manifest"]
    assert primary["source_identity"] == mirror["source_identity"]
    assert primary["data_pack_manifest"]["data_pack_identity"] == (
        DATA_PACK_IDENTITY
    )
    source = primary["source_identity"]
    assert source["calculation_commit_sha"] == CALCULATION_COMMIT_SHA
    assert source["strategy_pack_digest"] == STRATEGY_PACK_DIGEST
    assert source["dependency_lock_sha256"] == DEPENDENCY_LOCK_SHA256
    assert primary["locked_data_opened"] is False
    assert mirror["locked_data_opened"] is False


def test_verification_rejects_a_single_identity_change() -> None:
    primary = _load(PRIMARY_VERIFICATION_PATH)
    tampered = deepcopy(primary)
    tampered["data_pack_manifest"]["data_pack_identity"] = "0" * 64
    with pytest.raises(
        V6DependencyRecoveryError,
        match="receipt digest mismatch",
    ):
        validate_data_pack_verification(tampered, custody="primary")


def test_dependency_report_is_canonical_and_truthfully_incomplete() -> None:
    report = build_dependency_recovery_report()
    checked = _load(RECOVERY_REPORT_PATH)
    assert checked == report
    assert RECOVERY_REPORT_PATH.read_bytes() == canonical_bytes(report) + b"\n"
    assert report["report_digest"] == domain_digest(
        "GTBI_V6_DEPENDENCY_RECOVERY_REPORT_V1",
        report,
        omit_top_level_fields=("report_digest",),
    )
    assert [row["layer"] for row in report["layers"]] == [
        "C",
        "D0",
        "D1",
        "D2",
        "D3",
        "S",
        "R",
    ]
    assert report["missing_layers"] == ["D0", "D1", "D2"]
    assert {
        row["layer"]
        for row in report["layers"]
        if row["authenticated"]
    } == {"C", "D3", "S", "R"}
    for layer in {"D0", "D1", "D2"}:
        row = next(item for item in report["layers"] if item["layer"] == layer)
        assert row["candidate_copy"] == "gtbi-v7-frozen-data-lake-v1"
        assert row["found"] is False
        assert row["authenticated"] is False
        assert row["reproducible"] is False
    assert report["full_v6_reproduction_claim_allowed"] is False
    assert report["scientific_processing_performed"] is False
    assert report["strategy_evaluation_performed"] is False
    assert report["locked_data_opened"] is False


def test_recovery_updates_only_proved_scientific_manifest_claims() -> None:
    manifest = apply_recovery_to_scientific_manifest(
        wrapper_only_fixture(),
    )
    validate_scientific_asset_manifest(manifest)
    assert manifest["missing_v6_dependency_layers"] == ["D0", "D1", "D2"]
    assert manifest["reproducibility_classification"] == (
        "result_preserved_inputs_incomplete"
    )
    assert manifest["reference_engine_code_sha"] == CALCULATION_COMMIT_SHA
    assert manifest["data_digest"] == "sha256:" + DATA_PACK_IDENTITY
    assert manifest["first_date"] == "1962-01-02"
    assert manifest["last_date"] == "2020-12-31"
    assert manifest["historical_post_validation_contaminated"] is False
    assert manifest["pristine_locked"] is True
    assert manifest["reuse_recovered_v6_inputs"] is False
    assert manifest["v6_historical_reproduction_confirmed"] is False
