"""Real publication parser/provenance checks; only GitHub transport is controlled."""

import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import (
    FastAuthorityStateV1, bind_authority_edit,
)


def publication_transport(*, state=None, phase="bootstrap", run_id=123, job_id=789, edit_id="E_current", publication_bytes=None, reusable_issue_number=None):
    state = state if state is not None else FastAuthorityStateV1.bootstrap(campaigns=())
    anchor = {"production_enabled": True, "repository": "trading-optimizer-lab-org/aurora",
        "repository_node_id": "R_repo", "issue_number": 161, "issue_node_id": "I_anchor",
        "exact_title": "ledger", "creator_login": "creator", "created_at": "2026-08-23T16:31:19Z"}
    body = state.to_body() + f"\n<!-- AURORA_FAST_PUBLICATION:{run_id}:1:{phase}:" + "a" * 40 + f":{job_id} -->"
    edit = {"data": {"repository": {"id": "R_repo", "nameWithOwner": anchor["repository"],
        "issue": {"id": "I_anchor", "number": 161, "title": "ledger", "state": "OPEN",
            "locked": False, "author": {"login": "creator"}, "createdAt": anchor["created_at"],
            "body": body, "lastEditedAt": "2026-09-05T12:00:02Z", "editor": {"login": "github-actions[bot]"},
            "userContentEdits": {"nodes": [{"id": edit_id, "editedAt": "2026-09-05T12:00:02Z",
                "deletedAt": None, "editor": {"login": "github-actions[bot]"}}]}}}}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("catalog-fast-authority-publication-v1.json", publication_bytes if publication_bytes is not None else bind_authority_edit(
            state=state, issue_node_id="I_anchor", edit_node_id=edit_id).model_dump_json())
    raw = buffer.getvalue()
    artifact = {"id": 456, "name": f"catalog-fast-authority-{run_id}-1-{phase}-{job_id}", "expired": False,
        "size_in_bytes": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "created_at": "2026-09-05T12:00:04Z", "workflow_run": {"id": run_id,
            "head_sha": "a" * 40, "head_branch": "main", "repository_id": 99, "head_repository_id": 99}}
    run = {"id": run_id, "run_attempt": 1, "head_sha": "a" * 40, "head_branch": "main",
        "path": ".github/workflows/catalog-fast-authority-maintenance.yml" if phase == "bootstrap" else ".github/workflows/catalog-fast-controller.yml",
        "event": "workflow_dispatch" if phase == "bootstrap" else "issues",
        "repository": {"id": 99, "node_id": "R_repo", "full_name": anchor["repository"]}}
    job = {"id": job_id, "name": phase, "run_id": run_id, "run_attempt": 1, "head_sha": "a" * 40,
        "status": "completed", "steps": [
            {"name": "Write current authority edition", "number": 5, "status": "completed", "conclusion": "success",
                "started_at": "2026-09-05T12:00:01Z", "completed_at": "2026-09-05T12:00:03Z"},
            {"name": "Publish current authority edition", "number": 6, "status": "completed", "conclusion": "success",
                "started_at": "2026-09-05T12:00:03Z", "completed_at": "2026-09-05T12:00:05Z"}]}
    if reusable_issue_number is not None:
        run.update(path=".github/workflows/catalog-request-reconciler.yml", event="schedule",
            referenced_workflows=[{"path": anchor["repository"] + "/.github/workflows/catalog-fast-controller.yml@" + "a" * 40,
                "sha": "a" * 40, "ref": "refs/heads/main"}])
        job["name"] = f"catalog-request-{reusable_issue_number} / {phase}"
    calls = []

    class Client:
        repository = anchor["repository"]

        def get_json(self, path):
            calls.append(path)
            prefix = "/repos/" + self.repository
            responses = {
                prefix + f"/actions/runs/{run_id}": run,
                prefix + f"/actions/runs/{run_id}/artifacts?name=catalog-fast-authority-{run_id}-1-{phase}-{job_id}&per_page=100": {"total_count": 1, "artifacts": [artifact]},
                prefix + f"/actions/jobs/{job_id}": job,
            }
            return responses[path], None

    return SimpleNamespace(state=state, anchor=anchor, edit=edit, raw=raw, artifact=artifact,
        run=run, job=job, client=Client(), calls=calls)


@pytest.mark.parametrize("defect", [None, "large_run", "restored_edit", "wrong_source", "failed_write", "failed_upload", "lost_upload_response",
    "missing_artifact", "corrupt_archive", "other_anchor", "changed_during_read", "recovered_upload"])
def test_current_publication_requires_exact_live_edit_and_producer(defect):
    from aurora.infra.sp500_megarun.catalog_fast_authority_github import load_current_fast_authority

    fixture = publication_transport()
    if defect == "large_run":
        original_get = fixture.client.get_json

        def large_get(path):
            payload, response = original_get(path)
            if path.endswith("/jobs?per_page=100"):
                return {"total_count": 301, "jobs": [fixture.job] + [{"name": "other"}] * 99}, response
            return payload, response

        fixture.client.get_json = large_get
    issue = fixture.edit["data"]["repository"]["issue"]
    if defect == "restored_edit":
        issue["userContentEdits"]["nodes"][0]["id"] = "E_restored"
    elif defect == "wrong_source":
        fixture.run["head_sha"] = "b" * 40
    elif defect == "failed_write":
        fixture.job["steps"][0]["conclusion"] = "failure"
    elif defect == "failed_upload":
        fixture.job["steps"][1]["conclusion"] = "failure"
        fixture.artifact["name"] = "unrelated"
    elif defect == "lost_upload_response":
        fixture.job["steps"][1]["conclusion"] = "failure"
    elif defect == "recovered_upload":
        fixture.job["steps"][1]["conclusion"] = "failure"
        fixture.artifact["created_at"] = "2026-09-05T12:00:08Z"
        fixture.job["steps"].append({"name": "Recover missing authority publication", "number": 8,
            "status": "completed", "conclusion": "success", "started_at": "2026-09-05T12:00:07Z",
            "completed_at": "2026-09-05T12:00:09Z"})
    elif defect == "missing_artifact":
        fixture.artifact["name"] = "unrelated"
    elif defect == "corrupt_archive":
        fixture.raw += b"corrupt"
    elif defect == "other_anchor":
        issue["id"] = "I_other"
    reads = 0

    def read_edit():
        nonlocal reads
        reads += 1
        if defect == "changed_during_read" and reads == 2:
            issue["userContentEdits"]["nodes"][0]["id"] = "E_later"
        return json.loads(json.dumps(fixture.edit))

    def load():
        return load_current_fast_authority(client=fixture.client, anchor=fixture.anchor,
            protected_commit="a" * 40, read_edit=read_edit, download_archive=lambda _: fixture.raw)

    if defect in {None, "large_run", "lost_upload_response", "recovered_upload"}:
        result = load()
        assert result.revision == 1
        assert result.campaigns == ()
        assert len(fixture.calls) == 3
        assert reads == 2
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_"):
            load()
