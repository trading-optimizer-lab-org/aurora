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
    assert "github.workspace" in job["env"]["PYTHONPATH"]
    assert "optimized_evaluation_mode == 'clean_portfolio_v7'" in job["if"]
    assert "python -m scripts.run_gtbi_clean_portfolio" in text
    assert "gtbi-clean-portfolio-v7-results" in text


def test_clean_portfolio_v7_workflow_stays_github_only_and_locked() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "C:\\" not in text
    assert "self-hosted" not in text
    assert 'default: "2021-01-01"' in text
    assert 'default: "2020-12-31"' in text
    assert "actions/download-artifact@v4" in text
    assert "run-id: ${{ inputs.data_run_id }}" in text


def test_clean_portfolio_shell_does_not_interpolate_dispatch_inputs() -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = payload["jobs"]["clean_portfolio_v7"]
    run_step = next(step for step in job["steps"] if step.get("name") == "Run clean portfolio sizing V7")
    assert "${{ inputs." not in run_step["run"]
    assert job["env"]["INPUT_LOCKED_START"] == "${{ inputs.locked_start }}"
    assert job["env"]["INPUT_VALIDATION_END"] == "${{ inputs.validation_end }}"


def test_workflow_exposes_separate_locked_forward_pass_inputs() -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = payload.get("on", payload.get(True))
    inputs = on["workflow_dispatch"]["inputs"]
    assert inputs["include_locked"]["default"] == "false"
    assert inputs["forward_end"]["default"] == "max"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--include-locked" in text
    assert "INPUT_INCLUDE_LOCKED" in text
