"""Strict GET-only GitHub snapshots for catalog governance decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
from typing import Any, Literal, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .catalog_gate_budget import gate_timeout


API_ROOT = "https://api.github.com"
API_VERSION = "2026-03-10"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class CatalogGitHubSnapshotError(RuntimeError):
    """Raised when GitHub cannot provide one complete unambiguous snapshot."""


@dataclass(frozen=True)
class GitHubGetResponse:
    status: int
    requested_url: str
    final_url: str
    headers: Mapping[str, str]
    body: bytes


class GitHubGetTransport(Protocol):
    def get(self, url: str, headers: dict[str, str]) -> GitHubGetResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        del req, fp, code, msg, headers, newurl
        return None


class UrllibGitHubGetTransport:
    """Production transport that permits GET and refuses redirects."""

    def __init__(self, *, timeout_seconds: int = 60) -> None:
        self.timeout_seconds = timeout_seconds
        self._opener = build_opener(_NoRedirect())

    def get(self, url: str, headers: dict[str, str]) -> GitHubGetResponse:
        request = Request(url, method="GET", headers=headers)
        try:
            with self._opener.open(request, timeout=gate_timeout(self.timeout_seconds)) as response:
                return GitHubGetResponse(
                    status=int(response.status),
                    requested_url=url,
                    final_url=response.geturl(),
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as exc:
            return GitHubGetResponse(
                status=int(exc.code),
                requested_url=url,
                final_url=exc.geturl(),
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=exc.read(),
            )
        except (TimeoutError, URLError, OSError) as exc:
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_GET_UNAVAILABLE") from exc


@dataclass(frozen=True)
class CatalogGitHubPageReceipt:
    url: str
    etag: str
    body_sha256: str
    ordered_ids: tuple[int, ...]


@dataclass(frozen=True)
class CatalogGitHubCollection:
    rows: tuple[dict[str, Any], ...]
    ordered_ids: tuple[int, ...]
    pages: tuple[CatalogGitHubPageReceipt, ...]
    complete: bool
    collection_sha256: str


@dataclass(frozen=True)
class CatalogStableIssueCollection:
    issue: dict[str, Any]
    collection: CatalogGitHubCollection
    attempt: int
    stable: bool
    observed_at: datetime
    snapshot_sha256: str


@dataclass(frozen=True)
class CatalogStableInventory:
    collection: CatalogGitHubCollection
    attempt: int
    stable: bool
    observed_at: datetime
    snapshot_sha256: str


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == target:
            return str(value)
    return ""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise CatalogGitHubSnapshotError(f"CATALOG_GITHUB_JSON_NONFINITE:{value}")


def _with_per_page(path_or_url: str) -> str:
    parsed = urlparse(path_or_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if "per_page" in query and query["per_page"] != ["100"]:
        raise CatalogGitHubSnapshotError("CATALOG_GITHUB_PAGE_SIZE_INVALID")
    query["per_page"] = ["100"]
    encoded = urlencode(
        [(key, item) for key in sorted(query) for item in query[key]],
        doseq=True,
    )
    return urlunparse(parsed._replace(query=encoded))


def _next_link(headers: Mapping[str, str]) -> str | None:
    found: list[str] = []
    for part in _header(headers, "Link").split(","):
        if 'rel="next"' not in part:
            continue
        candidate = part.split(";", 1)[0].strip()
        if not (candidate.startswith("<") and candidate.endswith(">")):
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_PAGINATION_LINK_INVALID")
        found.append(candidate[1:-1])
    if len(found) > 1:
        raise CatalogGitHubSnapshotError("CATALOG_GITHUB_PAGINATION_LINK_INVALID")
    return found[0] if found else None


class CatalogGitHubReadOnlyClient:
    """Bounded GitHub reader with strict pagination and stability checks."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        transport: GitHubGetTransport | None = None,
    ) -> None:
        if not _REPOSITORY.fullmatch(repository):
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_REPOSITORY_INVALID")
        if not token:
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_TOKEN_MISSING")
        self.repository = repository
        self._token = token
        self._transport = transport or UrllibGitHubGetTransport()
        self.observed_at: datetime | None = None

    def _url(self, path_or_url: str) -> str:
        url = (
            path_or_url
            if path_or_url.startswith("https://")
            else urljoin(API_ROOT, path_or_url)
        )
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_PAGINATION_ORIGIN_INVALID")
        return url

    def _request(self, path_or_url: str) -> GitHubGetResponse:
        url = self._url(path_or_url)
        gate_timeout(60)
        response = self._transport.get(
            url,
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "aurora-catalog-controller-v1",
            },
        )
        gate_timeout(60)
        if response.requested_url != url or response.final_url != url:
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_REDIRECT_INVALID")
        remaining = _header(response.headers, "X-RateLimit-Remaining")
        retry_after = _header(response.headers, "Retry-After")
        if response.status in {403, 429} and (remaining == "0" or retry_after):
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_RATE_LIMIT_UNCERTAIN")
        if response.status != 200:
            raise CatalogGitHubSnapshotError(
                f"CATALOG_GITHUB_HTTP_STATUS_INVALID:{response.status}"
            )
        date_header = _header(response.headers, "Date")
        try:
            observed = parsedate_to_datetime(date_header).astimezone(UTC)
        except Exception:
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_DATE_INVALID") from None
        if self.observed_at is None or observed > self.observed_at:
            self.observed_at = observed
        return response

    def get_json(self, path_or_url: str) -> tuple[object, GitHubGetResponse]:
        response = self._request(path_or_url)
        try:
            payload = json.loads(
                response.body.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite,
            )
        except CatalogGitHubSnapshotError:
            raise
        except Exception as exc:
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_JSON_INVALID") from exc
        return payload, response

    def paginated(
        self,
        path: str,
        *,
        root: Literal["list"] | str,
    ) -> CatalogGitHubCollection:
        next_url = self._url(_with_per_page(path))
        seen_urls: set[str] = set()
        seen_ids: set[int] = set()
        rows: list[dict[str, Any]] = []
        pages: list[CatalogGitHubPageReceipt] = []
        while next_url:
            if next_url in seen_urls:
                raise CatalogGitHubSnapshotError("CATALOG_GITHUB_PAGINATION_LOOP")
            seen_urls.add(next_url)
            parsed = urlparse(next_url)
            query = parse_qs(parsed.query)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "api.github.com"
                or query.get("per_page") != ["100"]
            ):
                raise CatalogGitHubSnapshotError(
                    "CATALOG_GITHUB_PAGINATION_ORIGIN_INVALID"
                )
            payload, response = self.get_json(next_url)
            page_rows = payload if root == "list" else (
                payload.get(root) if isinstance(payload, dict) else None
            )
            if not isinstance(page_rows, list):
                raise CatalogGitHubSnapshotError(
                    "CATALOG_GITHUB_PAGINATION_PAYLOAD_INVALID"
                )
            page_ids: list[int] = []
            for raw in page_rows:
                if not isinstance(raw, dict):
                    raise CatalogGitHubSnapshotError(
                        "CATALOG_GITHUB_PAGINATION_PAYLOAD_INVALID"
                    )
                row_id = raw.get("id")
                if (
                    isinstance(row_id, bool)
                    or not isinstance(row_id, int)
                    or row_id < 1
                    or row_id in seen_ids
                ):
                    raise CatalogGitHubSnapshotError(
                        "CATALOG_GITHUB_PAGINATION_DUPLICATE_ID"
                    )
                seen_ids.add(row_id)
                page_ids.append(row_id)
                rows.append(dict(raw))
            etag = _header(response.headers, "ETag")
            if not etag:
                raise CatalogGitHubSnapshotError("CATALOG_GITHUB_ETAG_MISSING")
            pages.append(
                CatalogGitHubPageReceipt(
                    url=next_url,
                    etag=etag,
                    body_sha256=hashlib.sha256(response.body).hexdigest(),
                    ordered_ids=tuple(page_ids),
                )
            )
            candidate = _next_link(response.headers)
            next_url = self._url(candidate) if candidate else ""
        identity = {
            "api_version": API_VERSION,
            "ordered_ids": [row["id"] for row in rows],
            "pages": [
                {
                    "url": page.url,
                    "etag": page.etag,
                    "body_sha256": page.body_sha256,
                    "ordered_ids": list(page.ordered_ids),
                }
                for page in pages
            ],
        }
        return CatalogGitHubCollection(
            rows=tuple(rows),
            ordered_ids=tuple(int(row["id"]) for row in rows),
            pages=tuple(pages),
            complete=True,
            collection_sha256=_sha256(identity),
        )

    def stable_issue_collection(
        self,
        *,
        issue_path: str,
        collection_path: str,
        root: Literal["list"] | str,
        count_field: str | None = None,
        attempts: int = 3,
    ) -> CatalogStableIssueCollection:
        if attempts != 3:
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_ATTEMPT_LIMIT_INVALID")
        for attempt in range(1, attempts + 1):
            before_raw, _ = self.get_json(issue_path)
            if not isinstance(before_raw, dict):
                raise CatalogGitHubSnapshotError("CATALOG_GITHUB_ISSUE_INVALID")
            collection = self.paginated(collection_path, root=root)
            after_raw, _ = self.get_json(issue_path)
            if not isinstance(after_raw, dict):
                raise CatalogGitHubSnapshotError("CATALOG_GITHUB_ISSUE_INVALID")
            identity_before = (
                before_raw.get("id"),
                before_raw.get("node_id"),
                before_raw.get("updated_at"),
                before_raw.get(count_field) if count_field else None,
            )
            identity_after = (
                after_raw.get("id"),
                after_raw.get("node_id"),
                after_raw.get("updated_at"),
                after_raw.get(count_field) if count_field else None,
            )
            expected_count = before_raw.get(count_field) if count_field else None
            count_matches = (
                True if count_field is None else expected_count == len(collection.rows)
            )
            if identity_before == identity_after and count_matches:
                if self.observed_at is None:
                    raise CatalogGitHubSnapshotError("CATALOG_GITHUB_DATE_INVALID")
                identity = {
                    "api_version": API_VERSION,
                    "issue_id": before_raw.get("id"),
                    "issue_node_id": before_raw.get("node_id"),
                    "issue_updated_at": before_raw.get("updated_at"),
                    "collection_sha256": collection.collection_sha256,
                    "attempt": attempt,
                }
                return CatalogStableIssueCollection(
                    issue=dict(before_raw),
                    collection=collection,
                    attempt=attempt,
                    stable=True,
                    observed_at=self.observed_at,
                    snapshot_sha256=_sha256(identity),
                )
        raise CatalogGitHubSnapshotError("CATALOG_GITHUB_SNAPSHOT_UNSTABLE")

    def stable_paginated(
        self,
        path: str,
        *,
        root: Literal["list"] | str,
        attempts: int = 3,
    ) -> CatalogStableInventory:
        if attempts != 3:
            raise CatalogGitHubSnapshotError("CATALOG_GITHUB_ATTEMPT_LIMIT_INVALID")
        for attempt in range(1, attempts + 1):
            before = self.paginated(path, root=root)
            after = self.paginated(path, root=root)
            if before.collection_sha256 == after.collection_sha256:
                if self.observed_at is None:
                    raise CatalogGitHubSnapshotError("CATALOG_GITHUB_DATE_INVALID")
                identity = {
                    "api_version": API_VERSION,
                    "collection_sha256": before.collection_sha256,
                    "attempt": attempt,
                }
                return CatalogStableInventory(
                    collection=before,
                    attempt=attempt,
                    stable=True,
                    observed_at=self.observed_at,
                    snapshot_sha256=_sha256(identity),
                )
        raise CatalogGitHubSnapshotError("CATALOG_GITHUB_SNAPSHOT_UNSTABLE")


__all__ = [
    "API_ROOT",
    "API_VERSION",
    "CatalogGitHubCollection",
    "CatalogGitHubPageReceipt",
    "CatalogGitHubReadOnlyClient",
    "CatalogGitHubSnapshotError",
    "CatalogStableIssueCollection",
    "CatalogStableInventory",
    "GitHubGetResponse",
    "UrllibGitHubGetTransport",
]
