"""Private handoff bindings and fresh source checks; no live GitHub transport."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import CheckpointRecoveryOwnerAuthenticationV1
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import verify_checkpoint_failure_owner
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
from scripts import catalog_fast_gate_handoff as handoff
from tests.test_catalog_checkpoint_recovery_authority import _case as successor_case
from tests.test_catalog_checkpoint_recovery_owner import _case as owner_case
from tests.test_catalog_fast_authority_github import publication_transport
from tests.test_catalog_fast_path import NOW


def stage(tmp_path, monkeypatch, *, recovery=False):
    fixture = publication_transport()
    for key, value in {"RUNNER_TEMP": str(tmp_path), "GITHUB_ACTIONS": "true",
            "GITHUB_REF": "refs/heads/main", "GITHUB_JOB": "gate", "GITHUB_RUN_ID": "800",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": fixture.client.repository,
            "CATALOG_PROTECTED_COMMIT_SHA": "a" * 40}.items():
        monkeypatch.setenv(key, value)
    request = successor_case()[2].request
    context = {"request": request.model_dump(mode="json"), "issue_number": 342,
               "protected_commit_sha": "a" * 40}
    context["content_sha256"] = canonical_sha256(context)
    decision = CatalogFastLaunchDecisionV1.create(state="QUEUED", reason_code="CATALOG_READY",
        request_sha256=request.request_sha256, submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key, prepared_receipt_sha256="1" * 64,
        selected_workers=30, launch_required=True, existing_run_id=None,
        decided_at=NOW, expires_at=NOW + timedelta(minutes=5))
    profile, owner = owner_case()
    owner = replace(owner, jobs=(*owner.jobs, {"id": 99, "name": "unrelated-worker"}))
    proof = verify_checkpoint_failure_owner(profile=profile, owner=owner, terminal=None)
    authenticated = CheckpointRecoveryOwnerAuthenticationV1(owner, proof) if recovery else None
    handoff.stage_authority(state=fixture.state, edit=fixture.edit, anchor=fixture.anchor, commit="a" * 40)
    handoff.stage_admission(anchor=fixture.anchor, commit="a" * 40, authority=fixture.state,
        context=context, decision=decision, authenticated=authenticated, profile=profile if recovery else None)
    if recovery:
        saved = json.loads((tmp_path / ".catalog-fast-gate-handoff/admission.json").read_bytes())
        assert [job["name"] for job in saved["recovery"]["owner"]["jobs"]] == ["finalize"]
    monkeypatch.setattr(handoff, "load_checkpoint_recovery_profile", lambda *args: profile if recovery else None)
    reads = []

    def signed(client, root, actual_profile):
        assert actual_profile is profile
        reads.append("source-signature")
    monkeypatch.setattr(handoff, "_read_signed_request", signed)

    class Client:
        repository = fixture.client.repository
        run_reads = 0
        terminal_rows = ()
        stable = True
        complete = True
        after_run = None
        run = deepcopy(owner.run)

        def get_json(self, path):
            assert path == f"/repos/{self.repository}/actions/runs/{profile.source_run_id}"
            self.run_reads += 1
            reads.append("run")
            return deepcopy(self.after_run if self.run_reads > 1 and self.after_run else self.run), None

        def stable_paginated(self, path, *, root):
            assert path == (f"/repos/{self.repository}/actions/runs/{profile.source_run_id}/artifacts"
                            f"?name=catalog-terminal-receipt-{profile.source_request_sha256}")
            assert root == "artifacts"
            reads.append("terminal-inventory")
            return SimpleNamespace(stable=self.stable,
                collection=SimpleNamespace(complete=self.complete, rows=self.terminal_rows))

    client = Client()
    def no_download(_):
        raise AssertionError("source absence must not redownload historical archives")
    args = dict(root=tmp_path, anchor=fixture.anchor, commit="a" * 40,
                context=context, decision=decision, client=client,
                read_edit=lambda: fixture.edit, download_archive=no_download)
    return fixture, profile, proof, client, reads, args


def test_handoff_is_single_use_and_preserves_authenticated_state(tmp_path, monkeypatch):
    fixture, _, _, _, reads, args = stage(tmp_path, monkeypatch)
    current, edit_id, proof = handoff.consume_admission(**args)
    assert current == fixture.state and edit_id == "E_current" and proof is None
    assert reads == []
    with pytest.raises(FileExistsError):
        handoff.consume_admission(**args)


@pytest.mark.parametrize("defect", ["run", "attempt", "job", "commit", "repository", "anchor",
    "context", "decision", "edit", "bytes", "missing", "authority_swap", "symlink"])
def test_handoff_rejects_foreign_or_changed_evidence(tmp_path, monkeypatch, defect):
    fixture, _, _, _, reads, args = stage(tmp_path, monkeypatch)
    fields = {"run": ("GITHUB_RUN_ID", "801"), "attempt": ("GITHUB_RUN_ATTEMPT", "2"),
              "job": ("GITHUB_JOB", "finalize"), "repository": ("GITHUB_REPOSITORY", "other/repo"),
              "commit": ("CATALOG_PROTECTED_COMMIT_SHA", "b" * 40)}
    directory = tmp_path / ".catalog-fast-gate-handoff"
    if defect in fields:
        monkeypatch.setenv(*fields[defect])
    elif defect == "anchor":
        args["anchor"] = {**fixture.anchor, "issue_node_id": "I_foreign"}
    elif defect == "context":
        args["context"] = {**args["context"], "issue_number": 343}
    elif defect == "decision":
        args["decision"] = CatalogFastLaunchDecisionV1.create(
            **{**args["decision"].model_dump(exclude={"decision_sha256"}), "prepared_receipt_sha256": "2" * 64})
    elif defect == "edit":
        fixture.edit["data"]["repository"]["issue"]["userContentEdits"]["nodes"][0]["id"] = "E_other"
    elif defect == "bytes":
        path = directory / "admission.json"
        data = json.loads(path.read_bytes())
        data["issue_number"] = 343
        path.write_text(json.dumps(data))
    elif defect == "missing":
        (directory / "admission.json").unlink()
    elif defect == "authority_swap":
        path = directory / "authority.json"
        data = json.loads(path.read_bytes())
        data["edition"][1] = "E_other"
        data["content_sha256"] = canonical_sha256({k: v for k, v in data.items() if k != "content_sha256"})
        path.write_text(json.dumps(data))
    elif defect == "symlink":
        path = directory / "admission.json"
        target = directory / "foreign.json"
        path.rename(target)
        try:
            path.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation unavailable")
    with pytest.raises((ValueError, OSError)):
        handoff.consume_admission(**args)
    assert reads == []


@pytest.mark.parametrize("defect", [None, "attempt", "running", "success", "head", "after_attempt",
                                  "terminal", "unstable", "incomplete", "proof", "profile"])
def test_source_state_and_terminal_absence_are_fresh_without_redownload(tmp_path, monkeypatch, defect):
    _, profile, proof, client, reads, args = stage(tmp_path, monkeypatch, recovery=True)
    if defect == "attempt":
        client.run["run_attempt"] = 2
    elif defect == "running":
        client.run["status"] = "in_progress"
    elif defect == "success":
        client.run["conclusion"] = "success"
    elif defect == "head":
        client.run["head_sha"] = "c" * 40
    elif defect == "after_attempt":
        client.after_run = {**client.run, "run_attempt": 2}
    elif defect == "terminal":
        client.terminal_rows = ({"id": 77},)
    elif defect == "unstable":
        client.stable = False
    elif defect == "incomplete":
        client.complete = False
    elif defect in {"proof", "profile"}:
        path = tmp_path / ".catalog-fast-gate-handoff/admission.json"
        data = json.loads(path.read_bytes())
        if defect == "proof":
            data["recovery"]["proof"]["source_run_id"] = 99
        else:
            data["recovery"]["profile_sha256"] = "f" * 64
        data["content_sha256"] = canonical_sha256({k: v for k, v in data.items() if k != "content_sha256"})
        path.write_text(json.dumps(data))
    if defect:
        with pytest.raises(ValueError):
            handoff.consume_admission(**args)
    else:
        _, _, actual = handoff.consume_admission(**args)
        assert actual == proof and actual.source_run_id == profile.source_run_id
        assert reads == ["source-signature", "run", "terminal-inventory", "run"]


def test_authority_handoff_cannot_be_overwritten(tmp_path, monkeypatch):
    fixture, _, _, _, _, _ = stage(tmp_path, monkeypatch)
    with pytest.raises(FileExistsError):
        handoff.stage_authority(state=fixture.state, edit=fixture.edit, anchor=fixture.anchor, commit="a" * 40)
