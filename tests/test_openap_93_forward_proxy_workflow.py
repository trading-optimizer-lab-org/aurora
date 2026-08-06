from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/openap-five-forward-proxies.yml")


def test_forward_proxy_workflow_is_manual_github_only_and_chronological() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "GITHUB_ACTIONS: \"true\"" in text
    assert "train_end: \"2010-12-31\"" in text
    assert "validation_start: \"2011-01-01\"" in text
    assert "validation_end: \"2020-12-31\"" in text
    assert "locked_opened" in text
    assert "validation_used_for_selection" in text
    assert "backtest_enabled" in text


def test_forward_proxy_workflow_certifies_before_current_score() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "framework_contract:" in text
    assert "certify:" in text
    assert "current:" in text
    assert "publish:" in text
    assert "needs: [framework_contract, certify]" in text
    assert "forward_proxy_certificates.jsonl" in text
    assert "--forward-proxy-certificates" in text
    assert "--forward-proxy-source-manifest" in text
    assert "config/openap_93/five_forward_proxy_sources.yaml" in text


def test_forward_proxy_workflow_checkpoints_each_signal_before_certification() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "reconstruct:" in text
    assert "max-parallel: 5" in text
    for signal in (
        "DivSeason",
        "AnnouncementReturn",
        "EarningsStreak",
        "IndRetBig",
        "DelNetFin",
    ):
        assert f"          - {signal}" in text
    assert '--signals "${{ matrix.signal }}"' in text
    assert "Upload isolated reconstruction checkpoint" in text
    assert "merge_openap_five_proxy_reconstructions.py" in text
    assert "needs: [framework_contract, reconstruct]" in text


def test_forward_proxy_workflow_publishes_complete_final_artifact() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "name: openap-five-forward-proxies-results" in text
    for filename in (
        "forward_proxy_current_values.parquet",
        "forward_proxy_current_values.csv",
        "forward_proxy_candidate_metrics.csv",
        "forward_proxy_validation_metrics.csv",
        "forward_proxy_certificates.jsonl",
        "forward_proxy_score_ready.csv",
        "forward_proxy_missing_inputs.csv",
        "forward_proxy_source_audit.csv",
        "forward_proxy_summary.json",
    ):
        assert filename in text
    assert "if: ${{ always() }}" in text
