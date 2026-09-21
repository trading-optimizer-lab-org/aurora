"""GET-only restoration of one exact PREPARED catalog artifact.

The producer is the real ``catalog-prepare.yml`` workflow.  This module does
not create caches, artifacts, tokens, credentials, or scientific outputs.  It
reads a bounded run/job/artifact snapshot through the existing strict GitHub
reader, accepts only an archive no larger than :data:`MAX_ARCHIVE_BYTES` after
the GET, verifies the real bundle contracts, and publishes only into an absent
destination.

The accepted archive limit is intentionally 64 MiB compressed with 256 MiB
total uncompressed content.  That is bounded above the known ~45.5 MiB
producer bundle while remaining distinct from the 2 MiB qualification helper
limit.  The ``gh`` subprocess writes to a temporary file before the size is
checked, so this is an accepted-archive bound rather than a transfer-stream
cap.  Every GET, extraction checkpoint, verifier checkpoint, and archive
subprocess uses the shared absolute gate deadline; there is no retry loop.  The
second metadata read is a required mutation check, not a retry.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable, Iterator, Mapping, Sequence
import zipfile
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .catalog_fast_path import (
    CatalogPreparedReceiptV1,
    CatalogPreparationIdentityV1,
)
from .catalog_fast_reservation import _is_expected_workflow_path
from .catalog_gate_budget import gate_timeout
from .catalog_github_snapshot import CatalogGitHubReadOnlyClient
from .catalog_prepared_bundle import (
    CatalogPreparedBundleManifestV1,
    verify_prepared_catalog_bundle,
)


REPOSITORY = "trading-optimizer-lab-org/aurora"
REPOSITORY_ID = 1232647748
ALLOWED_WORKFLOW_EVENTS = frozenset({"push", "schedule"})
PRODUCER_BRANCH = "main"
PREFLIGHT_PHASE = "preflight"
FINALIZE_PHASE = "finalize"
PUBLISH_STEP_NAME = "Publish the PREPARED receipt and bundle as durable evidence"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 4096
MAX_COMPRESSION_RATIO = 100
MAX_JOB_ROWS = 4096
# Job pagination is separate from the four-page artifact-list bound.
MAX_JOB_PAGES = (MAX_JOB_ROWS + 99) // 100
MAX_ARTIFACT_ROWS = 100
MAX_PAGES = 4
DOWNLOAD_TIMEOUT_SECONDS = 35.0
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class PreparedArtifactRestoreError(ValueError):
    """Stable public failure without response bodies, paths, or credentials."""

    def __init__(self, code: str) -> None:
        if not re.fullmatch(r"[A-Z0-9_]+", code):
            code = "CATALOG_PREPARED_ARTIFACT_UNAVAILABLE"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PreparedArtifactRestoreResult:
    """Tuple-compatible result carrying public provenance for the CLI writer."""

    receipt: CatalogPreparedReceiptV1
    manifest: CatalogPreparedBundleManifestV1
    artifact_id: int
    run_id: int
    run_attempt: int
    digest: str
    source_commit: str
    campaign_key: str
    preparation_key_sha256: str

    def __iter__(self) -> Iterator[CatalogPreparedReceiptV1 | CatalogPreparedBundleManifestV1]:
        # Preserve the suggested ``receipt, manifest = ...`` API while making
        # the IDs available to a public report writer.
        yield self.receipt
        yield self.manifest


@dataclass(frozen=True)
class _RemoteCollection:
    rows: tuple[dict[str, Any], ...]
    snapshot_sha256: str


@dataclass(frozen=True)
class _SourceSnapshot:
    run_id: int
    run_attempt: int
    artifact_id: int
    artifact_digest: str
    artifact: dict[str, Any]
    snapshot_sha256: str


def _fail(code: str) -> PreparedArtifactRestoreError:
    return PreparedArtifactRestoreError(code)


def _canonical_sha256(value: object) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _fail("CATALOG_PREPARED_ARTIFACT_REMOTE_RESPONSE_INVALID") from exc
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(code)
    return value


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value < 1:
        raise _fail(code)
    return value


def _time(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise _fail(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _fail(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _fail(code)
    return parsed.astimezone(timezone.utc)


def _deadline_checkpoint() -> None:
    try:
        gate_timeout(1.0)
    except ValueError as exc:
        if str(exc) == "CATALOG_GATE_DEADLINE_EXCEEDED":
            raise _fail("CATALOG_PREPARED_ARTIFACT_DEADLINE_EXCEEDED") from None
        if str(exc) == "CATALOG_GATE_DEADLINE_INVALID":
            raise _fail("CATALOG_PREPARED_ARTIFACT_DEADLINE_INVALID") from None
        raise _fail("CATALOG_PREPARED_ARTIFACT_DEADLINE_INVALID") from None


def _client_is_usable(client: object) -> CatalogGitHubReadOnlyClient:
    if (
        not isinstance(getattr(client, "repository", None), str)
        or getattr(client, "repository", None) != REPOSITORY
        or not callable(getattr(client, "get_json", None))
    ):
        raise _fail("CATALOG_PREPARED_ARTIFACT_CLIENT_INVALID")
    return client  # type: ignore[return-value]


def _ensure_per_page(path: str) -> str:
    parsed = urlparse(path)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    existing = [value for key, value in query if key == "per_page"]
    if existing and existing != ["100"]:
        raise _fail("CATALOG_PREPARED_ARTIFACT_PAGE_SIZE_INVALID")
    if not existing:
        query.append(("per_page", "100"))
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _header(headers: object, name: str) -> str:
    if not isinstance(headers, Mapping):
        raise _fail("CATALOG_PREPARED_ARTIFACT_RESPONSE_INVALID")
    target = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == target:
            return str(value)
    return ""


def _next_url(headers: object) -> str | None:
    link = _header(headers, "Link")
    candidates: list[str] = []
    for part in link.split(","):
        if 'rel="next"' not in part:
            continue
        candidate = part.split(";", 1)[0].strip()
        if not (candidate.startswith("<") and candidate.endswith(">")):
            raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INVALID")
        candidates.append(candidate[1:-1])
    if len(candidates) > 1:
        raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INVALID")
    if not candidates:
        return None
    parsed = urlparse(candidates[0])
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INVALID")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if [value for key, value in query if key == "per_page"] != ["100"]:
        raise _fail("CATALOG_PREPARED_ARTIFACT_PAGE_SIZE_INVALID")
    return candidates[0]


def _response_body(response: object) -> bytes:
    body = getattr(response, "body", None)
    if type(body) is not bytes:
        raise _fail("CATALOG_PREPARED_ARTIFACT_RESPONSE_INVALID")
    return body


def _get_json(client: CatalogGitHubReadOnlyClient, path: str) -> tuple[Mapping[str, Any], object]:
    try:
        payload, response = client.get_json(path)
    except PreparedArtifactRestoreError:
        raise
    except ValueError as exc:
        if str(exc) == "CATALOG_GATE_DEADLINE_EXCEEDED":
            raise _fail("CATALOG_PREPARED_ARTIFACT_DEADLINE_EXCEEDED") from None
        if str(exc) == "CATALOG_GATE_DEADLINE_INVALID":
            raise _fail("CATALOG_PREPARED_ARTIFACT_DEADLINE_INVALID") from None
        raise _fail("CATALOG_PREPARED_ARTIFACT_REMOTE_READ_FAILED") from None
    except Exception as exc:
        raise _fail("CATALOG_PREPARED_ARTIFACT_REMOTE_READ_FAILED") from exc
    return _mapping(payload, "CATALOG_PREPARED_ARTIFACT_RESPONSE_INVALID"), response


def _paginate_exact(
    client: CatalogGitHubReadOnlyClient,
    path: str,
    *,
    root: str,
    max_rows: int,
    max_pages: int = MAX_PAGES,
) -> _RemoteCollection:
    if type(max_pages) is not int or max_pages < 1:
        raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INVALID")
    next_path = _ensure_per_page(path)
    rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    declared_total: int | None = None
    pages: list[dict[str, object]] = []
    for _page_number in range(1, max_pages + 1):
        payload, response = _get_json(client, next_path)
        raw_rows = payload.get(root)
        total_count = payload.get("total_count")
        if (
            not isinstance(raw_rows, list)
            or type(total_count) is not int
            or total_count < 0
            or total_count > max_rows
        ):
            raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INVALID")
        if declared_total is None:
            declared_total = total_count
        elif declared_total != total_count:
            raise _fail("CATALOG_PREPARED_ARTIFACT_REMOTE_MUTATED")
        if len(rows) + len(raw_rows) > declared_total:
            raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INVALID")
        page_ids: list[int] = []
        for raw in raw_rows:
            row = _mapping(raw, "CATALOG_PREPARED_ARTIFACT_RESPONSE_INVALID")
            row_id = _positive_int(row.get("id"), "CATALOG_PREPARED_ARTIFACT_RESPONSE_INVALID")
            if row_id in seen_ids:
                raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_DUPLICATE")
            seen_ids.add(row_id)
            page_ids.append(row_id)
            rows.append(dict(row))
        etag = _header(getattr(response, "headers", None), "ETag")
        body = _response_body(response)
        if not etag:
            raise _fail("CATALOG_PREPARED_ARTIFACT_ETAG_MISSING")
        pages.append(
            {
                "url": next_path,
                "etag": etag,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "ordered_ids": page_ids,
            }
        )
        candidate = _next_url(getattr(response, "headers", None))
        if candidate is None:
            if declared_total != len(rows):
                raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INCOMPLETE")
            return _RemoteCollection(
                rows=tuple(rows),
                snapshot_sha256=_canonical_sha256(
                    {"total_count": declared_total, "pages": pages, "rows": rows}
                ),
            )
        if len(rows) >= declared_total:
            raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INVALID")
        next_path = candidate
    raise _fail("CATALOG_PREPARED_ARTIFACT_PAGINATION_INCOMPLETE")


def _run_matches(run: Mapping[str, Any], expected_identity: CatalogPreparationIdentityV1) -> bool:
    repository = run.get("repository")
    attempt = run.get("run_attempt")
    return (
        _is_expected_workflow_path(
            run.get("path"), ".github/workflows/catalog-prepare.yml"
        )
        and run.get("event") in ALLOWED_WORKFLOW_EVENTS
        and run.get("head_branch") == PRODUCER_BRANCH
        and run.get("head_sha") == expected_identity.protected_commit_sha
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and isinstance(repository, Mapping)
        and repository.get("id") == REPOSITORY_ID
        and repository.get("full_name") == REPOSITORY
        and type(attempt) is int
        and attempt >= 1
    )


def _validate_job(
    job: Mapping[str, Any],
    *,
    name: str,
    run_id: int,
    run_attempt: int,
    protected_commit: str,
) -> tuple[datetime, datetime]:
    if (
        job.get("name") != name
        or job.get("run_id") != run_id
        or job.get("run_attempt") != run_attempt
        or job.get("head_sha") != protected_commit
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
    ):
        raise _fail("CATALOG_PREPARED_ARTIFACT_JOB_INVALID")
    _positive_int(job.get("id"), "CATALOG_PREPARED_ARTIFACT_JOB_INVALID")
    started = _time(job.get("started_at"), "CATALOG_PREPARED_ARTIFACT_JOB_TIME_INVALID")
    completed = _time(job.get("completed_at"), "CATALOG_PREPARED_ARTIFACT_JOB_TIME_INVALID")
    if completed < started:
        raise _fail("CATALOG_PREPARED_ARTIFACT_JOB_TIME_INVALID")
    return started, completed


def _producer_job_names(campaign_key: str) -> tuple[str, str]:
    if not isinstance(campaign_key, str) or not campaign_key:
        raise _fail("CATALOG_PREPARED_ARTIFACT_IDENTITY_INVALID")
    return (
        f"prepare ({campaign_key}) / {PREFLIGHT_PHASE}",
        f"prepare ({campaign_key}) / {FINALIZE_PHASE}",
    )


def _validate_publish_step(
    job: Mapping[str, Any],
    *,
    artifact_created_at: datetime,
    job_started: datetime,
    job_completed: datetime,
) -> None:
    raw_steps = job.get("steps")
    if not isinstance(raw_steps, list):
        raise _fail("CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_INVALID")
    matches: list[Mapping[str, Any]] = []
    for raw_step in raw_steps:
        step = _mapping(raw_step, "CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_INVALID")
        if step.get("name") == PUBLISH_STEP_NAME:
            matches.append(step)
    if len(matches) != 1:
        raise _fail("CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_INVALID")
    step = matches[0]
    if step.get("status") != "completed" or step.get("conclusion") != "success":
        raise _fail("CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_INVALID")
    started = _time(
        step.get("started_at"), "CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_TIME_INVALID"
    )
    completed = _time(
        step.get("completed_at"), "CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_TIME_INVALID"
    )
    if (
        completed < started
        or started < job_started
        or completed > job_completed
        or artifact_created_at < started
        or artifact_created_at > completed
        or artifact_created_at < job_started
        or artifact_created_at > job_completed
    ):
        raise _fail("CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_TIME_INVALID")


def _artifact_name(identity: CatalogPreparationIdentityV1) -> str:
    return f"catalog-prepared-{identity.campaign_key}-{identity.preparation_key_sha256}"


def _validate_artifact(
    artifact: Mapping[str, Any],
    *,
    expected_identity: CatalogPreparationIdentityV1,
    run_id: int,
    run_attempt: int,
    observed_at: datetime,
) -> tuple[int, str, datetime]:
    expected_name = _artifact_name(expected_identity)
    artifact_id = _positive_int(
        artifact.get("id"), "CATALOG_PREPARED_ARTIFACT_METADATA_INVALID"
    )
    digest = artifact.get("digest")
    size = artifact.get("size_in_bytes")
    if (
        artifact.get("name") != expected_name
    ):
        raise _fail("CATALOG_PREPARED_ARTIFACT_NAME_INVALID")
    if (
        artifact.get("expired") is not False
        or type(size) is not int
        or not 0 < size <= MAX_ARCHIVE_BYTES
        or type(digest) is not str
        or _SHA256.fullmatch(digest) is None
    ):
        raise _fail("CATALOG_PREPARED_ARTIFACT_METADATA_INVALID")
    created_at = _time(
        artifact.get("created_at"), "CATALOG_PREPARED_ARTIFACT_TIME_INVALID"
    )
    expires_at = _time(
        artifact.get("expires_at"), "CATALOG_PREPARED_ARTIFACT_TIME_INVALID"
    )
    if created_at > observed_at or expires_at <= observed_at or expires_at <= created_at:
        raise _fail("CATALOG_PREPARED_ARTIFACT_EXPIRED")
    workflow_run = _mapping(
        artifact.get("workflow_run"), "CATALOG_PREPARED_ARTIFACT_PROVENANCE_INVALID"
    )
    if (
        workflow_run.get("id") != run_id
        or (
            "run_attempt" in workflow_run
            and workflow_run.get("run_attempt") != run_attempt
        )
        or workflow_run.get("head_branch") != PRODUCER_BRANCH
        or workflow_run.get("head_sha") != expected_identity.protected_commit_sha
        or workflow_run.get("repository_id") != REPOSITORY_ID
        or workflow_run.get("head_repository_id") != REPOSITORY_ID
    ):
        raise _fail("CATALOG_PREPARED_ARTIFACT_PROVENANCE_INVALID")
    return artifact_id, digest, created_at


def _read_source_snapshot(
    client: CatalogGitHubReadOnlyClient,
    expected_identity: CatalogPreparationIdentityV1,
) -> _SourceSnapshot:
    artifact_rows = _paginate_exact(
        client,
        f"/repos/{REPOSITORY}/actions/artifacts"
        f"?name={_artifact_name(expected_identity)}",
        root="artifacts",
        max_rows=MAX_ARTIFACT_ROWS,
    )
    if len(artifact_rows.rows) != 1:
        raise _fail("CATALOG_PREPARED_ARTIFACT_AMBIGUOUS_ARTIFACT")
    artifact = artifact_rows.rows[0]
    artifact_workflow_run = _mapping(
        artifact.get("workflow_run"),
        "CATALOG_PREPARED_ARTIFACT_PROVENANCE_INVALID",
    )
    run_id = _positive_int(
        artifact_workflow_run.get("id"),
        "CATALOG_PREPARED_ARTIFACT_RUN_INVALID",
    )
    source_run, _run_response = _get_json(
        client,
        f"/repos/{REPOSITORY}/actions/runs/{run_id}",
    )
    if not _run_matches(source_run, expected_identity):
        raise _fail("CATALOG_PREPARED_ARTIFACT_RUN_INVALID")
    run_attempt = _positive_int(
        source_run.get("run_attempt"), "CATALOG_PREPARED_ARTIFACT_RUN_INVALID"
    )
    jobs = _paginate_exact(
        client,
        f"/repos/{REPOSITORY}/actions/runs/{run_id}/jobs?filter=latest",
        root="jobs",
        max_rows=MAX_JOB_ROWS,
        max_pages=MAX_JOB_PAGES,
    )
    preflight_name, finalize_name = _producer_job_names(expected_identity.campaign_key)
    job_windows: dict[str, tuple[datetime, datetime]] = {}
    selected_jobs: dict[str, Mapping[str, Any]] = {}
    for job_name in (preflight_name, finalize_name):
        matches = [row for row in jobs.rows if row.get("name") == job_name]
        if len(matches) != 1:
            raise _fail("CATALOG_PREPARED_ARTIFACT_JOB_AMBIGUOUS")
        selected_job = matches[0]
        job_windows[job_name] = _validate_job(
            selected_job,
            name=job_name,
            run_id=run_id,
            run_attempt=run_attempt,
            protected_commit=expected_identity.protected_commit_sha,
        )
        selected_jobs[job_name] = selected_job
    observed_at = getattr(client, "observed_at", None)
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise _fail("CATALOG_PREPARED_ARTIFACT_OBSERVATION_TIME_INVALID")
    observed_at = observed_at.astimezone(timezone.utc)
    artifact_id, artifact_digest, artifact_created_at = _validate_artifact(
        artifact,
        expected_identity=expected_identity,
        run_id=run_id,
        run_attempt=run_attempt,
        observed_at=observed_at,
    )
    _validate_publish_step(
        selected_jobs[finalize_name],
        artifact_created_at=artifact_created_at,
        job_started=job_windows[finalize_name][0],
        job_completed=job_windows[finalize_name][1],
    )
    snapshot = {
        "artifact_rows": artifact_rows.snapshot_sha256,
        "run": source_run,
        "jobs": jobs.snapshot_sha256,
        "artifact": artifact,
    }
    return _SourceSnapshot(
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
        artifact=dict(artifact),
        snapshot_sha256=_canonical_sha256(snapshot),
    )


def _download_archive(client: CatalogGitHubReadOnlyClient, artifact_id: int) -> bytes:
    token = getattr(client, "_token", None)
    if type(token) is not str or not token:
        raise _fail("CATALOG_PREPARED_ARTIFACT_DOWNLOAD_UNAVAILABLE")
    try:
        timeout = gate_timeout(DOWNLOAD_TIMEOUT_SECONDS, reserve_seconds=2.0)
        with tempfile.TemporaryFile() as stream:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip",
                ],
                stdout=stream,
                stderr=subprocess.PIPE,
                env={**os.environ, "GH_TOKEN": token},
                timeout=timeout,
                check=False,
            )
            if result.returncode != 0:
                raise _fail("CATALOG_PREPARED_ARTIFACT_DOWNLOAD_FAILED")
            stream.seek(0)
            raw = stream.read(MAX_ARCHIVE_BYTES + 1)
    except PreparedArtifactRestoreError:
        raise
    except ValueError as exc:
        if str(exc) == "CATALOG_GATE_DEADLINE_EXCEEDED":
            raise _fail("CATALOG_PREPARED_ARTIFACT_DEADLINE_EXCEEDED") from None
        if str(exc) == "CATALOG_GATE_DEADLINE_INVALID":
            raise _fail("CATALOG_PREPARED_ARTIFACT_DEADLINE_INVALID") from None
        raise _fail("CATALOG_PREPARED_ARTIFACT_DOWNLOAD_FAILED") from None
    except subprocess.TimeoutExpired:
        raise _fail("CATALOG_PREPARED_ARTIFACT_DOWNLOAD_TIMEOUT") from None
    except (OSError, subprocess.SubprocessError):
        raise _fail("CATALOG_PREPARED_ARTIFACT_DOWNLOAD_FAILED") from None
    if not raw or len(raw) > MAX_ARCHIVE_BYTES:
        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_SIZE_INVALID")
    return raw


def _safe_destination(destination: Path) -> Path:
    if not isinstance(destination, Path) or not destination.is_absolute():
        raise _fail("CATALOG_PREPARED_ARTIFACT_DESTINATION_INVALID")
    if destination.name in {"", ".", ".."}:
        raise _fail("CATALOG_PREPARED_ARTIFACT_DESTINATION_INVALID")
    if destination.exists() or destination.is_symlink():
        raise _fail("CATALOG_PREPARED_ARTIFACT_DESTINATION_EXISTS")
    parent = destination.parent
    try:
        if not parent.is_dir() or parent.is_symlink():
            raise _fail("CATALOG_PREPARED_ARTIFACT_DESTINATION_INVALID")
        metadata = parent.stat(follow_symlinks=False)
    except (OSError, ValueError) as exc:
        raise _fail("CATALOG_PREPARED_ARTIFACT_DESTINATION_INVALID") from exc
    if _is_reparse(metadata):
        raise _fail("CATALOG_PREPARED_ARTIFACT_DESTINATION_INVALID")
    return destination


def _rename_without_overwrite(staging: Path, destination: Path) -> None:
    if os.name == "nt":
        os.rename(staging, destination)
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2: Any = getattr(libc, "renameat2")
    except (AttributeError, OSError):
        raise _fail("CATALOG_PREPARED_ARTIFACT_PUBLISH_UNAVAILABLE") from None
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(os.fspath(staging)),
        _AT_FDCWD,
        os.fsencode(os.fspath(destination)),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(errno.EEXIST, os.strerror(error_number), destination)
    raise OSError(error_number, os.strerror(error_number), destination)


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT)


def _member_path(name: str, *, is_directory: bool, seen: set[str]) -> str | None:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_PATH_INVALID")
    clean = name[:-1] if is_directory and name.endswith("/") else name
    if not clean or clean.startswith("/") or re.match(r"^[A-Za-z]:", clean):
        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_PATH_INVALID")
    path = PurePosixPath(clean)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != clean
    ):
        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_PATH_INVALID")
    key = clean.casefold()
    if key in seen:
        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_DUPLICATE")
    seen.add(key)
    return None if is_directory else clean


def _extract_archive(raw: bytes, staging: Path) -> None:
    _deadline_checkpoint()
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_SIZE_INVALID")
    seen: set[str] = set()
    total_size = 0
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_INVALID") from exc
    try:
        members = archive.infolist()
        if not members or len(members) > MAX_ARCHIVE_MEMBERS:
            raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_BOUNDS_INVALID")
        for member in members:
            _deadline_checkpoint()
            mode = (member.external_attr >> 16) & 0o170000
            is_directory = member.is_dir() or member.filename.endswith("/")
            if is_directory:
                if mode not in {0, 0o040000}:
                    raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_SYMLINK")
                _member_path(member.filename, is_directory=True, seen=seen)
                continue
            if (
                member.flag_bits & 1
                or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or mode not in {0, 0o100000}
            ):
                raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_MEMBER_INVALID")
            relative = _member_path(member.filename, is_directory=False, seen=seen)
            if relative is None:
                raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_PATH_INVALID")
            if (
                type(member.file_size) is not int
                or member.file_size < 0
                or member.file_size > MAX_MEMBER_BYTES
                or type(member.compress_size) is not int
                or member.compress_size < 0
                or (
                    member.file_size > 0
                    and member.file_size > max(1, member.compress_size) * MAX_COMPRESSION_RATIO
                )
            ):
                raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_BOUNDS_INVALID")
            total_size += member.file_size
            if total_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_BOUNDS_INVALID")
            target = staging.joinpath(*relative.split("/"))
            parent = target.parent
            parent.mkdir(parents=True, exist_ok=True)
            if parent.is_symlink() or target.exists() or target.is_symlink():
                raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_DUPLICATE")
            try:
                with archive.open(member, "r") as source, target.open("xb") as sink:
                    copied = 0
                    while True:
                        _deadline_checkpoint()
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > member.file_size:
                            raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_BOUNDS_INVALID")
                        sink.write(chunk)
                    if copied != member.file_size:
                        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_INVALID")
            except PreparedArtifactRestoreError:
                raise
            except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
                raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_INVALID") from exc
    finally:
        archive.close()


def restore_prepared_artifact(
    client: CatalogGitHubReadOnlyClient,
    expected_identity: CatalogPreparationIdentityV1,
    destination: Path,
    *,
    download_archive: Callable[[int], bytes] | None = None,
) -> PreparedArtifactRestoreResult:
    """Restore one exact PREPARED artifact into an absent destination.

    ``receipt.identity`` is the authoritative read-back of source commit,
    campaign, and preparation key.  The returned result also exposes the
    authenticated artifact/run IDs and digest for a public writer report.
    ``download_archive`` is a boundary-only test seam; production defaults to
    the bounded GET used by the existing qualification helper, with a larger
    explicit limit for the real PREPARED bundle.
    """

    client = _client_is_usable(client)
    if not isinstance(expected_identity, CatalogPreparationIdentityV1):
        raise _fail("CATALOG_PREPARED_ARTIFACT_IDENTITY_INVALID")
    destination = _safe_destination(destination)
    first = _read_source_snapshot(client, expected_identity)
    downloader = download_archive or (lambda artifact_id: _download_archive(client, artifact_id))
    try:
        raw = downloader(first.artifact_id)
    except PreparedArtifactRestoreError:
        raise
    except Exception as exc:
        raise _fail("CATALOG_PREPARED_ARTIFACT_DOWNLOAD_FAILED") from exc
    if type(raw) is not bytes:
        raise _fail("CATALOG_PREPARED_ARTIFACT_ARCHIVE_INVALID")
    if len(raw) != first.artifact.get("size_in_bytes"):
        raise _fail("CATALOG_PREPARED_ARTIFACT_DIGEST_INVALID")
    if "sha256:" + hashlib.sha256(raw).hexdigest() != first.artifact_digest:
        raise _fail("CATALOG_PREPARED_ARTIFACT_DIGEST_INVALID")

    staging: Path | None = None
    try:
        try:
            staging = Path(tempfile.mkdtemp(prefix=".catalog-prepared-", dir=str(destination.parent)))
        except (OSError, PermissionError) as exc:
            raise _fail("CATALOG_PREPARED_ARTIFACT_STAGING_UNAVAILABLE") from exc
        _extract_archive(raw, staging)
        _deadline_checkpoint()
        try:
            receipt, manifest = verify_prepared_catalog_bundle(
                bundle_dir=staging,
                expected_identity=expected_identity,
            )
        except Exception as exc:
            raise _fail("CATALOG_PREPARED_ARTIFACT_BUNDLE_INVALID") from exc
        _deadline_checkpoint()
        second = _read_source_snapshot(client, expected_identity)
        if (
            second.snapshot_sha256 != first.snapshot_sha256
            or second.run_id != first.run_id
            or second.run_attempt != first.run_attempt
            or second.artifact_id != first.artifact_id
            or second.artifact_digest != first.artifact_digest
        ):
            raise _fail("CATALOG_PREPARED_ARTIFACT_REMOTE_MUTATED")
        if destination.exists() or destination.is_symlink():
            raise _fail("CATALOG_PREPARED_ARTIFACT_DESTINATION_EXISTS")
        try:
            # Keep the verified staging tree on the same filesystem and use a
            # no-replace rename on Linux; os.replace is never appropriate.
            _rename_without_overwrite(staging, destination)
        except FileExistsError as exc:
            raise _fail("CATALOG_PREPARED_ARTIFACT_DESTINATION_EXISTS") from exc
        except OSError as exc:
            raise _fail("CATALOG_PREPARED_ARTIFACT_PUBLISH_FAILED") from exc
        staging = None
        return PreparedArtifactRestoreResult(
            receipt=receipt,
            manifest=manifest,
            artifact_id=first.artifact_id,
            run_id=first.run_id,
            run_attempt=first.run_attempt,
            digest=first.artifact_digest,
            source_commit=receipt.identity.protected_commit_sha,
            campaign_key=receipt.identity.campaign_key,
            preparation_key_sha256=receipt.identity.preparation_key_sha256,
        )
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


__all__ = [
    "MAX_ARCHIVE_BYTES",
    "PreparedArtifactRestoreError",
    "PreparedArtifactRestoreResult",
    "restore_prepared_artifact",
]
