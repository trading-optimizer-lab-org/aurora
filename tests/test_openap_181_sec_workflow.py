from __future__ import annotations

from pathlib import Path


def test_sec_accounting_workflow_is_manual_bounded_pinned_and_fail_closed():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "openap-181-sec-accounting-batch.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "workflow_call:" in text
    assert "  push:" not in text
    assert "  pull_request:" not in text
    for required_input in {
        "source_sha:",
        "sec_user_agent:",
        "start_quarter:",
        "end_quarter:",
        "formation_start:",
        "formation_end:",
    }:
        assert required_input in text
    assert 'default: "2021q1"' in text
    assert 'default: "2024q4"' in text
    assert 'default: "2021-01-31"' in text
    assert 'default: "2024-12-31"' in text
    threshold_step = text.index("Print frozen validation thresholds")
    download_step = text.index("Download bounded official SEC FSD")
    assert threshold_step < download_step
    assert "minimum_cross_sectional_coverage" in text
    assert "minimum_extreme_decile_agreement" in text
    assert "SEC_USER_AGENT" in text
    assert "Declared research identity and contact email or HTTPS URL" in text
    assert '${#SEC_USER_AGENT} -ge 20' in text
    assert "scripts/run_openap_181_sec_fsd_access.py" in text
    assert "FSD_AVAILABLE" in text
    assert "official_sec_fsd_access_blocked" in text
    assert "scripts/run_openap_181_sec_fsd_inputs.py" in text
    assert "scripts/run_openap_181_sec_accounting_batch.py" in text
    assert "scripts/run_openap_181_sec_accounting_validation.py" in text
    assert "historical_cik_permno_bridge_unavailable" in text
    assert "identity_not_verified" in text
    assert "scripts/run_openap_181_implementation_status.py" in text
    assert "len(strict_inventory) == 31" in text
    assert "openap-181-sec-accounting-validation" in text
    assert "retention-days: 90" in text


def test_companyfacts_probe_workflow_is_bounded_pinned_and_evidence_only():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "openap-181-sec-companyfacts-probe.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "  push:" not in text
    assert "source_sha:" in text
    assert "sec_user_agent:" in text
    assert "320193,789019,21344" in text
    assert "scripts/run_openap_181_sec_companyfacts_access.py" in text
    assert "all_downloaded" in text
    assert "score_eligible" not in text
    assert "openap-181-sec-companyfacts-probe" in text
    assert "retention-days: 90" in text
