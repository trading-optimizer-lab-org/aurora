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


def test_official_sec_transport_probe_covers_hosted_runner_families_without_proxy():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "openap-181-sec-official-transport-probe.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "  push:" not in text
    for runner in {"ubuntu-24.04", "windows-2025", "macos-15"}:
        assert runner in text
    assert "source_sha:" in text
    assert "scripts/run_openap_181_sec_companyfacts_access.py" in text
    assert "scripts/run_openap_181_sec_fsd_access.py" in text
    assert 'CIKS: "320193"' in text
    assert 'START_QUARTER: "2024q4"' in text
    assert 'END_QUARTER: "2024q4"' in text
    assert "sec_official_companyfacts_fair_access" in text
    assert "sec_official_direct_fair_access" in text
    assert "openap-181-sec-official-transport-probe-" in text
    assert "build_sec_transport_matrix_blocker_evidence" in text
    assert "sec_accounting_batch_evidence.csv" in text
    assert "retention-days: 90" in text
    assert "r.jina.ai" not in text
    assert "score_eligible" not in text


def test_completion_audit_can_prefer_all_runner_sec_transport_evidence():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "openap-181-completion-audit.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "sec_transport_evidence_run_id:" in text
    assert "SEC_TRANSPORT_EVIDENCE_RUN_ID" in text
    assert "openap-181-sec-official-transport-probe-summary" in text
    assert "sec_accounting_batch_evidence.csv" in text
    assert "SEC_ACCOUNTING_EVIDENCE_EFFECTIVE_RUN_ID" in text
    assert "SEC_ACCOUNTING_EVIDENCE_ARTIFACT" in text
    assert (
        "official_sec_access_blocked_all_github_hosted_runner_families_http_403"
        in text
    )


def test_patent_source_probe_is_manual_pinned_and_fail_closed():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "openap-181-patent-source-probe.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "workflow_call:" in text
    assert "push:" not in text
    assert "2ee29097f7ca05fc0e56905e82474ad426c387b9" in text
    assert "60215d8db687b0c40060de1649cf0f14364cbac2cbdd16b5cb3dee2dcdb85f27" in text
    assert "4686ee4383bfc8bf43b7721766f28e04e331ea02bbffe4dd1358d5c02b5e675a" in text
    assert "openap-181-patent-source-probe-results" in text
    assert "patent_batch_evidence.csv" in text
    assert "retention-days: 90" in text
    assert "OOS_LOCKED" not in text
    assert "FORWARD" not in text
    assert "score_eligible" not in text


def test_completion_audit_can_consume_patent_source_evidence():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "openap-181-completion-audit.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "patent_evidence_run_id:" in text
    assert "patent_probe:" in text
    assert "uses: ./.github/workflows/openap-181-patent-source-probe.yml" in text
    assert "needs: patent_probe" in text
    assert "PATENT_EVIDENCE_RUN_ID" in text
    assert "openap-181-patent-source-probe-results" in text
    assert "patent_batch_evidence.csv" in text
    assert "PATENT_EVIDENCE" in text
    assert "patent_source_partial:" in text


def test_short_interest_source_probe_is_manual_official_and_fail_closed():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "openap-181-short-interest-source-probe.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "workflow_call:" in text
    assert "push:" not in text
    assert "www.finra.org/finra-data/browse-catalog/equity-short-interest" in text
    assert "scripts/run_openap_181_short_interest_source_probe.py" in text
    assert "short_interest_batch_evidence.csv" in text
    assert "openap-181-short-interest-source-probe-results" in text
    assert "raw_files_in_artifact" in text
    assert "retention-days: 90" in text
    assert "OOS_LOCKED" not in text
    assert "FORWARD" not in text
    assert "score_eligible" not in text


def test_completion_audit_can_consume_short_interest_source_evidence():
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "openap-181-completion-audit.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "short_interest_evidence_run_id:" in text
    assert "short_interest_probe:" in text
    assert (
        "uses: ./.github/workflows/openap-181-short-interest-source-probe.yml"
        in text
    )
    assert "needs: [patent_probe, short_interest_probe]" in text
    assert "SHORT_INTEREST_EVIDENCE_RUN_ID" in text
    assert "openap-181-short-interest-source-probe-results" in text
    assert "short_interest_batch_evidence.csv" in text
    assert "SHORT_INTEREST_EVIDENCE" in text
    assert "short_interest_source_partial:" in text
