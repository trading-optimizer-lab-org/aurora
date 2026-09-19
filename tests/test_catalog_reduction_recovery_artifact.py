from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun import catalog_fast_reservation as reservation
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1


def _fixture():
    raw = b"bounded artifact bytes"
    commit = "a" * 40
    source = {"id": 17, "head_sha": commit, "head_branch": "main",
              "repository_id": 1232647748, "head_repository_id": 1232647748}
    artifact = {"id": 23, "name": "catalog-reduction-group-source-g00",
                "expired": False, "size_in_bytes": len(raw),
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "workflow_run": source, "created_at": "2026-09-19T10:09:43Z"}
    job = {"id": 31, "name": "engine / reduce_groups (0)", "run_id": 17,
           "run_attempt": 1, "head_sha": commit, "status": "completed",
           "conclusion": "success", "steps": [{
               "name": "Upload one bounded reduction group", "status": "completed",
               "conclusion": "success", "started_at": "2026-09-19T10:09:43Z",
               "completed_at": "2026-09-19T10:09:44Z"}]}
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED", reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256="b" * 64, submission_key_sha256="c" * 64,
        campaign_key="catalog-fast-canary-v1", prepared_receipt_sha256="d" * 64,
        selected_workers=4, launch_required=True, existing_run_id=None,
        decided_at=now, expires_at=now,
    )
    owner = reservation.FastGateOwnerEvidence(
        run_id=17, decision=decision, jobs=(job,), run={
            "id": 17, "status": "completed", "run_attempt": 1,
            "head_sha": commit, "head_branch": "main",
            "repository": {"id": 1232647748},
        },
    )
    inventory = SimpleNamespace(stable=True, collection=SimpleNamespace(
        complete=True, rows=(artifact,)))
    client = SimpleNamespace(repository="trading-optimizer-lab-org/aurora",
                             stable_paginated=lambda *a, **k: inventory)
    return raw, artifact, job, owner, client, inventory


def _read(raw, owner, client):
    reader = getattr(reservation, "read_owner_artifact_archive", None)
    assert callable(reader), "authenticated reduction artifact reader is missing"
    return reader(
        client=client, owner=owner,
        artifact_name="catalog-reduction-group-source-g00",
        publisher_job_name="engine / reduce_groups (0)",
        publish_step_name="Upload one bounded reduction group",
        download_archive=lambda artifact_id: raw if artifact_id == 23 else b"",
    )


def test_reads_only_exact_owner_artifact_with_verified_digest():
    raw, artifact, _, owner, client, _ = _fixture()
    result = _read(raw, owner, client)
    assert result == (raw, artifact)


@pytest.mark.parametrize("field,value", [
    ("expired", True), ("id", True), ("name", "other"),
    ("size_in_bytes", 0), ("digest", "sha256:" + "0" * 64),
    ("created_at", "2026-09-19T10:09:42Z"),
    ("created_at", "2026-09-19T10:09:45Z"),
])
def test_rejects_invalid_artifact_metadata(field, value):
    raw, artifact, _, owner, client, _ = _fixture()
    artifact[field] = value
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_ARTIFACT"):
        _read(raw, owner, client)


@pytest.mark.parametrize("field,value", [
    ("id", 18), ("head_sha", "f" * 40), ("head_branch", "feature"),
    ("repository_id", 1), ("head_repository_id", 1),
])
def test_rejects_artifact_from_another_owner(field, value):
    raw, artifact, _, owner, client, _ = _fixture()
    artifact["workflow_run"][field] = value
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_ARTIFACT"):
        _read(raw, owner, client)


@pytest.mark.parametrize("field,value", [
    ("run_id", 18), ("run_attempt", 2), ("head_sha", "f" * 40),
    ("conclusion", "failure"), ("status", "in_progress"),
])
def test_rejects_wrong_or_unsuccessful_publisher(field, value):
    raw, _, job, owner, client, _ = _fixture()
    job[field] = value
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_ARTIFACT"):
        _read(raw, owner, client)


@pytest.mark.parametrize("mutation", ["unstable", "incomplete", "duplicate", "missing", "failed_step"])
def test_rejects_unproven_publication(mutation):
    raw, artifact, job, owner, client, inventory = _fixture()
    if mutation == "unstable":
        inventory.stable = False
    elif mutation == "incomplete":
        inventory.collection.complete = False
    elif mutation == "duplicate":
        inventory.collection.rows = (artifact, deepcopy(artifact))
    elif mutation == "missing":
        inventory.collection.rows = ()
    else:
        job["steps"][0]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_ARTIFACT"):
        _read(raw, owner, client)


def test_rejects_changed_archive_bytes():
    raw, _, _, owner, client, _ = _fixture()
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_ARTIFACT"):
        _read(raw + b"changed", owner, client)
