"""Exercise the deployed reader entrypoint, with authenticated HTTP replaced only in transport."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from tests.test_catalog_fast_authority_github import publication_transport


@pytest.mark.parametrize("corrupt", [False, True, "missing"])
def test_reader_cli_writes_only_after_current_publication_verified(tmp_path, monkeypatch, corrupt):
    from scripts import verify_catalog_fast_authority as command

    fixture = publication_transport()
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config/catalog_authority_anchor_v1.json").write_text(json.dumps(fixture.anchor))
    output = tmp_path / "current.json"
    if corrupt is True:
        fixture.artifact["digest"] = "sha256:" + "0" * 64
    if corrupt == "missing":
        original_get = fixture.client.get_json
        fixture.client.get_json = lambda path: ({"total_count": 0, "artifacts": []}, None) if "/artifacts?" in path else original_get(path)

    def process(args, **kwargs):
        if args[0] == "git":
            assert args == ["git", "-C", str(root), "rev-parse", "HEAD"]
            return SimpleNamespace(returncode=0, stdout="a" * 40 + "\n")
        assert args == ["gh", "api", "graphql", "--input", "-"]
        query = json.loads(kwargs["input"])["query"]
        assert "userContentEdits(first:1)" in query
        assert "issue(number:161)" in query
        return SimpleNamespace(returncode=0, stdout=json.dumps(fixture.edit))

    monkeypatch.setattr(command.subprocess, "run", process)
    monkeypatch.setattr(command, "CatalogGitHubReadOnlyClient", lambda *args: fixture.client)
    monkeypatch.setattr(command, "_download_owner_archive", lambda *args: fixture.raw)
    monkeypatch.setenv("GH_TOKEN", "fixture-only")
    monkeypatch.setenv("GITHUB_REPOSITORY", fixture.client.repository)
    monkeypatch.setenv("CATALOG_PROTECTED_COMMIT_SHA", "a" * 40)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    exit_code = command.main(["--repo-root", str(root), "--output", str(output)])
    if corrupt:
        assert exit_code == (4 if corrupt == "missing" else 2)
        assert not output.exists()
    else:
        assert exit_code == 0
        assert FastAuthorityStateV1.model_validate_json(output.read_text()).revision == 1


def test_workflow_checks_current_authority_before_admission():
    # Wiring complements the real CLI test; live workflow acceptance remains T13.
    workflow = load_github_yaml(Path(__file__).resolve().parents[1] / ".github/workflows/catalog-fast-controller.yml")
    steps = workflow["jobs"]["gate"]["steps"]
    reader = next(step for step in steps if step.get("id") == "authority")
    admission = next(step for step in steps if step.get("id") == "admit")
    assert steps.index(reader) < steps.index(admission)
    assert reader.get("continue-on-error", False) is False
    assert "scripts/verify_catalog_fast_authority.py" in reader["run"]
    assert "always()" not in admission["if"]


@pytest.mark.parametrize(("verification_exit", "write_outcome", "expected"), [
    ("0", "success", False), ("2", "success", False), ("4", "success", True),
    ("4", "failure", False), ("", "success", False),
])
def test_recovery_is_one_same_payload_upload_only_after_confirmed_absence(verification_exit, write_outcome, expected):
    root = Path(__file__).resolve().parents[1]
    for workflow_name, job_names in [("catalog-fast-controller.yml", ("gate", "finalize")),
            ("catalog-fast-authority-maintenance.yml", ("bootstrap",))]:
        workflow = load_github_yaml(root / ".github/workflows" / workflow_name)
        for job_name in job_names:
            steps = workflow["jobs"][job_name]["steps"]
            recovery = [step for step in steps if step.get("id") == "recover_authority"]
            assert len(recovery) == 1
            initial = next(step for step in steps if step.get("id") == "publish_authority")
            final = next(step for step in steps if step.get("id") == "verify_authority")
            assert recovery[0]["with"] == initial["with"]
            assert steps.index(initial) < steps.index(recovery[0]) < steps.index(final)
            assert final.get("continue-on-error", False) is False
            expression = recovery[0]["if"].removeprefix("${{").removesuffix("}}")
            expression = expression.replace("&&", " and ").replace("||", " or ")
            context = SimpleNamespace(write_authority=SimpleNamespace(outcome=write_outcome),
                inspect_publication=SimpleNamespace(outputs=SimpleNamespace(verification_exit=verification_exit)))
            assert eval(expression, {"__builtins__": {}}, {"steps": context}) is expected
