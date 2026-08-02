"""Resumable, two-pass GitHub inventory used by GTBI V7 reorganization."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from .canonical import canonical_bytes

SCHEMA_VERSION = "gtbi_v7_complete_inventory_v1"
PACKAGE_TYPES = ("container", "maven", "npm", "nuget", "rubygems")

OUTPUT_COLUMNS = {
    "artifacts.csv": [
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
        "source_page",
    ],
    "releases_complete.csv": [
        "release_id",
        "tag_name",
        "target_commitish",
        "name",
        "draft",
        "prerelease",
        "immutable",
        "created_at",
        "published_at",
        "html_url",
        "assets_count",
        "source_page",
    ],
    "packages_complete.csv": [
        "package_version_id",
        "package_id",
        "package_type",
        "package_name",
        "version_name",
        "created_at",
        "updated_at",
        "html_url",
        "metadata_json",
        "source_page",
    ],
}


class FullInventoryError(RuntimeError):
    """A complete inventory could not be proven."""


@dataclass(frozen=True)
class PageResponse:
    status: int
    payload: Any | None
    headers: Mapping[str, str]


class PageClient(Protocol):
    def get_page(self, url: str, *, etag: str | None = None) -> PageResponse:
        """Fetch one API page, returning 200 or 304."""


class GitHubPageClient:
    """Read-only GitHub REST client with conditional requests and rate pacing."""

    def __init__(
        self,
        token: str,
        *,
        api_url: str = "https://api.github.com",
        timeout_seconds: int = 60,
        rate_reserve: int = 75,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token:
            raise FullInventoryError("a GitHub token is required")
        self._token = token
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = int(timeout_seconds)
        self.rate_reserve = int(rate_reserve)
        self._sleep = sleep

    def get_page(self, url: str, *, etag: str | None = None) -> PageResponse:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "aurora-gtbi-v7-complete-inventory/1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if etag:
            headers["If-None-Match"] = etag
        for attempt in range(7):
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    response_headers = dict(response.headers.items())
                    payload = json.loads(response.read().decode("utf-8"))
                    self._pace(response_headers)
                    return PageResponse(response.status, payload, response_headers)
            except urllib.error.HTTPError as exc:
                response_headers = dict(exc.headers.items())
                if exc.code == 304:
                    self._pace(response_headers)
                    return PageResponse(304, None, response_headers)
                if exc.code in {403, 429, 500, 502, 503, 504} and attempt < 6:
                    retry_after = int(response_headers.get("Retry-After", "0") or 0)
                    wait = max(retry_after, min(2**attempt, 60))
                    self._sleep(float(wait))
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise FullInventoryError(
                    f"GitHub API {exc.code} for {url}: {body[:500]}"
                ) from exc
            except urllib.error.URLError as exc:
                if attempt < 6:
                    self._sleep(float(min(2**attempt, 60)))
                    continue
                raise FullInventoryError(f"GitHub API connection failed: {url}") from exc
        raise AssertionError("unreachable retry loop")

    def _pace(self, headers: Mapping[str, str]) -> None:
        remaining = int(headers.get("X-RateLimit-Remaining", "999999") or 0)
        reset = int(headers.get("X-RateLimit-Reset", "0") or 0)
        if remaining > self.rate_reserve or not reset:
            return
        wait = max(0, reset - int(time.time()) + 2)
        if wait:
            self._sleep(float(wait))


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _plain(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _api_url(api_url: str, path: str, **params: object) -> str:
    query = urllib.parse.urlencode([(key, str(value)) for key, value in params.items()])
    return f"{api_url.rstrip('/')}/{path.lstrip('/')}?{query}"


class InventoryCheckpoint:
    """SQLite checkpoint committed after every remote page."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pages(
                scan_id TEXT NOT NULL,
                surface TEXT NOT NULL,
                request_key TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                request_url TEXT NOT NULL,
                response_status INTEGER NOT NULL,
                etag TEXT,
                rate_limit TEXT,
                rate_remaining TEXT,
                rate_reset TEXT,
                cutoff_utc TEXT NOT NULL,
                page_digest TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                post_cutoff_count INTEGER NOT NULL,
                completed_at_utc TEXT NOT NULL,
                PRIMARY KEY(scan_id, surface, request_key, page_number)
            );
            CREATE TABLE IF NOT EXISTS records(
                scan_id TEXT NOT NULL,
                surface TEXT NOT NULL,
                immutable_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source_page TEXT NOT NULL,
                record_json TEXT NOT NULL,
                PRIMARY KEY(scan_id, surface, immutable_id)
            );
            CREATE TABLE IF NOT EXISTS surface_status(
                scan_id TEXT NOT NULL,
                surface TEXT NOT NULL,
                complete INTEGER NOT NULL,
                reason TEXT NOT NULL,
                request_count INTEGER NOT NULL,
                retained_count INTEGER NOT NULL,
                post_cutoff_count INTEGER NOT NULL,
                finished_at_utc TEXT NOT NULL,
                PRIMARY KEY(scan_id, surface)
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()

    def set_meta(self, key: str, value: str) -> None:
        existing = self.get_meta(key)
        if existing is not None and existing != value:
            raise FullInventoryError(f"checkpoint metadata mismatch: {key}")
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", (key, value)
        )
        self.connection.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key=?", (key,)
        ).fetchone()
        return None if row is None else str(row[0])

    def page(self, scan_id: str, surface: str, request_key: str, page: int) -> sqlite3.Row | None:
        self.connection.row_factory = sqlite3.Row
        return self.connection.execute(
            "SELECT * FROM pages WHERE scan_id=? AND surface=? AND request_key=? AND page_number=?",
            (scan_id, surface, request_key, page),
        ).fetchone()

    def page_records(
        self, scan_id: str, surface: str, source_page: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT record_json FROM records WHERE scan_id=? AND surface=? AND source_page=? ORDER BY immutable_id",
            (scan_id, surface, source_page),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_page(
        self,
        *,
        scan_id: str,
        surface: str,
        request_key: str,
        page_number: int,
        request_url: str,
        response: PageResponse,
        cutoff_utc: str,
        records: list[dict[str, Any]],
        created_at_field: str,
        id_field: str,
    ) -> tuple[int, int]:
        source_page = f"{request_key}:{page_number}"
        self.connection.execute(
            "DELETE FROM records WHERE scan_id=? AND surface=? AND source_page=?",
            (scan_id, surface, source_page),
        )
        cutoff = _parse_utc(cutoff_utc)
        retained = 0
        post_cutoff = 0
        for record in records:
            created_at = str(record.get(created_at_field) or "1970-01-01T00:00:00Z")
            if _parse_utc(created_at) > cutoff:
                post_cutoff += 1
                continue
            immutable_id = str(record[id_field])
            record = dict(record)
            record["source_page"] = source_page
            self.connection.execute(
                "INSERT OR REPLACE INTO records(scan_id,surface,immutable_id,created_at,source_page,record_json) VALUES(?,?,?,?,?,?)",
                (
                    scan_id,
                    surface,
                    immutable_id,
                    created_at,
                    source_page,
                    canonical_bytes(record).decode("utf-8"),
                ),
            )
            retained += 1
        headers = response.headers
        self.connection.execute(
            """
            INSERT OR REPLACE INTO pages(
                scan_id,surface,request_key,page_number,request_url,response_status,
                etag,rate_limit,rate_remaining,rate_reset,cutoff_utc,page_digest,
                item_count,post_cutoff_count,completed_at_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                scan_id,
                surface,
                request_key,
                page_number,
                request_url,
                response.status,
                headers.get("ETag") or headers.get("etag") or "",
                headers.get("X-RateLimit-Limit") or "",
                headers.get("X-RateLimit-Remaining") or "",
                headers.get("X-RateLimit-Reset") or "",
                cutoff_utc,
                _canonical_digest(records),
                len(records),
                post_cutoff,
                _utc_now(),
            ),
        )
        self.connection.commit()
        return retained, post_cutoff

    def mark_surface(self, scan_id: str, surface: str, *, complete: bool, reason: str) -> None:
        request_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM pages WHERE scan_id=? AND surface=?",
                (scan_id, surface),
            ).fetchone()[0]
        )
        retained_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM records WHERE scan_id=? AND surface=?",
                (scan_id, surface),
            ).fetchone()[0]
        )
        post_cutoff_count = int(
            self.connection.execute(
                "SELECT COALESCE(SUM(post_cutoff_count),0) FROM pages WHERE scan_id=? AND surface=?",
                (scan_id, surface),
            ).fetchone()[0]
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO surface_status VALUES(?,?,?,?,?,?,?,?)",
            (
                scan_id,
                surface,
                int(complete),
                reason,
                request_count,
                retained_count,
                post_cutoff_count,
                _utc_now(),
            ),
        )
        self.connection.commit()

    def surface_complete(self, scan_id: str, surface: str) -> bool:
        row = self.connection.execute(
            "SELECT complete FROM surface_status WHERE scan_id=? AND surface=?",
            (scan_id, surface),
        ).fetchone()
        return bool(row and row[0])


def _artifact_record(item: Mapping[str, Any]) -> dict[str, Any]:
    run = item.get("workflow_run") or {}
    return {
        "artifact_id": item.get("id"),
        "run_id": run.get("id"),
        "name": item.get("name"),
        "size_in_bytes": item.get("size_in_bytes"),
        "digest": item.get("digest"),
        "expired": item.get("expired"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "expires_at": item.get("expires_at"),
        "archive_download_url": item.get("archive_download_url"),
    }


def _release_record(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "release_id": item.get("id"),
        "tag_name": item.get("tag_name"),
        "target_commitish": item.get("target_commitish"),
        "name": item.get("name"),
        "draft": item.get("draft"),
        "prerelease": item.get("prerelease"),
        "immutable": item.get("immutable"),
        "created_at": item.get("created_at"),
        "published_at": item.get("published_at"),
        "html_url": item.get("html_url"),
        "assets_count": len(item.get("assets") or []),
    }


def _package_version_record(
    item: Mapping[str, Any], package: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "package_version_id": item.get("id"),
        "package_id": package.get("id"),
        "package_type": package.get("package_type"),
        "package_name": package.get("name"),
        "version_name": item.get("name"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "html_url": item.get("html_url"),
        "metadata_json": canonical_bytes(item.get("metadata") or {}).decode("utf-8"),
    }


def _mapping_record(item: Mapping[str, Any]) -> dict[str, Any]:
    return dict(item)


def _package_version_transform(
    package: Mapping[str, Any],
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def transform(item: Mapping[str, Any]) -> dict[str, Any]:
        return _package_version_record(item, package)

    return transform


def _page_items(payload: Any, item_key: str | None) -> list[dict[str, Any]]:
    value = payload.get(item_key, []) if item_key else payload
    if not isinstance(value, list):
        raise FullInventoryError("GitHub page response is not a list")
    return [dict(item) for item in value]


def _scan_paginated(
    *,
    checkpoint: InventoryCheckpoint,
    client: PageClient,
    scan_id: str,
    baseline_scan_id: str | None,
    surface: str,
    request_key: str,
    first_url: str,
    cutoff_utc: str,
    item_key: str | None,
    transform: Callable[[Mapping[str, Any]], dict[str, Any]],
    id_field: str,
    created_at_field: str = "created_at",
) -> list[dict[str, Any]]:
    page_number = 1
    all_source_items: list[dict[str, Any]] = []
    while True:
        existing = checkpoint.page(scan_id, surface, request_key, page_number)
        source_page = f"{request_key}:{page_number}"
        if existing is not None:
            records = checkpoint.page_records(scan_id, surface, source_page)
            all_source_items.extend(records)
            if int(existing["item_count"]) < 100:
                break
            page_number += 1
            continue

        separator = "&" if "?" in first_url else "?"
        url = f"{first_url}{separator}page={page_number}"
        baseline = (
            checkpoint.page(baseline_scan_id, surface, request_key, page_number)
            if baseline_scan_id
            else None
        )
        etag = str(baseline["etag"]) if baseline is not None else None
        response = client.get_page(url, etag=etag or None)
        if response.status == 304:
            if baseline is None:
                raise FullInventoryError("304 response without a baseline page")
            records = [
                {key: value for key, value in record.items() if key != "source_page"}
                for record in checkpoint.page_records(
                    baseline_scan_id or "", surface, source_page
                )
            ]
            source_count = int(baseline["item_count"])
        else:
            raw_items = _page_items(response.payload, item_key)
            records = [transform(item) for item in raw_items]
            source_count = len(raw_items)
        checkpoint.record_page(
            scan_id=scan_id,
            surface=surface,
            request_key=request_key,
            page_number=page_number,
            request_url=url,
            response=response,
            cutoff_utc=cutoff_utc,
            records=records,
            created_at_field=created_at_field,
            id_field=id_field,
        )
        all_source_items.extend(records)
        if source_count < 100:
            break
        page_number += 1
    return all_source_items


def run_scan(
    *,
    checkpoint: InventoryCheckpoint,
    client: PageClient,
    repository: str,
    organization: str,
    api_url: str,
    cutoff_utc: str,
    scan_id: str,
    baseline_scan_id: str | None = None,
) -> None:
    repo_path = f"repos/{repository}"
    if not checkpoint.surface_complete(scan_id, "artifacts"):
        try:
            _scan_paginated(
                checkpoint=checkpoint,
                client=client,
                scan_id=scan_id,
                baseline_scan_id=baseline_scan_id,
                surface="artifacts",
                request_key="repository",
                first_url=_api_url(
                    api_url, f"{repo_path}/actions/artifacts", per_page=100
                ),
                cutoff_utc=cutoff_utc,
                item_key="artifacts",
                transform=_artifact_record,
                id_field="artifact_id",
            )
            checkpoint.mark_surface(scan_id, "artifacts", complete=True, reason="")
        except Exception as exc:
            checkpoint.mark_surface(
                scan_id, "artifacts", complete=False, reason=str(exc)
            )
            raise

    if not checkpoint.surface_complete(scan_id, "releases"):
        try:
            _scan_paginated(
                checkpoint=checkpoint,
                client=client,
                scan_id=scan_id,
                baseline_scan_id=baseline_scan_id,
                surface="releases",
                request_key="repository",
                first_url=_api_url(api_url, f"{repo_path}/releases", per_page=100),
                cutoff_utc=cutoff_utc,
                item_key=None,
                transform=_release_record,
                id_field="release_id",
            )
            checkpoint.mark_surface(scan_id, "releases", complete=True, reason="")
        except Exception as exc:
            checkpoint.mark_surface(scan_id, "releases", complete=False, reason=str(exc))
            raise

    if not checkpoint.surface_complete(scan_id, "packages"):
        try:
            for package_type in PACKAGE_TYPES:
                packages = _scan_paginated(
                    checkpoint=checkpoint,
                    client=client,
                    scan_id=scan_id,
                    baseline_scan_id=baseline_scan_id,
                    surface="package_index",
                    request_key=package_type,
                    first_url=_api_url(
                        api_url,
                        f"orgs/{organization}/packages",
                        package_type=package_type,
                        per_page=100,
                    ),
                    cutoff_utc=cutoff_utc,
                    item_key=None,
                    transform=_mapping_record,
                    id_field="id",
                )
                for package in packages:
                    encoded_name = urllib.parse.quote(str(package["name"]), safe="")
                    package_key = f"{package_type}:{package['id']}"
                    _scan_paginated(
                        checkpoint=checkpoint,
                        client=client,
                        scan_id=scan_id,
                        baseline_scan_id=baseline_scan_id,
                        surface="packages",
                        request_key=package_key,
                        first_url=_api_url(
                            api_url,
                            f"orgs/{organization}/packages/{package_type}/{encoded_name}/versions",
                            per_page=100,
                        ),
                        cutoff_utc=cutoff_utc,
                        item_key=None,
                        transform=_package_version_transform(package),
                        id_field="package_version_id",
                    )
            checkpoint.mark_surface(scan_id, "package_index", complete=True, reason="")
            checkpoint.mark_surface(scan_id, "packages", complete=True, reason="")
        except Exception as exc:
            checkpoint.mark_surface(
                scan_id, "packages", complete=False, reason=str(exc)
            )
            raise


def _record_ids(
    checkpoint: InventoryCheckpoint, scan_id: str, surface: str
) -> list[str]:
    return [
        str(row[0])
        for row in checkpoint.connection.execute(
            "SELECT immutable_id FROM records WHERE scan_id=? AND surface=? ORDER BY immutable_id",
            (scan_id, surface),
        )
    ]


def _surface_status(
    checkpoint: InventoryCheckpoint, scan_id: str, surface: str
) -> dict[str, Any]:
    checkpoint.connection.row_factory = sqlite3.Row
    row = checkpoint.connection.execute(
        "SELECT * FROM surface_status WHERE scan_id=? AND surface=?",
        (scan_id, surface),
    ).fetchone()
    return {} if row is None else dict(row)


def _write_csv(
    path: Path,
    columns: list[str],
    rows: Iterable[Mapping[str, Any]],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _plain(row.get(key)) for key in columns})
            count += 1
    return count


def finalize_inventory(
    checkpoint: InventoryCheckpoint,
    *,
    output_dir: Path,
    repository: str,
    organization: str,
    cutoff_utc: str,
    scan_ids: tuple[str, str] = ("scan_a", "scan_b"),
) -> dict[str, Any]:
    first, second = scan_ids
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    surfaces = ("artifacts", "releases", "packages")
    surface_reports: dict[str, Any] = {}
    complete = True
    for surface in surfaces:
        ids_a = _record_ids(checkpoint, first, surface)
        ids_b = _record_ids(checkpoint, second, surface)
        status_a = _surface_status(checkpoint, first, surface)
        status_b = _surface_status(checkpoint, second, surface)
        stable = ids_a == ids_b
        missing_in_second = sorted(set(ids_a) - set(ids_b))
        added_in_second = sorted(set(ids_b) - set(ids_a))
        scan_complete = checkpoint.surface_complete(
            first, surface
        ) and checkpoint.surface_complete(second, surface)
        complete = complete and stable and scan_complete
        surface_reports[surface] = {
            "scan_a_retained_count": len(ids_a),
            "scan_b_retained_count": len(ids_b),
            "scan_a_post_cutoff_count": int(status_a.get("post_cutoff_count", 0)),
            "scan_b_post_cutoff_count": int(status_b.get("post_cutoff_count", 0)),
            "scan_a_id_set_digest": _canonical_digest(ids_a),
            "scan_b_id_set_digest": _canonical_digest(ids_b),
            "stable_retained_id_set": stable,
            "deleted_during_scan_count": len(missing_in_second),
            "added_at_or_before_cutoff_during_scan_count": len(added_in_second),
            "inaccessible_count": 0 if scan_complete else 1,
            "scan_a_incomplete_reason": str(status_a.get("reason", "")),
            "scan_b_incomplete_reason": str(status_b.get("reason", "")),
            "scan_complete": scan_complete,
        }

    file_map = {
        "artifacts": "artifacts.csv",
        "releases": "releases_complete.csv",
        "packages": "packages_complete.csv",
    }
    output_counts: dict[str, int] = {}
    for surface, filename in file_map.items():
        rows = (
            json.loads(row[0])
            for row in checkpoint.connection.execute(
                "SELECT record_json FROM records WHERE scan_id=? AND surface=? ORDER BY immutable_id",
                (second, surface),
            )
        )
        output_counts[filename] = _write_csv(
            output_dir / filename, OUTPUT_COLUMNS[filename], rows
        )

    pages = []
    for row in checkpoint.connection.execute(
        """
        SELECT scan_id,surface,request_key,page_number,request_url,response_status,
               etag,rate_limit,rate_remaining,rate_reset,cutoff_utc,page_digest,
               item_count,post_cutoff_count,completed_at_utc
        FROM pages ORDER BY scan_id,surface,request_key,page_number
        """
    ):
        pages.append(
            {
                "scan_id": row[0],
                "surface": row[1],
                "request_key": row[2],
                "page_number": row[3],
                "request_url": row[4],
                "response_status": row[5],
                "etag": row[6],
                "rate_limit": row[7],
                "rate_remaining": row[8],
                "rate_reset": row[9],
                "cutoff_utc": row[10],
                "page_digest": row[11],
                "item_count": row[12],
                "post_cutoff_count": row[13],
                "completed_at_utc": row[14],
            }
        )
    page_manifest_digest = _canonical_digest(pages)
    reconciliation: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "organization": organization,
        "cutoff_utc": cutoff_utc,
        "scan_ids": list(scan_ids),
        "complete": complete,
        "completion_rule": "two_consecutive_identical_retained_id_sets",
        "surfaces": surface_reports,
        "output_row_counts": output_counts,
        "page_request_count": len(pages),
        "page_manifest_digest": page_manifest_digest,
        "request_urls_contain_credentials": False,
        "checkpoint_committed_after_every_page": True,
        "generated_at_utc": _utc_now(),
    }
    reconciliation["receipt_digest"] = _canonical_digest(reconciliation)
    (output_dir / "inventory_reconciliation.json").write_bytes(
        canonical_bytes(reconciliation) + b"\n"
    )
    if not complete:
        raise FullInventoryError("two-pass inventory reconciliation is incomplete")
    return reconciliation


def run_complete_inventory(
    *,
    client: PageClient,
    repository: str,
    organization: str,
    api_url: str,
    cutoff_utc: str,
    checkpoint_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    checkpoint = InventoryCheckpoint(checkpoint_path)
    try:
        checkpoint.set_meta("schema_version", SCHEMA_VERSION)
        checkpoint.set_meta("repository", repository)
        checkpoint.set_meta("organization", organization)
        checkpoint.set_meta("cutoff_utc", cutoff_utc)
        try:
            run_scan(
                checkpoint=checkpoint,
                client=client,
                repository=repository,
                organization=organization,
                api_url=api_url,
                cutoff_utc=cutoff_utc,
                scan_id="scan_a",
            )
            run_scan(
                checkpoint=checkpoint,
                client=client,
                repository=repository,
                organization=organization,
                api_url=api_url,
                cutoff_utc=cutoff_utc,
                scan_id="scan_b",
                baseline_scan_id="scan_a",
            )
        except Exception:
            try:
                finalize_inventory(
                    checkpoint,
                    output_dir=output_dir,
                    repository=repository,
                    organization=organization,
                    cutoff_utc=cutoff_utc,
                )
            except FullInventoryError:
                pass
            raise
        return finalize_inventory(
            checkpoint,
            output_dir=output_dir,
            repository=repository,
            organization=organization,
            cutoff_utc=cutoff_utc,
        )
    finally:
        checkpoint.close()


def token_from_environment() -> str:
    return (
        os.environ.get("GTBI_INVENTORY_TOKEN", "").strip()
        or os.environ.get("GH_TOKEN", "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
    )
