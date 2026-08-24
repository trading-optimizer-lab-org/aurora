#!/usr/bin/env python3
"""Read-only adapter for the protected catalog GitHub-controls audit."""

from __future__ import annotations

import argparse
import base64
import math
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
from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityAnchorV1,
    CatalogAuthorityRecordV1,
    CatalogControllerActorsV1,
    extract_authority_comment_records,
    verify_authority_issue_anchor,
)
from aurora.infra.sp500_megarun.catalog_github_controls import (
    AUDITOR_CALLER_TOPOLOGY,
    CatalogGithubAuditorV1,
    CatalogGithubControlsV1,
    audit_catalog_github_controls,
    inventory_heavy_workflows,
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
        self._repository_token: str | None = None
        self._enterprise_token: str | None = None
        self._last_oauth_scopes: tuple[str, ...] = ()
        self.installation_proof: dict[str, object] | None = None

    def __enter__(self) -> "AppReadOnlyClient":
        app_id = os.environ.get(self.auditor.app_id_variable)
        private_key = os.environ.get(self.auditor.private_key_environment_secret)
        enterprise_token = os.environ.get(
            self.auditor.enterprise_billing_token_environment_secret
        )
        if not app_id or not private_key or not enterprise_token:
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
        expected_repository_permissions = {
            **dict(self.auditor.required_repository_permissions),
            "organization_administration": "read",
        }
        if permissions != expected_repository_permissions:
            raise ValueError("CATALOG_AUDITOR_PERMISSIONS_INVALID")
        token_payload = self._request(
            "POST",
            f"/app/installations/{installation['id']}/access_tokens",
            bearer=jwt,
            body={
                "repositories": [self.repository.split("/", maxsplit=1)[1]],
                "permissions": expected_repository_permissions,
            },
        )
        if not isinstance(token_payload, dict) or not isinstance(
            token_payload.get("token"), str
        ):
            raise ValueError("CATALOG_AUDITOR_TOKEN_MINT_FAILED")
        self._repository_token = token_payload["token"]
        self._enterprise_token = enterprise_token
        self._request("GET", "/user", bearer=enterprise_token)
        if self._last_oauth_scopes != tuple(
            sorted(self.auditor.required_enterprise_token_scopes)
        ):
            raise ValueError("CATALOG_AUDITOR_ENTERPRISE_TOKEN_SCOPES_INVALID")
        self.installation_proof = {
            "repository_permissions": dict(self.auditor.required_repository_permissions),
            "organization_permissions": dict(self.auditor.required_organization_permissions),
            "enterprise_permissions": dict(self.auditor.required_enterprise_permissions),
            "repositories": [self.repository],
            "token_minted_in_process": True,
            "fixed_get_endpoints_only": True,
            "repository_installation_id": installation["id"],
            "app_slug": installation.get("app_slug"),
            "public_key_sha256": fingerprint,
            "enterprise_credential_kind": "classic_pat",
            "enterprise_credential_scopes": list(self._last_oauth_scopes),
            "enterprise_write_blocked_by_client": True,
        }
        private_key = ""
        key_bytes = b""
        jwt = ""
        return self

    def __exit__(self, *_: object) -> None:
        self._repository_token = None
        self._enterprise_token = None
        self._last_oauth_scopes = ()
        self._session.headers.clear()
        self._session.close()

    def get(self, endpoint: str) -> object:
        return self._request("GET", endpoint, bearer=self._token_for_endpoint(endpoint))

    def _token_for_endpoint(self, endpoint: str) -> str:
        enterprise_prefix = f"/enterprises/{self.auditor.enterprise}/settings/billing/"
        if endpoint.startswith(enterprise_prefix):
            if self._enterprise_token is None:
                raise ValueError("CATALOG_AUDITOR_ENTERPRISE_TOKEN_UNAVAILABLE")
            return self._enterprise_token
        if endpoint.startswith("/enterprises/"):
            raise ValueError("CATALOG_AUDITOR_ENDPOINT_INVALID")
        if self._repository_token is None:
            raise ValueError("CATALOG_AUDITOR_TOKEN_UNAVAILABLE")
        return self._repository_token

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
        raw_scopes = response.headers.get("X-OAuth-Scopes")
        self._last_oauth_scopes = tuple(
            sorted(scope.strip() for scope in raw_scopes.split(",") if scope.strip())
        ) if raw_scopes is not None else ()
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


def _page_endpoint(endpoint: str, page: int) -> str:
    if page < 1 or not endpoint.startswith("/") or "page=" in endpoint:
        raise ValueError("CATALOG_GITHUB_PAGINATION_ENDPOINT_INVALID")
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}per_page=100&page={page}"


def _row_identity(row: dict[str, object]) -> object:
    for key in ("id", "run_id", "database_id", "node_id", "full_name"):
        value = row.get(key)
        if isinstance(value, str | int) and not isinstance(value, bool):
            return (key, value)
    raise ValueError("CATALOG_GITHUB_PAGINATION_ID_MISSING")


def _paginate_object_rows(
    client: GhReadOnlyClient | AppReadOnlyClient | object,
    endpoint: str,
    *,
    root: str,
    max_pages: int = 100,
) -> tuple[tuple[dict[str, object], ...], bool]:
    """Read one documented ``total_count`` collection within a fixed bound."""

    if max_pages < 1 or not root:
        raise ValueError("CATALOG_GITHUB_PAGINATION_BOUND_INVALID")
    rows: list[dict[str, object]] = []
    identities: set[object] = set()
    expected_total: int | None = None
    for page in range(1, max_pages + 1):
        payload = getattr(client, "get")(_page_endpoint(endpoint, page))
        if not isinstance(payload, dict):
            raise ValueError("CATALOG_GITHUB_PAGINATION_SHAPE_INVALID")
        total = payload.get("total_count")
        page_rows = payload.get(root)
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or not isinstance(page_rows, list)
            or len(page_rows) > 100
        ):
            raise ValueError("CATALOG_GITHUB_PAGINATION_SHAPE_INVALID")
        if expected_total is None:
            expected_total = total
            if expected_total > max_pages * 100:
                for raw in page_rows:
                    if not isinstance(raw, dict):
                        raise ValueError("CATALOG_GITHUB_PAGINATION_SHAPE_INVALID")
                    identity = _row_identity(raw)
                    if identity in identities:
                        raise ValueError("CATALOG_GITHUB_PAGINATION_DUPLICATE")
                    identities.add(identity)
                    rows.append(raw)
                return tuple(rows), False
        elif total != expected_total:
            raise ValueError("CATALOG_GITHUB_PAGINATION_UNSTABLE")
        for raw in page_rows:
            if not isinstance(raw, dict):
                raise ValueError("CATALOG_GITHUB_PAGINATION_SHAPE_INVALID")
            identity = _row_identity(raw)
            if identity in identities:
                raise ValueError("CATALOG_GITHUB_PAGINATION_DUPLICATE")
            identities.add(identity)
            rows.append(raw)
        if len(rows) == expected_total:
            return tuple(rows), True
        if not page_rows or len(page_rows) < 100:
            raise ValueError("CATALOG_GITHUB_PAGINATION_COUNT_MISMATCH")
    return tuple(rows), False


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _load_closed_json(path: Path) -> dict[str, object]:
    payload = _strict_json(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_PROTECTED_CONFIG_INVALID")
    return payload


def _authority_anchor_status(
    *,
    client: GhReadOnlyClient | AppReadOnlyClient,
    repository: str,
    repository_snapshot: dict[str, object],
    repo_root: Path,
) -> tuple[bool, tuple[CatalogAuthorityRecordV1, ...], bool]:
    try:
        anchor = CatalogAuthorityAnchorV1.model_validate(
            _load_closed_json(repo_root / "config/catalog_authority_anchor_v1.json")
        )
        if not anchor.production_enabled or anchor.issue_number is None:
            raise ValueError
        variable = _dict(
            client.get(
                f"/repos/{repository}/actions/variables/"
                "CATALOG_AUTHORITY_ISSUE_NUMBER"
            )
        )
        issue = _dict(client.get(f"/repos/{repository}/issues/{anchor.issue_number}"))
        verify_authority_issue_anchor(
            anchor=anchor,
            repository_variable_number=variable.get("value"),
            repository_snapshot=repository_snapshot,
            issue_snapshot=issue,
        )
        comments, complete = _paginate_list_rows(
            client,
            f"/repos/{repository}/issues/{anchor.issue_number}/comments",
            max_pages=100,
        )
        if not complete:
            return True, (), False
        records = extract_authority_comment_records(
            comments,
            expected_author="github-actions[bot]",
        )
        return True, records, True
    except Exception:
        return False, (), False


def _request_actor_permissions(
    *,
    client: GhReadOnlyClient | AppReadOnlyClient,
    repo_root: Path,
) -> dict[str, object]:
    """Use only a protected exact bootstrap permission receipt; never infer it."""

    try:
        actors = CatalogControllerActorsV1.model_validate(
            _load_closed_json(repo_root / "config/catalog_controller_actors_v1.json")
        )
        proof_path = repo_root / "config/catalog_requester_app_permissions_v1.json"
        if (
            not actors.production_enabled
            or len(actors.request_actors) != 1
            or not proof_path.is_file()
        ):
            return {}
        actor = actors.request_actors[0]
        proof = _load_closed_json(proof_path)
        user = _dict(client.get(f"/users/{actor}"))
        expected = {
            "login": actor,
            "kind": "GitHubApp",
            "repository_administration": "none",
            "repository_actions": "none",
            "repository_contents": "none",
            "repository_issues": "write",
        }
        if (
            proof.get("schema_version") != "1"
            or proof.get("verified") is not True
            or proof.get("permissions") != expected
            or user.get("login") != actor
            or user.get("type") != "Bot"
        ):
            return {}
        return expected
    except Exception:
        return {}


def _job_name_is_heavy(value: object) -> bool:
    name = str(value or "").casefold()
    return any(
        marker in name
        for marker in (
            "engine_optimized_catalog",
            "catalog-optimized",
            "component",
            "recipe",
            "recovery_wave",
            "reconcile_wave",
            "reduce",
        )
    )


def _collect_active_run_inventory(
    *,
    client: GhReadOnlyClient | AppReadOnlyClient,
    repository: str,
    heavy_paths: set[str],
    authority_records: tuple[CatalogAuthorityRecordV1, ...],
) -> tuple[tuple[dict[str, object], ...], bool, bool]:
    runs: list[dict[str, object]] = []
    seen: set[int] = set()
    runs_complete = True
    jobs_complete = True
    latest_by_authority: dict[object, CatalogAuthorityRecordV1] = {}
    for record in authority_records:
        latest_by_authority[record.authority_id] = record
    latest_records = tuple(latest_by_authority.values())
    for status in ("queued", "in_progress"):
        rows, complete = _paginate_object_rows(
            client,
            f"/repos/{repository}/actions/runs?status={status}",
            root="workflow_runs",
            max_pages=10,
        )
        runs_complete = runs_complete and complete
        for run in rows:
            run_id = run.get("id")
            if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id in seen:
                raise ValueError("CATALOG_ACTIVE_RUN_INVENTORY_INVALID")
            seen.add(run_id)
            jobs, complete_jobs = _paginate_object_rows(
                client,
                f"/repos/{repository}/actions/runs/{run_id}/jobs",
                root="jobs",
                max_pages=20,
            )
            jobs_complete = jobs_complete and complete_jobs
            active_heavy_jobs = tuple(
                job
                for job in jobs
                if job.get("status") in {"queued", "in_progress", "waiting", "pending"}
                and _job_name_is_heavy(job.get("name"))
            )
            path = str(run.get("path") or "").split("@", maxsplit=1)[0]
            if not active_heavy_jobs and path not in heavy_paths:
                continue
            if not active_heavy_jobs and path.endswith("catalog-run-controller.yml"):
                continue
            matching = [record for record in latest_records if record.run_id == run_id]
            record = matching[0] if len(matching) == 1 else None
            writer_matches = False
            if record is not None:
                writer_matches = any(
                    job.get("id") == record.writer_job_database_id
                    and (
                        job.get("name") == record.writer_job_id
                        or str(job.get("name", "")).endswith(
                            f" / {record.writer_job_id}"
                        )
                    )
                    for job in jobs
                )
            nonterminal = record is not None and record.state in {
                AuthorityState.RESERVED,
                AuthorityState.RUNNING,
                AuthorityState.RECOVERING,
                AuthorityState.WAITING_RETRY,
            }
            runs.append(
                {
                    "run_id": run_id,
                    "workflow_path": path,
                    "status": run.get("status"),
                    "authority_bound": nonterminal,
                    "protected_commit_matches": (
                        record is not None and record.protected_commit_sha == run.get("head_sha")
                    ),
                    "sealed_identifiers_match": (
                        nonterminal
                        and record is not None
                        and bool(record.science_sha256)
                        and bool(record.execution_plan_sha256)
                        and bool(record.execution_protocol_sha256)
                    ),
                    "writer_provenance_verified": writer_matches,
                    "current_engine_owner": nonterminal,
                    "active_heavy_job_database_ids": sorted(
                        int(job["id"])
                        for job in active_heavy_jobs
                        if isinstance(job.get("id"), int)
                        and not isinstance(job.get("id"), bool)
                    ),
                }
            )
    return tuple(sorted(runs, key=lambda row: int(row["run_id"]))), runs_complete, jobs_complete


def _billing_paid_usage(
    payload: dict[str, object],
    *,
    repository_name: str,
) -> tuple[int, int, datetime | None]:
    items = payload.get("usageItems")
    if not isinstance(items, list):
        return 0, 0, None
    paid_minutes = 0.0
    paid_amount = 0.0
    latest: datetime | None = None
    for raw in items:
        if not isinstance(raw, dict):
            return 0, 0, None
        target_repository = (
            str(raw.get("repositoryName", "")).casefold()
            == repository_name.casefold()
        )
        target_product = str(raw.get("product", "")).casefold() == "actions"
        observed = _parse_utc(raw.get("date"))
        if (
            target_repository
            and target_product
            and observed is not None
            and (latest is None or observed > latest)
        ):
            latest = observed
        if (
            target_repository
            and target_product
            and str(raw.get("unitType", "")).casefold() == "minutes"
            and isinstance(raw.get("netAmount"), int | float)
            and not isinstance(raw.get("netAmount"), bool)
            and math.isfinite(float(raw["netAmount"]))
            and float(raw["netAmount"]) > 0
        ):
            paid_amount += float(raw["netAmount"])
            if (
                isinstance(raw.get("quantity"), int | float)
                and not isinstance(raw.get("quantity"), bool)
                and math.isfinite(float(raw["quantity"]))
                and float(raw["quantity"]) >= 0
            ):
                paid_minutes += float(raw["quantity"])
    return math.ceil(paid_minutes), math.ceil(paid_amount * 100), latest


def _billing_usage_endpoint(owner: str, observed_at: datetime) -> str:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("CATALOG_BILLING_OBSERVED_AT_INVALID")
    observed_utc = observed_at.astimezone(UTC)
    return (
        f"/organizations/{owner}/settings/billing/usage"
        f"?year={observed_utc.year}&month={observed_utc.month}"
    )


def _billing_actions_storage_evidence(
    payload: dict[str, object],
    *,
    repository_name: str,
    observed_at: datetime,
    included_shared_storage_bytes: int,
) -> dict[str, object]:
    """Expose period-average billing evidence without calling it current use."""

    empty: dict[str, object] = {
        "billing_storage_period_evidence_complete": False,
        "billing_storage_period_started_at": None,
        "billing_storage_quantity_gigabyte_hours": None,
        "billing_storage_period_elapsed_seconds": None,
        "billing_storage_period_average_bytes": None,
        "billing_storage_period_average_exceeds_allowance": None,
    }
    if (
        observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or isinstance(included_shared_storage_bytes, bool)
        or not isinstance(included_shared_storage_bytes, int)
        or included_shared_storage_bytes < 0
    ):
        return empty
    items = payload.get("usageItems")
    if not isinstance(items, list):
        return empty
    rows: list[tuple[datetime, float]] = []
    for raw in items:
        if not isinstance(raw, dict):
            return empty
        if not (
            str(raw.get("repositoryName", "")).casefold()
            == repository_name.casefold()
            and str(raw.get("product", "")).casefold() == "actions"
            and str(raw.get("sku", "")).casefold() == "actions storage"
            and str(raw.get("unitType", "")).casefold() == "gigabytehours"
        ):
            continue
        period_start = _parse_utc(raw.get("date"))
        quantity = raw.get("quantity")
        if (
            period_start is None
            or isinstance(quantity, bool)
            or not isinstance(quantity, int | float)
            or not math.isfinite(float(quantity))
            or float(quantity) < 0
        ):
            return empty
        rows.append((period_start, float(quantity)))
    if not rows:
        return empty
    latest_start = max(start for start, _ in rows)
    quantity = sum(value for start, value in rows if start == latest_start)
    observed_utc = observed_at.astimezone(UTC)
    elapsed_seconds = int((observed_utc - latest_start).total_seconds())
    current_daily_period = (
        latest_start.date() == observed_utc.date()
        and 0 < elapsed_seconds <= 24 * 60 * 60
    )
    if not current_daily_period:
        return {
            **empty,
            "billing_storage_period_started_at": latest_start.isoformat().replace(
                "+00:00", "Z"
            ),
            "billing_storage_quantity_gigabyte_hours": quantity,
        }
    average_bytes = math.ceil(quantity * 3_600 * 1_000_000_000 / elapsed_seconds)
    return {
        "billing_storage_period_evidence_complete": True,
        "billing_storage_period_started_at": latest_start.isoformat().replace(
            "+00:00", "Z"
        ),
        "billing_storage_quantity_gigabyte_hours": quantity,
        "billing_storage_period_elapsed_seconds": elapsed_seconds,
        "billing_storage_period_average_bytes": average_bytes,
        "billing_storage_period_average_exceeds_allowance": (
            average_bytes > included_shared_storage_bytes
        ),
    }


def _active_artifact_inventory(
    artifacts: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], ...], bool]:
    """Return only live artifacts and reject telemetry with an unknown shape."""

    active: list[dict[str, object]] = []
    for row in artifacts:
        expired = row.get("expired")
        size = row.get("size_in_bytes")
        if (
            not isinstance(expired, bool)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            return (), False
        if not expired:
            active.append(row)
    return tuple(active), True


def _reported_shared_storage_evidence(
    *,
    explicit_shared: int | None,
    billing_fresh: bool,
    billing_period_complete: bool,
    inventory_complete: bool,
    artifact_inventory_bytes: int,
    package_inventory_bytes: int,
) -> dict[str, object]:
    """Select a current-use value without mislabelling period-average billing."""

    if explicit_shared is not None and billing_fresh:
        return {
            "reported_shared_use_bytes": explicit_shared,
            "billing_snapshot_complete": True,
            "reported_shared_use_source": "explicit_billing_current_use",
        }
    if billing_fresh and billing_period_complete and inventory_complete:
        return {
            "reported_shared_use_bytes": (
                artifact_inventory_bytes + package_inventory_bytes
            ),
            "billing_snapshot_complete": True,
            "reported_shared_use_source": "complete_active_inventory",
        }
    return {
        "reported_shared_use_bytes": 0,
        "billing_snapshot_complete": False,
        "reported_shared_use_source": "unavailable",
    }


def _campaign_storage_projection(
    *,
    qualification: dict[str, object],
    caller_workflow: str,
    caller_job: str,
    purpose: str,
) -> tuple[int, int, bool]:
    """Require campaign projections for production, but not zero-work checks."""

    projected_artifact = qualification.get("projected_artifact_storage_bytes")
    projected_cache = qualification.get("projected_cache_storage_bytes")
    if (
        qualification.get("status") == "ready"
        and isinstance(projected_artifact, int)
        and not isinstance(projected_artifact, bool)
        and projected_artifact >= 0
        and isinstance(projected_cache, int)
        and not isinstance(projected_cache, bool)
        and projected_cache >= 0
    ):
        return projected_artifact, projected_cache, True
    zero_work_callers = {
        (
            ".github/workflows/catalog-live-controls-qualification.yml",
            "qualify_live_admission_controls",
            "admission",
        ),
        (
            ".github/workflows/catalog-live-controls-qualification.yml",
            "qualify_live_terminal_controls",
            "terminal",
        ),
        (
            ".github/workflows/catalog-artifact-keeper.yml",
            "live_controls_audit_before_maintenance",
            "maintenance",
        ),
    }
    if (caller_workflow, caller_job, purpose) in zero_work_callers:
        return 0, 0, True
    return 0, 0, False


def _collect_storage_snapshot(
    *,
    client: GhReadOnlyClient | AppReadOnlyClient,
    desired: CatalogGithubControlsV1,
    repository: str,
    owner: str,
    billing: dict[str, object],
    github_date: datetime,
    repo_root: Path,
    writer_inventory_complete: bool,
    caller_workflow: str,
    caller_job: str,
    purpose: str,
) -> tuple[dict[str, object], bool]:
    artifacts, artifacts_complete = _paginate_object_rows(
        client,
        f"/repos/{repository}/actions/artifacts",
        root="artifacts",
        max_pages=2_000,
    )
    caches, caches_complete = _paginate_object_rows(
        client,
        f"/repos/{repository}/actions/caches",
        root="actions_caches",
        max_pages=10,
    )
    package_rows: list[dict[str, object]] = []
    packages_complete = True
    for package_type in ("container", "maven", "npm", "nuget", "rubygems"):
        rows, complete = _paginate_list_rows(
            client,
            f"/orgs/{owner}/packages?package_type={package_type}",
            max_pages=10,
        )
        package_rows.extend(rows)
        packages_complete = packages_complete and complete
    active_artifacts, artifact_sizes_valid = _active_artifact_inventory(artifacts)
    package_sizes_valid = not package_rows or all(
        isinstance(row.get("size_in_bytes"), int)
        and not isinstance(row.get("size_in_bytes"), bool)
        and int(row["size_in_bytes"]) >= 0
        for row in package_rows
    )
    cache_sizes_valid = all(
        isinstance(row.get("size_in_bytes"), int)
        and not isinstance(row.get("size_in_bytes"), bool)
        and int(row["size_in_bytes"]) >= 0
        for row in caches
    )
    org_cache = _dict(client.get(f"/orgs/{owner}/actions/cache/usage"))
    reported_cache = org_cache.get("total_active_caches_size_in_bytes")
    reported_cache_valid = (
        isinstance(reported_cache, int)
        and not isinstance(reported_cache, bool)
        and reported_cache >= 0
    )
    repository_name = repository.split("/", maxsplit=1)[1]
    paid_minutes, paid_cost, latest_billing = _billing_paid_usage(
        billing,
        repository_name=repository_name,
    )
    billing_storage_evidence = _billing_actions_storage_evidence(
        billing,
        repository_name=repository_name,
        observed_at=github_date,
        included_shared_storage_bytes=desired.billing.included_shared_storage_bytes,
    )
    explicit_shared = next(
        (
            billing.get(key)
            for key in (
                "shared_storage_bytes",
                "total_storage_bytes",
                "actions_storage_bytes",
            )
            if isinstance(billing.get(key), int)
            and not isinstance(billing.get(key), bool)
            and int(billing[key]) >= 0
        ),
        None,
    )
    billing_fresh = latest_billing is not None and (
        latest_billing.date() == github_date.date()
        or (
            github_date >= latest_billing
            and github_date - latest_billing
            <= timedelta(
                hours=desired.billing.artifact_and_packages_reporting_lag_hours
            )
        )
    )
    qualification = _load_closed_json(
        repo_root / "config/catalog_operational_qualification_v1.json"
    )
    projected_artifact, projected_cache, projection_valid = (
        _campaign_storage_projection(
            qualification=qualification,
            caller_workflow=caller_workflow,
            caller_job=caller_job,
            purpose=purpose,
        )
    )
    artifact_cutoff = github_date - timedelta(
        hours=desired.billing.artifact_and_packages_reporting_lag_hours
    )
    cache_cutoff = github_date - timedelta(
        minutes=desired.billing.cache_reporting_lag_minutes
    )
    unreflected = sum(
        int(row["size_in_bytes"])
        for row in active_artifacts
        if artifact_sizes_valid
        and (created := _parse_utc(row.get("created_at"))) is not None
        and created >= artifact_cutoff
    )
    pending_cache = sum(
        int(row["size_in_bytes"])
        for row in caches
        if cache_sizes_valid
        and (created := _parse_utc(row.get("created_at"))) is not None
        and created >= cache_cutoff
    )
    artifact_inventory_bytes = (
        sum(int(row["size_in_bytes"]) for row in active_artifacts)
        if artifact_sizes_valid
        else 0
    )
    package_inventory_bytes = (
        sum(int(row["size_in_bytes"]) for row in package_rows)
        if package_sizes_valid
        else 0
    )
    shared_evidence = _reported_shared_storage_evidence(
        explicit_shared=int(explicit_shared) if explicit_shared is not None else None,
        billing_fresh=billing_fresh,
        billing_period_complete=(
            billing_storage_evidence["billing_storage_period_evidence_complete"]
            is True
        ),
        inventory_complete=(
            artifacts_complete
            and packages_complete
            and artifact_sizes_valid
            and package_sizes_valid
        ),
        artifact_inventory_bytes=artifact_inventory_bytes,
        package_inventory_bytes=package_inventory_bytes,
    )
    billing_complete = shared_evidence["billing_snapshot_complete"] is True
    if shared_evidence["reported_shared_use_source"] == "complete_active_inventory":
        unreflected = 0
    telemetry_complete = (
        artifacts_complete
        and packages_complete
        and caches_complete
        and artifact_sizes_valid
        and package_sizes_valid
        and cache_sizes_valid
        and reported_cache_valid
        and billing_complete
        and projection_valid
        and writer_inventory_complete
    )
    storage = {
        "telemetry_complete": telemetry_complete,
        "artifacts_pagination_complete": artifacts_complete,
        "packages_pagination_complete": packages_complete,
        "caches_pagination_complete": caches_complete,
        "writer_inventory_complete": writer_inventory_complete,
        "shared_allowance_bytes": desired.billing.included_shared_storage_bytes,
        "reported_shared_use_bytes": shared_evidence["reported_shared_use_bytes"],
        "reported_shared_use_source": shared_evidence[
            "reported_shared_use_source"
        ],
        "artifact_inventory_bytes": artifact_inventory_bytes,
        "package_inventory_bytes": package_inventory_bytes,
        "unreflected_upload_bytes": unreflected,
        "reported_cache_use_bytes": int(reported_cache or 0),
        "cache_inventory_bytes": sum(int(row["size_in_bytes"]) for row in caches)
        if cache_sizes_valid
        else 0,
        "pending_cache_bytes": pending_cache,
        "projected_campaign_artifact_bytes": int(projected_artifact or 0),
        "projected_campaign_cache_bytes": int(projected_cache or 0),
        "paid_runner_minutes": paid_minutes,
        "estimated_paid_actions_cost": paid_cost,
        "billing_snapshot_complete": billing_complete,
        "billing_latest_usage_at": (
            latest_billing.isoformat().replace("+00:00", "Z")
            if latest_billing is not None
            else None
        ),
        **billing_storage_evidence,
    }
    return storage, telemetry_complete


def _paginate_list_rows(
    client: GhReadOnlyClient | AppReadOnlyClient | object,
    endpoint: str,
    *,
    max_pages: int = 100,
) -> tuple[tuple[dict[str, object], ...], bool]:
    """Read one documented plain-array collection within a fixed bound."""

    if max_pages < 1:
        raise ValueError("CATALOG_GITHUB_PAGINATION_BOUND_INVALID")
    rows: list[dict[str, object]] = []
    identities: set[object] = set()
    for page in range(1, max_pages + 1):
        payload = getattr(client, "get")(_page_endpoint(endpoint, page))
        if not isinstance(payload, list) or len(payload) > 100:
            raise ValueError("CATALOG_GITHUB_PAGINATION_SHAPE_INVALID")
        for raw in payload:
            if not isinstance(raw, dict):
                raise ValueError("CATALOG_GITHUB_PAGINATION_SHAPE_INVALID")
            identity = _row_identity(raw)
            if identity in identities:
                raise ValueError("CATALOG_GITHUB_PAGINATION_DUPLICATE")
            identities.add(identity)
            rows.append(raw)
        if len(payload) < 100:
            return tuple(rows), True
    return tuple(rows), False


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
    larger_runners, larger_runners_complete = _paginate_object_rows(
        client,
        f"/orgs/{owner}/actions/hosted-runners",
        root="runners",
        max_pages=10,
    )
    self_hosted_runners, self_hosted_runners_complete = _paginate_object_rows(
        client,
        f"/repos/{repository}/actions/runners",
        root="runners",
        max_pages=10,
    )
    larger_runner_count = len(larger_runners)
    self_hosted_runner_count = len(self_hosted_runners)
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
    organization = desired.billing.budget_control_plane.organization
    enterprise = desired.billing.budget_control_plane.enterprise
    budgets, budgets_complete = _paginate_object_rows(
        client,
        f"/enterprises/{enterprise}/settings/billing/budgets?scope=repository",
        root="budgets",
        max_pages=10,
    )
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
    billing_observed_at = client.github_date
    if billing_observed_at is None:
        raise ValueError("CATALOG_GITHUB_DATE_HEADER_MISSING")
    billing = _dict(
        client.get(_billing_usage_endpoint(owner, billing_observed_at))
    )
    workflows, workflow_hashes = _workflow_documents(repo_root)
    heavy_paths = {
        str(row["path"])
        for row in inventory_heavy_workflows(workflows)  # type: ignore[arg-type]
        if row.get("heavy") is True
    }
    authority_anchor_verified, authority_records, authority_comments_complete = (
        _authority_anchor_status(
            client=client,
            repository=repository,
            repository_snapshot=repo,
            repo_root=repo_root,
        )
    )
    active_runs, runs_complete, jobs_complete = _collect_active_run_inventory(
        client=client,
        repository=repository,
        heavy_paths=heavy_paths,
        authority_records=authority_records,
    )
    request_actor = _request_actor_permissions(client=client, repo_root=repo_root)
    now = datetime.now(tz=UTC)
    github_date = client.github_date
    if github_date is None:
        raise ValueError("CATALOG_GITHUB_DATE_HEADER_MISSING")
    storage, storage_complete = _collect_storage_snapshot(
        client=client,
        desired=desired,
        repository=repository,
        owner=owner,
        billing=billing,
        github_date=github_date,
        repo_root=repo_root,
        writer_inventory_complete=runs_complete and jobs_complete,
        caller_workflow=caller_workflow,
        caller_job=caller_job,
        purpose=purpose,
    )
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
            "required_reviewers": sorted(
                str(reviewer.get("login"))
                for rule in environment.get("protection_rules", ())
                if isinstance(rule, dict)
                and isinstance(rule.get("reviewers"), list)
                for reviewer in rule["reviewers"]
                if isinstance(reviewer, dict) and reviewer.get("login")
            ),
        },
        "labels": [label] if label else [],
        "budgets": list(budgets),
        "budget_details": budget_details,
        "cache_settings": cache_settings,
        "storage": storage,
        "workflow_documents": workflows,
        "workflow_source_sha256s": workflow_hashes,
        "active_runs": list(active_runs),
        "runs_pagination_complete": runs_complete,
        "jobs_pagination_complete": jobs_complete,
        "request_actor_permissions": request_actor,
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
        "authority_anchor_verified": authority_anchor_verified,
        "pagination_complete": (
            larger_runners_complete
            and self_hosted_runners_complete
            and budgets_complete
            and authority_comments_complete
            and runs_complete
            and jobs_complete
            and storage_complete
        ),
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
