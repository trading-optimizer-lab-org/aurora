from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from types import SimpleNamespace
import zipfile

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastLaunchDecisionV1,
    CatalogTerminalReceiptV1,
    CatalogTerminalReceiptV2,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import (
    FastGateOwnerEvidence,
    _is_expected_workflow_path,
    bind_owner_terminal_receipt,
    load_fast_gate_owner,
    load_owner_terminal_receipt,
    verify_fast_gate_owner_metadata,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
from scripts.catalog_atlas_terminal_correction_lookup import (
    _load_atlas_terminal_correction, resolve_atlas_terminal_correction,
)


COMMIT = "44d4f5e1bfe0d2d9396b99f44b4684205e737c0e"
NOW = datetime(2026, 9, 18, 16, 0, tzinfo=timezone.utc)


class _WorkflowPath(str):
    pass


@pytest.mark.parametrize(
    ("path", "expected", "valid"),
    (
        (
            ".github/workflows/catalog-fast-controller.yml",
            ".github/workflows/catalog-fast-controller.yml",
            True,
        ),
        (
            ".github/workflows/catalog-request-reconciler.yml",
            ".github/workflows/catalog-fast-controller.yml",
            False,
        ),
        (
            _WorkflowPath(".github/workflows/catalog-fast-controller.yml"),
            ".github/workflows/catalog-fast-controller.yml",
            False,
        ),
    ),
)
def test_workflow_path_identity_requires_exact_string(
    path: object, expected: str, valid: bool
) -> None:
    assert _is_expected_workflow_path(path, expected) is valid


def _request() -> CatalogRunRequestV1:
    return CatalogRunRequestV1.model_validate({
        "schema_version": "1",
        "request_id": "018f47a2-6e91-7c34-8000-000000000001",
        "campaign_key": "sp500-optimized-catalog-v1",
        "launch_generation": 1,
        "launch_ticket_sha256": "8" * 64,
        "previous_terminal_request_sha256": None,
        "campaign_definition_sha256": "c" * 64,
        "prompt_sha256": "9" * 64,
        "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        "free_resources_only": True,
        "automatic_recovery": True,
        "max_same_failure_count": 3,
        "requester_public_key_sha256": "a" * 64,
        "requester_attestation_algorithm": "rsa-pss-sha256-v1",
        "requester_attestation_b64": "A" * 300,
    })


def _blocked_decision(request: CatalogRunRequestV1, **updates: object) -> CatalogFastLaunchDecisionV1:
    values: dict[str, object] = {
        "state": "BLOCKED",
        "reason_code": "CATALOG_REQUEST_EXPIRED",
        "request_sha256": request.request_sha256,
        "submission_key_sha256": request.submission_key_sha256,
        "campaign_key": request.campaign_key,
        "prepared_receipt_sha256": "f" * 64,
        "selected_workers": 0,
        "launch_required": False,
        "existing_run_id": None,
        "decided_at": NOW,
        "expires_at": NOW - timedelta(seconds=1),
    }
    values.update(updates)
    return CatalogFastLaunchDecisionV1.create(**values)


def _unlaunched_receipt(request: CatalogRunRequestV1, **updates: object) -> CatalogTerminalReceiptV1:
    values: dict[str, object] = {
        "state": "BLOCKED",
        "reason_code": "CATALOG_REQUEST_EXPIRED",
        "request_sha256": request.request_sha256,
        "submission_key_sha256": request.submission_key_sha256,
        "campaign_key": request.campaign_key,
        "prepared_receipt_sha256": "f" * 64,
        "engine_run_id": None,
        "run_url": None,
        "expected_recipe_count": 1,
        "observed_recipe_count": 0,
        "queue_seconds": 0.0,
        "preparation_seconds": 0.0,
        "computation_seconds": 0.0,
        "recovery_seconds": 0.0,
        "reduction_seconds": 0.0,
        "recovered_block_count": 0,
        "failure_class": "request",
        "result_science_sha256": None,
        "created_at": NOW,
    }
    values.update(updates)
    return CatalogTerminalReceiptV1.create(**values)


def _terminal_owner_fixture(
    created_at: str, *, wrong_owner: bool = False,
    create_completed_at: str = "2026-09-19T10:11:09Z",
    publish_started_at: str = "2026-09-19T10:11:09Z",
) -> tuple[object, FastGateOwnerEvidence, object]:
    request = _request()
    run_id = 35436320227
    head_sha = "fc77968dceeb93b332c143cc367b99128f488093"
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED",
        reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256="f" * 64,
        selected_workers=1,
        launch_required=True,
        existing_run_id=None,
        decided_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    receipt = CatalogTerminalReceiptV1.create(
        state="SUCCESS",
        reason_code="CATALOG_RUN_SUCCESS",
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256="f" * 64,
        engine_run_id=run_id,
        run_url=f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{run_id}",
        expected_recipe_count=8,
        observed_recipe_count=8,
        queue_seconds=0.0,
        preparation_seconds=0.0,
        computation_seconds=1.0,
        recovery_seconds=0.0,
        reduction_seconds=0.0,
        recovered_block_count=0,
        failure_class=None,
        result_science_sha256="e" * 64,
        created_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")),
    )
    terminal_buffer = io.BytesIO()
    with zipfile.ZipFile(terminal_buffer, "w") as archive:
        archive.writestr("catalog-terminal-receipt-v1.json", receipt.model_dump_json())
    raw = terminal_buffer.getvalue()
    artifact = {
        "id": 10582396128,
        "name": f"catalog-terminal-receipt-{request.request_sha256}",
        "expired": False,
        "size_in_bytes": len(raw),
        "created_at": "2026-09-19T10:11:10Z",
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "workflow_run": {
            "id": run_id + 1 if wrong_owner else run_id,
            "head_sha": head_sha,
            "head_branch": "main",
            "repository_id": 1232647748,
            "head_repository_id": 1232647748,
        },
    }
    run = {
        "id": run_id,
        "run_attempt": 1,
        "head_sha": head_sha,
        "head_branch": "main",
        "path": ".github/workflows/catalog-fast-controller.yml",
        "event": "issues",
        "repository": {
            "id": 1232647748,
            "full_name": "trading-optimizer-lab-org/aurora",
        },
        "status": "completed",
        "conclusion": "failure",
    }
    finalizer = {
        "id": 105880454451,
        "run_id": run_id,
        "run_attempt": 1,
        "head_sha": head_sha,
        "name": "finalize",
        "status": "completed",
        "conclusion": "failure",
        "steps": [
            {
                "name": "Create exactly one terminal receipt",
                "number": 9,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-09-19T10:11:09Z",
                "completed_at": create_completed_at,
            },
            {
                "name": "Publish the terminal receipt before changing the issue",
                "number": 10,
                "status": "completed",
                "conclusion": "success",
                "started_at": publish_started_at,
                "completed_at": "2026-09-19T10:11:10Z",
            },
        ],
    }

    class Client:
        repository = "trading-optimizer-lab-org/aurora"

        def stable_paginated(self, path: str, *, root: str):
            assert root == "artifacts"
            assert path.endswith(
                f"/actions/runs/{run_id}/artifacts?name=catalog-terminal-receipt-{request.request_sha256}"
            )
            return SimpleNamespace(
                stable=True,
                collection=SimpleNamespace(complete=True, rows=(artifact,)),
            )

    owner = FastGateOwnerEvidence(run_id, run, decision, (finalizer,))

    def download(artifact_id: int) -> bytes:
        assert artifact_id == artifact["id"]
        return raw

    return Client(), owner, download


@pytest.mark.parametrize(
    ("created_at", "accepted"),
    (
        pytest.param("2026-09-19T10:11:09.728262Z", True, id="end_fraction_accepted"),
        pytest.param("2026-09-19T10:11:09.999999Z", True, id="last_fraction_accepted"),
        pytest.param("2026-09-19T10:11:10.000000Z", False, id="next_second_rejected"),
        pytest.param("2026-09-19T10:11:08.999999Z", False, id="before_start_rejected"),
    ),
)
def test_owner_terminal_receipt_uses_exclusive_second_boundary(
    created_at: str, accepted: bool,
) -> None:
    client, owner, download = _terminal_owner_fixture(created_at)

    if accepted:
        receipt = load_owner_terminal_receipt(
            client=client, owner=owner, issue_number=323, download_archive=download,
        )
        assert receipt is not None
        assert receipt.created_at == datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_TERMINAL_TIME_INVALID"):
            load_owner_terminal_receipt(
                client=client, owner=owner, issue_number=323, download_archive=download,
            )


@pytest.mark.parametrize(
    ("created_at", "accepted"),
    (
        pytest.param("2026-09-19T10:11:09.500000Z", True, id="fractional_end_inclusive"),
        pytest.param("2026-09-19T10:11:09.500001Z", False, id="fractional_end_not_widened"),
    ),
)
def test_owner_terminal_receipt_does_not_widen_fractional_step_end(
    created_at: str, accepted: bool,
) -> None:
    client, owner, download = _terminal_owner_fixture(
        created_at,
        create_completed_at="2026-09-19T10:11:09.500000Z",
        publish_started_at="2026-09-19T10:11:09.500000Z",
    )

    if accepted:
        receipt = load_owner_terminal_receipt(
            client=client, owner=owner, issue_number=323, download_archive=download,
        )
        assert receipt is not None
        assert receipt.created_at == datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_TERMINAL_TIME_INVALID"):
            load_owner_terminal_receipt(
                client=client, owner=owner, issue_number=323, download_archive=download,
            )


def test_owner_terminal_receipt_keeps_wrong_owner_rejected() -> None:
    client, owner, download = _terminal_owner_fixture(
        "2026-09-19T10:11:09.728262Z", wrong_owner=True,
    )

    with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_TERMINAL_PROVENANCE_INVALID"):
        load_owner_terminal_receipt(
            client=client, owner=owner, issue_number=323, download_archive=download,
        )


def test_non_atlas_authority_hash_mismatch_cannot_use_correction() -> None:
    client, owner, download = _terminal_owner_fixture("2026-09-19T10:11:09.728262Z")
    original = load_owner_terminal_receipt(client=client, owner=owner, issue_number=323,
                                           download_archive=download)
    assert original is not None
    with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_TERMINAL_CONFLICT"):
        resolve_atlas_terminal_correction(
            client=client, owner=owner, issue_number=323, original=original,
            expected_sha256="f" * 64, download_archive=download,
        )


def test_atlas_correction_lookup_requires_protected_publisher_and_exact_hash() -> None:
    _, owner, _ = _terminal_owner_fixture("2026-09-19T10:11:09.728262Z")
    corrected = CatalogTerminalReceiptV2.create(
        state="SUCCESS", reason_code="CATALOG_RUN_SUCCESS",
        request_sha256=owner.decision.request_sha256,
        submission_key_sha256=owner.decision.submission_key_sha256,
        campaign_key=owner.decision.campaign_key,
        prepared_receipt_sha256=owner.decision.prepared_receipt_sha256,
        engine_run_id=owner.run_id,
        run_url=f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{owner.run_id}",
        expected_recipe_count=209906, observed_recipe_count=209906,
        timing={}, recovered_block_ids=None, failure_class=None,
        result_science_sha256="18e614ffd8ef079fe7f6488db922d8bee33f539d07f37dc2de4bc1309c12df42",
        created_at=NOW,
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("catalog-terminal-receipt-v1.json", corrected.model_dump_json())
    raw = buffer.getvalue()
    correction_run = 999
    artifact = {
        "id": 1001, "name": "catalog-terminal-correction-378", "expired": False,
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "size_in_bytes": len(raw),
        "workflow_run": {"id": correction_run, "head_sha": "a" * 40,
                         "head_branch": "main", "repository_id": 1232647748,
                         "head_repository_id": 1232647748},
    }
    run = {
        "id": correction_run, "head_sha": "a" * 40, "head_branch": "main",
        "path": ".github/workflows/catalog-fast-authority-maintenance.yml",
        "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
        "repository": {"id": 1232647748}, "run_attempt": 1,
    }
    steps = [{"name": name, "number": index, "conclusion": "success"} for index, name in enumerate((
        "Reverify all original Atlas results", "Publish independently verified Atlas terminal",
        "Write current authority edition", "Publish current authority edition",
        "Verify initial authority through its production reader",
    ), 1)]

    class Client:
        repository = "trading-optimizer-lab-org/aurora"

        def stable_paginated(self, path: str, *, root: str):
            if root == "artifacts":
                return SimpleNamespace(stable=True, collection=SimpleNamespace(complete=True, rows=(artifact,)))
            assert root == "jobs"
            return SimpleNamespace(stable=True, collection=SimpleNamespace(complete=True, rows=(
                {"name": "bootstrap", "status": "completed", "conclusion": "success",
                 "run_id": correction_run, "run_attempt": 1, "head_sha": "a" * 40,
                 "steps": steps},
            )))

        def get_json(self, path: str):
            return run, None

    client = Client()
    assert _load_atlas_terminal_correction(
        client=client, owner=owner, expected_sha256=corrected.receipt_sha256,
        download_archive=lambda _: raw,
    ) == corrected
    run["head_branch"] = "unprotected"
    with pytest.raises(ValueError, match="CATALOG_FAST_ATLAS_TERMINAL_CORRECTION_INVALID"):
        _load_atlas_terminal_correction(client=client, owner=owner,
                                        expected_sha256=corrected.receipt_sha256,
                                        download_archive=lambda _: raw)


def test_pinned_unlaunched_terminal_binds_as_existing_without_science() -> None:
    request = _request()
    decision = _blocked_decision(request)
    owner = FastGateOwnerEvidence(123, {"id": 123}, decision, unlaunched_terminal=True)

    existing = bind_owner_terminal_receipt(
        owner=owner,
        receipt=_unlaunched_receipt(request),
    )

    assert owner.unlaunched_terminal is True
    assert existing.run_id == 123
    assert existing.state == "BLOCKED"
    assert existing.submission_key_sha256 == request.submission_key_sha256


@pytest.mark.parametrize("mutation", (
    "launch", "existing", "success", "engine", "url", "observed", "science",
    "request_hash", "prepared_hash", "before_expiry", "reason",
    "decision_not_expired", "before_decision",
))
def test_pinned_unlaunched_terminal_rejects_science_or_identity_drift(mutation: str) -> None:
    request = _request()
    decision = _blocked_decision(request)
    receipt_values: dict[str, object] = {}
    decision_values: dict[str, object] = {}
    if mutation == "launch":
        decision_values.update(state="QUEUED", selected_workers=1, launch_required=True)
    elif mutation == "existing":
        decision_values.update(existing_run_id=456)
    elif mutation == "success":
        receipt_values.update(
            state="SUCCESS", reason_code="CATALOG_RUN_SUCCESS", engine_run_id=123,
            run_url="https://github.com/trading-optimizer-lab-org/aurora/actions/runs/123",
            expected_recipe_count=1, observed_recipe_count=1,
            failure_class=None, result_science_sha256="e" * 64,
        )
    elif mutation == "engine":
        receipt_values.update(engine_run_id=123)
    elif mutation == "url":
        receipt_values.update(run_url="https://github.com/trading-optimizer-lab-org/aurora/actions/runs/123")
    elif mutation == "observed":
        receipt_values.update(observed_recipe_count=1)
    elif mutation == "science":
        receipt_values.update(result_science_sha256="e" * 64)
    elif mutation == "request_hash":
        receipt_values.update(request_sha256="1" * 64)
    elif mutation == "prepared_hash":
        receipt_values.update(prepared_receipt_sha256="1" * 64)
    elif mutation == "before_expiry":
        receipt_values.update(created_at=NOW - timedelta(seconds=2))
    elif mutation == "reason":
        receipt_values.update(reason_code="CATALOG_CONTROLLER_DISABLED")
    elif mutation == "decision_not_expired":
        decision_values.update(decided_at=NOW, expires_at=NOW)
    elif mutation == "before_decision":
        receipt_values.update(created_at=NOW - timedelta(seconds=1))
    receipt = _unlaunched_receipt(request, **receipt_values)
    owner = FastGateOwnerEvidence(123, {"id": 123},
        _blocked_decision(request, **decision_values), unlaunched_terminal=True)

    with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_TERMINAL_BINDING_INVALID"):
        bind_owner_terminal_receipt(owner=owner, receipt=receipt)


@pytest.mark.parametrize("run_id", (True, 0, -1))
def test_lookup_rejects_invalid_pinned_terminal_run_id(run_id: object) -> None:
    with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_LOOKUP_INVALID"):
        load_fast_gate_owner(
            client=SimpleNamespace(repository="trading-optimizer-lab-org/aurora"),
            issue_number=276, request=_request(), approved_commits=frozenset({COMMIT}),
            download_archive=lambda _artifact_id: b"", terminal_owner_run_id=run_id,
        )


def test_lookup_only_pins_a_proven_blocked_run_as_unlaunched_owner() -> None:
    request = _request()
    decision = _blocked_decision(request)
    context = {"request": request.model_dump(mode="json"), "issue_number": 276}
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("catalog-fast-request-context.json", json.dumps({
            **context, "content_sha256": canonical_sha256(context),
        }))
        archive.writestr("catalog-fast-decision-v1.json", decision.model_dump_json())
    raw = archive_buffer.getvalue()
    artifact = {
        "id": 11, "name": "catalog-fast-gate-276", "expired": False,
        "size_in_bytes": len(raw), "created_at": "2026-09-18T16:00:01Z",
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "workflow_run": {"id": 22, "head_sha": COMMIT, "head_branch": "main",
                         "repository_id": 123, "head_repository_id": 123},
    }
    run = {
        "id": 22, "run_attempt": 1, "head_sha": COMMIT, "head_branch": "main",
        "path": ".github/workflows/catalog-fast-controller.yml", "event": "issues",
        "repository": {"id": 123, "full_name": "trading-optimizer-lab-org/aurora"},
        "status": "completed", "conclusion": "failure",
    }
    jobs = ({
        "id": 33, "run_id": 22, "run_attempt": 1, "head_sha": COMMIT,
        "name": "gate", "status": "completed", "conclusion": "success",
        "steps": [
            {"name": "Publish the one gate decision", "number": 1, "status": "completed",
             "conclusion": "success", "started_at": "2026-09-18T16:00:00Z",
             "completed_at": "2026-09-18T16:00:02Z"},
            {"name": "Reserve the campaign atomically and expose QUEUED", "number": 2,
             "status": "completed", "conclusion": "skipped"},
        ],
    },)

    class Client:
        repository = "trading-optimizer-lab-org/aurora"

        def stable_paginated(self, path: str, *, root: str):
            if root == "artifacts":
                assert path.endswith("/actions/artifacts?name=catalog-fast-gate-276")
                return SimpleNamespace(stable=True, collection=SimpleNamespace(complete=True, rows=(artifact,)))
            assert path.endswith("/actions/runs/22/attempts/1/jobs")
            return SimpleNamespace(stable=True, collection=SimpleNamespace(complete=True, rows=jobs))

        def get_json(self, path: str):
            assert path.endswith("/actions/runs/22")
            return run, None

    def download(artifact_id: int) -> bytes:
        assert artifact_id == 11
        return raw

    ignored = load_fast_gate_owner(
        client=Client(), issue_number=276, request=request,
        approved_commits=frozenset({COMMIT}), download_archive=download,
    )
    assert ignored is None

    owner = load_fast_gate_owner(
        client=Client(), issue_number=276, request=request,
        approved_commits=frozenset({COMMIT}), download_archive=download,
        terminal_owner_run_id=22,
    )
    assert isinstance(owner, FastGateOwnerEvidence)
    assert owner.run_id == 22
    assert owner.unlaunched_terminal is True

    assert load_fast_gate_owner(
        client=Client(), issue_number=276, request=request,
        approved_commits=frozenset({COMMIT}), download_archive=download,
        terminal_owner_run_id=23,
    ) is None


def _metadata():
    # Shape and identifiers from the read-only run33910681070 observation.
    artifact = {
        "id": 9951225148, "name": "catalog-fast-gate-276", "size_in_bytes": 3487,
        "digest": "sha256:fc62dc8cf2807cb531c0996f77c21bc08e3d24effe775b074094fbfe400aae88",
        "expired": False, "created_at": "2026-09-04T19:21:04Z",
        "workflow_run": {"id": 33910681070, "head_sha": COMMIT, "head_branch": "main",
                         "repository_id": 1232647748, "head_repository_id": 1232647748},
    }
    run = {"id": 33910681070, "run_attempt": 1, "head_sha": COMMIT,
           "head_branch": "main", "path": ".github/workflows/catalog-fast-controller.yml",
           "event": "issues", "repository": {"id": 1232647748, "full_name": "trading-optimizer-lab-org/aurora"},
           "status": "completed", "conclusion": "failure"}
    jobs = [{"id": 101146103606, "run_id": run["id"], "run_attempt": 1,
             "head_sha": COMMIT, "name": "gate", "status": "completed", "conclusion": "success",
             "steps": [
                 {"name": "Publish the one gate decision", "number": 13, "status": "completed", "conclusion": "success",
                  "started_at": "2026-09-04T19:21:03Z", "completed_at": "2026-09-04T19:21:04Z"},
                 {"name": "Reserve the campaign atomically and expose QUEUED", "number": 15,
                  "status": "completed", "conclusion": "success",
                  "started_at": "2026-09-04T19:21:05Z", "completed_at": "2026-09-04T19:21:07Z"},
             ]}]
    return artifact, run, jobs


@pytest.mark.parametrize("mutation", (None, "unreserved", "wrong_attempt", "old_artifact", "foreign_repo", "wrong_commit", "ambiguous_gate", "expired"))
def test_owner_metadata_requires_exact_successful_reservation(mutation):
    artifact, run, jobs = _metadata()
    if mutation == "unreserved":
        jobs[0]["steps"][1]["conclusion"] = "failure"
    elif mutation == "wrong_attempt":
        jobs[0]["run_attempt"] = 2
    elif mutation == "old_artifact":
        artifact["created_at"] = "2026-09-03T19:21:04Z"
    elif mutation == "foreign_repo":
        run["repository"]["full_name"] = "other/aurora"
    elif mutation == "wrong_commit":
        run["head_sha"] = "b" * 40
    elif mutation == "ambiguous_gate":
        jobs.append(deepcopy(jobs[0]))
    elif mutation == "expired":
        artifact["expired"] = True
    if mutation is None:
        assert verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
            expected_issue_number=276, expected_commit=COMMIT) == 33910681070
        # Ownership exists even though the scientific run failed; no SUCCESS is returned.
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_PROVENANCE_INVALID"):
            verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
                expected_issue_number=276, expected_commit=COMMIT)


@pytest.mark.parametrize("mutation", (None, "missing_reference", "wrong_sha", "wrong_ref", "wrong_job", "foreign_caller"))
def test_reconciler_owner_requires_exact_reusable_binding(mutation):
    artifact, run, jobs = _metadata()
    run["path"] = ".github/workflows/catalog-request-reconciler.yml"
    run["event"] = "schedule"
    run["referenced_workflows"] = [{
        "path": f"trading-optimizer-lab-org/aurora/.github/workflows/catalog-fast-controller.yml@{COMMIT}",
        "sha": COMMIT, "ref": "refs/heads/main",
    }]
    jobs[0]["name"] = "catalog-request-276 / gate"
    if mutation == "missing_reference":
        run["referenced_workflows"] = []
    elif mutation == "wrong_sha":
        run["referenced_workflows"][0]["sha"] = "b" * 40
    elif mutation == "wrong_ref":
        run["referenced_workflows"][0]["ref"] = "refs/heads/other"
    elif mutation == "wrong_job":
        jobs[0]["name"] = "catalog-request-277 / gate"
    elif mutation == "foreign_caller":
        run["path"] = ".github/workflows/other.yml"
    if mutation is None:
        assert verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
            expected_issue_number=276, expected_commit=COMMIT) == 33910681070
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_PROVENANCE_INVALID"):
            verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
                expected_issue_number=276, expected_commit=COMMIT)


@pytest.mark.parametrize("mutation", [None, "lost_upload_response", "failed_verification", "missing_upload", "early_verification"])
def test_failed_gate_retains_only_a_verified_durable_reservation(mutation):
    artifact, run, jobs = _metadata()
    gate = jobs[0]
    gate["conclusion"] = "failure"
    gate["steps"][1].update(number=19, conclusion="failure", started_at="2026-09-04T19:21:11Z", completed_at="2026-09-04T19:21:12Z")
    gate["steps"] += [
        {"name": name, "number": number, "status": "completed", "conclusion": "success",
         "started_at": f"2026-09-04T19:21:{start:02}Z", "completed_at": f"2026-09-04T19:21:{start + 1:02}Z"}
        for name, number, start in [("Write current authority edition", 16, 5),
            ("Publish current authority edition", 17, 7),
            ("Verify the uploaded reservation before exposing QUEUED", 18, 9)]
    ]
    if mutation == "failed_verification":
        gate["steps"][-1]["conclusion"] = "failure"
    elif mutation == "lost_upload_response":
        gate["steps"][-2]["conclusion"] = "failure"
    elif mutation == "missing_upload":
        gate["steps"].pop(-2)
    elif mutation == "early_verification":
        gate["steps"][-1]["started_at"] = "2026-09-04T19:21:02Z"
    if mutation in {None, "lost_upload_response"}:
        assert verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
            expected_issue_number=276, expected_commit=COMMIT) == 33910681070
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_PROVENANCE_INVALID"):
            verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
                expected_issue_number=276, expected_commit=COMMIT)
