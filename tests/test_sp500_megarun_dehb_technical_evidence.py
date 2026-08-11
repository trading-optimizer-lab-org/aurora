from __future__ import annotations

import json
from pathlib import Path


def _official_report() -> dict[str, object]:
    return {
        "ready": True,
        "official_dehb_version": "0.1.2",
        "configspace_version": "1.2.2",
        "lane_count": 240,
        "all_configspaces_exact": True,
        "fidelities": [1, 3, 9, 27],
        "eta": 3,
        "actual_four_worker_run": True,
        "worker_equivalence_1_2_4": True,
        "checkpoint_resume_exact": True,
        "forbidden_config_rejection_safe": True,
        "f015_parameter_grid_finite": True,
        "search_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "snapshot_mounted": False,
        "dependency_lock_verified": True,
    }


def test_technical_evidence_closes_system_gates_55_56_and_60(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )
    from aurora.infra.sp500_megarun.dehb_technical_evidence import (
        build_technical_evidence,
        validate_technical_evidence,
    )

    repo = Path(__file__).resolve().parents[1]
    campaign = load_and_validate_campaign_contract(
        repo / "config/sp500_megarun_dehb_campaign_v1.json"
    )
    report_path = tmp_path / "official_report.json"
    report_path.write_text(json.dumps(_official_report()), encoding="utf-8")

    evidence = build_technical_evidence(
        campaign,
        official_report_path=report_path,
        work_dir=tmp_path / "faults",
        github_sha="a" * 40,
    )

    validate_technical_evidence(evidence, campaign_sha256=campaign.sha256)
    assert evidence["gates"]["55"]["status"] == "PASS"
    assert evidence["gates"]["56"]["status"] == "PASS"
    assert evidence["gates"]["60"]["status"] == "PASS"
    assert evidence["fault_injection"]["controller_retries_missing_jobs"] is True
    assert evidence["fault_injection"]["tampered_job_payload_rejected"] is True
    assert evidence["fault_injection"]["tampered_checkpoint_rejected"] is True
    assert evidence["validation_opened"] is False
    assert evidence["locked_opened"] is False


def test_technical_evidence_rejects_opened_validation() -> None:
    from aurora.infra.sp500_megarun.dehb_technical_evidence import (
        TechnicalEvidenceError,
        validate_technical_evidence,
    )

    evidence = {
        "campaign_contract_sha256": "b" * 64,
        "gates": {
            gate: {"status": "PASS"} for gate in ("55", "56", "60")
        },
        "validation_opened": True,
        "locked_opened": False,
    }
    try:
        validate_technical_evidence(evidence, campaign_sha256="b" * 64)
    except TechnicalEvidenceError as exc:
        assert "TECHNICAL_EVIDENCE_BOUNDARY_OPEN" in str(exc)
    else:
        raise AssertionError("opened validation evidence was accepted")
