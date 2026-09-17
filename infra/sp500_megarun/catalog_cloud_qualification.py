"""Authenticated, read-only evidence for the non-scientific cloud qualification.

The producer workflow is deliberately outside this module.  This reader only
accepts a completed ``workflow_dispatch`` run from protected ``main`` and a
single canonical receipt artifact produced by that run.  It never obtains a
key, calls a broker, writes GitHub state, or reads authority/science state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import zipfile
from typing import Annotated, Literal, Protocol, cast

from pydantic import Field, StrictInt, field_validator, model_validator

from .catalog_gate_budget import gate_timeout
from .catalog_request_contract import FrozenModel, Sha256, canonical_sha256


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_REPOSITORY_ID = 1_232_647_748
_APP_ID = 4_693_452
_INSTALLATION_ID = 155_982_969
_WORKFLOW_PATH = ".github/workflows/catalog-cloud-qualification.yml"
_JOB_NAME = "qualify"
_STEP_NAME = "Qualify existing requester App without scientific publication"
_ARTIFACT_NAME = "catalog-cloud-qualification-v1-{run_id}-{attempt}"
_ARTIFACT_MEMBER = "catalog-cloud-qualification-v1.json"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
_MAX_RECEIPT_BYTES = 64 * 1024

PositiveInt = Annotated[StrictInt, Field(gt=0)]


class CloudQualificationReceiptV1(FrozenModel):
    """Canonical public proof produced by the remote App-only qualification."""

    schema_version: Literal["1"] = "1"
    repository: Literal["trading-optimizer-lab-org/aurora"] = (
        "trading-optimizer-lab-org/aurora"
    )
    repository_id: Literal[1232647748] = 1232647748
    producer_run_id: PositiveInt
    producer_run_attempt: PositiveInt
    producer_job_id: PositiveInt
    producer_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    actor_id: PositiveInt
    app_id: Literal[4693452] = 4693452
    installation_id: Literal[155982969] = 155982969
    requester_public_key_sha256: Sha256
    permissions: tuple[
        tuple[Literal["issues"], Literal["write"]],
        tuple[Literal["metadata"], Literal["read"]],
    ] = (("issues", "write"), ("metadata", "read"))
    signed_test_request_sha256: Sha256
    observed_at: datetime
    receipt_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CLOUD_QUALIFICATION_TIME_INVALID")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _require_closed_permissions_and_hash(self) -> "CloudQualificationReceiptV1":
        if self.permissions != (("issues", "write"), ("metadata", "read")):
            raise ValueError("CLOUD_QUALIFICATION_PERMISSIONS_INVALID")
        if canonical_sha256(
            self.model_copy(update={"receipt_sha256": "0" * 64})
        ) != self.receipt_sha256:
            raise ValueError("CLOUD_QUALIFICATION_RECEIPT_HASH_INVALID")
        return self


class _QualificationReader(Protocol):
    repository: str
    observed_at: datetime | None

    def get_json(self, path: str) -> tuple[object, object]: ...


class _QualificationError(ValueError):
    """Internal stable failure code; remote details never escape the boundary."""


def _fail(code: str) -> _QualificationError:
    return _QualificationError(code)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise _fail("CLOUD_QUALIFICATION_PAYLOAD_INVALID")
    return value


def _positive_int(value: object) -> int:
    if type(value) is not int or value < 1:
        raise _fail("CLOUD_QUALIFICATION_INTEGER_INVALID")
    return value


def _time(value: object) -> datetime:
    if type(value) is not str:
        raise _fail("CLOUD_QUALIFICATION_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise _fail("CLOUD_QUALIFICATION_TIME_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _fail("CLOUD_QUALIFICATION_TIME_INVALID")
    return parsed.astimezone(timezone.utc)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise _fail("CLOUD_QUALIFICATION_CANONICAL_INVALID") from None


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("CLOUD_QUALIFICATION_JSON_INVALID")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    del value
    raise _fail("CLOUD_QUALIFICATION_JSON_INVALID")


def _strict_json(data: bytes) -> Mapping[str, object]:
    if not data or len(data) > _MAX_RECEIPT_BYTES:
        raise _fail("CLOUD_QUALIFICATION_RECEIPT_SIZE_INVALID")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except _QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise _fail("CLOUD_QUALIFICATION_JSON_INVALID") from None
    return _mapping(value)


def _get_json(client: _QualificationReader, path: str) -> object:
    try:
        payload, _ = client.get_json(path)
    except Exception:
        raise _fail("CLOUD_QUALIFICATION_REMOTE_READ_FAILED") from None
    return payload


def _validate_run(
    run: Mapping[str, object],
    *,
    run_id: int,
    expected_commit: str,
    allowed_actor_ids: tuple[int, ...],
) -> tuple[int, int]:
    if (
        _positive_int(run.get("id")) != run_id
        or run.get("path") != _WORKFLOW_PATH
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("head_sha") != expected_commit
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise _fail("CLOUD_QUALIFICATION_RUN_PROVENANCE_INVALID")
    repository = _mapping(run.get("repository"))
    if (
        _positive_int(repository.get("id")) != _REPOSITORY_ID
        or repository.get("full_name") != _REPOSITORY
    ):
        raise _fail("CLOUD_QUALIFICATION_RUN_PROVENANCE_INVALID")
    actor = _mapping(run.get("actor"))
    triggering_actor = _mapping(run.get("triggering_actor"))
    actor_id = _positive_int(actor.get("id"))
    triggering_actor_id = _positive_int(triggering_actor.get("id"))
    if actor_id not in allowed_actor_ids or triggering_actor_id not in allowed_actor_ids:
        raise _fail("CLOUD_QUALIFICATION_ACTOR_INVALID")
    attempt = _positive_int(run.get("run_attempt"))
    return attempt, actor_id


def _validate_step(
    job: Mapping[str, object],
    *,
    run_id: int,
    attempt: int,
    expected_commit: str,
) -> tuple[int, datetime, datetime, datetime, datetime]:
    if (
        _positive_int(job.get("id")) <= 0
        or job.get("name") != _JOB_NAME
        or _positive_int(job.get("run_id")) != run_id
        or _positive_int(job.get("run_attempt")) != attempt
        or job.get("head_sha") != expected_commit
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
    ):
        raise _fail("CLOUD_QUALIFICATION_JOB_PROVENANCE_INVALID")
    job_started = _time(job.get("started_at"))
    job_completed = _time(job.get("completed_at"))
    if job_completed < job_started:
        raise _fail("CLOUD_QUALIFICATION_TIME_INVALID")
    raw_steps = job.get("steps")
    if not isinstance(raw_steps, list):
        raise _fail("CLOUD_QUALIFICATION_STEPS_INVALID")
    matches = [
        _mapping(step)
        for step in raw_steps
        if isinstance(step, Mapping) and step.get("name") == _STEP_NAME
    ]
    if len(matches) != 1:
        raise _fail("CLOUD_QUALIFICATION_STEP_INVALID")
    step = matches[0]
    if step.get("status") != "completed" or step.get("conclusion") != "success":
        raise _fail("CLOUD_QUALIFICATION_STEP_INVALID")
    step_started = _time(step.get("started_at"))
    step_completed = _time(step.get("completed_at"))
    if not (
        job_started <= step_started <= step_completed <= job_completed
    ):
        raise _fail("CLOUD_QUALIFICATION_STEP_TIME_INVALID")
    return (
        _positive_int(job.get("id")),
        job_started,
        job_completed,
        step_started,
        step_completed,
    )


def _load_jobs(
    client: _QualificationReader,
    *,
    run_id: int,
    attempt: int,
    expected_commit: str,
) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    seen_ids: set[int] = set()
    declared_total: int | None = None
    for page in range(1, 11):
        payload = _mapping(
            _get_json(
                client,
                f"/repos/{_REPOSITORY}/actions/runs/{run_id}/attempts/"
                f"{attempt}/jobs?per_page=100&page={page}",
            )
        )
        raw_rows = payload.get("jobs")
        page_total = payload.get("total_count")
        if (
            not isinstance(raw_rows, list)
            or type(page_total) is not int
            or page_total < 0
        ):
            raise _fail("CLOUD_QUALIFICATION_JOBS_INVALID")
        if declared_total is None:
            declared_total = page_total
        elif page_total != declared_total:
            raise _fail("CLOUD_QUALIFICATION_JOBS_UNSTABLE")
        for raw in raw_rows:
            row = _mapping(raw)
            row_id = _positive_int(row.get("id"))
            if row_id in seen_ids:
                raise _fail("CLOUD_QUALIFICATION_JOB_DUPLICATE")
            seen_ids.add(row_id)
            rows.append(row)
        if len(raw_rows) < 100:
            if declared_total != len(rows):
                raise _fail("CLOUD_QUALIFICATION_JOBS_INCOMPLETE")
            break
    else:
        raise _fail("CLOUD_QUALIFICATION_JOBS_INCOMPLETE")
    if len(rows) != 1:
        raise _fail("CLOUD_QUALIFICATION_JOB_AMBIGUOUS")
    _validate_step(
        rows[0],
        run_id=run_id,
        attempt=attempt,
        expected_commit=expected_commit,
    )
    return tuple(rows)


def _artifact(
    client: _QualificationReader,
    *,
    run_id: int,
    attempt: int,
    expected_commit: str,
    job_started: datetime,
    job_completed: datetime,
) -> Mapping[str, object]:
    name = _ARTIFACT_NAME.format(run_id=run_id, attempt=attempt)
    payload = _mapping(
        _get_json(
            client,
            f"/repos/{_REPOSITORY}/actions/runs/{run_id}/artifacts"
            f"?name={name}&per_page=100",
        )
    )
    raw_rows = payload.get("artifacts")
    total_count = payload.get("total_count")
    if (
        not isinstance(raw_rows, list)
        or type(total_count) is not int
        or total_count != len(raw_rows)
        or total_count != 1
    ):
        raise _fail("CLOUD_QUALIFICATION_ARTIFACT_AMBIGUOUS")
    artifact = _mapping(raw_rows[0])
    artifact_id = _positive_int(artifact.get("id"))
    size_in_bytes = artifact.get("size_in_bytes")
    digest = artifact.get("digest")
    if (
        artifact.get("name") != name
        or artifact.get("expired") is not False
        or type(size_in_bytes) is not int
        or type(digest) is not str
    ):
        raise _fail("CLOUD_QUALIFICATION_ARTIFACT_METADATA_INVALID")
    if not 0 < size_in_bytes <= _MAX_ARCHIVE_BYTES:
        raise _fail("CLOUD_QUALIFICATION_ARTIFACT_METADATA_INVALID")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise _fail("CLOUD_QUALIFICATION_ARTIFACT_METADATA_INVALID")
    created_at = _time(artifact.get("created_at"))
    expires_at = _time(artifact.get("expires_at"))
    observed_at = getattr(client, "observed_at", None)
    if (
        not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        raise _fail("CLOUD_QUALIFICATION_OBSERVATION_TIME_INVALID")
    observed_at = observed_at.astimezone(timezone.utc)
    if (
        expires_at <= created_at
        or expires_at <= observed_at
        or created_at < job_started
        or created_at > job_completed
    ):
        raise _fail("CLOUD_QUALIFICATION_ARTIFACT_TIME_INVALID")
    source = _mapping(artifact.get("workflow_run"))
    if (
        _positive_int(source.get("id")) != run_id
        or source.get("head_sha") != expected_commit
        or source.get("head_branch") != "main"
        or _positive_int(source.get("repository_id")) != _REPOSITORY_ID
        or (
            "head_repository_id" in source
            and _positive_int(source.get("head_repository_id")) != _REPOSITORY_ID
        )
        or (
            "repository" in source
            and _mapping(source.get("repository")).get("full_name") != _REPOSITORY
        )
        or (
            "run_attempt" in source
            and _positive_int(source.get("run_attempt")) != attempt
        )
    ):
        raise _fail("CLOUD_QUALIFICATION_ARTIFACT_PROVENANCE_INVALID")
    return artifact


def _download_archive(client: _QualificationReader, artifact_id: int) -> bytes:
    token = getattr(client, "_token", None)
    if type(token) is not str or not token:
        raise _fail("CLOUD_QUALIFICATION_ARTIFACT_DOWNLOAD_UNAVAILABLE")
    with tempfile.TemporaryFile() as stream:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    f"repos/{_REPOSITORY}/actions/artifacts/{artifact_id}/zip",
                ],
                stdout=stream,
                stderr=subprocess.PIPE,
                env={**os.environ, "GH_TOKEN": token},
                timeout=gate_timeout(20),
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise _fail("CLOUD_QUALIFICATION_ARTIFACT_DOWNLOAD_FAILED") from None
        if result.returncode != 0:
            raise _fail("CLOUD_QUALIFICATION_ARTIFACT_DOWNLOAD_FAILED")
        stream.seek(0)
        raw = stream.read(_MAX_ARCHIVE_BYTES + 1)
    if not raw or len(raw) > _MAX_ARCHIVE_BYTES:
        raise _fail("CLOUD_QUALIFICATION_ARCHIVE_SIZE_INVALID")
    return raw


def _receipt_from_archive(raw: bytes) -> CloudQualificationReceiptV1:
    if not raw or len(raw) > _MAX_ARCHIVE_BYTES:
        raise _fail("CLOUD_QUALIFICATION_ARCHIVE_SIZE_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise _QualificationError("CLOUD_QUALIFICATION_ARCHIVE_MEMBERS_INVALID")
            member = members[0]
            mode = (member.external_attr >> 16) & 0o170000
            if (
                member.filename != _ARTIFACT_MEMBER
                or member.is_dir()
                or member.flag_bits & 1
                or mode not in {0, 0o100000}
                or not 0 < member.file_size <= _MAX_RECEIPT_BYTES
            ):
                raise _QualificationError("CLOUD_QUALIFICATION_ARCHIVE_MEMBER_INVALID")
            data = archive.read(member)
    except _QualificationError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise _fail("CLOUD_QUALIFICATION_ARCHIVE_INVALID") from None
    payload = _strict_json(data)
    try:
        receipt = CloudQualificationReceiptV1.model_validate(payload)
    except Exception:
        raise _fail("CLOUD_QUALIFICATION_RECEIPT_INVALID") from None
    if data != _canonical_bytes(receipt.model_dump(mode="json")) + b"\n":
        raise _fail("CLOUD_QUALIFICATION_RECEIPT_NONCANONICAL")
    return receipt


def _snapshot_hash(
    run: Mapping[str, object],
    jobs: tuple[Mapping[str, object], ...],
    artifact: Mapping[str, object],
) -> str:
    return _sha256_bytes(_canonical_bytes({"run": run, "jobs": jobs, "artifact": artifact}))


def verify_cloud_qualification(
    client: _QualificationReader,
    run_id: int,
    expected_commit: str,
    expected_public_key_sha256: str,
    allowed_actor_ids: tuple[int, ...],
    *,
    download_archive: Callable[[int], bytes] | None = None,
) -> CloudQualificationReceiptV1:
    """Return one stable, authenticated N08 receipt or fail closed.

    ``download_archive`` is a test seam only.  Production callers omit it and
    the bounded GET download uses the token already held by the read-only
    client.  All remote/API/ZIP/parser details are converted to stable public
    failure codes; response bodies and credentials never appear in errors.
    """

    try:
        if type(run_id) is not int or run_id < 1:
            raise _fail("CLOUD_QUALIFICATION_RUN_ID_INVALID")
        if type(expected_commit) is not str or _COMMIT.fullmatch(expected_commit) is None:
            raise _fail("CLOUD_QUALIFICATION_COMMIT_INVALID")
        if (
            type(expected_public_key_sha256) is not str
            or _SHA256.fullmatch(expected_public_key_sha256) is None
        ):
            raise _fail("CLOUD_QUALIFICATION_PUBLIC_KEY_HASH_INVALID")
        if (
            type(allowed_actor_ids) is not tuple
            or not allowed_actor_ids
            or any(type(actor_id) is not int or actor_id < 1 for actor_id in allowed_actor_ids)
            or len(set(allowed_actor_ids)) != len(allowed_actor_ids)
        ):
            raise _fail("CLOUD_QUALIFICATION_ACTOR_ALLOWLIST_INVALID")
        if getattr(client, "repository", None) != _REPOSITORY:
            raise _fail("CLOUD_QUALIFICATION_REPOSITORY_INVALID")

        first_run = _mapping(
            _get_json(client, f"/repos/{_REPOSITORY}/actions/runs/{run_id}")
        )
        first_attempt, actor_id = _validate_run(
            first_run,
            run_id=run_id,
            expected_commit=expected_commit,
            allowed_actor_ids=allowed_actor_ids,
        )
        first_jobs = _load_jobs(
            client,
            run_id=run_id,
            attempt=first_attempt,
            expected_commit=expected_commit,
        )
        first_job_id, job_started, job_completed, step_started, step_completed = _validate_step(
            first_jobs[0],
            run_id=run_id,
            attempt=first_attempt,
            expected_commit=expected_commit,
        )
        first_artifact = _artifact(
            client,
            run_id=run_id,
            attempt=first_attempt,
            expected_commit=expected_commit,
            job_started=job_started,
            job_completed=job_completed,
        )
        observed_at = getattr(client, "observed_at", None)
        if (
            not isinstance(observed_at, datetime)
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
        ):
            raise _fail("CLOUD_QUALIFICATION_OBSERVATION_TIME_INVALID")
        snapshot = _snapshot_hash(first_run, first_jobs, first_artifact)
        downloader = download_archive or (lambda artifact_id: _download_archive(client, artifact_id))
        try:
            raw_archive = downloader(_positive_int(first_artifact.get("id")))
        except _QualificationError:
            raise
        except Exception:
            raise _fail("CLOUD_QUALIFICATION_ARTIFACT_DOWNLOAD_FAILED") from None
        if type(raw_archive) is not bytes:
            raise _fail("CLOUD_QUALIFICATION_ARCHIVE_INVALID")
        if (
            len(raw_archive)
            != cast(int, first_artifact.get("size_in_bytes"))
            or _sha256_bytes(raw_archive)
            != cast(str, first_artifact.get("digest"))[7:]
        ):
            raise _fail("CLOUD_QUALIFICATION_ARTIFACT_DIGEST_INVALID")
        receipt = _receipt_from_archive(raw_archive)
        if (
            receipt.producer_run_id != run_id
            or receipt.producer_run_attempt != first_attempt
            or receipt.producer_job_id != first_job_id
            or receipt.producer_commit != expected_commit
            or receipt.actor_id != actor_id
            or receipt.requester_public_key_sha256 != expected_public_key_sha256
            or not (step_started <= receipt.observed_at <= step_completed)
        ):
            raise _fail("CLOUD_QUALIFICATION_RECEIPT_BINDING_INVALID")

        second_run = _mapping(
            _get_json(client, f"/repos/{_REPOSITORY}/actions/runs/{run_id}")
        )
        second_attempt, second_actor_id = _validate_run(
            second_run,
            run_id=run_id,
            expected_commit=expected_commit,
            allowed_actor_ids=allowed_actor_ids,
        )
        second_jobs = _load_jobs(
            client,
            run_id=run_id,
            attempt=second_attempt,
            expected_commit=expected_commit,
        )
        _, second_job_started, second_job_completed, _, _ = _validate_step(
            second_jobs[0],
            run_id=run_id,
            attempt=second_attempt,
            expected_commit=expected_commit,
        )
        second_artifact = _artifact(
            client,
            run_id=run_id,
            attempt=second_attempt,
            expected_commit=expected_commit,
            job_started=second_job_started,
            job_completed=second_job_completed,
        )
        if (
            second_attempt != first_attempt
            or second_actor_id != actor_id
            or _snapshot_hash(second_run, second_jobs, second_artifact) != snapshot
        ):
            raise _fail("CLOUD_QUALIFICATION_REMOTE_READ_UNSTABLE")
        if (
            second_artifact.get("id") != first_artifact.get("id")
            or second_artifact.get("digest") != first_artifact.get("digest")
        ):
            raise _fail("CLOUD_QUALIFICATION_REMOTE_READ_UNSTABLE")
        return receipt
    except _QualificationError as exc:
        raise ValueError(str(exc)) from None
    except Exception:
        raise ValueError("CLOUD_QUALIFICATION_INVALID") from None


__all__ = ["CloudQualificationReceiptV1", "verify_cloud_qualification"]
