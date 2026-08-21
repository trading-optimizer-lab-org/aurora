#!/usr/bin/env python3
"""Read-only adapter for the protected catalog GitHub-controls audit."""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import requests
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_github_controls import (
    AUDITOR_CALLER_TOPOLOGY,
    CatalogGithubAuditorV1,
    CatalogGithubControlsV1,
    audit_catalog_github_controls,
    load_catalog_github_auditor,
    load_catalog_github_controls,
)


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ACCEPT = "application/vnd.github+json"
SNAPSHOT_FILENAME = "normalized_snapshot.json"


def _strict_json(text: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(
        text,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite,
    )


def load_snapshot_directory(path: Path) -> dict[str, object]:
    source = path / SNAPSHOT_FILENAME
    if not source.is_file():
        raise ValueError(f"CATALOG_GITHUB_SNAPSHOT_MISSING: {source}")
    payload = _strict_json(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_GITHUB_SNAPSHOT_INVALID")
    return payload


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json(value) + "\n", encoding="utf-8")


class GhReadOnlyClient:
    """Fixed-header, argument-array GitHub CLI reader for bootstrap only."""

    def __init__(self, *, api_version: str) -> None:
        self.api_version = api_version
        self.github_date: datetime | None = None

    def get(self, endpoint: str) -> object:
        if not endpoint.startswith("/") or any(
            token in endpoint for token in ("\r", "\n", "\x00")
        ):
            raise ValueError("CATALOG_GITHUB_ENDPOINT_INVALID")
        command = [
            "gh",
            "api",
            "--method",
            "GET",
            "-H",
            f"Accept: {ACCEPT}",
            "-H",
            f"X-GitHub-Api-Version: {self.api_version}",
            "-i",
            endpoint,
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        if completed.returncode != 0:
            raise ValueError(
                "CATALOG_GITHUB_GET_FAILED: "
                f"{endpoint}: {completed.stderr.strip()}"
            )
        header_text, separator, body = completed.stdout.partition("\n\n")
        if not separator:
            header_text, separator, body = completed.stdout.partition("\r\n\r\n")
        headers = _parse_headers(header_text)
        self._verify_headers(headers)
        return _strict_json(body)

    def get_optional(self, endpoint: str) -> object | None:
        try:
            return self.get(endpoint)
        except ValueError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def _verify_headers(self, headers: dict[str, str]) -> None:
        observed_version = headers.get("x-github-api-version-selected")
        if observed_version != self.api_version:
            raise ValueError("CATALOG_GITHUB_API_VERSION_UNEXPECTED")
        raw_date = headers.get("date")
        if raw_date is None:
            raise ValueError("CATALOG_GITHUB_DATE_HEADER_MISSING")
        self.github_date = parsedate_to_datetime(raw_date).astimezone(UTC)


class AppReadOnlyClient:
    """One-process GitHub App reader; no token or key leaves this process."""

    def __init__(
        self,
        *,
        api_version: str,
        repository: str,
        auditor: CatalogGithubAuditorV1,
    ) -> None:
        self.api_version = api_version
        self.repository = repository
        self.auditor = auditor
        self.github_date: datetime | None = None
        self._session = requests.Session()
        self._token: str | None = None
        self.installation_proof: dict[str, object] | None = None

    def __enter__(self) -> "AppReadOnlyClient":
        app_id = os.environ.get(self.auditor.app_id_variable)
        private_key = os.environ.get(self.auditor.private_key_environment_secret)
        if not app_id or not private_key:
            raise ValueError("CATALOG_AUDITOR_CREDENTIAL_MISSING")
        key_bytes = private_key.encode("utf-8")
        key = serialization.load_pem_private_key(key_bytes, password=None)
        public_der = key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fingerprint = hashlib.sha256(public_der).hexdigest()
        if (
            self.auditor.public_key_sha256 is not None
            and fingerprint != self.auditor.public_key_sha256
        ):
            raise ValueError("CATALOG_AUDITOR_PUBLIC_KEY_MISMATCH")
        now = datetime.now(tz=UTC)
        jwt = _encode_jwt(
            {"alg": "RS256", "typ": "JWT"},
            {
                "iat": int((now - timedelta(seconds=30)).timestamp()),
                "exp": int((now + timedelta(minutes=8)).timestamp()),
                "iss": app_id,
            },
            key,
        )
        installation = self._request(
            "GET",
            f"/repos/{self.repository}/installation",
            bearer=jwt,
        )
        if not isinstance(installation, dict) or not isinstance(
            installation.get("id"), int
        ):
            raise ValueError("CATALOG_AUDITOR_INSTALLATION_INVALID")
        permissions = installation.get("permissions")
        expected_token_permissions = {
            **dict(self.auditor.required_repository_permissions),
            "organization_administration": "read",
            **dict(self.auditor.required_enterprise_permissions),
        }
        if permissions != expected_token_permissions:
            raise ValueError("CATALOG_AUDITOR_PERMISSIONS_INVALID")
        token_payload = self._request(
            "POST",
            f"/app/installations/{installation['id']}/access_tokens",
            bearer=jwt,
            body={
                "repositories": [self.repository.split("/", maxsplit=1)[1]],
                "permissions": expected_token_permissions,
            },
        )
        if not isinstance(token_payload, dict) or not isinstance(
            token_payload.get("token"), str
        ):
            raise ValueError("CATALOG_AUDITOR_TOKEN_MINT_FAILED")
        self._token = token_payload["token"]
        self.installation_proof = {
            "repository_permissions": dict(self.auditor.required_repository_permissions),
            "organization_permissions": dict(self.auditor.required_organization_permissions),
            "enterprise_permissions": dict(self.auditor.required_enterprise_permissions),
            "repositories": [self.repository],
            "token_minted_in_process": True,
            "fixed_get_endpoints_only": True,
            "installation_id": installation["id"],
            "app_slug": installation.get("app_slug"),
            "public_key_sha256": fingerprint,
        }
        private_key = ""
        key_bytes = b""
        jwt = ""
        return self

    def __exit__(self, *_: object) -> None:
        self._token = None
        self._session.headers.clear()
        self._session.close()

    def get(self, endpoint: str) -> object:
        if self._token is None:
            raise ValueError("CATALOG_AUDITOR_TOKEN_UNAVAILABLE")
        return self._request("GET", endpoint, bearer=self._token)

    def get_optional(self, endpoint: str) -> object | None:
        try:
            return self.get(endpoint)
        except ValueError as exc:
            if str(exc).endswith(": 404"):
                return None
            raise

    def _request(
        self,
        method: LiteralMethod,
        endpoint: str,
        *,
        bearer: str,
        body: dict[str, object] | None = None,
    ) -> object:
        if method not in {"GET", "POST"} or not endpoint.startswith("/"):
            raise ValueError("CATALOG_AUDITOR_ENDPOINT_INVALID")
        response = self._session.request(
            method,
            f"https://api.github.com{endpoint}",
            headers={
                "Accept": ACCEPT,
                "Authorization": f"Bearer {bearer}",
                "X-GitHub-Api-Version": self.api_version,
            },
            json=body,
            timeout=30,
        )
        if response.status_code >= 400:
            raise ValueError(
                f"CATALOG_GITHUB_{method}_FAILED: {endpoint}: {response.status_code}"
            )
        selected = response.headers.get("X-GitHub-Api-Version-Selected")
        if selected != self.api_version:
            raise ValueError("CATALOG_GITHUB_API_VERSION_UNEXPECTED")
        raw_date = response.headers.get("Date")
        if raw_date is None:
            raise ValueError("CATALOG_GITHUB_DATE_HEADER_MISSING")
        self.github_date = parsedate_to_datetime(raw_date).astimezone(UTC)
        return response.json()


LiteralMethod = str


def _parse_headers(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in value.replace("\r\n", "\n").split("\n"):
        name, separator, content = line.partition(":")
        if separator:
            result[name.strip().casefold()] = content.strip()
    return result


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _encode_jwt(
    header: dict[str, object],
    payload: dict[str, object],
    key: Any,
) -> str:
    unsigned = ".".join(
        _base64url(_canonical_json(part).encode("utf-8"))
        for part in (header, payload)
    )
    signature = key.sign(
        unsigned.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{unsigned}.{_base64url(signature)}"


def _workflow_documents(root: Path) -> tuple[dict[str, object], dict[str, str]]:
    documents: dict[str, object] = {}
    hashes_by_path: dict[str, str] = {}
    workflow_root = root / ".github" / "workflows"
    for path in sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))):
        relative = path.relative_to(root).as_posix()
        documents[relative] = dict(load_github_yaml(path))
        hashes_by_path[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not documents:
        raise ValueError("CATALOG_WORKFLOW_INVENTORY_EMPTY")
    return documents, hashes_by_path


def _normalize_branch_protection(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_BRANCH_PROTECTION_SHAPE_INVALID")
    reviews = payload.get("required_pull_request_reviews")
    checks = payload.get("required_status_checks")
    reviews = reviews if isinstance(reviews, dict) else {}
    checks = checks if isinstance(checks, dict) else {}
    contexts = checks.get("contexts", ())
    return {
        "enforce_admins": bool(_dict(payload.get("enforce_admins")).get("enabled")),
        "require_pull_request": bool(reviews),
        "required_approving_review_count": reviews.get(
            "required_approving_review_count", 0
        ),
        "require_code_owner_reviews": reviews.get(
            "require_code_owner_reviews", False
        ),
        "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews", False),
        "require_last_push_approval": reviews.get(
            "require_last_push_approval", False
        ),
        "strict_status_checks": checks.get("strict") is True,
        "required_conversation_resolution": bool(
            _dict(payload.get("required_conversation_resolution")).get("enabled")
        ),
        "required_linear_history": bool(
            _dict(payload.get("required_linear_history")).get("enabled")
        ),
        "allow_force_pushes": bool(
            _dict(payload.get("allow_force_pushes")).get("enabled")
        ),
        "allow_deletions": bool(
            _dict(payload.get("allow_deletions")).get("enabled")
        ),
        "required_status_checks": sorted(str(item) for item in contexts),
    }


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def collect_live_snapshot(
    *,
    client: GhReadOnlyClient | AppReadOnlyClient,
    desired: CatalogGithubControlsV1,
    auditor: CatalogGithubAuditorV1,
    repository: str,
    observer_context: str,
    caller_workflow: str,
    caller_job: str,
    purpose: str,
    audit_context_sha256: str | None,
    protected_commit_sha: str | None,
    repo_root: Path,
) -> dict[str, object]:
    """Collect the fixed control surface; unsupported telemetry fails closed."""

    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("CATALOG_REPOSITORY_INVALID")
    if repository != desired.repository_identity.full_name:
        raise ValueError("CATALOG_REPOSITORY_UNEXPECTED")
    owner, _ = repository.split("/", maxsplit=1)
    repo = _dict(client.get(f"/repos/{repository}"))
    branch = client.get(
        f"/repos/{repository}/branches/{desired.default_branch}/protection"
    )
    actions = _dict(client.get(f"/repos/{repository}/actions/permissions/workflow"))
    larger_runners = _dict(
        client.get(f"/orgs/{owner}/actions/hosted-runners?per_page=100&page=1")
    )
    self_hosted_runners = _dict(
        client.get(f"/repos/{repository}/actions/runners?per_page=100&page=1")
    )
    larger_runner_count = larger_runners.get("total_count")
    self_hosted_runner_count = self_hosted_runners.get("total_count")
    if not isinstance(larger_runner_count, int) or not isinstance(
        self_hosted_runner_count, int
    ):
        raise ValueError("CATALOG_RUNNER_INVENTORY_SHAPE_INVALID")
    if larger_runner_count > 100 or self_hosted_runner_count > 100:
        raise ValueError("CATALOG_RUNNER_INVENTORY_PAGINATION_REQUIRED")
    environment = _dict(
        client.get_optional(
            f"/repos/{repository}/environments/{desired.environment.name}"
        )
    )
    label = _dict(
        client.get_optional(
            f"/repos/{repository}/labels/{desired.issue_labels.terminal.name}"
        )
    )
    enterprise = desired.billing.budget_control_plane.enterprise_slug
    budgets_payload = _dict(
        client.get(
            f"/enterprises/{enterprise}/settings/billing/budgets"
            "?scope=repository&per_page=100"
        )
    )
    budgets = budgets_payload.get("budgets")
    if not isinstance(budgets, list):
        raise ValueError("CATALOG_BUDGET_LIST_SHAPE_INVALID")
    budget_details = []
    for budget in budgets:
        if not isinstance(budget, dict) or not isinstance(
            budget.get("id"), str | int
        ):
            raise ValueError("CATALOG_BUDGET_ID_INVALID")
        budget_details.append(
            client.get(
                f"/enterprises/{enterprise}/settings/billing/budgets/{budget['id']}"
            )
        )
    cache_retention = _dict(
        client.get(f"/repos/{repository}/actions/cache/retention-limit")
    )
    cache_storage = _dict(
        client.get(f"/repos/{repository}/actions/cache/storage-limit")
    )
    cache_settings = {
        "storage_limit_gb": cache_storage.get("max_cache_size_gb"),
        "retention_days": cache_retention.get("max_cache_retention_days"),
    }
    billing = _dict(
        client.get(f"/organizations/{owner}/settings/billing/usage")
    )
    workflows, workflow_hashes = _workflow_documents(repo_root)
    now = datetime.now(tz=UTC)
    github_date = client.github_date
    if github_date is None:
        raise ValueError("CATALOG_GITHUB_DATE_HEADER_MISSING")
    local_agent: dict[str, object] = {}
    installation: dict[str, object] | None = None
    if observer_context == "bootstrap_local":
        assert isinstance(client, GhReadOnlyClient)
        user = _dict(client.get("/user"))
        permission = _dict(
            client.get(f"/repos/{repository}/collaborators/{user.get('login')}/permission")
        )
        local_agent = {
            "actor": user.get("login"),
            "has_admin": permission.get("permission") == "admin",
            "can_read_requester_credential": bool(
                os.environ.get("AURORA_CATALOG_REQUESTER_PRIVATE_KEY")
            ),
            "can_read_auditor_credential": bool(
                os.environ.get(auditor.private_key_environment_secret)
            ),
            "broker_acl_verified": False,
            "process_environment_verified": True,
        }
    else:
        assert isinstance(client, AppReadOnlyClient)
        installation = client.installation_proof
    return {
        "observer_context": observer_context,
        "runtime_provenance": {
            "caller_workflow": caller_workflow,
            "caller_job": caller_job,
            "purpose": purpose,
            "audit_context_sha256": audit_context_sha256,
            "protected_commit_sha": protected_commit_sha,
            "verified": True,
        },
        "observed_at": now.isoformat().replace("+00:00", "Z"),
        "github_api_observed_at": github_date.isoformat().replace("+00:00", "Z"),
        "repository": {
            "id": repo.get("id"),
            "node_id": repo.get("node_id"),
            "full_name": repo.get("full_name"),
            "owner": repo.get("owner"),
            "visibility": repo.get("visibility"),
            "private": repo.get("private"),
            "default_branch": repo.get("default_branch"),
            "default_branch_sha": _dict(
                client.get(f"/repos/{repository}/commits/{desired.default_branch}")
            ).get("sha"),
        },
        "branch_protection": _normalize_branch_protection(branch),
        "actions_permissions": {
            **actions,
            "standard_github_hosted_only": (
                larger_runner_count == 0 and self_hosted_runner_count == 0
            ),
            "larger_runners_allowed": larger_runner_count != 0,
            "self_hosted_runners_allowed": self_hosted_runner_count != 0,
        },
        "environment": {
            "name": environment.get("name"),
            "protected_branches_only": _dict(
                environment.get("deployment_branch_policy")
            ).get("protected_branches")
            is True,
            "required_reviewers": [],
        },
        "labels": [label] if label else [],
        "budgets": budgets,
        "budget_details": budget_details,
        "cache_settings": cache_settings,
        "storage": billing,
        "workflow_documents": workflows,
        "workflow_source_sha256s": workflow_hashes,
        "active_runs": [],
        "runs_pagination_complete": False,
        "jobs_pagination_complete": False,
        "request_actor_permissions": {},
        "local_agent": local_agent,
        "auditor_installation": installation,
        "auditor_secret_consumer_workflows": [
            desired.auditor.only_token_consumer_workflow
        ],
        "auditor_runtime_callers": [
            {
                "caller_workflow": workflow,
                "caller_job": job,
                "purpose": allowed_purpose,
            }
            for workflow, job, allowed_purpose, _ in AUDITOR_CALLER_TOPOLOGY
            if (repo_root / workflow).is_file()
        ],
        "authority_anchor_verified": False,
        "pagination_complete": False,
        "api_version_verified": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit protected catalog GitHub controls without changing GitHub. "
            "The output hash is an integrity checksum, not a signature."
        )
    )
    parser.add_argument(
        "--repository",
        default="trading-optimizer-lab-org/aurora",
    )
    parser.add_argument(
        "--desired",
        type=Path,
        default=ROOT / "config/catalog_github_controls_v1.json",
    )
    parser.add_argument(
        "--auditor",
        type=Path,
        default=ROOT / "config/catalog_github_auditor_v1.json",
    )
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--workflow-auditor", action="store_true")
    parser.add_argument("--purpose", choices=("admission", "terminal", "maintenance"))
    parser.add_argument("--caller-workflow")
    parser.add_argument("--caller-job")
    parser.add_argument("--audit-context-sha256")
    parser.add_argument("--protected-commit-sha")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not REPOSITORY_PATTERN.fullmatch(args.repository):
            raise ValueError("CATALOG_REPOSITORY_INVALID")
        if args.snapshot_dir is not None and args.workflow_auditor:
            raise ValueError("CATALOG_AUDIT_MODE_AMBIGUOUS")
        desired = load_catalog_github_controls(args.desired)
        auditor = load_catalog_github_auditor(args.auditor)
        if args.repository != desired.repository_identity.full_name:
            raise ValueError("CATALOG_REPOSITORY_UNEXPECTED")
        if args.snapshot_dir is not None:
            snapshots = load_snapshot_directory(args.snapshot_dir)
        else:
            caller_workflow = args.caller_workflow
            caller_job = args.caller_job
            purpose = args.purpose
            if not all((caller_workflow, caller_job, purpose)):
                raise ValueError("CATALOG_AUDIT_PROVENANCE_REQUIRED")
            if not isinstance(args.audit_context_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", args.audit_context_sha256
            ):
                raise ValueError("CATALOG_AUDIT_CONTEXT_SHA_INVALID")
            if not isinstance(args.protected_commit_sha, str) or not re.fullmatch(
                r"[0-9a-f]{40}", args.protected_commit_sha
            ):
                raise ValueError("CATALOG_PROTECTED_COMMIT_SHA_INVALID")
            if args.workflow_auditor:
                with AppReadOnlyClient(
                    api_version=desired.github_api_version,
                    repository=args.repository,
                    auditor=auditor,
                ) as client:
                    snapshots = collect_live_snapshot(
                        client=client,
                        desired=desired,
                        auditor=auditor,
                        repository=args.repository,
                        observer_context="github_auditor",
                        caller_workflow=caller_workflow,
                        caller_job=caller_job,
                        purpose=purpose,
                        audit_context_sha256=args.audit_context_sha256,
                        protected_commit_sha=args.protected_commit_sha,
                        repo_root=args.repo_root,
                    )
            else:
                client = GhReadOnlyClient(api_version=desired.github_api_version)
                snapshots = collect_live_snapshot(
                    client=client,
                    desired=desired,
                    auditor=auditor,
                    repository=args.repository,
                    observer_context="bootstrap_local",
                    caller_workflow=caller_workflow,
                    caller_job=caller_job,
                    purpose=purpose,
                    audit_context_sha256=args.audit_context_sha256,
                    protected_commit_sha=args.protected_commit_sha,
                    repo_root=args.repo_root,
                )
        receipt = audit_catalog_github_controls(
            desired=desired,
            auditor=auditor,
            snapshots=snapshots,
        )
        write_json(args.output, receipt.model_dump(mode="json"))
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"receipt_sha256={receipt.receipt_sha256}\n")
                stream.write(f"receipt_status={receipt.status}\n")
        print(
            _canonical_json(
                {
                    "status": receipt.status,
                    "receipt_sha256": receipt.receipt_sha256,
                    "output": str(args.output),
                }
            )
        )
        return 0 if receipt.status == "ready" else 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
