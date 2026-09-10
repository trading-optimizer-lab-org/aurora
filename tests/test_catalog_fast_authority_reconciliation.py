"""Focused checks for the fixed historical authority reconciliation."""

import copy
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Mapping, cast
import zipfile

import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import (
    FastAuthorityStateV1,
    bind_authority_edit,
)
from aurora.infra.sp500_megarun.catalog_fast_authority_github import (
    load_current_fast_authority,
    write_current_fast_authority,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubCollection,
    CatalogGitHubReadOnlyClient,
    CatalogStableInventory,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import verify_nonreserving_fast_gate_execution
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
from scripts.reconcile_catalog_fast_authority import (
    _validate_artifact,
    _validate_config,
    _validate_current,
    _validate_issue,
)
from scripts.publish_catalog_fast_authority import _publisher_job
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request


_HISTORICAL_GATE_STEPS = (
    (1, "Set up job", "completed", "success"),
    (2, "Start the admission time budget", "completed", "success"),
    (3, "Check out the exact protected branch", "completed", "success"),
    (4, "Bind the gate to the checked-out commit", "completed", "success"),
    (5, "Use the controller Python family", "completed", "success"),
    (6, "Install only the locked controller dependencies", "completed", "success"),
    (7, "Fetch exactly one existing request issue", "completed", "success"),
    (8, "Authenticate and inspect the signed request once", "completed", "success"),
    (9, "Record an invalid shaped request without running anything", "completed", "skipped"),
    (10, "Verify the current protected authority before admission", "completed", "success"),
    (11, "Restore the exact current PREPARED bundle", "completed", "success"),
    (12, "Run the one live admission gate and materialize the hot plan", "completed", "success"),
    (13, "Terminate one unexpected admission failure without retrying it", "completed", "skipped"),
    (14, "Stage the small immutable gate evidence", "completed", "success"),
    (15, "Publish the one gate decision", "completed", "success"),
    (16, "Publish the already-materialized sealed plan", "completed", "skipped"),
    (17, "Write current authority edition", "completed", "skipped"),
    (18, "Publish current authority edition", "completed", "skipped"),
    (19, "Check current authority publication", "completed", "skipped"),
    (20, "Recover missing authority publication", "completed", "skipped"),
    (21, "Verify the uploaded reservation before exposing QUEUED", "completed", "skipped"),
    (22, "Reserve the campaign atomically and expose QUEUED", "completed", "skipped"),
    (23, "Close one unexpected gate publication failure", "completed", "skipped"),
    (45, "Post Use the controller Python family", "completed", "success"),
    (46, "Post Check out the exact protected branch", "completed", "success"),
    (47, "Complete job", "completed", "success"),
)
_HISTORICAL_FINALIZE_STEPS = (
    (1, "Set up job", "completed", "success"),
    (2, "Check out the exact protected source", "completed", "success"),
    (3, "Use the controller Python family", "completed", "success"),
    (4, "Install only the locked controller dependencies", "completed", "success"),
    (5, "Download the gate decision", "completed", "success"),
    (6, "Download the unique engine outcome", "completed", "skipped"),
    (7, "Download terminal science only for a successful engine candidate", "completed", "skipped"),
    (8, "Fetch one bounded timing snapshot", "completed", "success"),
    (9, "Create exactly one terminal receipt", "completed", "success"),
    (10, "Publish the terminal receipt before changing the issue", "completed", "skipped"),
    (11, "Write current authority edition", "completed", "skipped"),
    (12, "Publish current authority edition", "completed", "skipped"),
    (13, "Check current authority publication", "completed", "skipped"),
    (14, "Recover missing authority publication", "completed", "skipped"),
    (15, "Verify the terminal publication before releasing the campaign", "completed", "skipped"),
    (16, "Publish the terminal state and release the reservation", "completed", "skipped"),
    (17, "Fail closed once and release a stuck reservation", "completed", "failure"),
    (33, "Post Use the controller Python family", "completed", "skipped"),
    (34, "Post Check out the exact protected source", "completed", "success"),
    (35, "Complete job", "completed", "success"),
)


def _historical_steps(shape: tuple[tuple[int, str, str, str], ...]) -> list[dict[str, Any]]:
    return [{"number": number, "name": name, "status": status, "conclusion": conclusion,
             "started_at": "2026-09-09T05:41:25Z", "completed_at": "2026-09-09T05:41:25Z"}
            for number, name, status, conclusion in shape]


def _historical_jobs(run: Mapping[str, Any], *, extra_job: bool = False,
                     extra_step: bool = False) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = [
        {"id": 102351822548, "name": "gate", "run_id": run["id"], "run_attempt": run["run_attempt"],
         "head_sha": run["head_sha"], "status": "completed", "conclusion": "success",
         "steps": _historical_steps(_HISTORICAL_GATE_STEPS)},
        {"id": 102351929745, "name": "engine", "run_id": run["id"], "run_attempt": run["run_attempt"],
         "head_sha": run["head_sha"], "status": "completed", "conclusion": "skipped", "steps": None},
        {"id": 102351929239, "name": "finalize", "run_id": run["id"], "run_attempt": run["run_attempt"],
         "head_sha": run["head_sha"], "status": "completed", "conclusion": "failure",
         "steps": _historical_steps(_HISTORICAL_FINALIZE_STEPS)},
    ]
    if extra_job:
        jobs.append({"id": 102351929746, "name": "evaluator", "run_id": run["id"],
                     "run_attempt": run["run_attempt"], "head_sha": run["head_sha"],
                     "status": "completed", "conclusion": "success", "steps": []})
    if extra_step:
        jobs[0]["steps"].append({"number": 24, "name": "Run evaluator", "status": "completed",
                                  "conclusion": "success", "started_at": "2026-09-09T05:41:25Z",
                                  "completed_at": "2026-09-09T05:41:25Z"})
    return jobs
from tests.test_catalog_fast_path import _request


def test_blocked_generation_one_gap_is_closed_without_science_or_reservation() -> None:
    empty = FastAuthorityStateV1.bootstrap(campaigns=())
    generation_two = _request(
        request_id="018f47a2-6e91-7c34-8000-000000000002",
        launch_generation=2,
        previous_terminal_request_sha256=_request().request_sha256,
    )
    with pytest.raises(ValueError, match="CATALOG_FAST_GENERATION_CONFLICT"):
        empty.reserve(request=generation_two, issue_number=281, run_id=101)

    reconciled = empty.reconcile_legacy_closure(
        request=_request(), issue_number=294, historical_run_id=34315861130,
        legacy_closure_evidence_sha256="d" * 64,
    )
    assert reconciled.revision == 2
    assert reconciled.campaigns[0].terminal_receipt_sha256 is None
    assert reconciled.campaigns[0].legacy_closure_evidence_sha256 == "d" * 64
    successor = reconciled.reserve(request=generation_two, issue_number=281, run_id=101)
    assert successor.campaigns[0].generation == 2
    assert successor.campaigns[0].owner_run_id == 101
    assert successor.campaigns[0].legacy_closure_evidence_sha256 is None


def test_reconciliation_is_idempotent_and_conflict_safe() -> None:
    request = _request()
    state = FastAuthorityStateV1.bootstrap(campaigns=()).reconcile_legacy_closure(
        request=request, issue_number=294, historical_run_id=34315861130,
        legacy_closure_evidence_sha256="d" * 64,
    )
    assert state.reconcile_legacy_closure(
        request=request, issue_number=294, historical_run_id=34315861130,
        legacy_closure_evidence_sha256="d" * 64,
    ) == state
    with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_RECONCILIATION_CONFLICT"):
        state.reconcile_legacy_closure(
            request=request, issue_number=295, historical_run_id=34315861130,
            legacy_closure_evidence_sha256="d" * 64,
        )


def test_nonreserving_execution_accepts_unpublished_local_receipt_creation() -> None:
    run = {"id": 34315861130, "run_attempt": 1, "head_sha": "a" * 40, "head_branch": "main"}
    gate, engine, finalize = _historical_jobs(run)
    verify_nonreserving_fast_gate_execution(
        jobs=(gate, engine, finalize), run=run,
        expected_gate_job_id=gate["id"], expected_engine_job_id=engine["id"],
        expected_finalize_job_id=finalize["id"],
    )


def test_reconciliation_config_is_pinned_and_hash_bound() -> None:
    with open("config/catalog_fast_authority_reconciliation_v1.json", encoding="utf-8") as stream:
        config = json.load(stream)
    assert _validate_config(config)["operation"] == "reconcile"
    config["gate"]["artifact"]["id"] += 1
    with pytest.raises(ValueError, match="CATALOG_FAST_RECONCILIATION_EVIDENCE_HASH_INVALID"):
        _validate_config(config)


def test_reconcile_cli_uses_real_actor_pin_and_controlled_github_snapshot(tmp_path, monkeypatch) -> None:
    """The CLI authenticates the protected actor, then stages one real transition."""
    import scripts.reconcile_catalog_fast_authority as command

    root = Path(__file__).resolve().parents[1]
    fixtures = Path(__file__).parent / "fixtures" / "catalog_fast_reconciliation"
    context = json.loads((fixtures / "catalog-fast-request-context.json").read_text(encoding="utf-8"))
    decision = json.loads((fixtures / "catalog-fast-decision-v1.json").read_text(encoding="utf-8"))
    request_body = "```json\n" + json.dumps(context["request"], sort_keys=True, separators=(",", ":")) + "\n```\n"
    issue = {
        "number": 294,
        "node_id": "I_kwDOSXi2RM8AAAABQZhMjQ",
        "title": "[AURORA CATALOG RUN REQUEST] 01a08088-f094-73f7-a8e8-0e7f03f8b195",
        "body": request_body,
        "state": "closed",
        "state_reason": "completed",
        "created_at": "2026-09-09T05:40:51Z",
        "updated_at": "2026-09-09T05:41:50Z",
        "closed_at": "2026-09-09T05:41:50Z",
        "closed_by": {"login": "github-actions[bot]"},
        "user": {"login": "aurora-catalog-request-f10c7b40e1[bot]"},
        "labels": [{"name": "catalog-run-terminal-v1"}],
    }
    historical_run = {
        "id": 34315861130, "run_attempt": 1, "path": ".github/workflows/catalog-fast-controller.yml",
        "event": "issues", "head_branch": "main", "head_sha": "476221d5efab95532f2eb7c720f7194a3df198c6",
        "status": "completed", "conclusion": "failure",
        "repository": {"id": 1232647748, "full_name": "trading-optimizer-lab-org/aurora"},
    }
    jobs = tuple(_historical_jobs(historical_run))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("catalog-fast-request-context.json", json.dumps(context, sort_keys=True, separators=(",", ":")))
        bundle.writestr("catalog-fast-decision-v1.json", json.dumps(decision, sort_keys=True, separators=(",", ":")))
    raw = archive.getvalue()
    artifact = {
        "id": 10090035553, "name": "catalog-fast-gate-294", "size_in_bytes": len(raw),
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "created_at": "2026-09-09T05:41:25Z",
        "expires_at": "2026-12-08T05:40:55Z", "expired": False,
        "workflow_run": {"id": 34315861130, "repository_id": 1232647748, "head_repository_id": 1232647748,
                          "head_branch": "main", "head_sha": historical_run["head_sha"]},
    }
    maintenance_run = {
        "id": 999, "run_attempt": 1, "head_sha": "a24aace1e3ba14c7b416d8da9f995542bbdb9de1",
        "head_branch": "main", "path": ".github/workflows/catalog-fast-authority-maintenance.yml",
        "event": "workflow_dispatch", "repository": {"full_name": "trading-optimizer-lab-org/aurora"},
    }
    maintenance_job = {"id": 888, "name": "bootstrap", "run_id": 999, "run_attempt": 1,
                       "head_sha": maintenance_run["head_sha"], "status": "in_progress"}

    class Client:
        repository = "trading-optimizer-lab-org/aurora"

        def __init__(self, repository, token):
            assert repository == self.repository
            assert token == "controlled-test-token"

        def get_json(self, path):
            if path.endswith("/issues/294"):
                return issue, None
            if path.endswith("/actions/runs/34315861130"):
                return historical_run, None
            if "/compare/476221d5efab95532f2eb7c720f7194a3df198c6..." in path:
                return {"status": "ahead", "base_commit": {"sha": historical_run["head_sha"]},
                        "merge_base_commit": {"sha": historical_run["head_sha"]}}, None
            if path.endswith("/actions/artifacts/10090035553"):
                return artifact, None
            if path.endswith("/actions/runs/34315861130/artifacts?per_page=100"):
                return {"total_count": 1, "artifacts": [artifact]}, None
            if path.endswith("/actions/runs/999"):
                return maintenance_run, None
            if path.endswith("/attempts/1/jobs?per_page=100&page=1"):
                return {"jobs": [maintenance_job]}, None
            raise AssertionError(path)

        def stable_paginated(self, path, *, root):
            assert path.endswith("/actions/runs/34315861130/attempts/1/jobs")
            collection = CatalogGitHubCollection(rows=tuple(jobs), ordered_ids=tuple(job["id"] for job in jobs),
                pages=(), complete=True, collection_sha256="jobs")
            return CatalogStableInventory(collection=collection, attempt=1, stable=True,
                                          observed_at=None, snapshot_sha256="snapshot")

    config = json.loads((root / "config/catalog_fast_authority_reconciliation_v1.json").read_text(encoding="utf-8"))
    config = copy.deepcopy(config)
    config["gate"]["artifact"].update({"size_in_bytes": len(raw), "digest": artifact["digest"]})
    config["evidence"]["legacy_closure_evidence_sha256"] = command.canonical_sha256(
        {key: config[key] for key in ("request", "issue", "gate", "context")}
    )
    monkeypatch.setattr(command, "_validate_config", lambda value: _validate_config(config))
    monkeypatch.setattr(command, "CatalogGitHubReadOnlyClient", Client)
    monkeypatch.setattr(command, "_download_owner_archive", lambda *_args: raw)
    monkeypatch.setattr(command, "_historical_owner_commit_approved", lambda *_args: True)
    current = FastAuthorityStateV1.bootstrap(campaigns=())
    live_body = {"value": current.to_body() + "\n<!-- AURORA_FAST_PUBLICATION:100:1:bootstrap:" + "a" * 40 + ":700 -->",
                 "edit_id": "E_current"}
    anchor = json.loads((root / "config/catalog_authority_anchor_v1.json").read_text(encoding="utf-8"))

    def read_live(_anchor):
        return {"data": {"repository": {"id": anchor["repository_node_id"], "nameWithOwner": "trading-optimizer-lab-org/aurora",
            "issue": {"id": anchor["issue_node_id"], "number": 161, "title": anchor["exact_title"], "state": "OPEN",
                "locked": False, "author": {"login": anchor["creator_login"]}, "createdAt": anchor["created_at"],
                "body": live_body["value"], "lastEditedAt": "2026-09-10T12:00:00Z",
                "editor": {"login": "github-actions[bot]"}, "userContentEdits": {"nodes": [
                    {"id": live_body["edit_id"], "editedAt": "2026-09-10T12:00:00Z", "deletedAt": None,
                     "editor": {"login": "github-actions[bot]"}}]}}}}}

    monkeypatch.setattr(command, "read_live_edit", read_live)
    monkeypatch.setattr(command, "load_current_fast_authority", lambda **kwargs: (kwargs["read_edit"]() and current))
    monkeypatch.setattr(command, "_validate_current", lambda *_args: None)

    def write_body(body):
        live_body["value"] = body
        live_body["edit_id"] = "E_reconciled"

    monkeypatch.setattr(command, "_write_body", lambda *_args: write_body(_args[-1]))
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    output = runner_temp / "publication.json"
    github_output = runner_temp / "github-output"
    github_output.touch()
    monkeypatch.setenv("GITHUB_REPOSITORY", "trading-optimizer-lab-org/aurora")
    monkeypatch.setenv("GH_TOKEN", "controlled-test-token")
    monkeypatch.setenv("CATALOG_PROTECTED_COMMIT_SHA", maintenance_run["head_sha"])
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_JOB", "bootstrap")
    monkeypatch.setenv("CATALOG_AUTHORITY_MAINTENANCE_OPERATION", "reconcile")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    assert command.main(["--repo-root", str(root), "--output", str(output), "--github-output", str(github_output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["state"]["campaigns"][0]["request"]["campaign_key"] == "catalog-fast-canary-v1"
    assert "authority_already_applied=false" in github_output.read_text(encoding="utf-8")


def _fixture_request(root: Path) -> CatalogRunRequestV1:
    fixtures = Path(__file__).parent / "fixtures" / "catalog_fast_reconciliation"
    context = json.loads((fixtures / "catalog-fast-request-context.json").read_text(encoding="utf-8"))
    actors = json.loads((root / "config/catalog_controller_actors_v1.json").read_text(encoding="utf-8"))
    key_path = root / actors["requester_public_key_path"]
    title = "[AURORA CATALOG RUN REQUEST] 01a08088-f094-73f7-a8e8-0e7f03f8b195"
    body = "```json\n" + json.dumps(context["request"], sort_keys=True, separators=(",", ":")) + "\n```\n"
    return parse_catalog_run_request(title, body, key_path.read_bytes())


def _authority_issue(anchor: dict[str, Any], body: str, edit_id: str, edited_at: str) -> dict[str, Any]:
    return {"data": {"repository": {"id": anchor["repository_node_id"],
        "nameWithOwner": anchor["repository"], "issue": {"id": anchor["issue_node_id"],
            "number": anchor["issue_number"], "title": anchor["exact_title"], "state": "OPEN",
            "locked": False, "author": {"login": anchor["creator_login"]},
            "createdAt": anchor["created_at"], "body": body, "lastEditedAt": edited_at,
            "editor": {"login": "github-actions[bot]"}, "userContentEdits": {"nodes": [{
                "id": edit_id, "editedAt": edited_at, "deletedAt": None,
                "editor": {"login": "github-actions[bot]"}}]}}}}}


def _authority_archive(publication_json: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("catalog-fast-authority-publication-v1.json", publication_json)
    return buffer.getvalue()


def _authority_artifact(*, artifact_id: int, run_id: int, job_id: int, phase: str,
                        commit: str, raw: bytes, created_at: str) -> dict[str, Any]:
    return {"id": artifact_id, "name": f"catalog-fast-authority-{run_id}-1-{phase}-{job_id}",
        "expired": False, "size_in_bytes": len(raw),
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "created_at": created_at,
        "workflow_run": {"id": run_id, "head_sha": commit, "head_branch": "main",
            "repository_id": 99, "head_repository_id": 99}}


def test_real_sp500_reconciliation_round_trip_preserves_high_water_and_reads_back() -> None:
    """The protected reader and writer, not test doubles, own the transition."""
    root = Path(__file__).resolve().parents[1]
    config = _validate_config(json.loads(
        (root / "config/catalog_fast_authority_reconciliation_v1.json").read_text(encoding="utf-8")
    ))
    anchor = json.loads((root / "config/catalog_authority_anchor_v1.json").read_text(encoding="utf-8"))
    current = FastAuthorityStateV1.model_validate_json(
        (Path(__file__).parent / "fixtures/catalog_fast_reconciliation/sp500-authority-state-v1.json").read_text(
            encoding="utf-8"
        )
    )
    _validate_current(current, config["current_authority"])
    assert current.state_sha256 == "32f5f233e1a53bcc50c7f1f05756d6fa1dcf308c2f130829b34ca88a389c3dcf"
    request = _fixture_request(root)
    candidate = current.reconcile_legacy_closure(
        request=request, issue_number=294, historical_run_id=34315861130,
        legacy_closure_evidence_sha256=config["evidence"]["legacy_closure_evidence_sha256"],
    )
    sp500 = next(row for row in current.campaigns if row.request.campaign_key == "sp500-optimized-catalog-v1")
    canary = next(row for row in candidate.campaigns if row.request.campaign_key == "catalog-fast-canary-v1")
    assert next(row for row in candidate.campaigns if row.request.campaign_key == "sp500-optimized-catalog-v1") == sp500
    assert canary.request.campaign_key == "catalog-fast-canary-v1"
    assert candidate.reconcile_legacy_closure(
        request=request, issue_number=294, historical_run_id=34315861130,
        legacy_closure_evidence_sha256=config["evidence"]["legacy_closure_evidence_sha256"],
    ) == candidate

    protected_commit = "a" * 40
    initial_run = {"id": 700, "run_attempt": 1, "head_sha": protected_commit,
        "head_branch": "main", "path": ".github/workflows/catalog-fast-authority-maintenance.yml",
        "event": "workflow_dispatch", "repository": {"id": 99, "node_id": anchor["repository_node_id"],
            "full_name": anchor["repository"]}}
    initial_job = {"id": 702, "name": "bootstrap", "run_id": 700, "run_attempt": 1,
        "head_sha": protected_commit, "status": "completed", "steps": [
            {"name": "Write current authority edition", "number": 5, "status": "completed",
             "conclusion": "success", "started_at": "2026-09-10T11:00:01Z", "completed_at": "2026-09-10T11:00:03Z"},
            {"name": "Publish current authority edition", "number": 6, "status": "completed",
             "conclusion": "success", "started_at": "2026-09-10T11:00:03Z", "completed_at": "2026-09-10T11:00:05Z"}]}
    initial_edit_id = "E_current"
    initial_body = current.to_body() + (
        "\n<!-- AURORA_FAST_PUBLICATION:700:1:bootstrap:" + protected_commit + ":702 -->"
    )
    initial_binding = bind_authority_edit(
        state=current, issue_node_id=anchor["issue_node_id"], edit_node_id=initial_edit_id,
    )
    archives = {703: _authority_archive(initial_binding.model_dump_json())}
    artifacts = {702: _authority_artifact(
        artifact_id=703, run_id=700, job_id=702, phase="bootstrap", commit=protected_commit,
        raw=archives[703], created_at="2026-09-10T11:00:04Z",
    )}
    writer_run = {"id": 999, "run_attempt": 1, "head_sha": protected_commit,
        "head_branch": "main", "path": ".github/workflows/catalog-fast-authority-maintenance.yml",
        "event": "workflow_dispatch", "repository": {"id": 99, "node_id": anchor["repository_node_id"],
            "full_name": anchor["repository"]}}
    writer_job = {"id": 888, "name": "bootstrap", "run_id": 999, "run_attempt": 1,
        "head_sha": protected_commit, "status": "in_progress", "steps": []}
    live = {"body": initial_body, "edit_id": initial_edit_id, "edited_at": "2026-09-10T11:00:02Z"}
    calls: list[str] = []

    class Client:
        repository = anchor["repository"]

        def get_json(self, path: str):
            calls.append(path)
            prefix = f"/repos/{self.repository}"
            if path == prefix + "/actions/runs/700":
                return initial_run, None
            if path == prefix + "/actions/runs/700/artifacts?name=catalog-fast-authority-700-1-bootstrap-702&per_page=100":
                return {"total_count": 1, "artifacts": [artifacts[702]]}, None
            if path == prefix + "/actions/jobs/702":
                return initial_job, None
            if path == prefix + "/actions/runs/999":
                return writer_run, None
            if path == prefix + "/actions/runs/999/attempts/1/jobs?per_page=100&page=1":
                return {"jobs": [writer_job]}, None
            if path == prefix + "/actions/runs/999/artifacts?name=catalog-fast-authority-999-1-reconcile-888&per_page=100":
                return {"total_count": 1, "artifacts": [artifacts[888]]}, None
            if path == prefix + "/actions/jobs/888":
                return writer_job, None
            raise AssertionError(path)

    client = cast(CatalogGitHubReadOnlyClient, Client())

    def read_edit() -> dict[str, object]:
        return _authority_issue(anchor, live["body"], live["edit_id"], live["edited_at"])

    observed = load_current_fast_authority(
        client=client, anchor=anchor, protected_commit=protected_commit,
        read_edit=read_edit, download_archive=lambda artifact_id: archives[artifact_id],
    )
    assert observed == current
    _validate_current(observed, config["current_authority"])
    published_job = _publisher_job(client, 999, 1, protected_commit, "reconcile")
    assert published_job == 888

    writes: list[str] = []

    def write_body(body: str) -> None:
        writes.append(body)
        live.update(body=body, edit_id="E_reconciled", edited_at="2026-09-10T12:00:02Z")

    publication = write_current_fast_authority(
        current=current, candidate=candidate, expected_edit_id=initial_edit_id, anchor=anchor,
        run_id=999, run_attempt=1, job_id=published_job, phase="reconcile", commit=protected_commit,
        read_edit=read_edit, write_body=write_body,
    )
    assert len(writes) == 1
    assert publication.state == candidate
    archives[889] = _authority_archive(publication.model_dump_json())
    artifacts[888] = _authority_artifact(
        artifact_id=889, run_id=999, job_id=888, phase="reconcile", commit=protected_commit,
        raw=archives[889], created_at="2026-09-10T12:00:04Z",
    )
    writer_job.update(status="completed", steps=[
        {"name": "Write current authority edition", "number": 5, "status": "completed",
         "conclusion": "success", "started_at": "2026-09-10T12:00:01Z", "completed_at": "2026-09-10T12:00:03Z"},
        {"name": "Publish current authority edition", "number": 6, "status": "completed",
         "conclusion": "success", "started_at": "2026-09-10T12:00:03Z", "completed_at": "2026-09-10T12:00:05Z"},
    ])
    readback = load_current_fast_authority(
        client=client, anchor=anchor, protected_commit=protected_commit,
        read_edit=read_edit, download_archive=lambda artifact_id: archives[artifact_id],
    )
    assert readback == candidate
    assert next(row for row in readback.campaigns if row.request.campaign_key == "sp500-optimized-catalog-v1") == sp500
    assert next(row for row in readback.campaigns if row.request.campaign_key == "catalog-fast-canary-v1").legacy_closure_evidence_sha256 is not None

    generation_two = request.model_validate({**request.model_dump(mode="json"),
        "request_id": "018f47a2-6e91-7c34-8000-000000000002", "launch_generation": 2,
        "previous_terminal_request_sha256": request.request_sha256})
    successor = candidate.reserve(request=generation_two, issue_number=295, run_id=1000)
    assert next(row for row in successor.campaigns if row.request.campaign_key == "sp500-optimized-catalog-v1") == sp500
    assert next(row for row in successor.campaigns if row.request.campaign_key == "catalog-fast-canary-v1").request.launch_generation == 2
    assert len(calls) >= 7


def test_write_current_lost_response_is_confirmed_without_a_second_post() -> None:
    """A committed body after a lost HTTP acknowledgement must not be retried."""
    root = Path(__file__).resolve().parents[1]
    anchor = json.loads((root / "config/catalog_authority_anchor_v1.json").read_text(encoding="utf-8"))
    current = FastAuthorityStateV1.bootstrap(campaigns=())
    request = _request()
    candidate = current.reconcile_legacy_closure(
        request=request, issue_number=294, historical_run_id=34315861130, legacy_closure_evidence_sha256="d" * 64,
    )
    commit = "a" * 40
    live = {"body": current.to_body() + f"\n<!-- AURORA_FAST_PUBLICATION:700:1:bootstrap:{commit}:702 -->",
        "edit_id": "E_before", "edited_at": "2026-09-10T11:00:02Z"}
    writes = 0

    def read_edit() -> dict[str, object]:
        return _authority_issue(anchor, live["body"], live["edit_id"], live["edited_at"])

    def lost_write(body: str) -> None:
        nonlocal writes
        writes += 1
        live.update(body=body, edit_id="E_after", edited_at="2026-09-10T12:00:02Z")
        raise OSError("response lost after server commit")

    binding = write_current_fast_authority(
        current=current, candidate=candidate, expected_edit_id="E_before", anchor=anchor,
        run_id=999, run_attempt=1, job_id=888, phase="reconcile", commit=commit,
        read_edit=read_edit, write_body=lost_write,
    )
    assert writes == 1
    assert binding.edit_node_id == "E_after"


@pytest.mark.parametrize("field", ["revision", "state_sha256"])
def test_reconciliation_rejects_changed_pinned_current(field: str) -> None:
    root = Path(__file__).resolve().parents[1]
    config = _validate_config(json.loads(
        (root / "config/catalog_fast_authority_reconciliation_v1.json").read_text(encoding="utf-8")
    ))
    current = FastAuthorityStateV1.bootstrap(campaigns=()).reserve(
        request=_request(), issue_number=276, run_id=33910681070,
    )
    if field == "revision":
        altered = current.model_copy(update={"revision": current.revision + 1})
    else:
        altered = current.model_copy(update={"state_sha256": "f" * 64})
    with pytest.raises(ValueError, match="CATALOG_FAST_RECONCILIATION_CURRENT_CHANGED"):
        _validate_current(altered, config["current_authority"])


def test_reconciliation_rejects_edit_concurrency_before_post() -> None:
    root = Path(__file__).resolve().parents[1]
    anchor = json.loads((root / "config/catalog_authority_anchor_v1.json").read_text(encoding="utf-8"))
    current = FastAuthorityStateV1.bootstrap(campaigns=())
    candidate = current.reconcile_legacy_closure(
        request=_request(), issue_number=294, historical_run_id=34315861130, legacy_closure_evidence_sha256="d" * 64,
    )
    commit = "a" * 40
    reads = 0

    def read_edit() -> dict[str, object]:
        nonlocal reads
        reads += 1
        edit = "E_concurrent"
        body = current.to_body() + f"\n<!-- AURORA_FAST_PUBLICATION:700:1:bootstrap:{commit}:702 -->"
        return _authority_issue(anchor, body, edit, "2026-09-10T11:00:02Z")

    posts = 0

    def write_body(_body: str) -> None:
        nonlocal posts
        posts += 1

    with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_WRITE_CONFLICT"):
        write_current_fast_authority(
            current=current, candidate=candidate, expected_edit_id="E_before", anchor=anchor,
            run_id=999, run_attempt=1, job_id=888, phase="reconcile", commit=commit,
            read_edit=read_edit, write_body=write_body,
        )
    assert posts == 0


@pytest.mark.parametrize("defect", ["engine_success", "reservation_success", "extra_job", "extra_step"])
def test_nonreserving_execution_rejects_engine_or_reservation(defect: str) -> None:
    run = {"id": 34315861130, "run_attempt": 1, "head_sha": "a" * 40, "head_branch": "main"}
    jobs = _historical_jobs(run, extra_job=defect == "extra_job", extra_step=defect == "extra_step")
    gate, engine, finalize = jobs[:3]
    if defect == "engine_success":
        engine["conclusion"] = "success"
    if defect == "reservation_success":
        next(step for step in gate["steps"] if step["name"] == "Reserve the campaign atomically and expose QUEUED")["conclusion"] = "success"
    with pytest.raises(ValueError, match="CATALOG_FAST_NONRESERVING_EXECUTION_INVALID"):
        verify_nonreserving_fast_gate_execution(
            jobs=jobs, run=run, expected_gate_job_id=102351822548,
            expected_engine_job_id=102351929745, expected_finalize_job_id=102351929239,
        )


def test_reconciliation_rejects_invalid_actor_and_altered_artifact() -> None:
    root = Path(__file__).resolve().parents[1]
    config = _validate_config(json.loads(
        (root / "config/catalog_fast_authority_reconciliation_v1.json").read_text(encoding="utf-8")
    ))
    issue = {"number": 294, "node_id": config["request"]["issue_node_id"], "title": config["request"]["title"],
        "state": "closed", "state_reason": "completed", "created_at": config["issue"]["created_at"],
        "updated_at": config["issue"]["updated_at"], "closed_at": config["issue"]["closed_at"],
        "user": {"login": "attacker"}, "closed_by": {"login": "github-actions[bot]"},
        "labels": [{"name": "catalog-run-terminal-v1"}]}
    with pytest.raises(ValueError, match="CATALOG_FAST_RECONCILIATION_ISSUE_CLOSURE_INVALID"):
        _validate_issue(issue, {**config["request"], **config["issue"]})
    artifact = dict(config["gate"]["artifact"])
    artifact["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="CATALOG_FAST_RECONCILIATION_ARTIFACT_INVALID"):
        _validate_artifact(artifact, config["gate"]["artifact"])


def test_maintenance_choice_is_compared_through_the_existing_job_environment() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/catalog-fast-authority-maintenance.yml").read_text(
        encoding="utf-8"
    )
    assert "          - bootstrap\n          - reconcile" in workflow
    assert "CATALOG_AUTHORITY_MAINTENANCE_OPERATION: ${{ inputs.operation }}" in workflow
    assert 'if [[ "$CATALOG_AUTHORITY_MAINTENANCE_OPERATION" == "reconcile" ]]; then' in workflow
    assert 'if [[ "${{ inputs.operation }}" == "reconcile" ]]; then' not in workflow
    assert workflow.count("${{ inputs.operation }}") == 1
    assert "publish_catalog_fast_authority_bootstrap.py" in workflow
    assert "reconcile_catalog_fast_authority.py" in workflow
