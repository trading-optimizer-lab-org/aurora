"""Exercise the deployed reader entrypoint, with authenticated HTTP replaced only in transport."""

import json
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from tests.test_catalog_fast_authority_github import publication_transport


@pytest.mark.parametrize("corrupt", [False, True, "missing", "handoff", "handoff_corrupt"])
def test_reader_cli_writes_only_after_current_publication_verified(tmp_path, monkeypatch, corrupt):
    from scripts import verify_catalog_fast_authority as command

    fixture = publication_transport()
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config/catalog_authority_anchor_v1.json").write_text(json.dumps(fixture.anchor))
    output = tmp_path / "current.json"
    if corrupt is True or corrupt == "handoff_corrupt":
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
    extra = []
    if corrupt in {"handoff", "handoff_corrupt"}:
        for name, value in {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
                "GITHUB_RUN_ID": "800", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "gate"}.items():
            monkeypatch.setenv(name, value)
        extra = ["--gate-handoff"]
    exit_code = command.main(["--repo-root", str(root), "--output", str(output)] + extra)
    if corrupt in {True, "missing", "handoff_corrupt"}:
        assert exit_code == (4 if corrupt == "missing" else 2)
        assert not output.exists()
        assert not (tmp_path / ".catalog-fast-gate-handoff").exists()
    else:
        assert exit_code == 0
        assert FastAuthorityStateV1.model_validate_json(output.read_text()).revision == 1
        if corrupt == "handoff":
            saved = json.loads((tmp_path / ".catalog-fast-gate-handoff/authority.json").read_bytes())
            assert saved["edition"][1] == "E_current"
            assert saved["state"]["state_sha256"] == fixture.state.state_sha256
