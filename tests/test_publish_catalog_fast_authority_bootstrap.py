"""Maintenance CLI imports authentic fixture history and mutates only a pristine anchor."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityEditBindingV1
from scripts.bootstrap_catalog_fast_authority import build_bootstrap_candidate
from tests.test_bootstrap_catalog_fast_authority import bootstrap_transport, COMMIT
from tests.test_catalog_fast_authority_github import publication_transport


@pytest.mark.parametrize("fault", [None, "modified_anchor", "restored_anchor", "wrong_pin", "response_lost"])
def test_bootstrap_cli_preserves_six_verified_generations(tmp_path, monkeypatch, fault):
    from scripts import publish_catalog_fast_authority_bootstrap as command

    history = bootstrap_transport()
    expected = build_bootstrap_candidate(**history)
    fixture = publication_transport()
    issue = fixture.edit["data"]["repository"]["issue"]
    issue.update(body="AURORA CATALOG AUTHORITY LEDGER V1\n", lastEditedAt=None, editor=None)
    issue["userContentEdits"]["nodes"] = []
    if fault == "modified_anchor":
        issue["body"] = "unrelated existing state"
    if fault == "restored_anchor":
        issue.update(lastEditedAt="2026-09-05T11:59:00Z", editor={"login": "github-actions[bot]"})
        issue["userContentEdits"]["nodes"] = [{"id": "E_restored", "editedAt": issue["lastEditedAt"],
            "deletedAt": None, "editor": issue["editor"]}]
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "requester.pem").write_bytes(history["public_key"])
    (root / "config/catalog_authority_anchor_v1.json").write_text(json.dumps(fixture.anchor))
    (root / "config/catalog_controller_actors_v1.json").write_text(json.dumps({"requester_public_key_path": "requester.pem",
        "request_actors": ["requester"], "ledger_actor": "github-actions[bot]"}))
    (root / "config/catalog_fast_authority_bootstrap_v1.json").write_text(json.dumps({"schema_version": "1",
        "campaign_key": history["campaign_key"], "expected_tail_sha256": history["expected_tail_sha256"],
        "expected_state_sha256": "f" * 64 if fault == "wrong_pin" else expected.state_sha256}))
    client = history["client"]
    original_get = client.get_json

    def get_json(path):
        if path.endswith("/actions/runs/234"):
            return {**fixture.run, "id": 234, "head_sha": COMMIT}, None
        if path.endswith("/actions/runs/234/attempts/1/jobs?per_page=100&page=1"):
            return {"total_count": 1, "jobs": [{"id": 790, "name": "bootstrap", "run_id": 234,
                "run_attempt": 1, "head_sha": COMMIT, "status": "in_progress"}]}, None
        return original_get(path)

    client.get_json = get_json
    writes = []

    def process(args, **kwargs):
        if args[0] == "git":
            return SimpleNamespace(returncode=0, stdout=COMMIT + "\n")
        if args == ["gh", "api", "graphql", "--input", "-"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(fixture.edit))
        assert args == ["gh", "api", "--method", "PATCH", "repos/" + client.repository + "/issues/161", "--input", "-"]
        writes.append(args)
        issue.update(body=json.loads(kwargs["input"])["body"], lastEditedAt="2026-09-05T12:00:02Z",
            editor={"login": "github-actions[bot]"})
        issue["userContentEdits"]["nodes"] = [{"id": "E_bootstrap", "editedAt": issue["lastEditedAt"],
            "deletedAt": None, "editor": issue["editor"]}]
        if fault == "response_lost":
            raise TimeoutError("lost response")
        return SimpleNamespace(returncode=0, stdout="{}")

    monkeypatch.setattr(command.subprocess, "run", process)
    monkeypatch.setattr(command, "CatalogGitHubReadOnlyClient", lambda *args: client)
    monkeypatch.setattr(command, "_download_owner_archive", lambda repository, token, artifact: history["download_archive"](artifact))
    for name, value in {"GH_TOKEN": "fixture-only", "GITHUB_REPOSITORY": client.repository,
        "CATALOG_PROTECTED_COMMIT_SHA": COMMIT, "RUNNER_TEMP": str(tmp_path), "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ID": "234", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "bootstrap"}.items():
        monkeypatch.setenv(name, value)
    output = tmp_path / "publication.json"
    code = command.main(["--repo-root", str(root), "--output", str(output)])
    if fault in {None, "response_lost"}:
        assert code == 0
        staged = FastAuthorityEditBindingV1.model_validate_json(output.read_text())
        assert staged.state.campaigns[0].generation == 6
        assert staged.state.campaigns[0].owner_run_id == 33910681070
        assert staged.state.campaigns[0].terminal_receipt_sha256 is None
        assert staged.edit_node_id == "E_bootstrap"
        assert len(writes) == 1
        second_output = tmp_path / "second-publication.json"
        assert command.main(["--repo-root", str(root), "--output", str(second_output)]) == 2
        assert not second_output.exists()
        assert len(writes) == 1
    else:
        assert code == 2
        assert not output.exists()
        assert writes == []


def test_maintenance_writer_shares_lock_and_has_no_engine():
    root = Path(__file__).resolve().parents[1]
    maintenance = load_github_yaml(root / ".github/workflows/catalog-fast-authority-maintenance.yml")
    controller = load_github_yaml(root / ".github/workflows/catalog-fast-controller.yml")
    assert set(maintenance["jobs"]) == {"bootstrap"}
    job = maintenance["jobs"]["bootstrap"]
    assert job["concurrency"] == controller["jobs"]["gate"]["concurrency"]
    ids = [step.get("id") for step in job["steps"]]
    assert ids.index("write_authority") < ids.index("publish_authority") < ids.index("verify_authority")
