"""Synthetic, GET-only evidence for the non-scientific cloud qualification reader."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import io
import json
import zipfile

import pytest

from aurora.infra.sp500_megarun.catalog_cloud_qualification import (
    CloudQualificationReceiptV1,
    verify_cloud_qualification,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_sha256


REPOSITORY = "trading-optimizer-lab-org/aurora"
REPOSITORY_ID = 1_232_647_748
COMMIT = "a" * 40
PUBLIC_KEY_SHA256 = "b" * 64
ACTOR_ID = 47_000_001
RUN_ID = 17_000_001
ATTEMPT = 2
JOB_ID = 27_000_001
ARTIFACT_ID = 37_000_001
WORKFLOW_PATH = ".github/workflows/catalog-cloud-qualification.yml"
STEP_NAME = "Qualify existing requester App without scientific publication"
ARTIFACT_MEMBER = "catalog-cloud-qualification-v1.json"
REQUEST_NAMESPACE = "cloud-origin-qualification-v1"
REQUEST_ID = "00000000-0000-7000-8000-000000000001"
QUALIFICATION_TEST_REQUEST = {
    "namespace": REQUEST_NAMESPACE,
    "request_id": REQUEST_ID,
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def qualification_test_request_sha256() -> str:
    """Hash used by the producer fixture; the request body is never uploaded."""

    return hashlib.sha256(_canonical_bytes(QUALIFICATION_TEST_REQUEST)).hexdigest()


def make_qualification_receipt(
    **updates: object,
) -> CloudQualificationReceiptV1:
    """Build a valid canonical receipt for producer/pipeline tests."""

    values: dict[str, object] = {
        "schema_version": "1",
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "producer_run_id": RUN_ID,
        "producer_run_attempt": ATTEMPT,
        "producer_job_id": JOB_ID,
        "producer_commit": COMMIT,
        "actor_id": ACTOR_ID,
        "app_id": 4_693_452,
        "installation_id": 155_982_969,
        "requester_public_key_sha256": PUBLIC_KEY_SHA256,
        "permissions": (("issues", "write"), ("metadata", "read")),
        "signed_test_request_sha256": qualification_test_request_sha256(),
        "observed_at": datetime(2026, 9, 17, 12, 0, 3, tzinfo=UTC),
        "receipt_sha256": "0" * 64,
    }
    values.update(updates)
    unsigned = CloudQualificationReceiptV1.model_construct(**values)
    values["receipt_sha256"] = canonical_sha256(unsigned)
    return CloudQualificationReceiptV1.model_validate(values)


def make_qualification_archive(
    receipt: CloudQualificationReceiptV1,
    *,
    members: Mapping[str, bytes] | None = None,
    receipt_bytes: bytes | None = None,
) -> bytes:
    """Build an artifact ZIP, with knobs for parser and boundary tests."""

    if members is None:
        members = {
            ARTIFACT_MEMBER: (
                receipt_bytes
                if receipt_bytes is not None
                else _canonical_bytes(receipt.model_dump(mode="json")) + b"\n"
            )
        }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return output.getvalue()


@dataclass
class QualificationFixture:
    client: "SyntheticQualificationClient"
    receipt: CloudQualificationReceiptV1
    raw_archive: bytes
    run: dict[str, object]
    job: dict[str, object]
    artifact: dict[str, object]


class SyntheticQualificationClient:
    """Small authenticated-client-shaped transport with no network capability."""

    repository = REPOSITORY
    _token = "synthetic-only-token"
    observed_at = datetime(2026, 9, 17, 12, 0, 30, tzinfo=UTC)

    def __init__(
        self,
        *,
        run: dict[str, object],
        job: dict[str, object],
        artifact: dict[str, object],
        archive: bytes,
        second_snapshot: Mapping[str, object] | None = None,
    ) -> None:
        self.run = run
        self.job = job
        self.artifact = artifact
        self.archive = archive
        self.second_snapshot = dict(second_snapshot or {})
        self.calls: list[str] = []
        self._reads = {"run": 0, "jobs": 0, "artifact": 0}

    def get_json(self, path: str) -> tuple[object, object]:
        self.calls.append(path)
        prefix = f"/repos/{REPOSITORY}/actions"
        if path == f"{prefix}/runs/{RUN_ID}":
            kind = "run"
            base: object = self.run
        elif path == (
            f"{prefix}/runs/{RUN_ID}/attempts/{ATTEMPT}/jobs"
            "?per_page=100&page=1"
        ):
            kind = "jobs"
            base = {"total_count": 1, "jobs": [self.job]}
        elif path == (
            f"{prefix}/runs/{RUN_ID}/artifacts"
            f"?name=catalog-cloud-qualification-v1-{RUN_ID}-{ATTEMPT}&per_page=100"
        ):
            kind = "artifact"
            base = {"total_count": 1, "artifacts": [self.artifact]}
        else:
            raise AssertionError(f"unexpected GET path: {path}")
        self._reads[kind] += 1
        if self._reads[kind] >= 2 and kind in self.second_snapshot:
            base = self.second_snapshot[kind]
        return deepcopy(base), object()


def make_qualification_fixture(
    *,
    receipt: CloudQualificationReceiptV1 | None = None,
    second_snapshot: Mapping[str, object] | None = None,
) -> QualificationFixture:
    """Return reusable run/job/artifact data for the real reader seam."""

    receipt = receipt or make_qualification_receipt()
    run: dict[str, object] = {
        "id": RUN_ID,
        "run_attempt": ATTEMPT,
        "head_sha": COMMIT,
        "head_branch": "main",
        "path": WORKFLOW_PATH,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "actor": {"id": ACTOR_ID},
        "triggering_actor": {"id": ACTOR_ID},
        "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
    }
    job: dict[str, object] = {
        "id": JOB_ID,
        "name": "qualify",
        "run_id": RUN_ID,
        "run_attempt": ATTEMPT,
        "head_sha": COMMIT,
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-09-17T12:00:00Z",
        "completed_at": "2026-09-17T12:00:10Z",
        "steps": [
            {
                "name": STEP_NAME,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-09-17T12:00:01Z",
                "completed_at": "2026-09-17T12:00:05Z",
            }
        ],
    }
    raw_archive = make_qualification_archive(receipt)
    artifact: dict[str, object] = {
        "id": ARTIFACT_ID,
        "name": f"catalog-cloud-qualification-v1-{RUN_ID}-{ATTEMPT}",
        "expired": False,
        "size_in_bytes": len(raw_archive),
        "digest": "sha256:" + hashlib.sha256(raw_archive).hexdigest(),
        "created_at": "2026-09-17T12:00:06Z",
        "expires_at": "2026-09-18T12:00:00Z",
        "workflow_run": {
            "id": RUN_ID,
            "run_attempt": ATTEMPT,
            "head_sha": COMMIT,
            "head_branch": "main",
            "repository_id": REPOSITORY_ID,
            "head_repository_id": REPOSITORY_ID,
            "repository": {"full_name": REPOSITORY},
        },
    }
    client = SyntheticQualificationClient(
        run=run,
        job=job,
        artifact=artifact,
        archive=raw_archive,
        second_snapshot=second_snapshot,
    )
    return QualificationFixture(client, receipt, raw_archive, run, job, artifact)


def _replace_archive(fixture: QualificationFixture, raw_archive: bytes) -> None:
    fixture.raw_archive = raw_archive
    fixture.client.archive = raw_archive
    fixture.artifact["size_in_bytes"] = len(raw_archive)
    fixture.artifact["digest"] = "sha256:" + hashlib.sha256(raw_archive).hexdigest()


def _verify(fixture: QualificationFixture) -> CloudQualificationReceiptV1:
    return verify_cloud_qualification(
        fixture.client,
        run_id=RUN_ID,
        expected_commit=COMMIT,
        expected_public_key_sha256=PUBLIC_KEY_SHA256,
        allowed_actor_ids=(ACTOR_ID,),
        download_archive=lambda artifact_id: fixture.raw_archive,
    )


def test_valid_receipt_is_bound_to_completed_get_only_evidence() -> None:
    fixture = make_qualification_fixture()

    result = _verify(fixture)

    assert result == fixture.receipt
    assert fixture.client.calls == [
        f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}",
        f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/{ATTEMPT}/jobs"
        "?per_page=100&page=1",
        f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts"
        f"?name=catalog-cloud-qualification-v1-{RUN_ID}-{ATTEMPT}&per_page=100",
    ] * 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", ".github/workflows/other.yml"),
        ("event", "push"),
        ("head_branch", "feature"),
        ("head_sha", "c" * 40),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("actor", {"id": ACTOR_ID + 1}),
        ("triggering_actor", {"id": ACTOR_ID + 1}),
    ],
)
def test_run_provenance_and_actor_allowlist_are_fail_closed(
    field: str,
    value: object,
) -> None:
    fixture = make_qualification_fixture()
    fixture.run[field] = value

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_"):
        _verify(fixture)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda job: job.update(name="other"),
        lambda job: job.update(status="in_progress"),
        lambda job: job.update(conclusion="failure"),
        lambda job: job["steps"].__getitem__(0).update(conclusion="failure"),
        lambda job: job["steps"].__getitem__(0).update(
            started_at="2026-09-17T11:59:00Z"
        ),
        lambda job: job["steps"].append(
            {
                "name": STEP_NAME,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-09-17T12:00:01Z",
                "completed_at": "2026-09-17T12:00:05Z",
            }
        ),
    ],
)
def test_job_step_uniqueness_success_and_temporal_binding(mutator) -> None:
    fixture = make_qualification_fixture()
    mutator(fixture.job)

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_"):
        _verify(fixture)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expired", True),
        ("name", "wrong-artifact"),
        ("expires_at", "2026-09-17T12:00:30Z"),
        ("workflow_run", {"id": RUN_ID + 1}),
    ],
)
def test_artifact_expiry_name_and_provenance_are_verified(
    field: str,
    value: object,
) -> None:
    fixture = make_qualification_fixture()
    fixture.artifact[field] = value

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_"):
        _verify(fixture)


def test_artifact_digest_must_match_the_bounded_download() -> None:
    fixture = make_qualification_fixture()
    fixture.artifact["digest"] = "sha256:" + "c" * 64

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_ARTIFACT_DIGEST_INVALID"):
        _verify(fixture)


def test_artifact_size_must_match_the_downloaded_zip() -> None:
    fixture = make_qualification_fixture()
    fixture.artifact["size_in_bytes"] = len(fixture.raw_archive) + 1

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_ARTIFACT_DIGEST_INVALID"):
        _verify(fixture)


@pytest.mark.parametrize(
    "members",
    [
        {"wrong.json": b"{}"},
        {
            ARTIFACT_MEMBER: b"{}",
            "unexpected.txt": b"not a receipt",
        },
    ],
)
def test_archive_requires_one_expected_member_and_canonical_model(members) -> None:
    fixture = make_qualification_fixture()
    _replace_archive(fixture, make_qualification_archive(fixture.receipt, members=members))

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_ARCHIVE"):
        _verify(fixture)


def test_archive_receipt_must_be_canonical_and_self_hashed() -> None:
    fixture = make_qualification_fixture()
    pretty = json.dumps(
        fixture.receipt.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    _replace_archive(
        fixture,
        make_qualification_archive(fixture.receipt, receipt_bytes=pretty),
    )

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_RECEIPT_NONCANONICAL"):
        _verify(fixture)


def test_receipt_observation_and_public_key_are_bound_to_the_step() -> None:
    receipt = make_qualification_receipt(
        requester_public_key_sha256="c" * 64,
        observed_at=datetime(2026, 9, 17, 12, 0, 8, tzinfo=UTC),
    )
    fixture = make_qualification_fixture(receipt=receipt)

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_RECEIPT_BINDING_INVALID"):
        _verify(fixture)


def test_second_remote_snapshot_must_be_identical() -> None:
    fixture = make_qualification_fixture(
        second_snapshot={
            "artifact": {
                "total_count": 1,
                "artifacts": [
                    {
                        **make_qualification_fixture().artifact,
                        "digest": "sha256:" + "d" * 64,
                    }
                ],
            },
        }
    )

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_REMOTE_READ_UNSTABLE"):
        _verify(fixture)


def test_remote_errors_are_sanitized() -> None:
    fixture = make_qualification_fixture()

    def fail(_path: str) -> tuple[object, object]:
        raise RuntimeError("bearer super-secret-token")

    fixture.client.get_json = fail  # type: ignore[method-assign]

    with pytest.raises(ValueError) as error:
        _verify(fixture)
    assert str(error.value) == "CLOUD_QUALIFICATION_REMOTE_READ_FAILED"
    assert "super-secret-token" not in str(error.value)


def test_request_fixture_exposes_only_the_signed_request_hash() -> None:
    assert QUALIFICATION_TEST_REQUEST["namespace"] == REQUEST_NAMESPACE
    assert QUALIFICATION_TEST_REQUEST["request_id"] == REQUEST_ID
    assert len(qualification_test_request_sha256()) == 64
    assert make_qualification_receipt().signed_test_request_sha256 == (
        qualification_test_request_sha256()
    )
