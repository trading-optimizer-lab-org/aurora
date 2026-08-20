"""Incremental, read-only GitHub Actions ingestion for the Aurora dashboard.

The command writes only through the authenticated dashboard ingestion endpoint.
It never dispatches, cancels, reruns, or changes a GitHub workflow.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from scripts.aurora_dashboard_archive import archive_decision
from scripts.aurora_dashboard_parsers import ParserContext, parse_artifact


GITHUB_API_VERSION = "2022-11-28"
DEFAULT_OWNER = "trading-optimizer-lab-org"
DEFAULT_REPO = "aurora"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class GitHubApiError(RuntimeError):
    """A bounded GitHub API error with the endpoint and status code."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SyncCursor:
    page: int = 1
    updated_after: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "updated_after": self.updated_after}


@dataclass
class SyncReport:
    page: int
    runs_seen: int = 0
    workflows_seen: int = 0
    jobs_seen: int = 0
    artifacts_seen: int = 0
    results_seen: int = 0
    archives_prepared: int = 0
    next_cursor: SyncCursor | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "runs_seen": self.runs_seen,
            "workflows_seen": self.workflows_seen,
            "jobs_seen": self.jobs_seen,
            "artifacts_seen": self.artifacts_seen,
            "results_seen": self.results_seen,
            "archives_prepared": self.archives_prepared,
            "next_cursor": self.next_cursor.to_dict() if self.next_cursor else None,
            "errors": self.errors,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _duration(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        left = datetime.fromisoformat(start.replace("Z", "+00:00"))
        right = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0, int((right - left).total_seconds()))
    except ValueError:
        return None


def _login(actor: Any) -> str:
    if isinstance(actor, dict):
        return str(actor.get("login") or actor.get("name") or "unknown")
    return str(actor or "unknown")


def _safe_name(name: str) -> str:
    normalized = _SAFE_NAME.sub("-", name.strip()).strip(".-")
    return normalized[:160] or "artifact"


def _content_type(name: str) -> str | None:
    suffix = PurePosixPath(name.lower()).suffix
    return {
        ".json": "application/json",
        ".jsonl": "application/jsonl",
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".html": "text/html",
        ".htm": "text/html",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
    }.get(suffix)


class GitHubClient:
    def __init__(self, token: str | None, owner: str = DEFAULT_OWNER, repo: str = DEFAULT_REPO, base_url: str = "https://api.github.com"):
        self.token = token
        self.owner = owner
        self.repo = repo
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, *, params: dict[str, Any] | None = None, accept: str = "application/vnd.github+json", raw: bool = False) -> Any:
        query = urllib.parse.urlencode({key: value for key, value in (params or {}).items() if value is not None})
        url = f"{self.base_url}{path}{'?' + query if query else ''}"
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "aurora-dashboard-sync/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = response.read()
                return payload if raw else json.loads(payload.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read(1024).decode("utf-8", errors="replace")
                if exc.code in {429, 500, 502, 503, 504} and attempt < 3:
                    time.sleep(2**attempt)
                    continue
                raise GitHubApiError(f"GitHub {exc.code} at {path}: {body[:300]}", exc.code) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < 3:
                    time.sleep(2**attempt)
                    continue
                raise GitHubApiError(f"GitHub network error at {path}: {exc}") from exc
        raise GitHubApiError(f"GitHub request exhausted at {path}")

    def list_workflows(self, page: int = 1, per_page: int = 100) -> list[dict[str, Any]]:
        payload = self._request(f"/repos/{self.owner}/{self.repo}/actions/workflows", params={"page": page, "per_page": per_page})
        return list(payload.get("workflows", []))

    def list_runs(self, page: int = 1, per_page: int = 100) -> list[dict[str, Any]]:
        payload = self._request(f"/repos/{self.owner}/{self.repo}/actions/runs", params={"page": page, "per_page": per_page})
        return list(payload.get("workflow_runs", []))

    def list_jobs(self, run_id: int, per_page: int = 100) -> list[dict[str, Any]]:
        payload = self._request(f"/repos/{self.owner}/{self.repo}/actions/runs/{run_id}/jobs", params={"per_page": per_page})
        return list(payload.get("jobs", []))

    def list_artifacts(self, run_id: int, per_page: int = 100) -> list[dict[str, Any]]:
        payload = self._request(f"/repos/{self.owner}/{self.repo}/actions/runs/{run_id}/artifacts", params={"per_page": per_page})
        return list(payload.get("artifacts", []))

    def download_artifact(self, archive_url: str) -> bytes:
        parsed = urllib.parse.urlparse(archive_url)
        if parsed.scheme not in {"https"} or parsed.netloc not in {"api.github.com", "github.com"}:
            raise GitHubApiError("refusing artifact URL outside github.com")
        return self._request(parsed.path, accept="application/zip", raw=True)


def normalize_workflow(payload: dict[str, Any], captured_at: str | None = None) -> dict[str, Any]:
    captured_at = captured_at or _now()
    return {
        "workflow_id": int(payload.get("id", 0)),
        "name": str(payload.get("name") or "Unknown workflow"),
        "path": str(payload.get("path") or ""),
        "state": str(payload.get("state") or "unknown"),
        "triggers": [],
        "parser_key": "generic",
        "parser_status": "generic",
        "first_seen_at": captured_at,
        "last_seen_at": captured_at,
        "run_count": 0,
        "success_count": 0,
        "failure_count": 0,
    }


def normalize_run(payload: dict[str, Any], captured_at: str | None = None) -> dict[str, Any]:
    captured_at = captured_at or _now()
    started = payload.get("run_started_at") or payload.get("created_at")
    completed = payload.get("updated_at") if payload.get("status") == "completed" else None
    workflow_name = str(payload.get("name") or payload.get("display_title") or "Unknown workflow")
    parser_key = next((key for key in ("atlas", "swr", "spy", "btc", "paper", "literature", "openap") if key in workflow_name.lower()), "generic")
    parser_status = "specialized" if parser_key != "generic" else "generic"
    return {
        "run_id": int(payload.get("id", 0)),
        "workflow_id": int(payload.get("workflow_id", 0)),
        "workflow_name": workflow_name,
        "name": str(payload.get("display_title") or payload.get("name") or workflow_name),
        "status": str(payload.get("status") or "unknown"),
        "conclusion": payload.get("conclusion"),
        "event": str(payload.get("event") or "unknown"),
        "branch": str(payload.get("head_branch") or "unknown"),
        "commit_sha": str(payload.get("head_sha") or ""),
        "actor": _login(payload.get("actor")),
        "run_number": int(payload.get("run_number") or 0),
        "run_attempt": int(payload.get("run_attempt") or 1),
        "created_at": str(payload.get("created_at") or captured_at),
        "updated_at": str(payload.get("updated_at") or captured_at),
        "started_at": started,
        "completed_at": completed,
        "duration_seconds": _duration(started, completed),
        "html_url": str(payload.get("html_url") or ""),
        "parser_status": parser_status,
        "artifact_count": 0,
        "result_count": 0,
        "raw_manifest_key": f"runs/{int(payload.get('id', 0))}/manifest.json",
        "captured_at": captured_at,
    }


def normalize_job(payload: dict[str, Any], captured_at: str | None = None) -> dict[str, Any]:
    captured_at = captured_at or _now()
    started = payload.get("started_at")
    completed = payload.get("completed_at")
    return {
        "job_id": int(payload.get("id", 0)),
        "run_id": int(payload.get("run_id", 0)),
        "name": str(payload.get("name") or "Unnamed job"),
        "status": str(payload.get("status") or "unknown"),
        "conclusion": payload.get("conclusion"),
        "started_at": started,
        "completed_at": completed,
        "duration_seconds": _duration(started, completed),
        "runner_name": payload.get("runner_name"),
        "html_url": str(payload.get("html_url") or ""),
        "steps": payload.get("steps") if isinstance(payload.get("steps"), list) else [],
        "captured_at": captured_at,
    }


def normalize_artifact(payload: dict[str, Any], captured_at: str | None = None) -> dict[str, Any]:
    captured_at = captured_at or _now()
    run = payload.get("workflow_run") if isinstance(payload.get("workflow_run"), dict) else {}
    run_id = int(run.get("id") or payload.get("run_id") or 0)
    artifact_id = int(payload.get("id", 0))
    expired = bool(payload.get("expired", False))
    return {
        "artifact_id": artifact_id,
        "run_id": run_id,
        "name": str(payload.get("name") or f"artifact-{artifact_id}"),
        "size_bytes": int(payload.get("size_in_bytes") or 0),
        "created_at": str(payload.get("created_at") or captured_at),
        "expires_at": payload.get("expires_at"),
        "expired": expired,
        "archive_state": "expired" if expired else "indexed",
        "archive_key": None,
        "content_type": None,
        "parser_status": "unclassified",
        "source_url": str(payload.get("archive_download_url") or payload.get("html_url") or ""),
        "captured_at": captured_at,
        "archive_download_url": str(payload.get("archive_download_url") or ""),
    }


def _archive_entries(
    client: GitHubClient,
    artifact: dict[str, Any],
    context_workflow: str,
    used_bytes: int,
    quota_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, list[str]]:
    """Download one GitHub ZIP only when explicitly requested and inspect it."""
    archives: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    if not artifact.get("archive_download_url"):
        return archives, results, used_bytes, errors
    try:
        raw_zip = client.download_artifact(str(artifact["archive_download_url"]))
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as bundle:
            for member in bundle.infolist():
                if member.is_dir() or member.file_size > 50 * 1024 * 1024:
                    continue
                name = PurePosixPath(member.filename).name
                payload = bundle.read(member)
                content_type = _content_type(name)
                decision = archive_decision(name, len(payload), content_type, used_bytes, quota_bytes)
                if decision.should_archive:
                    key = f"runs/{artifact['run_id']}/artifacts/{artifact['artifact_id']}/{_safe_name(member.filename)}"
                    archives.append({
                        "key": key,
                        "content_base64": base64.b64encode(payload).decode("ascii"),
                        "content_type": content_type or "application/octet-stream",
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    })
                    used_bytes += len(payload)
                    report = parse_artifact(name, payload, ParserContext(int(artifact["run_id"]), int(artifact["artifact_id"]), context_workflow, name))
                    results.extend(metric.to_dict() for metric in report.metrics)
                if len(archives) >= 20:
                    break
    except (GitHubApiError, zipfile.BadZipFile, OSError) as exc:
        errors.append(f"artifact {artifact.get('artifact_id')}: {exc}")
    return archives, results, used_bytes, errors


def build_batch(
    client: GitHubClient,
    page: int,
    per_page: int = 100,
    *,
    archive: bool = False,
    used_bytes: int = 0,
    quota_bytes: int = 7_516_192_768,
    max_runs: int | None = None,
) -> tuple[dict[str, Any], SyncReport]:
    captured_at = _now()
    run_payloads = client.list_runs(page=page, per_page=per_page)
    if max_runs is not None:
        run_payloads = run_payloads[:max_runs]
    report = SyncReport(page=page, runs_seen=len(run_payloads))
    workflows: dict[int, dict[str, Any]] = {}
    if page == 1:
        for payload in client.list_workflows(page=1, per_page=100):
            workflow = normalize_workflow(payload, captured_at)
            workflows[workflow["workflow_id"]] = workflow
    runs: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    archives: list[dict[str, Any]] = []
    for payload in run_payloads:
        run = normalize_run(payload, captured_at)
        runs.append(run)
        workflows.setdefault(run["workflow_id"], {
            "workflow_id": run["workflow_id"],
            "name": run["workflow_name"],
            "path": "",
            "state": "active",
            "triggers": [],
            "parser_key": run["workflow_name"].lower().split(" ", 1)[0],
            "parser_status": run["parser_status"],
            "first_seen_at": run["created_at"],
            "last_seen_at": run["updated_at"],
            "run_count": 0,
            "success_count": 0,
            "failure_count": 0,
        })
        try:
            run_jobs = [normalize_job(item, captured_at) for item in client.list_jobs(run["run_id"])]
            run_artifacts = [normalize_artifact(item, captured_at) for item in client.list_artifacts(run["run_id"])]
        except GitHubApiError as exc:
            report.errors.append(str(exc))
            run_jobs, run_artifacts = [], []
        jobs.extend(run_jobs)
        artifacts.extend(run_artifacts)
        if archive:
            for artifact in run_artifacts:
                prepared, parsed, used_bytes, errors = _archive_entries(client, artifact, run["workflow_name"], used_bytes, quota_bytes)
                archives.extend(prepared)
                results.extend(parsed)
                report.errors.extend(errors)
                if prepared:
                    artifact["archive_state"] = "archived"
                    artifact["archive_key"] = prepared[0]["key"]
                    artifact["parser_status"] = "specialized" if parsed else "generic"
                elif artifact["archive_state"] == "indexed":
                    artifact["archive_state"] = "source_only"
        run["artifact_count"] = sum(1 for artifact in run_artifacts if artifact["run_id"] == run["run_id"])
        run["result_count"] = sum(1 for metric in results if metric["run_id"] == run["run_id"])
    report.workflows_seen = len(workflows)
    report.jobs_seen = len(jobs)
    report.artifacts_seen = len(artifacts)
    report.results_seen = len(results)
    report.archives_prepared = len(archives)
    if len(run_payloads) >= per_page:
        report.next_cursor = SyncCursor(page=page + 1)
    batch = {
        "schema_version": 1,
        "captured_at": captured_at,
        "cursor": SyncCursor(page=page, updated_after=None).to_dict(),
        "next_cursor": report.next_cursor.to_dict() if report.next_cursor else None,
        "workflows": list(workflows.values()),
        "runs": runs,
        "jobs": jobs,
        "artifacts": artifacts,
        "results": results,
        "archives": archives,
    }
    return batch, report


def post_batch(url: str, token: str, batch: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url.rstrip("/") + "/internal/sync/batch",
        data=json.dumps(batch, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", "User-Agent": "aurora-dashboard-sync/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"dashboard ingestion {exc.code}: {body[:300]}") from exc


def _fixture_batch(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("fixture root must be an object")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default=os.getenv("AURORA_DASHBOARD_OWNER", DEFAULT_OWNER))
    parser.add_argument("--repo", default=os.getenv("AURORA_DASHBOARD_REPO", DEFAULT_REPO))
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--per-page", type=int, choices=(10, 25, 50, 100), default=100)
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--archive", action="store_true")
    parser.add_argument("--quota-bytes", type=int, default=7_516_192_768)
    parser.add_argument("--dashboard-url", default=os.getenv("AURORA_DASHBOARD_URL"))
    parser.add_argument("--sync-token", default=os.getenv("AURORA_DASHBOARD_SYNC_TOKEN"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fixture", help="load an already normalized batch without making network calls")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.fixture:
        batch = _fixture_batch(args.fixture)
        print(json.dumps({"fixture": args.fixture, "runs": len(batch.get("runs", [])), "artifacts": len(batch.get("artifacts", []))}, indent=2))
        return 0
    client = GitHubClient(args.token, args.owner, args.repo)
    batch, report = build_batch(client, args.page, args.per_page, archive=args.archive, quota_bytes=args.quota_bytes, max_runs=args.max_runs)
    if args.dry_run or not args.dashboard_url:
        print(json.dumps({"report": report.to_dict(), "batch_counts": {key: len(batch.get(key, [])) for key in ("workflows", "runs", "jobs", "artifacts", "results", "archives")}}, indent=2))
        return 0
    if not args.sync_token:
        raise SystemExit("--sync-token or AURORA_DASHBOARD_SYNC_TOKEN is required for writes")
    response = post_batch(args.dashboard_url, args.sync_token, batch)
    print(json.dumps({"report": report.to_dict(), "ingestion": response}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
