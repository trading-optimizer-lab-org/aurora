from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/global-technical-buy-indicator-external-pack-360jobs.yml")


def test_registered_workflow_has_clean_portfolio_v7_job() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    jobs = payload["jobs"]
    assert "clean_portfolio_v7" in jobs
    job = jobs["clean_portfolio_v7"]
    assert job["runs-on"] == "ubuntu-latest"
    assert "optimized_evaluation_mode == 'clean_portfolio_v7'" in job["if"]
    assert "scripts/run_gtbi_clean_portfolio.py" in text
    assert "gtbi-clean-portfolio-v7-results" in text


def test_clean_portfolio_v7_workflow_stays_github_only_and_locked() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "C:\\" not in text
    assert "self-hosted" not in text
    assert 'default: "2021-01-01"' in text
    assert 'default: "2020-12-31"' in text
    assert "actions/download-artifact@v4" in text
    assert "run-id: ${{ inputs.data_run_id }}" in text

