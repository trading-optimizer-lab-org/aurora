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
    assert (
        "https://www.sec.gov/files/dera/data/"
        "financial-statement-data-sets/" in text
    )
    assert "SEC_USER_AGENT" in text
    assert "--header \"User-Agent: ${SEC_USER_AGENT}\"" in text
    assert "scripts/run_openap_181_sec_fsd_inputs.py" in text
    assert "scripts/run_openap_181_sec_accounting_batch.py" in text
    assert "scripts/run_openap_181_sec_accounting_validation.py" in text
    assert "historical_cik_permno_bridge_unavailable" in text
    assert "identity_not_verified" in text
    assert "scripts/run_openap_181_implementation_status.py" in text
    assert "len(strict_inventory) == 31" in text
    assert "openap-181-sec-accounting-validation" in text
    assert "retention-days: 90" in text
