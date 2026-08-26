#!/usr/bin/env python3
"""Reconcile one deterministic mirror-first delivery slot via fixed GitHub GETs."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile
import io

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    CatalogAuthorityRecordV1,
    extract_authority_comment_records,
)
from aurora.infra.sp500_megarun.catalog_mirror_delivery import (
    CatalogMirrorArtifactV1,
    CatalogMirrorCurrentRepairWriterContextV1,
    CatalogMirrorRepairClaimV1,
    CatalogMirrorRepairWriterContextV1,
    CatalogMirrorWriterEvidenceV1,
    catalog_mirror_repair_claim_artifact_name,
    decide_authority_mirror_delivery,
    decide_request_receipt_mirror_delivery,
    prepare_catalog_mirror_repair_claim,
)
from aurora.infra.sp500_megarun.catalog_request_receipt import (
    REQUEST_RECEIPT_MARKER,
    CatalogRequestReceiptV1,
    parse_request_receipt_comment,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,255}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 1024 * 1024
_MAX_SLOT_ARTIFACTS = 2
_MAX_REPAIR_ATTEMPTS = 3
_REPAIR_CLAIM_STEP_NAME = "Claim one mirror-comment repair attempt"
_REQUEST_REPORT_PUBLICATION_STEP_NAME = "Read back, append exactly once"

_STEP_NAMES: dict[tuple[str, str], tuple[str, str]] = {
    ("authority", "reserve"): (
        "Mirror the exact authority record before its comment",
        "Read back the mirror, append the exact comment, and read it back",
    ),
    ("authority", "record_running"): (
        "Mirror RUNNING before appending its exact comment",
        "Read back the mirror and append the exact RUNNING comment",
    ),
    ("authority", "record_nonterminal_wait"): (
        "Mirror WAITING_RETRY before its exact comment",
        "Read back the WAITING_RETRY mirror and append its comment",
    ),
    ("authority", "finalize"): (
        "Mirror the terminal authority record before its comment",
        "Read back the terminal mirror and append its exact authority comment",
    ),
    ("request", "report_nonexecuting_decision"): (
        "Mirror the request receipt first",
        _REQUEST_REPORT_PUBLICATION_STEP_NAME,
    ),
    ("request", "record_nonterminal_wait"): (
        "Mirror WAITING_RETRY request status before posting it",
        "Read back and post the exact nonterminal request status once",
    ),
    ("request", "finalize"): (
        "Mirror the terminal request receipt before its comment",
        "Read back the request mirror, post once, verify, and atomically close",
    ),
    ("request", "repair_request_receipt_orphan"): (
        _REPAIR_CLAIM_STEP_NAME,
        "Append the exact missing comment once",
    ),
}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_MIRROR_JSON_DUPLICATE")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_MIRROR_JSON_NONFINITE:{value}")


def _json_bytes(data: bytes) -> object:
    if not data or len(data) > _MAX_JSON_BYTES:
        raise ValueError("CATALOG_MIRROR_PAYLOAD_SIZE_INVALID")
    try:
        return json.loads(
            data,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("CATALOG_MIRROR_JSON_INVALID") from None


def _read_json(path: Path, *, runner_temp: Path) -> object:
    if path.is_symlink():
        raise ValueError("CATALOG_MIRROR_INPUT_INVALID")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError("CATALOG_MIRROR_INPUT_INVALID") from None
    if not resolved.is_file() or not resolved.is_relative_to(runner_temp):
        raise ValueError("CATALOG_MIRROR_INPUT_INVALID")
    return _json_bytes(resolved.read_bytes())


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("CATALOG_MIRROR_TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("CATALOG_MIRROR_TIMESTAMP_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CATALOG_MIRROR_TIMESTAMP_INVALID")
    return parsed.astimezone(UTC)


def _gh(endpoint: str, *, binary: bool = False) -> bytes:
    if not os.environ.get("GH_TOKEN"):
        raise ValueError("CATALOG_MIRROR_GITHUB_TOKEN_MISSING")
    if not endpoint.startswith(f"repos/{_REPOSITORY}/") or ".." in endpoint:
        raise ValueError("CATALOG_MIRROR_ENDPOINT_INVALID")
    completed = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "GET",
            endpoint,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ValueError("CATALOG_MIRROR_GITHUB_READ_FAILED")
    if not binary and len(completed.stdout) > 10 * _MAX_JSON_BYTES:
        raise ValueError("CATALOG_MIRROR_GITHUB_RESPONSE_TOO_LARGE")
    return completed.stdout


def _gh_json(endpoint: str) -> object:
    return _json_bytes(_gh(endpoint))


def _artifact_rows(name: str) -> tuple[dict[str, object], ...]:
    if not _ARTIFACT_NAME.fullmatch(name):
        raise ValueError("CATALOG_MIRROR_ARTIFACT_NAME_INVALID")

    def snapshot() -> tuple[int, tuple[dict[str, object], ...]]:
        rows: list[dict[str, object]] = []
        expected_total: int | None = None
        for page in range(1, 4):
            payload = _gh_json(
                "repos/"
                f"{_REPOSITORY}/actions/artifacts?name={quote(name, safe='')}"
                f"&per_page=100&page={page}"
            )
            if not isinstance(payload, dict):
                raise ValueError("CATALOG_MIRROR_ARTIFACT_SNAPSHOT_INVALID")
            total = payload.get("total_count")
            page_rows = payload.get("artifacts")
            if (
                isinstance(total, bool)
                or not isinstance(total, int)
                or total < 0
                or not isinstance(page_rows, list)
                or any(not isinstance(row, dict) for row in page_rows)
            ):
                raise ValueError("CATALOG_MIRROR_ARTIFACT_SNAPSHOT_INVALID")
            if expected_total is None:
                expected_total = total
                if total > _MAX_SLOT_ARTIFACTS:
                    raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
            elif total != expected_total:
                raise ValueError("CATALOG_MIRROR_ARTIFACT_SNAPSHOT_UNSTABLE")
            rows.extend(page_rows)
            if len(page_rows) < 100:
                break
        if expected_total is None or len(rows) != expected_total:
            raise ValueError("CATALOG_MIRROR_ARTIFACT_SNAPSHOT_INCOMPLETE")
        ids = [row.get("id") for row in rows]
        if len(set(ids)) != len(ids) or any(row.get("name") != name for row in rows):
            raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
        return expected_total, tuple(rows)

    first = snapshot()
    second = snapshot()
    if first != second:
        raise ValueError("CATALOG_MIRROR_ARTIFACT_SNAPSHOT_UNSTABLE")
    return first[1]


def _artifact_payload(
    *,
    artifact_id: int,
    filename: str,
    kind: Literal["authority", "request"],
) -> tuple[CatalogAuthorityRecordV1 | CatalogRequestReceiptV1, str | None]:
    if artifact_id < 1 or filename not in {"record.json", "request-receipt.json"}:
        raise ValueError("CATALOG_MIRROR_ARTIFACT_INVALID")
    raw_zip = _gh(
        f"repos/{_REPOSITORY}/actions/artifacts/{artifact_id}/zip",
        binary=True,
    )
    try:
        with ZipFile(io.BytesIO(raw_zip)) as archive:
            files = tuple(item for item in archive.infolist() if not item.is_dir())
            names = {item.filename for item in files}
            expected_names = {filename}
            if kind == "request":
                expected_names.add("comment.md")
            if (
                names not in ({filename}, expected_names)
                or any(
                    item.file_size > _MAX_JSON_BYTES
                    or item.compress_size > _MAX_JSON_BYTES
                    or ".." in Path(item.filename).parts
                    for item in files
                )
            ):
                raise ValueError("CATALOG_MIRROR_ARTIFACT_INVALID")
            data = archive.read(filename)
            comment_data = (
                archive.read("comment.md") if "comment.md" in names else None
            )
    except BadZipFile:
        raise ValueError("CATALOG_MIRROR_ARTIFACT_INVALID") from None
    payload = _json_bytes(data)
    model = (
        CatalogAuthorityRecordV1.model_validate(payload)
        if kind == "authority"
        else CatalogRequestReceiptV1.model_validate(payload)
    )
    if data != canonical_model_bytes(model) + b"\n":
        raise ValueError("CATALOG_MIRROR_ARTIFACT_NONCANONICAL")
    comment: str | None = None
    if comment_data is not None:
        try:
            comment = comment_data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("CATALOG_MIRROR_ARTIFACT_NONCANONICAL") from None
        if not isinstance(model, CatalogRequestReceiptV1):
            raise ValueError("CATALOG_MIRROR_ARTIFACT_NONCANONICAL")
        marker = "\n\n<!-- AURORA_CATALOG_REQUEST_RECEIPT_V1 -->\n```json\n"
        if comment.count(marker) != 1 or not comment.endswith("\n```\n"):
            raise ValueError("CATALOG_MIRROR_ARTIFACT_NONCANONICAL")
        summary = comment.split(marker, 1)[0]
        if comment != model.comment_body(summary):
            raise ValueError("CATALOG_MIRROR_ARTIFACT_NONCANONICAL")
    return model, comment


def _repair_claim_payload(
    *,
    artifact_id: int,
    artifact_name: str,
) -> CatalogMirrorRepairClaimV1:
    if artifact_id < 1:
        raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_INVALID")
    raw_zip = _gh(
        f"repos/{_REPOSITORY}/actions/artifacts/{artifact_id}/zip",
        binary=True,
    )
    try:
        with ZipFile(io.BytesIO(raw_zip)) as archive:
            files = tuple(item for item in archive.infolist() if not item.is_dir())
            if (
                len(files) != 1
                or files[0].filename != "repair-claim.json"
                or files[0].file_size > _MAX_JSON_BYTES
                or files[0].compress_size > _MAX_JSON_BYTES
                or ".." in Path(files[0].filename).parts
            ):
                raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_INVALID")
            data = archive.read("repair-claim.json")
    except BadZipFile:
        raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_INVALID") from None
    claim = CatalogMirrorRepairClaimV1.model_validate(_json_bytes(data))
    if (
        data != canonical_model_bytes(claim) + b"\n"
        or claim.artifact_name != artifact_name
    ):
        raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_INVALID")
    return claim


def _steps_conclusion(
    steps: object,
    *,
    expected_name: str,
) -> str | None:
    if not isinstance(steps, list):
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    matching = [
        row
        for row in steps
        if isinstance(row, dict) and row.get("name") == expected_name
    ]
    if len(matching) != 1:
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    value = matching[0].get("conclusion")
    return value if isinstance(value, str) else None


def _completed_run_jobs(run_id: int, run_attempt: int) -> tuple[dict[str, object], ...]:
    def snapshot() -> tuple[dict[str, object], ...]:
        rows: list[dict[str, object]] = []
        expected_total: int | None = None
        for page in range(1, 12):
            payload = _gh_json(
                f"repos/{_REPOSITORY}/actions/runs/{run_id}/attempts/"
                f"{run_attempt}/jobs?filter=all&per_page=100&page={page}"
            )
            if not isinstance(payload, dict) or not isinstance(
                payload.get("jobs"), list
            ):
                raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
            total = payload.get("total_count")
            page_rows = payload["jobs"]
            if (
                isinstance(total, bool)
                or not isinstance(total, int)
                or total < 1
                or any(not isinstance(row, dict) for row in page_rows)
            ):
                raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
            rows.extend(page_rows)
            if len(page_rows) < 100:
                break
        if expected_total is None or len(rows) != expected_total:
            raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
        ids = [row.get("id") for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
        return tuple(rows)

    first = snapshot()
    second = snapshot()
    if first != second:
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    return first


def _writer_evidence(
    payload: CatalogAuthorityRecordV1 | CatalogRequestReceiptV1,
    *,
    kind: Literal["authority", "request"],
) -> CatalogMirrorWriterEvidenceV1:
    run_id = (
        payload.run_id
        if isinstance(payload, CatalogAuthorityRecordV1)
        else payload.writer_run_id
    )
    run_attempt = (
        payload.run_attempt
        if isinstance(payload, CatalogAuthorityRecordV1)
        else payload.writer_run_attempt
    )
    database_id = payload.writer_job_database_id
    job_id = payload.writer_job_id
    names = _STEP_NAMES.get((kind, job_id))
    if names is None:
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    run = _gh_json(f"repos/{_REPOSITORY}/actions/runs/{run_id}")
    run_readback = _gh_json(f"repos/{_REPOSITORY}/actions/runs/{run_id}")
    if not isinstance(run, dict) or run != run_readback:
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    job_rows = _completed_run_jobs(run_id, run_attempt)
    jobs = [
        row
        for row in job_rows
        if row.get("id") == database_id
    ]
    if len(jobs) != 1:
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    job = jobs[0]
    logical_name = job.get("name")
    if not isinstance(logical_name, str) or not (
        logical_name == job_id or logical_name.endswith(f" / {job_id}")
    ):
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    repository = run.get("repository")
    repository_name = (
        repository.get("full_name") if isinstance(repository, dict) else None
    )
    path = run.get("path")
    head_sha = run.get("head_sha")
    if (
        repository_name != _REPOSITORY
        or not isinstance(path, str)
        or not _COMMIT.fullmatch(str(head_sha))
    ):
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    return CatalogMirrorWriterEvidenceV1(
        complete=True,
        stable=True,
        authenticated=True,
        repository=_REPOSITORY,
        workflow_path=path,
        protected_commit_sha=str(head_sha),
        run_id=run_id,
        run_attempt=run_attempt,
        run_status=str(run.get("status", "")),
        writer_job_id=job_id,
        writer_job_database_id=database_id,
        job_status=str(job.get("status", "")),
        upload_step_conclusion=_steps_conclusion(
            job.get("steps"), expected_name=names[0]
        ),
        post_step_conclusion=_steps_conclusion(
            job.get("steps"), expected_name=names[1]
        ),
    )


def _positive_environment_integer(name: str) -> int:
    value = os.environ.get(name, "")
    if not value.isdigit() or int(value) < 1:
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_INVALID")
    return int(value)


def _current_repair_writer(
    *,
    kind: Literal["authority", "request"],
) -> CatalogMirrorCurrentRepairWriterContextV1:
    run_id = _positive_environment_integer("GITHUB_RUN_ID")
    run_attempt = _positive_environment_integer("GITHUB_RUN_ATTEMPT")
    job_id = os.environ.get("GITHUB_JOB", "")
    github_sha = os.environ.get("GITHUB_SHA", "")
    if (
        (kind, job_id) not in _STEP_NAMES
        or job_id == "repair_request_receipt_orphan"
        or not _COMMIT.fullmatch(github_sha)
    ):
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_INVALID")
    run = _gh_json(f"repos/{_REPOSITORY}/actions/runs/{run_id}")
    run_readback = _gh_json(f"repos/{_REPOSITORY}/actions/runs/{run_id}")
    jobs = _completed_run_jobs(run_id, run_attempt)
    matching = [
        row
        for row in jobs
        if isinstance(row.get("name"), str)
        and (
            row.get("name") == job_id
            or str(row.get("name")).endswith(f" / {job_id}")
        )
    ]
    repository = run.get("repository") if isinstance(run, dict) else None
    repository_name = (
        repository.get("full_name") if isinstance(repository, dict) else None
    )
    if (
        not isinstance(run, dict)
        or run != run_readback
        or run.get("id") != run_id
        or run.get("run_attempt") != run_attempt
        or run.get("status") != "in_progress"
        or run.get("head_sha") != github_sha
        or repository_name != _REPOSITORY
        or len(matching) != 1
    ):
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_INVALID")
    job = matching[0]
    database_id = job.get("id")
    if (
        isinstance(database_id, bool)
        or not isinstance(database_id, int)
        or database_id < 1
        or job.get("status") != "in_progress"
        or job.get("conclusion") is not None
    ):
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_INVALID")
    return CatalogMirrorCurrentRepairWriterContextV1(
        run_id=run_id,
        run_attempt=run_attempt,
        writer_job_id=job_id,
        writer_job_database_id=database_id,
        workflow_path=str(run.get("path", "")),
        repository=_REPOSITORY,
        protected_commit_sha=github_sha,
        observed_at=datetime_now_utc(),
    )


def _repair_claim_writer_evidence(
    claim: CatalogMirrorRepairClaimV1,
) -> CatalogMirrorWriterEvidenceV1:
    writer = claim.writer
    names = _STEP_NAMES.get((claim.target_kind, writer.writer_job_id))
    if names is None:
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_EVIDENCE_INVALID")
    run = _gh_json(f"repos/{_REPOSITORY}/actions/runs/{writer.run_id}")
    run_readback = _gh_json(f"repos/{_REPOSITORY}/actions/runs/{writer.run_id}")
    if not isinstance(run, dict) or run != run_readback:
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_EVIDENCE_INVALID")
    jobs = [
        row
        for row in _completed_run_jobs(writer.run_id, writer.run_attempt)
        if row.get("id") == writer.writer_job_database_id
    ]
    if len(jobs) != 1:
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_EVIDENCE_INVALID")
    job = jobs[0]
    logical_name = job.get("name")
    repository = run.get("repository")
    repository_name = (
        repository.get("full_name") if isinstance(repository, dict) else None
    )
    if (
        not isinstance(logical_name, str)
        or not (
            logical_name == writer.writer_job_id
            or logical_name.endswith(f" / {writer.writer_job_id}")
        )
        or repository_name != writer.repository
        or run.get("path") != writer.workflow_path
        or run.get("head_sha") != writer.protected_commit_sha
    ):
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_EVIDENCE_INVALID")
    return CatalogMirrorWriterEvidenceV1(
        complete=True,
        stable=True,
        authenticated=True,
        repository=_REPOSITORY,
        workflow_path=writer.workflow_path,
        protected_commit_sha=writer.protected_commit_sha,
        run_id=writer.run_id,
        run_attempt=writer.run_attempt,
        run_status=str(run.get("status", "")),
        writer_job_id=writer.writer_job_id,
        writer_job_database_id=writer.writer_job_database_id,
        job_status=str(job.get("status", "")),
        upload_step_conclusion=_steps_conclusion(
            job.get("steps"),
            expected_name=_REPAIR_CLAIM_STEP_NAME,
        ),
        post_step_conclusion=_steps_conclusion(
            job.get("steps"),
            expected_name=names[1],
        ),
    )


def _prior_repair_claims(
    decision_payload_sha256: str,
) -> tuple[CatalogMirrorRepairClaimV1, ...]:
    claims: list[CatalogMirrorRepairClaimV1] = []
    missing_seen = False
    for sequence in range(_MAX_REPAIR_ATTEMPTS):
        name = catalog_mirror_repair_claim_artifact_name(
            decision_payload_sha256,
            sequence,
        )
        rows = _artifact_rows(name)
        if not rows:
            missing_seen = True
            continue
        if (
            missing_seen
            or len(rows) != 1
            or rows[0].get("expired") is not False
        ):
            raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_CHAIN_INVALID")
        artifact_id = rows[0].get("id")
        if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
            raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_INVALID")
        claims.append(
            _repair_claim_payload(
                artifact_id=artifact_id,
                artifact_name=name,
            )
        )
    return tuple(claims)


def _request_comments(document: object) -> tuple[CatalogRequestReceiptV1, ...]:
    if not isinstance(document, dict) or any(
        document.get(flag) is not True for flag in ("complete", "stable")
    ):
        raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_INVALID")
    rows = document.get("receipts")
    if not isinstance(rows, list):
        raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_INVALID")
    receipts: list[CatalogRequestReceiptV1] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("receipt") is None:
            continue
        receipts.append(CatalogRequestReceiptV1.model_validate(row["receipt"]))
    return tuple(receipts)


def _request_comments_live(issue_number: int) -> tuple[CatalogRequestReceiptV1, ...]:
    if issue_number < 1:
        raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_INVALID")

    def snapshot() -> tuple[dict[str, object], ...]:
        rows: list[dict[str, object]] = []
        for page in range(1, 101):
            payload = _gh_json(
                f"repos/{_REPOSITORY}/issues/{issue_number}/comments"
                f"?per_page=100&page={page}"
            )
            if not isinstance(payload, list) or any(
                not isinstance(row, dict) for row in payload
            ):
                raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_INVALID")
            rows.extend(payload)
            if len(payload) < 100:
                break
        else:
            raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_INCOMPLETE")
        ids = [row.get("id") for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_INVALID")
        return tuple(rows)

    first = snapshot()
    second = snapshot()
    if first != second:
        raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_UNSTABLE")
    receipts: list[CatalogRequestReceiptV1] = []
    for comment in first:
        body = comment.get("body")
        user = comment.get("user")
        author = user.get("login") if isinstance(user, dict) else None
        if (
            isinstance(body, str)
            and REQUEST_RECEIPT_MARKER in body
            and author == "github-actions[bot]"
        ):
            receipt = parse_request_receipt_comment(
                comment,
                expected_author="github-actions[bot]",
            )
            if receipt is None:
                raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_INVALID")
            receipts.append(receipt)
    return tuple(receipts)


def _authority_comments(document: object) -> tuple[CatalogAuthorityRecordV1, ...]:
    if not isinstance(document, dict) or not isinstance(document.get("comments"), list):
        raise ValueError("CATALOG_MIRROR_COMMENT_SNAPSHOT_INVALID")
    return extract_authority_comment_records(
        document["comments"],
        expected_author="github-actions[bot]",
    )


def _summary_from_comment(
    path: Path,
    receipt: CatalogRequestReceiptV1,
    *,
    runner_temp: Path,
) -> str:
    if path.is_symlink():
        raise ValueError("CATALOG_MIRROR_CANDIDATE_COMMENT_INVALID")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError("CATALOG_MIRROR_CANDIDATE_COMMENT_INVALID") from None
    if (
        not resolved.is_file()
        or not resolved.is_relative_to(runner_temp)
        or resolved.stat().st_size > _MAX_JSON_BYTES
    ):
        raise ValueError("CATALOG_MIRROR_CANDIDATE_COMMENT_INVALID")
    body = resolved.read_text("utf-8")
    marker = "\n\n<!-- AURORA_CATALOG_REQUEST_RECEIPT_V1 -->\n```json\n"
    if body.count(marker) != 1 or not body.endswith("\n```\n"):
        raise ValueError("CATALOG_MIRROR_CANDIDATE_COMMENT_INVALID")
    summary = body.split(marker, 1)[0]
    receipt.comment_body(summary)
    return summary


def reconcile(
    *,
    kind: Literal["authority", "request"],
    candidate_path: Path,
    candidate_comment_path: Path,
    comments_document_path: Path | None,
    output_dir: Path,
    github_output: Path,
) -> dict[str, str]:
    if os.environ.get("GITHUB_REPOSITORY") != _REPOSITORY:
        raise ValueError("CATALOG_MIRROR_REPOSITORY_INVALID")
    runner_temp_raw = os.environ.get("RUNNER_TEMP")
    if not runner_temp_raw:
        raise ValueError("CATALOG_MIRROR_RUNNER_TEMP_REQUIRED")
    runner_temp = Path(runner_temp_raw).resolve(strict=True)
    resolved_output = output_dir.resolve(strict=False)
    if github_output.is_symlink():
        raise ValueError("CATALOG_MIRROR_OUTPUT_INVALID")
    try:
        resolved_github_output = github_output.resolve(strict=True)
    except OSError:
        raise ValueError("CATALOG_MIRROR_OUTPUT_INVALID") from None
    if (
        output_dir.exists()
        or output_dir.is_symlink()
        or not resolved_output.is_relative_to(runner_temp)
        or not resolved_github_output.is_file()
        or not resolved_github_output.is_relative_to(runner_temp)
    ):
        raise ValueError("CATALOG_MIRROR_OUTPUT_INVALID")
    raw_candidate = _read_json(candidate_path, runner_temp=runner_temp)
    candidate = (
        CatalogAuthorityRecordV1.model_validate(raw_candidate)
        if kind == "authority"
        else CatalogRequestReceiptV1.model_validate(raw_candidate)
    )
    rows = _artifact_rows(candidate.artifact_name)
    mirrors: list[CatalogMirrorArtifactV1] = []
    mirror_comments: dict[int, str | None] = {}
    for row in rows:
        if row.get("expired") is True:
            continue
        artifact_id = row.get("id")
        if isinstance(artifact_id, bool) or not isinstance(artifact_id, int):
            raise ValueError("CATALOG_MIRROR_ARTIFACT_INVALID")
        payload, stored_comment = _artifact_payload(
            artifact_id=artifact_id,
            filename="record.json" if kind == "authority" else "request-receipt.json",
            kind=kind,
        )
        mirrors.append(
            CatalogMirrorArtifactV1.create(
                artifact_id=artifact_id,
                artifact_name=str(row.get("name", "")),
                expired=row.get("expired") is True,
                created_at=_parse_utc(row.get("created_at")),
                expires_at=_parse_utc(row.get("expires_at")),
                payload=payload,
            )
        )
        mirror_comments[artifact_id] = stored_comment
    comments_document = (
        _read_json(comments_document_path, runner_temp=runner_temp)
        if comments_document_path is not None
        else None
    )
    evidence = (
        (_writer_evidence(mirrors[0].payload, kind=kind),)
        if len(mirrors) == 1
        else ()
    )
    if kind == "authority":
        assert isinstance(candidate, CatalogAuthorityRecordV1)
        decision = decide_authority_mirror_delivery(
            candidate=candidate,
            artifacts=tuple(mirrors),
            comment_records=_authority_comments(comments_document),
            writer_evidence=evidence,
            now=datetime_now_utc(),
        )
    else:
        assert isinstance(candidate, CatalogRequestReceiptV1)
        decision = decide_request_receipt_mirror_delivery(
            candidate=candidate,
            artifacts=tuple(mirrors),
            comment_receipts=(
                _request_comments(comments_document)
                if comments_document is not None
                else _request_comments_live(candidate.issue_number)
            ),
            writer_evidence=evidence,
            now=datetime_now_utc(),
        )
    selected = candidate
    if decision.action != "upload_new":
        selected_rows = [
            row for row in mirrors if row.artifact_id == decision.artifact_id
        ]
        if len(selected_rows) != 1:
            raise ValueError("CATALOG_MIRROR_DECISION_INVALID")
        selected = selected_rows[0].payload
    repair_claim: CatalogMirrorRepairClaimV1 | None = None
    if decision.action == "repair_comment":
        prior_claims = _prior_repair_claims(decision.payload_sha256)
        repair_claim = prepare_catalog_mirror_repair_claim(
            decision=decision,
            prior_claims=prior_claims,
            prior_writer_evidence=tuple(
                _repair_claim_writer_evidence(claim) for claim in prior_claims
            ),
            current_writer=_current_repair_writer(kind=kind),
        )
    output_dir.mkdir(parents=False, exist_ok=False)
    filename = "record.json" if kind == "authority" else "request-receipt.json"
    (output_dir / filename).write_bytes(canonical_model_bytes(selected) + b"\n")
    if isinstance(selected, CatalogAuthorityRecordV1):
        comment = selected.to_comment() + "\n"
    else:
        if not isinstance(candidate, CatalogRequestReceiptV1):
            raise ValueError("CATALOG_MIRROR_DECISION_INVALID")
        stored_comment = (
            mirror_comments.get(decision.artifact_id)
            if decision.artifact_id is not None
            else None
        )
        if stored_comment is not None:
            comment = stored_comment
        else:
            summary = _summary_from_comment(
                candidate_comment_path,
                candidate,
                runner_temp=runner_temp,
            )
            comment = selected.comment_body(summary)
    (output_dir / "comment.md").write_text(comment, encoding="utf-8", newline="\n")
    if repair_claim is not None:
        (output_dir / "repair-claim.json").write_bytes(
            canonical_model_bytes(repair_claim) + b"\n"
        )
    if kind == "request":
        artifact_dir = output_dir / "artifact"
        artifact_dir.mkdir()
        (artifact_dir / "request-receipt.json").write_bytes(
            canonical_model_bytes(selected) + b"\n"
        )
        (artifact_dir / "comment.md").write_text(
            comment,
            encoding="utf-8",
            newline="\n",
        )
    (output_dir / "decision.json").write_text(
        json.dumps(
            decision.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    values = {
        "action": decision.action,
        "artifact_name": decision.artifact_name,
        "existing_artifact_id": str(decision.artifact_id or ""),
        "payload_sha256": decision.payload_sha256,
        "stop_after_repair": str(decision.stop_after_repair).lower(),
        "repair_claim_artifact_name": (
            repair_claim.artifact_name if repair_claim is not None else ""
        ),
        "repair_claim_sha256": (
            repair_claim.claim_sha256 if repair_claim is not None else ""
        ),
        "repair_sequence": (
            str(repair_claim.repair_sequence) if repair_claim is not None else ""
        ),
    }
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")
    return values


def datetime_now_utc() -> datetime:
    return datetime.now(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("authority", "request"), required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-comment", type=Path, required=True)
    parser.add_argument("--comments-document", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        reconcile(
            kind=args.kind,
            candidate_path=args.candidate,
            candidate_comment_path=args.candidate_comment,
            comments_document_path=args.comments_document,
            output_dir=args.output_dir,
            github_output=args.github_output,
        )
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
