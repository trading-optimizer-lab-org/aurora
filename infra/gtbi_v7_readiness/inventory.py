"""Bounded, fail-closed inventory for the GTBI V7 preservation bootstrap."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .canonical import canonical_bytes, raw_sha256

INVENTORY_SCOPE = "emergency_preservation"
SCHEMA_VERSION = "gtbi_v7_inventory_schema_v1"
USER_HOME_TOKEN = "<USER_HOME>"

CSV_SCHEMAS: dict[str, dict[str, Any]] = {
    "branches.csv": {
        "primary_key": ["name"],
        "columns": [
            "name",
            "sha",
            "protected",
            "protection_url",
            "commit_url",
        ],
    },
    "worktrees.csv": {
        "primary_key": ["worktree_path_redacted"],
        "columns": [
            "local_state",
            "worktree_path_redacted",
            "head_sha",
            "branch",
            "prunable",
            "locked",
            "dirty",
            "changed_paths_count",
            "scan_error",
        ],
    },
    "workflows.csv": {
        "primary_key": ["id"],
        "columns": [
            "id",
            "name",
            "path",
            "state",
            "created_at",
            "updated_at",
        ],
    },
    "runs_active.csv": {
        "primary_key": ["id"],
        "columns": [
            "id",
            "name",
            "workflow_id",
            "event",
            "status",
            "conclusion",
            "head_branch",
            "head_sha",
            "created_at",
            "updated_at",
            "run_started_at",
            "html_url",
        ],
    },
    "artifacts_critical.csv": {
        "primary_key": ["artifact_id"],
        "columns": [
            "artifact_id",
            "run_id",
            "name",
            "size_in_bytes",
            "digest",
            "expired",
            "created_at",
            "updated_at",
            "expires_at",
            "archive_download_url",
            "critical_reason",
            "metadata_match",
            "metadata_errors",
        ],
    },
    "releases.csv": {
        "primary_key": ["id"],
        "columns": [
            "id",
            "tag_name",
            "target_commitish",
            "name",
            "draft",
            "prerelease",
            "immutable",
            "created_at",
            "published_at",
            "html_url",
        ],
    },
    "packages.csv": {
        "primary_key": ["package_type", "name", "id"],
        "columns": [
            "id",
            "owner_scope",
            "package_type",
            "name",
            "visibility",
            "created_at",
            "updated_at",
            "html_url",
        ],
    },
    "collaborators.csv": {
        "primary_key": ["login"],
        "columns": [
            "login",
            "id",
            "type",
            "site_admin",
            "role_name",
            "permissions_json",
        ],
    },
    "environments.csv": {
        "primary_key": ["name"],
        "columns": [
            "id",
            "node_id",
            "name",
            "protection_rules_json",
            "deployment_branch_policy_json",
            "html_url",
            "created_at",
            "updated_at",
        ],
    },
    "privileged_surfaces.csv": {
        "primary_key": ["surface"],
        "columns": [
            "surface",
            "status",
            "http_status",
            "details_json",
        ],
    },
}

JSON_FILES = [
    "schema.json",
    "audit_metadata.json",
    "artifact_counts.json",
    "security_settings.json",
    "local_state_receipt.json",
]


class InventoryError(RuntimeError):
    """Raised when the declared inventory scope cannot be completed."""


class ApiClient(Protocol):
    def get(self, path: str, params: Mapping[str, object] | None = None) -> Any:
        """Return one decoded GitHub API response."""

    def paginate(
        self,
        path: str,
        *,
        item_key: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> list[Any]:
        """Return every item for one bounded endpoint."""


class GitHubApiError(InventoryError):
    """One GitHub API query failed."""

    def __init__(self, path: str, status: int, message: str) -> None:
        super().__init__(f"GitHub API {status} for {path}: {message}")
        self.path = path
        self.status = status
        self.message = message


class GitHubApiClient:
    """Small REST client with pagination and no mutable API operations."""

    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://api.github.com",
        timeout_seconds: int = 60,
    ) -> None:
        if not token:
            raise InventoryError("a GitHub token is required for remote inventory")
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _request(self, url: str) -> tuple[Any, Mapping[str, str]]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "aurora-gtbi-v7-inventory/1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout_seconds
            ) as response:
                return (
                    json.loads(response.read().decode("utf-8")),
                    dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(body).get("message", body)
            except json.JSONDecodeError:
                message = body
            raise GitHubApiError(url, exc.code, str(message)) from exc
        except urllib.error.URLError as exc:
            raise InventoryError(f"GitHub API connection failed for {url}: {exc}") from exc

    def _url(
        self, path: str, params: Mapping[str, object] | None = None
    ) -> str:
        if path.startswith("https://"):
            url = path
        else:
            url = f"{self._api_url}/{path.lstrip('/')}"
        if params:
            query = urllib.parse.urlencode(
                [(key, str(value)) for key, value in params.items()]
            )
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query}"
        return url

    def get(self, path: str, params: Mapping[str, object] | None = None) -> Any:
        payload, _ = self._request(self._url(path, params))
        return payload

    def paginate(
        self,
        path: str,
        *,
        item_key: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> list[Any]:
        merged_params: dict[str, object] = {"per_page": 100}
        if params:
            merged_params.update(params)
        url: str | None = self._url(path, merged_params)
        result: list[Any] = []
        while url:
            payload, headers = self._request(url)
            page = payload[item_key] if item_key else payload
            if not isinstance(page, list):
                raise InventoryError(f"expected list response while paginating {path}")
            result.extend(page)
            url = _next_link(headers.get("Link") or headers.get("link"))
        return result


@dataclass(frozen=True)
class QueryResult:
    name: str
    status: str
    http_status: int | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "http_status": self.http_status,
            "detail": self.detail,
        }


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', part)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


def _string(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _compact_json(value: object) -> str:
    return canonical_bytes(value).decode("utf-8")


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    definition = CSV_SCHEMAS[path.name]
    columns = definition["columns"]
    primary_key = definition["primary_key"]
    normalized = [
        {column: _string(row.get(column)) for column in columns} for row in rows
    ]
    normalized.sort(key=lambda row: tuple(row[key] for key in primary_key))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(normalized)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def inventory_schema() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory_scope": INVENTORY_SCOPE,
        "csv_files": CSV_SCHEMAS,
        "json_files": JSON_FILES,
        "audit_metadata_required_fields": [
            "audited_at_utc",
            "repository",
            "default_branch",
            "default_branch_sha",
            "gh_cli_version",
            "query_manifest_sha256",
            "inventory_scope",
            "complete",
        ],
    }


def _record_query(
    results: list[QueryResult],
    name: str,
    operation: Any,
    *,
    fallback: Any,
) -> Any:
    try:
        value = operation()
    except GitHubApiError as exc:
        results.append(
            QueryResult(name, "unavailable", exc.status, exc.message)
        )
        return fallback
    except Exception as exc:  # bounded diagnostic path
        results.append(QueryResult(name, "error", None, str(exc)))
        return fallback
    results.append(QueryResult(name, "complete"))
    return value


def _get_optional_not_found(
    client: ApiClient, path: str
) -> dict[str, Any] | None:
    try:
        return client.get(path)
    except GitHubApiError as exc:
        if exc.status == 404:
            return None
        raise


def _artifact_row(
    artifact: Mapping[str, Any],
    expected: Mapping[str, Any] | None,
    *,
    reason: str,
) -> dict[str, object]:
    workflow_run = artifact.get("workflow_run") or {}
    errors: list[str] = []
    if expected:
        checks = {
            "artifact_id": artifact.get("id"),
            "expected_run_id": workflow_run.get("id"),
            "expected_name": artifact.get("name"),
            "expected_size_in_bytes": artifact.get("size_in_bytes"),
            "expected_digest": artifact.get("digest"),
            "expected_expires_at": artifact.get("expires_at"),
        }
        for expected_key, actual in checks.items():
            if expected.get(expected_key) != actual:
                errors.append(
                    f"{expected_key}:expected={expected.get(expected_key)!r},actual={actual!r}"
                )
    return {
        "artifact_id": artifact.get("id"),
        "run_id": workflow_run.get("id"),
        "name": artifact.get("name"),
        "size_in_bytes": artifact.get("size_in_bytes"),
        "digest": artifact.get("digest"),
        "expired": artifact.get("expired"),
        "created_at": artifact.get("created_at"),
        "updated_at": artifact.get("updated_at"),
        "expires_at": artifact.get("expires_at"),
        "archive_download_url": artifact.get("archive_download_url"),
        "critical_reason": reason,
        "metadata_match": not errors,
        "metadata_errors": ";".join(errors),
    }


def _gh_cli_version() -> str:
    try:
        completed = subprocess.run(
            ["gh", "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unavailable"
    return completed.stdout.splitlines()[0].strip()


def generate_remote_inventory(
    *,
    client: ApiClient,
    query_manifest: Mapping[str, Any],
    query_manifest_path: Path,
    output_dir: Path,
    audited_at_utc: str | None = None,
    workflow_run_id: str | None = None,
) -> dict[str, Any]:
    """Generate the bounded remote inventory without mutating GitHub."""

    repository = str(query_manifest["repository"])
    owner, repo = repository.split("/", 1)
    base = f"repos/{repository}"
    query_results: list[QueryResult] = []

    repository_data = _record_query(
        query_results, "repository", lambda: client.get(base), fallback={}
    )
    default_branch = str(repository_data.get("default_branch") or "")
    default_ref = _record_query(
        query_results,
        "default_branch",
        lambda: client.get(f"{base}/git/ref/heads/{default_branch}"),
        fallback={},
    )
    default_branch_sha = str(
        ((default_ref.get("object") or {}).get("sha")) or ""
    )

    branches = _record_query(
        query_results,
        "branches",
        lambda: client.paginate(f"{base}/branches"),
        fallback=[],
    )
    branch_rows = [
        {
            "name": row.get("name"),
            "sha": (row.get("commit") or {}).get("sha"),
            "protected": row.get("protected"),
            "protection_url": row.get("protection_url"),
            "commit_url": (row.get("commit") or {}).get("url"),
        }
        for row in branches
    ]

    workflows = _record_query(
        query_results,
        "workflows",
        lambda: client.paginate(f"{base}/actions/workflows", item_key="workflows"),
        fallback=[],
    )
    workflow_rows = [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "path": row.get("path"),
            "state": row.get("state"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        for row in workflows
    ]

    active_runs_by_id: dict[int, Mapping[str, Any]] = {}
    active_run_complete = True
    for status in query_manifest["active_run_statuses"]:
        rows = _record_query(
            query_results,
            f"active_runs:{status}",
            lambda status=status: client.paginate(
                f"{base}/actions/runs",
                item_key="workflow_runs",
                params={"status": status},
            ),
            fallback=None,
        )
        if rows is None:
            active_run_complete = False
            continue
        for row in rows:
            active_runs_by_id[int(row["id"])] = row
    query_results.append(
        QueryResult(
            "active_runs",
            "complete" if active_run_complete else "unavailable",
            detail=f"unique_runs={len(active_runs_by_id)}",
        )
    )
    active_run_rows = [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "workflow_id": row.get("workflow_id"),
            "event": row.get("event"),
            "status": row.get("status"),
            "conclusion": row.get("conclusion"),
            "head_branch": row.get("head_branch"),
            "head_sha": row.get("head_sha"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "run_started_at": row.get("run_started_at"),
            "html_url": row.get("html_url"),
        }
        for row in active_runs_by_id.values()
    ]

    artifact_page = _record_query(
        query_results,
        "artifact_count",
        lambda: client.get(f"{base}/actions/artifacts", {"per_page": 1}),
        fallback={},
    )
    artifact_rows_by_id: dict[int, dict[str, object]] = {}
    for expected in query_manifest["critical_artifacts"]:
        artifact_id = int(expected["artifact_id"])
        artifact = _record_query(
            query_results,
            f"critical_artifact:{artifact_id}",
            lambda artifact_id=artifact_id: client.get(
                f"{base}/actions/artifacts/{artifact_id}"
            ),
            fallback=None,
        )
        if artifact is not None:
            artifact_rows_by_id[artifact_id] = _artifact_row(
                artifact, expected, reason=str(expected["reason"])
            )
    critical_query_statuses = [
        result.status
        for result in query_results
        if result.name.startswith("critical_artifact:")
    ]
    query_results.append(
        QueryResult(
            "critical_artifacts",
            (
                "complete"
                if critical_query_statuses
                and all(status == "complete" for status in critical_query_statuses)
                else "unavailable"
            ),
            detail=f"rows={len(artifact_rows_by_id)}",
        )
    )

    for run_id in query_manifest["known_runs"]:
        artifacts = _record_query(
            query_results,
            f"known_run_artifacts:{run_id}",
            lambda run_id=run_id: client.paginate(
                f"{base}/actions/runs/{run_id}/artifacts", item_key="artifacts"
            ),
            fallback=[],
        )
        for artifact in artifacts:
            artifact_id = int(artifact["id"])
            if artifact_id not in artifact_rows_by_id:
                artifact_rows_by_id[artifact_id] = _artifact_row(
                    artifact, None, reason=f"known_run:{run_id}"
                )

    releases = _record_query(
        query_results,
        "releases",
        lambda: client.paginate(f"{base}/releases"),
        fallback=[],
    )
    release_rows = [
        {
            "id": row.get("id"),
            "tag_name": row.get("tag_name"),
            "target_commitish": row.get("target_commitish"),
            "name": row.get("name"),
            "draft": row.get("draft"),
            "prerelease": row.get("prerelease"),
            "immutable": row.get("immutable"),
            "created_at": row.get("created_at"),
            "published_at": row.get("published_at"),
            "html_url": row.get("html_url"),
        }
        for row in releases
    ]

    package_rows: list[dict[str, object]] = []
    package_complete = True
    for package_type in query_manifest["package_types"]:
        packages = _record_query(
            query_results,
            f"packages:{package_type}",
            lambda package_type=package_type: client.paginate(
                f"orgs/{owner}/packages",
                params={"package_type": package_type},
            ),
            fallback=None,
        )
        if packages is None:
            package_complete = False
            continue
        for row in packages:
            package_rows.append(
                {
                    "id": row.get("id"),
                    "owner_scope": owner,
                    "package_type": row.get("package_type", package_type),
                    "name": row.get("name"),
                    "visibility": row.get("visibility"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                    "html_url": row.get("html_url"),
                }
            )
    query_results.append(
        QueryResult(
            "packages",
            "complete" if package_complete else "unavailable",
            detail=f"rows={len(package_rows)}",
        )
    )

    collaborators = _record_query(
        query_results,
        "collaborators",
        lambda: client.paginate(
            f"{base}/collaborators", params={"affiliation": "all"}
        ),
        fallback=[],
    )
    collaborator_rows = [
        {
            "login": row.get("login"),
            "id": row.get("id"),
            "type": row.get("type"),
            "site_admin": row.get("site_admin"),
            "role_name": row.get("role_name"),
            "permissions_json": _compact_json(row.get("permissions") or {}),
        }
        for row in collaborators
    ]

    environments_payload = _record_query(
        query_results,
        "environments",
        lambda: client.get(f"{base}/environments", {"per_page": 100}),
        fallback={},
    )
    environment_rows = [
        {
            "id": row.get("id"),
            "node_id": row.get("node_id"),
            "name": row.get("name"),
            "protection_rules_json": _compact_json(
                row.get("protection_rules") or []
            ),
            "deployment_branch_policy_json": _compact_json(
                row.get("deployment_branch_policy")
            ),
            "html_url": row.get("html_url"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        for row in environments_payload.get("environments", [])
    ]

    branch_protection = _record_query(
        query_results,
        "branch_protection",
        lambda: _get_optional_not_found(
            client, f"{base}/branches/{default_branch}/protection"
        ),
        fallback=None,
    )
    branch_protection_query_complete = any(
        result.name == "branch_protection" and result.status == "complete"
        for result in query_results
    )
    rulesets = _record_query(
        query_results,
        "rulesets",
        lambda: client.paginate(f"{base}/rulesets"),
        fallback=None,
    )
    privileged_rows = [
        {
            "surface": "branch_protection",
            "status": (
                "present"
                if branch_protection
                else (
                    "absent"
                    if branch_protection_query_complete
                    else "unavailable"
                )
            ),
            "http_status": "",
            "details_json": _compact_json(branch_protection or {}),
        },
        {
            "surface": "rulesets",
            "status": (
                "present"
                if rulesets
                else ("absent" if rulesets == [] else "unavailable")
            ),
            "http_status": "",
            "details_json": _compact_json(rulesets or []),
        },
        {
            "surface": "repository_visibility",
            "status": _string(repository_data.get("visibility")),
            "http_status": "",
            "details_json": _compact_json(
                {
                    "private": repository_data.get("private"),
                    "archived": repository_data.get("archived"),
                }
            ),
        },
    ]
    query_results.append(
        QueryResult(
            "security_settings",
            "complete" if repository_data else "unavailable",
        )
    )

    required = set(query_manifest["required_surfaces"])
    surface_status: dict[str, str] = {}
    for result in query_results:
        base_name = result.name.split(":", 1)[0]
        if base_name not in surface_status or result.status != "complete":
            surface_status[base_name] = result.status
    missing_required = sorted(
        name for name in required if surface_status.get(name) != "complete"
    )
    complete = not missing_required

    _write_json(output_dir / "schema.json", inventory_schema())
    _write_csv(output_dir / "branches.csv", branch_rows)
    _write_csv(
        output_dir / "worktrees.csv",
        [
            {
                "local_state": "unavailable_on_github_runner",
                "worktree_path_redacted": "",
                "head_sha": "",
                "branch": "",
                "prunable": "",
                "locked": "",
                "dirty": "",
                "changed_paths_count": "",
                "scan_error": "separate local read-only scan required",
            }
        ],
    )
    _write_csv(output_dir / "workflows.csv", workflow_rows)
    _write_csv(output_dir / "runs_active.csv", active_run_rows)
    _write_csv(
        output_dir / "artifacts_critical.csv", artifact_rows_by_id.values()
    )
    _write_csv(output_dir / "releases.csv", release_rows)
    _write_csv(output_dir / "packages.csv", package_rows)
    _write_csv(output_dir / "collaborators.csv", collaborator_rows)
    _write_csv(output_dir / "environments.csv", environment_rows)
    _write_csv(output_dir / "privileged_surfaces.csv", privileged_rows)
    _write_json(
        output_dir / "artifact_counts.json",
        {
            "schema_version": "gtbi_v7_artifact_counts_v1",
            "repository": repository,
            "registered_artifact_records": artifact_page.get("total_count"),
            "critical_artifact_rows": len(artifact_rows_by_id),
            "critical_artifacts_expired": sum(
                1
                for row in artifact_rows_by_id.values()
                if row["expired"] == "true" or row["expired"] is True
            ),
        },
    )
    _write_json(
        output_dir / "security_settings.json",
        {
            "schema_version": "gtbi_v7_security_settings_v1",
            "repository": repository,
            "visibility": repository_data.get("visibility"),
            "private": repository_data.get("private"),
            "archived": repository_data.get("archived"),
            "web_commit_signoff_required": repository_data.get(
                "web_commit_signoff_required"
            ),
            "allow_forking": repository_data.get("allow_forking"),
            "delete_branch_on_merge": repository_data.get(
                "delete_branch_on_merge"
            ),
            "security_and_analysis": repository_data.get(
                "security_and_analysis"
            )
            or {},
            "branch_protection": branch_protection,
            "rulesets": rulesets,
        },
    )
    _write_json(
        output_dir / "local_state_receipt.json",
        {
            "schema_version": "gtbi_v7_local_state_receipt_v1",
            "state": "unavailable",
            "observed_at_utc": audited_at_utc
            or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_known_inventory_digest": None,
            "last_known_inventory_at_utc": None,
            "affected_path_classes": ["local_git_worktrees"],
            "canonical_assets_depend_on_local_state": False,
            "campaign_authority_depends_on_local_state": False,
            "github_only_execution_depends_on_local_state": False,
        },
    )

    audited_at = audited_at_utc or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    # Laptop worktrees are a separate, non-blocking administrative snapshot.
    # Their later read-only scan must not rewrite the authoritative remote digest.
    data_file_names = sorted(
        name
        for name in [*CSV_SCHEMAS, *JSON_FILES]
        if name
        not in {
            "audit_metadata.json",
            "worktrees.csv",
            "local_state_receipt.json",
        }
    )
    file_digests = {
        name: raw_sha256(output_dir / name) for name in data_file_names
    }
    snapshot_payload = {
        "schema_version": "gtbi_v7_inventory_snapshot_v1",
        "repository": repository,
        "default_branch_sha": default_branch_sha,
        "inventory_scope": INVENTORY_SCOPE,
        "file_digests": file_digests,
    }
    snapshot_digest = raw_sha256(canonical_bytes(snapshot_payload))
    metadata = {
        "schema_version": "gtbi_v7_inventory_audit_metadata_v1",
        "audited_at_utc": audited_at,
        "repository": repository,
        "default_branch": default_branch,
        "default_branch_sha": default_branch_sha,
        "gh_cli_version": _gh_cli_version(),
        "query_manifest_sha256": raw_sha256(query_manifest_path),
        "inventory_scope": INVENTORY_SCOPE,
        "complete": complete,
        "missing_required_surfaces": missing_required,
        "query_results": [result.as_dict() for result in query_results],
        "workflow_run_id": workflow_run_id,
        "snapshot_digest": snapshot_digest,
        "file_digests": file_digests,
    }
    _write_json(output_dir / "audit_metadata.json", metadata)
    return metadata


def _redact_path(path: Path, home: Path) -> str:
    try:
        relative = path.resolve().relative_to(home.resolve())
    except ValueError:
        return f"<EXTERNAL_ROOT>/{path.name}"
    return f"{USER_HOME_TOKEN}/{relative.as_posix()}"


def _parse_worktree_porcelain(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in [*text.splitlines(), ""]:
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value if value else "true"
    return rows


def generate_local_inventory(
    *,
    repository_path: Path,
    output_dir: Path,
    home: Path | None = None,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Perform only the explicitly allowed local read-only worktree scan."""

    completed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repository_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    parsed = _parse_worktree_porcelain(completed.stdout)
    home_path = home or Path.home()
    rows: list[dict[str, object]] = []
    scan_errors: list[str] = []
    for item in parsed:
        raw_path = item.get("worktree", "")
        path = Path(raw_path)
        dirty: bool | str = ""
        changed_paths_count: int | str = ""
        error = ""
        if path.is_dir():
            try:
                status = subprocess.run(
                    ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                    cwd=path,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                changed = [line for line in status.stdout.splitlines() if line]
                dirty = bool(changed)
                changed_paths_count = len(changed)
            except subprocess.SubprocessError as exc:
                error = str(exc)
                scan_errors.append(f"{raw_path}:{exc}")
        else:
            error = "worktree_path_missing"
            scan_errors.append(f"{raw_path}:worktree_path_missing")
        rows.append(
            {
                "local_state": "inventoried",
                "worktree_path_redacted": _redact_path(path, home_path),
                "head_sha": item.get("HEAD", ""),
                "branch": item.get("branch", "").removeprefix("refs/heads/"),
                "prunable": "prunable" in item,
                "locked": "locked" in item,
                "dirty": dirty,
                "changed_paths_count": changed_paths_count,
                "scan_error": error,
            }
        )
    _write_csv(output_dir / "worktrees.csv", rows)
    observed_at = observed_at_utc or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    receipt = {
        "schema_version": "gtbi_v7_local_state_receipt_v1",
        "state": "inventoried",
        "observed_at_utc": observed_at,
        "worktree_count": len(rows),
        "dirty_worktree_count": sum(row["dirty"] is True for row in rows),
        "scan_error_count": len(scan_errors),
        "worktrees_csv_sha256": raw_sha256(output_dir / "worktrees.csv"),
        "home_prefix_redacted": True,
        "canonical_assets_depend_on_local_state": False,
        "campaign_authority_depends_on_local_state": False,
        "github_only_execution_depends_on_local_state": False,
    }
    _write_json(output_dir / "local_state_receipt.json", receipt)
    return receipt


def validate_inventory(
    output_dir: Path, *, require_complete: bool = True
) -> list[str]:
    """Validate generated files and return fail-closed errors."""

    errors: list[str] = []
    for name, definition in CSV_SCHEMAS.items():
        path = output_dir / name
        if not path.is_file():
            errors.append(f"missing {name}")
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != definition["columns"]:
                errors.append(f"{name} header mismatch")
                continue
            rows = list(reader)
        primary_key = definition["primary_key"]
        keys = [tuple(row[column] for column in primary_key) for row in rows]
        if keys != sorted(keys):
            errors.append(f"{name} rows are not sorted")
        if len(keys) != len(set(keys)):
            errors.append(f"{name} contains duplicate primary keys")
    for name in JSON_FILES:
        path = output_dir / name
        if not path.is_file():
            errors.append(f"missing {name}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"{name} invalid JSON: {exc}")
            continue
        if path.read_bytes() != canonical_bytes(payload) + b"\n":
            errors.append(f"{name} is not canonical JSON")
    metadata_path = output_dir / "audit_metadata.json"
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        required = inventory_schema()["audit_metadata_required_fields"]
        missing = [field for field in required if field not in metadata]
        if missing:
            errors.append(f"audit_metadata.json missing fields: {missing}")
        if metadata.get("inventory_scope") != INVENTORY_SCOPE:
            errors.append("audit_metadata.json has wrong inventory_scope")
        if require_complete and metadata.get("complete") is not True:
            errors.append(
                "remote inventory is incomplete: "
                + ",".join(metadata.get("missing_required_surfaces") or [])
            )
    return errors


def load_query_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise InventoryError("query manifest must be canonical JSON with final LF")
    return payload


def token_from_environment() -> str:
    return (
        os.environ.get("GTBI_INVENTORY_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or ""
    )
