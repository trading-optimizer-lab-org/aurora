#!/usr/bin/env python3
"""Capture one complete GET-only GitHub snapshot for cheap catalog routing."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import quote
import zipfile

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityRecordV1,
    extract_authority_comment_records,
)
from aurora.infra.sp500_megarun.catalog_comment_tamper import (
    AUTHORITY_TAMPER_MARKER,
    parse_catalog_comment_tamper_incident,
)
from aurora.infra.sp500_megarun.catalog_controller import CatalogProtectedHeadEvidenceV1
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes
from aurora.infra.sp500_megarun.catalog_request_receipt import (
    CatalogRequestReceiptV1,
    next_request_receipt_sequence,
    parse_request_receipt_comment,
    request_receipt_artifact_name,
)
from aurora.infra.sp500_megarun.catalog_routing_snapshot import (
    CatalogRoutingBundleV1,
    build_catalog_routing_bundle,
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ACTIVE_STATES = frozenset(
    {
        AuthorityState.RESERVED,
        AuthorityState.RUNNING,
        AuthorityState.RECOVERING,
        AuthorityState.WAITING_RETRY,
    }
)
_ALLOWED_STATES_BY_JOB: dict[str, tuple[str, ...]] = {
    "reserve": ("reserved", "recovering"),
    "record_running": ("running",),
    "record_nonterminal_wait": ("recovering", "waiting_retry", "blocked"),
    "finalize": ("recovering", "waiting_retry", "success", "failed", "blocked"),
    "issue_tamper_guard": ("blocked",),
    "report_nonexecuting_decision": ("blocked",),
}
_ALLOWED_WORKFLOW_PATHS = frozenset(
    {
        ".github/workflows/catalog-run-controller.yml",
        ".github/workflows/catalog-request-reconciler.yml",
        ".github/workflows/catalog-run-watchdog.yml",
    }
)
_MAX_MIRROR_ZIP_BYTES = 4 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture one stable, GET-only catalog routing snapshot."
    )
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser


def _strict_repository_file(root: Path, relative: str) -> Path:
    path = root.joinpath(*relative.split("/"))
    if path.is_symlink():
        raise ValueError("CATALOG_ROUTING_REPOSITORY_SYMLINK_FORBIDDEN")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("CATALOG_ROUTING_REPOSITORY_INPUT_INVALID")
    return resolved


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_ROUTING_REPOSITORY_JSON_INVALID")
    return payload


def _repository_identity_snapshot(
    *,
    client: CatalogGitHubReadOnlyClient,
    repository: str,
    variable_name: str,
) -> tuple[Mapping[str, Any], dict[str, str], Mapping[str, Any]]:
    repository_raw, _ = client.get_json(f"/repos/{repository}")
    if variable_name != "CATALOG_AUTHORITY_ISSUE_NUMBER":
        raise ValueError("CATALOG_ROUTING_GITHUB_SNAPSHOT_INVALID")
    variable_value = os.environ.get(variable_name, "")
    try:
        parsed_variable = int(variable_value)
    except ValueError:
        raise ValueError("CATALOG_ROUTING_GITHUB_SNAPSHOT_INVALID") from None
    if parsed_variable < 1 or variable_value != str(parsed_variable):
        raise ValueError("CATALOG_ROUTING_GITHUB_SNAPSHOT_INVALID")
    ref_raw, _ = client.get_json(f"/repos/{repository}/git/ref/heads/main")
    return (
        repository_raw,
        {
            "name": variable_name,
            "source": "github_actions_vars_context",
            "value": variable_value,
        },
        ref_raw,
    )


def _canonical_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _normalize_timeline(
    *, issue: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> dict[str, object]:
    normalized: list[dict[str, object]] = []
    for raw in events:
        event_id = raw.get("id")
        event_name = raw.get("event")
        if not isinstance(event_id, int) or not isinstance(event_name, str):
            raise ValueError("CATALOG_ROUTING_TIMELINE_INVALID")
        actor = raw.get("actor")
        actor_login = actor.get("login") if isinstance(actor, Mapping) else None
        label = raw.get("label")
        label_name = label.get("name") if isinstance(label, Mapping) else None
        normalized.append(
            {
                "id": event_id,
                "event": event_name,
                "actor": actor_login,
                "label": label_name,
                "created_at": raw.get("created_at"),
            }
        )
    labels = issue.get("labels", ())
    if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
        raise ValueError("CATALOG_ROUTING_TIMELINE_INVALID")
    current_labels = []
    for raw in labels:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str):
            raise ValueError("CATALOG_ROUTING_TIMELINE_INVALID")
        current_labels.append(str(raw["name"]))
    return {
        "complete": True,
        "pagination_complete": True,
        "stable": True,
        "historical_events": normalized,
        "current_state": issue.get("state"),
        "current_state_reason": issue.get("state_reason"),
        "current_labels": sorted(current_labels),
    }


def _writer_snapshot(
    *,
    client: CatalogGitHubReadOnlyClient,
    repository: str,
    run_id: int,
    records: Sequence[CatalogAuthorityRecordV1],
) -> tuple[dict[str, object], Mapping[str, Any]]:
    run_raw, run_response = client.get_json(
        f"/repos/{repository}/actions/runs/{run_id}"
    )
    if not isinstance(run_raw, dict):
        raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
    jobs = client.stable_paginated(
        f"/repos/{repository}/actions/runs/{run_id}/jobs",
        root="jobs",
    ).collection
    normalized_jobs: list[dict[str, object]] = []
    for record in sorted(
        records,
        key=lambda item: (item.writer_job_database_id, item.writer_job_id),
    ):
        job_id = record.writer_job_id
        matching = [
            row
            for row in jobs.rows
            if row.get("id") == record.writer_job_database_id
            and (
                row.get("name") == job_id
                or (
                    isinstance(row.get("name"), str)
                    and str(row["name"]).endswith(f" / {job_id}")
                )
            )
        ]
        if len(matching) != 1:
            raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
        job = matching[0]
        database_id = job.get("id")
        if database_id != record.writer_job_database_id:
            raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
        allowed_states = _ALLOWED_STATES_BY_JOB.get(job_id)
        if allowed_states is None:
            raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
        normalized_jobs.append(
            {
                "job_id": job_id,
                "database_id": database_id,
                "issues_write": True,
                "steps_are_allowlisted": True,
                "allowed_states": list(allowed_states),
            }
        )
    repository_payload = run_raw.get("repository")
    repository_name = (
        repository_payload.get("full_name")
        if isinstance(repository_payload, Mapping)
        else repository
    )
    path = run_raw.get("path")
    if path not in _ALLOWED_WORKFLOW_PATHS:
        raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
    etag = "|".join(
        filter(
            None,
            [
                str(run_response.headers.get("ETag") or run_response.headers.get("etag") or ""),
                jobs.collection_sha256,
            ],
        )
    )
    if not etag:
        raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
    snapshot = {
        "run_id": run_id,
        "run_attempt": run_raw.get("run_attempt"),
        "head_sha": run_raw.get("head_sha"),
        "workflow_path": path,
        "event": run_raw.get("event"),
        "repository": repository_name,
        "complete": True,
        "pagination_complete": True,
        "stable": True,
        "authenticated": True,
        "etag": etag,
        "workflow_policy_verified": True,
        "jobs": normalized_jobs,
    }
    return snapshot, run_raw


def _request_receipt_writer_snapshot(
    *,
    client: CatalogGitHubReadOnlyClient,
    repository: str,
    run_id: int,
    receipts: Sequence[CatalogRequestReceiptV1],
) -> dict[str, object]:
    run_raw, run_response = client.get_json(
        f"/repos/{repository}/actions/runs/{run_id}"
    )
    if not isinstance(run_raw, dict):
        raise ValueError("CATALOG_REQUEST_RECEIPT_PROVENANCE_INVALID")
    jobs = client.stable_paginated(
        f"/repos/{repository}/actions/runs/{run_id}/jobs",
        root="jobs",
    ).collection
    normalized_jobs: list[dict[str, object]] = []
    seen_jobs: set[tuple[str, int]] = set()
    for receipt in sorted(
        receipts,
        key=lambda item: (item.writer_job_database_id, item.receipt_sha256),
    ):
        key = (receipt.writer_job_id, receipt.writer_job_database_id)
        if key in seen_jobs:
            continue
        seen_jobs.add(key)
        matching = [
            row
            for row in jobs.rows
            if row.get("id") == receipt.writer_job_database_id
            and (
                row.get("name") == receipt.writer_job_id
                or (
                    isinstance(row.get("name"), str)
                    and str(row["name"]).endswith(
                        f" / {receipt.writer_job_id}"
                    )
                )
            )
        ]
        if len(matching) != 1:
            raise ValueError("CATALOG_REQUEST_RECEIPT_PROVENANCE_INVALID")
        normalized_jobs.append(
            {
                "job_id": receipt.writer_job_id,
                "database_id": receipt.writer_job_database_id,
                "issues_write": True,
                "steps_are_allowlisted": True,
                "request_receipt_write": True,
            }
        )
    repository_payload = run_raw.get("repository")
    repository_name = (
        repository_payload.get("full_name")
        if isinstance(repository_payload, Mapping)
        else repository
    )
    path = run_raw.get("path")
    if path not in _ALLOWED_WORKFLOW_PATHS:
        raise ValueError("CATALOG_REQUEST_RECEIPT_PROVENANCE_INVALID")
    etag = "|".join(
        filter(
            None,
            [
                str(
                    run_response.headers.get("ETag")
                    or run_response.headers.get("etag")
                    or ""
                ),
                jobs.collection_sha256,
            ],
        )
    )
    if not etag:
        raise ValueError("CATALOG_REQUEST_RECEIPT_PROVENANCE_INVALID")
    return {
        "run_id": run_id,
        "run_attempt": run_raw.get("run_attempt"),
        "head_sha": run_raw.get("head_sha"),
        "workflow_path": path,
        "event": run_raw.get("event"),
        "repository": repository_name,
        "complete": True,
        "pagination_complete": True,
        "stable": True,
        "authenticated": True,
        "etag": etag,
        "workflow_policy_verified": True,
        "jobs": normalized_jobs,
    }


def _download_artifact_zip(repository: str, artifact_id: int) -> bytes:
    if not _REPOSITORY.fullmatch(repository) or artifact_id < 1:
        raise ValueError("CATALOG_LEDGER_MIRROR_ARTIFACT_INVALID")
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repository}/actions/artifacts/{artifact_id}/zip",
        ],
        check=False,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0 or not result.stdout:
        raise ValueError("CATALOG_LEDGER_MIRROR_ARTIFACT_UNAVAILABLE")
    if len(result.stdout) > _MAX_MIRROR_ZIP_BYTES:
        raise ValueError("CATALOG_LEDGER_MIRROR_ARTIFACT_TOO_LARGE")
    return result.stdout


def _record_from_mirror_zip(data: bytes) -> CatalogAuthorityRecordV1:
    if len(data) > _MAX_MIRROR_ZIP_BYTES:
        raise ValueError("CATALOG_LEDGER_MIRROR_ARTIFACT_TOO_LARGE")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if len(files) != 1 or files[0].filename != "record.json":
                raise ValueError
            info = files[0]
            if (
                info.file_size > 128 * 1024
                or info.compress_size < 1
                or info.file_size > info.compress_size * 100
                or ".." in Path(info.filename).parts
            ):
                raise ValueError
            raw = archive.read(info)

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            payload: dict[str, object] = {}
            for key, value in pairs:
                if key in payload:
                    raise ValueError
                payload[key] = value
            return payload

        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        record = CatalogAuthorityRecordV1.model_validate(payload)
        canonical = canonical_model_bytes(record)
        if raw not in (canonical, canonical + b"\n"):
            raise ValueError
        return record
    except Exception:
        raise ValueError("CATALOG_LEDGER_MIRROR_ARTIFACT_INVALID") from None


def _request_receipt_bundle_from_mirror_zip(
    data: bytes,
) -> tuple[CatalogRequestReceiptV1, str | None]:
    if len(data) > _MAX_MIRROR_ZIP_BYTES:
        raise ValueError("CATALOG_REQUEST_RECEIPT_MIRROR_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            names = {item.filename for item in files}
            if names not in (
                {"request-receipt.json"},
                {"request-receipt.json", "comment.md"},
            ):
                raise ValueError
            for info in files:
                if (
                    info.file_size > 128 * 1024
                    or info.compress_size < 1
                    or info.file_size > info.compress_size * 100
                    or ".." in Path(info.filename).parts
                ):
                    raise ValueError
            raw = archive.read("request-receipt.json")
            comment_raw = (
                archive.read("comment.md") if "comment.md" in names else None
            )
        receipt = CatalogRequestReceiptV1.model_validate_json(raw)
        canonical = canonical_model_bytes(receipt)
        if raw not in (canonical, canonical + b"\n"):
            raise ValueError
        comment = None
        if comment_raw is not None:
            comment = comment_raw.decode("utf-8")
            marker = (
                "\n\n<!-- AURORA_CATALOG_REQUEST_RECEIPT_V1 -->\n```json\n"
            )
            if comment.count(marker) != 1 or not comment.endswith("\n```\n"):
                raise ValueError
            summary = comment.split(marker, 1)[0]
            if comment != receipt.comment_body(summary):
                raise ValueError
        return receipt, comment
    except Exception:
        raise ValueError("CATALOG_REQUEST_RECEIPT_MIRROR_INVALID") from None


def _request_receipt_from_mirror_zip(data: bytes) -> CatalogRequestReceiptV1:
    return _request_receipt_bundle_from_mirror_zip(data)[0]


def _artifact_record(
    *,
    client: CatalogGitHubReadOnlyClient,
    repository: str,
    record: CatalogAuthorityRecordV1,
) -> CatalogAuthorityRecordV1:
    name = record.artifact_name
    artifacts = client.stable_paginated(
        f"/repos/{repository}/actions/artifacts?name={quote(name, safe='')}",
        root="artifacts",
    ).collection.rows
    matching = [
        item
        for item in artifacts
        if item.get("name") == name and item.get("expired") is False
    ]
    if len(matching) != 1:
        raise ValueError("CATALOG_LEDGER_MIRROR_COVERAGE_INVALID")
    artifact_id = matching[0].get("id")
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
        raise ValueError("CATALOG_LEDGER_MIRROR_ARTIFACT_INVALID")
    mirrored = _record_from_mirror_zip(_download_artifact_zip(repository, artifact_id))
    if canonical_model_bytes(mirrored) != canonical_model_bytes(record):
        raise ValueError("CATALOG_LEDGER_MIRROR_CONFLICT")
    return mirrored


def _request_receipt_artifact(
    *,
    client: CatalogGitHubReadOnlyClient,
    repository: str,
    receipt: CatalogRequestReceiptV1,
) -> CatalogRequestReceiptV1:
    name = receipt.artifact_name
    artifacts = client.stable_paginated(
        f"/repos/{repository}/actions/artifacts?name={quote(name, safe='')}",
        root="artifacts",
    ).collection.rows
    matching = [
        item
        for item in artifacts
        if item.get("name") == name and item.get("expired") is False
    ]
    if len(matching) != 1:
        raise ValueError("CATALOG_REQUEST_RECEIPT_MIRROR_COVERAGE_INVALID")
    artifact_id = matching[0].get("id")
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
        raise ValueError("CATALOG_REQUEST_RECEIPT_MIRROR_INVALID")
    mirrored = _request_receipt_from_mirror_zip(
        _download_artifact_zip(repository, artifact_id)
    )
    if canonical_model_bytes(mirrored) != canonical_model_bytes(receipt):
        raise ValueError("CATALOG_REQUEST_RECEIPT_MIRROR_CONFLICT")
    return mirrored


def _request_receipt_orphan_from_slot(
    *,
    repository: str,
    artifact_name: str,
    artifacts: Sequence[Mapping[str, object]],
    issue_number: int,
    request_sha256: str,
    delivery_sequence: int,
) -> tuple[
    CatalogRequestReceiptV1 | None,
    str | None,
    dict[str, object] | None,
]:
    if any(row.get("name") != artifact_name for row in artifacts):
        raise ValueError("CATALOG_REQUEST_RECEIPT_MIRROR_CONFLICT")
    live = [row for row in artifacts if row.get("expired") is False]
    if len(live) > 1:
        raise ValueError("CATALOG_REQUEST_RECEIPT_MIRROR_CONFLICT")
    if not live:
        return None, None, None
    artifact_id = live[0].get("id")
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
        raise ValueError("CATALOG_REQUEST_RECEIPT_ORPHAN_INVALID")
    receipt, comment = _request_receipt_bundle_from_mirror_zip(
        _download_artifact_zip(repository, artifact_id)
    )
    if (
        comment is None
        or receipt.issue_number != issue_number
        or receipt.request_sha256 != request_sha256
        or receipt.delivery_sequence != delivery_sequence
        or receipt.artifact_name != artifact_name
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_ORPHAN_INVALID")
    metadata = {
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "receipt_sha256": receipt.receipt_sha256,
        "comment_sha256": hashlib.sha256(comment.encode("utf-8")).hexdigest(),
        "delivery_sequence": delivery_sequence,
    }
    return receipt, comment, metadata


def _extract_tamper_incidents(
    comments: Sequence[Mapping[str, Any]],
    *,
    authority_issue_number: int,
) -> tuple[dict[str, object], ...]:
    incidents: list[dict[str, object]] = []
    for comment in comments:
        body = comment.get("body")
        if not isinstance(body, str) or AUTHORITY_TAMPER_MARKER not in body:
            continue
        try:
            incident = parse_catalog_comment_tamper_incident(
                comment,
                expected_issue_number=authority_issue_number,
                expected_marker=AUTHORITY_TAMPER_MARKER,
            )
        except ValueError:
            raise ValueError("CATALOG_LEDGER_TAMPER_INCIDENT") from None
        if incident is not None:
            incidents.append(
                {
                    "verified": True,
                    "action": incident.event_action,
                    "incident_sha256": incident.incident_sha256,
                    "artifact_name": incident.artifact_name,
                }
            )
    return tuple(incidents)


def _write_bundle(
    *,
    output_dir: Path,
    bundle: CatalogRoutingBundleV1,
    github_output: Path | None,
    orphan_request_receipt: CatalogRequestReceiptV1 | None = None,
    orphan_request_comment: str | None = None,
    orphan_artifact_metadata: Mapping[str, object] | None = None,
) -> None:
    orphan_values = (
        orphan_request_receipt,
        orphan_request_comment,
        orphan_artifact_metadata,
    )
    if any(value is not None for value in orphan_values) and any(
        value is None for value in orphan_values
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_ORPHAN_INVALID")
    if orphan_request_receipt is not None:
        assert orphan_request_comment is not None
        assert orphan_artifact_metadata is not None
        marker = "\n\n<!-- AURORA_CATALOG_REQUEST_RECEIPT_V1 -->\n```json\n"
        if (
            orphan_request_comment.count(marker) != 1
            or not orphan_request_comment.endswith("\n```\n")
        ):
            raise ValueError("CATALOG_REQUEST_RECEIPT_ORPHAN_INVALID")
        summary = orphan_request_comment.split(marker, 1)[0]
        expected_metadata = {
            "artifact_id": orphan_artifact_metadata.get("artifact_id"),
            "artifact_name": orphan_request_receipt.artifact_name,
            "receipt_sha256": orphan_request_receipt.receipt_sha256,
            "comment_sha256": hashlib.sha256(
                orphan_request_comment.encode("utf-8")
            ).hexdigest(),
            "delivery_sequence": orphan_request_receipt.delivery_sequence,
        }
        artifact_id = expected_metadata["artifact_id"]
        if (
            isinstance(artifact_id, bool)
            or not isinstance(artifact_id, int)
            or artifact_id < 1
            or dict(orphan_artifact_metadata) != expected_metadata
            or orphan_request_receipt.issue_number
            != bundle.command.request_issue_number
            or orphan_request_receipt.request_sha256
            != bundle.command.request_sha256
            or orphan_request_receipt.delivery_sequence
            != bundle.request_receipts_document.get("next_delivery_sequence")
            or orphan_request_comment
            != orphan_request_receipt.comment_body(summary)
        ):
            raise ValueError("CATALOG_REQUEST_RECEIPT_ORPHAN_INVALID")
    output_dir.mkdir(parents=False, exist_ok=False)
    documents = {
        "routing-command.json": bundle.command,
        "event.json": bundle.event_document,
        "authority-issue.json": bundle.authority_issue_document,
        "authority-comments.json": bundle.authority_comments_document,
        "request-timeline.json": bundle.request_timeline_document,
        "request-receipts.json": bundle.request_receipts_document,
        "request-queue.json": bundle.request_queue_document,
        "protected-head.json": bundle.protected_head_document,
        "routing-snapshot.json": bundle.snapshot_manifest,
    }
    for name, value in documents.items():
        (output_dir / name).write_bytes(_canonical_bytes(value) + b"\n")
    if orphan_request_receipt is not None:
        assert orphan_request_comment is not None
        assert orphan_artifact_metadata is not None
        (output_dir / "request-receipt-orphan.json").write_bytes(
            canonical_model_bytes(orphan_request_receipt) + b"\n"
        )
        (output_dir / "request-receipt-orphan-comment.md").write_text(
            orphan_request_comment,
            encoding="utf-8",
            newline="\n",
        )
        (output_dir / "request-receipt-orphan-artifact.json").write_bytes(
            _canonical_bytes(orphan_artifact_metadata) + b"\n"
        )
    if github_output is not None:
        if github_output.is_symlink():
            raise ValueError("CATALOG_ROUTING_GITHUB_OUTPUT_INVALID")
        head = CatalogProtectedHeadEvidenceV1.model_validate(
            bundle.protected_head_document
        )
        values = {
            "snapshot_sha256": bundle.command.prerequisites.routing_snapshot_sha256,
            "request_sha256": bundle.command.request_sha256,
            "campaign_id": bundle.command.campaign_id,
            "applicable_commit_sha": head.applicable_commit_sha,
            "request_receipt_orphan": str(
                orphan_request_receipt is not None
            ).lower(),
        }
        with github_output.open("a", encoding="utf-8", newline="\n") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")


def capture(
    *,
    issue_number: int,
    repo_root: Path,
    output_dir: Path,
    github_output: Path | None,
) -> CatalogRoutingBundleV1:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    expected_commit = os.environ.get("GITHUB_SHA", "")
    if issue_number < 1 or not _REPOSITORY.fullmatch(repository):
        raise ValueError("CATALOG_ROUTING_INVOCATION_INVALID")
    if not _COMMIT.fullmatch(expected_commit):
        raise ValueError("CATALOG_ROUTING_INVOCATION_INVALID")
    root = repo_root.resolve(strict=True)
    runner_temp_value = os.environ.get("RUNNER_TEMP")
    if not runner_temp_value:
        raise ValueError("CATALOG_ROUTING_RUNNER_TEMP_REQUIRED")
    runner_temp = Path(runner_temp_value).resolve(strict=True)
    resolved_output = output_dir.resolve(strict=False)
    if output_dir.exists() or output_dir.is_symlink() or not resolved_output.is_relative_to(
        runner_temp
    ):
        raise ValueError("CATALOG_ROUTING_OUTPUT_INVALID")

    client = CatalogGitHubReadOnlyClient(repository, token)
    actors = _read_json(
        _strict_repository_file(root, "config/catalog_controller_actors_v1.json")
    )
    anchor = _read_json(
        _strict_repository_file(root, "config/catalog_authority_anchor_v1.json")
    )
    actor_names = actors.get("request_actors")
    authority_number = anchor.get("issue_number")
    variable_name = actors.get("authority_issue_repository_variable")
    if (
        not isinstance(actor_names, list)
        or not actor_names
        or isinstance(authority_number, bool)
        or not isinstance(authority_number, int)
        or authority_number < 1
        or variable_name != "CATALOG_AUTHORITY_ISSUE_NUMBER"
    ):
        raise ValueError("CATALOG_ROUTING_CONFIGURATION_INVALID")

    repository_raw, variable_raw, ref_raw = _repository_identity_snapshot(
        client=client,
        repository=repository,
        variable_name=variable_name,
    )
    if not isinstance(repository_raw, dict) or not isinstance(variable_raw, dict):
        raise ValueError("CATALOG_ROUTING_GITHUB_SNAPSHOT_INVALID")
    if not isinstance(ref_raw, dict) or not isinstance(ref_raw.get("object"), dict):
        raise ValueError("CATALOG_ROUTING_GITHUB_SNAPSHOT_INVALID")
    protected_head_sha = ref_raw["object"].get("sha")
    if not isinstance(protected_head_sha, str):
        raise ValueError("CATALOG_ROUTING_GITHUB_SNAPSHOT_INVALID")

    request_comments = client.stable_issue_collection(
        issue_path=f"/repos/{repository}/issues/{issue_number}",
        collection_path=f"/repos/{repository}/issues/{issue_number}/comments",
        root="list",
        count_field="comments",
    )
    request_timeline_raw = client.stable_issue_collection(
        issue_path=f"/repos/{repository}/issues/{issue_number}",
        collection_path=f"/repos/{repository}/issues/{issue_number}/timeline",
        root="list",
    )
    authority_comments_snapshot = client.stable_issue_collection(
        issue_path=f"/repos/{repository}/issues/{authority_number}",
        collection_path=f"/repos/{repository}/issues/{authority_number}/comments",
        root="list",
        count_field="comments",
    )
    authority_timeline_raw = client.stable_issue_collection(
        issue_path=f"/repos/{repository}/issues/{authority_number}",
        collection_path=f"/repos/{repository}/issues/{authority_number}/timeline",
        root="list",
    )
    queue_snapshot = client.stable_paginated(
        f"/repos/{repository}/issues?state=open&sort=created&direction=asc",
        root="list",
    )

    comments = authority_comments_snapshot.collection.rows
    records = extract_authority_comment_records(
        comments,
        expected_author="github-actions[bot]",
    )
    records_by_run: dict[int, list[CatalogAuthorityRecordV1]] = {}
    for record in records:
        records_by_run.setdefault(record.run_id, []).append(record)
    writer_snapshots: list[dict[str, object]] = []
    writer_runs: dict[int, Mapping[str, Any]] = {}
    for run_id, run_records in sorted(records_by_run.items()):
        snapshot, raw_run = _writer_snapshot(
            client=client,
            repository=repository,
            run_id=run_id,
            records=run_records,
        )
        writer_snapshots.append(snapshot)
        writer_runs[run_id] = raw_run
    artifact_records = tuple(
        _artifact_record(client=client, repository=repository, record=record)
        for record in records
    )
    trusted_request_receipts: dict[str, CatalogRequestReceiptV1] = {}
    for comment in request_comments.collection.rows:
        try:
            receipt = parse_request_receipt_comment(
                comment,
                expected_author="github-actions[bot]",
            )
        except ValueError:
            continue
        if receipt is not None:
            trusted_request_receipts.setdefault(receipt.receipt_sha256, receipt)
    receipts_by_run: dict[int, list[CatalogRequestReceiptV1]] = {}
    for receipt in trusted_request_receipts.values():
        receipts_by_run.setdefault(receipt.writer_run_id, []).append(receipt)
    request_receipt_writer_snapshot_list: list[dict[str, object]] = []
    for run_id, run_receipts in sorted(receipts_by_run.items()):
        try:
            request_receipt_writer_snapshot_list.append(
                _request_receipt_writer_snapshot(
                    client=client,
                    repository=repository,
                    run_id=run_id,
                    receipts=run_receipts,
                )
            )
        except ValueError:
            continue
    request_receipt_writer_snapshots = tuple(
        request_receipt_writer_snapshot_list
    )
    request_receipt_artifact_list: list[CatalogRequestReceiptV1] = []
    for receipt in sorted(
        trusted_request_receipts.values(),
        key=lambda item: item.receipt_sha256,
    ):
        try:
            request_receipt_artifact_list.append(
                _request_receipt_artifact(
                    client=client,
                    repository=repository,
                    receipt=receipt,
                )
            )
        except ValueError:
            continue
    request_receipt_artifacts = tuple(request_receipt_artifact_list)
    latest_by_authority: dict[object, CatalogAuthorityRecordV1] = {}
    for record in records:
        latest_by_authority[record.authority_id] = record
    active_owners = tuple(
        record.authority_id
        for record in latest_by_authority.values()
        if record.state in _ACTIVE_STATES
        and writer_runs.get(record.run_id, {}).get("status") != "completed"
    )
    request_timeline = _normalize_timeline(
        issue=request_timeline_raw.issue,
        events=request_timeline_raw.collection.rows,
    )
    authority_timeline = _normalize_timeline(
        issue=authority_timeline_raw.issue,
        events=authority_timeline_raw.collection.rows,
    )
    source_identity = {
        "repository": repository,
        "repository_id": repository_raw.get("id"),
        "repository_variable_sha256": _sha256(variable_raw),
        "protected_head_sha": protected_head_sha,
        "request_comments": request_comments.snapshot_sha256,
        "request_timeline": request_timeline_raw.snapshot_sha256,
        "authority_comments": authority_comments_snapshot.snapshot_sha256,
        "authority_timeline": authority_timeline_raw.snapshot_sha256,
        "queue": queue_snapshot.snapshot_sha256,
        "writer_snapshot_sha256s": [_sha256(item) for item in writer_snapshots],
        "artifact_record_sha256s": [item.record_sha256 for item in artifact_records],
        "request_receipt_writer_snapshot_sha256s": [
            _sha256(item) for item in request_receipt_writer_snapshots
        ],
        "request_receipt_artifact_sha256s": [
            item.receipt_sha256 for item in request_receipt_artifacts
        ],
    }
    if client.observed_at is None:
        raise ValueError("CATALOG_ROUTING_GITHUB_TIME_INVALID")
    bundle_arguments = dict(
        repo_root=root,
        repository_snapshot=repository_raw,
        repository_variable_number=variable_raw.get("value"),
        protected_head_sha=protected_head_sha,
        expected_protected_commit_sha=expected_commit,
        request_issue=request_comments.issue,
        open_issues=queue_snapshot.collection.rows,
        request_comments=request_comments.collection.rows,
        request_timeline=request_timeline,
        authority_issue=authority_comments_snapshot.issue,
        authority_comments=comments,
        authority_timeline=authority_timeline,
        writer_run_snapshots=writer_snapshots,
        artifact_records=artifact_records,
        checkpoints=(),
        tamper_incidents=_extract_tamper_incidents(
            comments,
            authority_issue_number=authority_number,
        ),
        active_owner_authority_ids=active_owners,
        observed_at=client.observed_at.astimezone(UTC),
        snapshot_source_sha256=_sha256(source_identity),
        request_receipt_writer_snapshots=request_receipt_writer_snapshots,
        request_receipt_artifacts=request_receipt_artifacts,
    )
    provisional = build_catalog_routing_bundle(**bundle_arguments)
    next_receipt_sequence = next_request_receipt_sequence(
        tuple(trusted_request_receipts.values()),
        issue_number=issue_number,
        request_sha256=provisional.command.request_sha256,
    )
    next_receipt_artifact_name = request_receipt_artifact_name(
        issue_number=issue_number,
        sequence=next_receipt_sequence,
    )
    next_receipt_artifacts = client.stable_paginated(
        "/repos/"
        f"{repository}/actions/artifacts?name="
        f"{quote(next_receipt_artifact_name, safe='')}",
        root="artifacts",
    ).collection.rows
    (
        orphan_request_receipt,
        orphan_request_comment,
        orphan_artifact_metadata,
    ) = _request_receipt_orphan_from_slot(
        repository=repository,
        artifact_name=next_receipt_artifact_name,
        artifacts=next_receipt_artifacts,
        issue_number=issue_number,
        request_sha256=provisional.command.request_sha256,
        delivery_sequence=next_receipt_sequence,
    )
    if orphan_request_receipt is not None:
        assert orphan_artifact_metadata is not None
        source_identity["request_receipt_orphan"] = orphan_artifact_metadata
    provisional_head = CatalogProtectedHeadEvidenceV1.model_validate(
        provisional.protected_head_document
    )
    applicable_commit = provisional_head.applicable_commit_sha
    reachable: tuple[str, ...] = ()
    compare_receipt: dict[str, object] = {
        "required": applicable_commit != protected_head_sha,
        "base_sha": applicable_commit,
        "head_sha": protected_head_sha,
        "reachable": applicable_commit == protected_head_sha,
    }
    if applicable_commit != protected_head_sha:
        compare_raw, compare_response = client.get_json(
            f"/repos/{repository}/compare/{applicable_commit}...{protected_head_sha}"
        )
        if not isinstance(compare_raw, Mapping):
            raise ValueError("CATALOG_BOUND_COMMIT_REACHABILITY_INVALID")
        merge_base = compare_raw.get("merge_base_commit")
        base_commit = compare_raw.get("base_commit")
        status = compare_raw.get("status")
        is_reachable = (
            status in {"ahead", "identical"}
            and isinstance(merge_base, Mapping)
            and merge_base.get("sha") == applicable_commit
            and isinstance(base_commit, Mapping)
            and base_commit.get("sha") == applicable_commit
        )
        if is_reachable:
            reachable = (applicable_commit,)
        compare_receipt = {
            **compare_receipt,
            "status": status,
            "merge_base_sha": (
                merge_base.get("sha") if isinstance(merge_base, Mapping) else None
            ),
            "base_commit_sha": (
                base_commit.get("sha") if isinstance(base_commit, Mapping) else None
            ),
            "reachable": is_reachable,
            "etag": str(
                compare_response.headers.get("ETag")
                or compare_response.headers.get("etag")
                or ""
            ),
        }
    source_identity["protected_commit_compare"] = compare_receipt
    bundle_arguments["snapshot_source_sha256"] = _sha256(source_identity)
    bundle_arguments["reachable_protected_commits"] = reachable
    bundle = build_catalog_routing_bundle(**bundle_arguments)
    _write_bundle(
        output_dir=output_dir,
        bundle=bundle,
        github_output=github_output,
        orphan_request_receipt=orphan_request_receipt,
        orphan_request_comment=orphan_request_comment,
        orphan_artifact_metadata=orphan_artifact_metadata,
    )
    return bundle


def main() -> int:
    args = _parser().parse_args()
    try:
        capture(
            issue_number=args.issue_number,
            repo_root=args.repo_root,
            output_dir=args.output_dir,
            github_output=args.github_output,
        )
        return 0
    except (CatalogGitHubSnapshotError, ValueError, TypeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
