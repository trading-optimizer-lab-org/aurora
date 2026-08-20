from __future__ import annotations

import json
import io
import urllib.request
import zipfile

from scripts.aurora_dashboard_sync import (
    GitHubClient,
    _GitHubRedirectHandler,
    build_batch,
    normalize_artifact,
    normalize_job,
    normalize_run,
    normalize_workflow,
)


class FakeGitHubClient(GitHubClient):
    def __init__(self) -> None:
        super().__init__(None)
        self.runs = [{
            "id": 10,
            "workflow_id": 20,
            "name": "SP500 Atlas Static Run",
            "display_title": "Atlas run",
            "status": "completed",
            "conclusion": "success",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": "abc123",
            "run_number": 4,
            "run_attempt": 1,
            "created_at": "2026-08-20T08:00:00Z",
            "updated_at": "2026-08-20T08:01:00Z",
            "run_started_at": "2026-08-20T08:00:00Z",
            "html_url": "https://github.com/example/run/10",
            "actor": {"login": "tester"},
        }]

    def list_workflows(self, page: int = 1, per_page: int = 100):
        return [{"id": 20, "name": "SP500 Atlas Static Run", "path": ".github/workflows/atlas.yml", "state": "active"}]

    def list_runs(self, page: int = 1, per_page: int = 100):
        return self.runs

    def list_jobs(self, run_id: int, per_page: int = 100):
        return [{"id": 30, "run_id": run_id, "name": "search", "status": "completed", "conclusion": "success", "started_at": "2026-08-20T08:00:00Z", "completed_at": "2026-08-20T08:00:30Z", "runner_name": "ubuntu", "html_url": "https://github.com/example/job/30", "steps": []}]

    def list_artifacts(self, run_id: int, per_page: int = 100):
        return [{"id": 40, "workflow_run": {"id": run_id}, "name": "summary.json", "size_in_bytes": 20, "created_at": "2026-08-20T08:01:00Z", "expires_at": "2026-09-19T08:01:00Z", "expired": False, "archive_download_url": "https://api.github.com/repos/example/artifacts/40"}]

    def download_artifact(self, archive_url: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("summary.csv", "sharpe\n" + "1.0\n" * 600)
        return buffer.getvalue()


def test_normalizers_map_github_shapes_to_stable_contracts() -> None:
    run = normalize_run({"id": 1, "workflow_id": 2, "name": "lint", "status": "completed", "conclusion": "failure", "head_branch": "main", "head_sha": "sha", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:01:00Z"})
    job = normalize_job({"id": 3, "run_id": 1, "name": "lint", "status": "completed", "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:00:02Z"})
    artifact = normalize_artifact({"id": 4, "workflow_run": {"id": 1}, "name": "report.json", "size_in_bytes": 10, "created_at": "2026-01-01T00:01:00Z"})

    assert run["run_id"] == 1 and run["parser_status"] == "generic"
    assert job["duration_seconds"] == 2
    assert artifact["run_id"] == 1 and artifact["archive_state"] == "indexed"


def test_build_batch_is_repeatable_and_contains_all_entity_groups() -> None:
    batch, report = build_batch(FakeGitHubClient(), 1, per_page=100)

    assert report.runs_seen == 1
    assert report.jobs_seen == 1
    assert report.artifacts_seen == 1
    assert batch["runs"][0]["run_id"] == 10
    assert batch["jobs"][0]["run_id"] == 10
    assert batch["artifacts"][0]["run_id"] == 10
    assert batch["next_cursor"] is None


def test_dry_run_fixture_is_json_safe() -> None:
    batch, _ = build_batch(FakeGitHubClient(), 1, per_page=100)
    json.dumps(batch)


def test_build_batch_caps_parsed_results_for_worker_batch_limit() -> None:
    batch, report = build_batch(FakeGitHubClient(), 1, per_page=100, archive=True)

    assert report.results_seen == 450
    assert len(batch["results"]) == 450


def test_artifact_redirect_drops_api_auth_before_signed_download() -> None:
    request = urllib.request.Request("https://api.github.com/repos/example/artifacts/40/zip")
    request.add_header("Authorization", "Bearer secret")
    request.add_header("Accept", "application/vnd.github+json")

    redirected = _GitHubRedirectHandler().redirect_request(
        request,
        None,
        302,
        "Found",
        {"Location": "https://production.example.invalid/artifact.zip"},
        "https://api.github.com/repos/example/artifacts/40/zip",
    )

    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Accept") == "application/octet-stream"
