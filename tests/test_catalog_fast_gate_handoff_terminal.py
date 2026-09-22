from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import zipfile

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import (
    CheckpointRecoveryOwnerAuthenticationV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
    verify_checkpoint_failure_owner,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastLaunchDecisionV1,
    CatalogTerminalReceiptV1,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence
from scripts import catalog_fast_gate_handoff as handoff
from tests.test_catalog_checkpoint_recovery_terminal_owner import (
    _terminal_case as owner_terminal_case,
)
from tests.test_catalog_cloud_authority import signed_request
from tests.test_catalog_fast_authority_github import publication_transport
from tests.test_catalog_fast_path import NOW


SOURCE_REQUEST_SHA256 = "f337320f4ebb3c863581b632e18e15eeba364621363310ed31fc120677f84fe0"
SOURCE_ISSUE_NUMBER = 353
SOURCE_RUN_ID = 35708742966
SOURCE_RUN_ATTEMPT = 1
SOURCE_COMMIT = CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA
CURRENT_COMMIT = "a" * 40


def _terminal_archive(receipt: CatalogTerminalReceiptV1) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("catalog-terminal-receipt-v1.json", receipt.model_dump_json())
    return buffer.getvalue()


def _profile9_terminal_case() -> tuple[SimpleNamespace, FastGateOwnerEvidence, CatalogTerminalReceiptV1, CheckpointRecoveryOwnerProofV1]:
    profile, base_owner, _ = owner_terminal_case()
    base_decision = base_owner.decision
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED",
        reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256=SOURCE_REQUEST_SHA256,
        submission_key_sha256=base_decision.submission_key_sha256,
        campaign_key=base_decision.campaign_key,
        prepared_receipt_sha256=base_decision.prepared_receipt_sha256,
        selected_workers=base_decision.selected_workers,
        launch_required=True,
        existing_run_id=None,
        decided_at=base_decision.decided_at,
        expires_at=base_decision.expires_at,
    )
    profile.source_issue_number = SOURCE_ISSUE_NUMBER
    profile.source_run_id = SOURCE_RUN_ID
    profile.source_run_attempt = SOURCE_RUN_ATTEMPT
    profile.source_request_sha256 = SOURCE_REQUEST_SHA256
    profile.source_protected_commit_sha = SOURCE_COMMIT
    profile.source_generation = 8
    profile.target_generation = 9
    profile.expected_total_count = 37258
    profile.source_plan_bindings = {
        **profile.source_plan_bindings,
        "request_sha256": SOURCE_REQUEST_SHA256,
        "protected_commit_sha": SOURCE_COMMIT,
        "decision_sha256": decision.decision_sha256,
    }

    run = deepcopy(dict(base_owner.run))
    run.update(
        {
            "id": SOURCE_RUN_ID,
            "run_attempt": SOURCE_RUN_ATTEMPT,
            "head_sha": SOURCE_COMMIT,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "failure",
            "path": ".github/workflows/catalog-fast-controller.yml",
            "repository": {"id": 1232647748, "full_name": "trading-optimizer-lab-org/aurora"},
        }
    )
    jobs = deepcopy(base_owner.jobs)
    finalizer = jobs[0]
    finalizer.update(
        {
            "run_id": SOURCE_RUN_ID,
            "run_attempt": SOURCE_RUN_ATTEMPT,
            "head_sha": SOURCE_COMMIT,
            "status": "completed",
            "conclusion": "success",
        }
    )
    for step in finalizer["steps"]:
        step["status"] = "completed"
        step["conclusion"] = "success"
    create_step = next(
        step for step in finalizer["steps"] if step["name"] == "Create exactly one terminal receipt"
    )
    create_step.update(
        {
            "number": 9,
            "started_at": "2026-09-20T10:11:09Z",
            "completed_at": "2026-09-20T10:11:09.728262Z",
        }
    )
    publish_step = next(
        step
        for step in finalizer["steps"]
        if step["name"] == "Publish the terminal receipt before changing the issue"
    )
    publish_step.update(
        {
            "number": 10,
            "started_at": "2026-09-20T10:11:09.800000Z",
            "completed_at": "2026-09-20T10:11:10Z",
        }
    )
    owner = replace(
        base_owner,
        run_id=SOURCE_RUN_ID,
        run=run,
        decision=decision,
        jobs=tuple(jobs),
    )
    terminal = CatalogTerminalReceiptV1.create(
        state="BLOCKED",
        reason_code="CATALOG_REDUCTION_FAILED",
        request_sha256=decision.request_sha256,
        submission_key_sha256=decision.submission_key_sha256,
        campaign_key=decision.campaign_key,
        prepared_receipt_sha256=decision.prepared_receipt_sha256,
        engine_run_id=SOURCE_RUN_ID,
        run_url=f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{SOURCE_RUN_ID}",
        expected_recipe_count=37258,
        observed_recipe_count=0,
        queue_seconds=0.0,
        preparation_seconds=0.0,
        computation_seconds=0.0,
        recovery_seconds=0.0,
        reduction_seconds=0.0,
        recovered_block_count=0,
        failure_class="infrastructure",
        result_science_sha256=None,
        created_at=datetime(2026, 9, 20, 10, 11, 9, 728262, tzinfo=timezone.utc),
    )
    profile.source_terminal_receipt_sha256 = terminal.receipt_sha256
    proof = verify_checkpoint_failure_owner(profile=profile, owner=owner, terminal=terminal)
    return profile, owner, terminal, proof


def _stage_profile9_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fixture = publication_transport()
    for key, value in {
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_ACTIONS": "true",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_JOB": "gate",
        "GITHUB_RUN_ID": "800",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": fixture.client.repository,
        "CATALOG_PROTECTED_COMMIT_SHA": CURRENT_COMMIT,
    }.items():
        monkeypatch.setenv(key, value)

    profile, owner, terminal, proof = _profile9_terminal_case()
    request = signed_request(
        request_id="018f47a2-6e91-7c34-8000-000000000009",
        launch_generation=9,
        previous_terminal_request_sha256=SOURCE_REQUEST_SHA256,
    )
    context = {
        "request": request.model_dump(mode="json"),
        "issue_number": 354,
        "protected_commit_sha": CURRENT_COMMIT,
    }
    context["content_sha256"] = canonical_sha256(context)
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED",
        reason_code="CATALOG_READY",
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256="1" * 64,
        selected_workers=60,
        launch_required=True,
        existing_run_id=None,
        decided_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    authenticated = CheckpointRecoveryOwnerAuthenticationV1(owner, proof, terminal)
    handoff.stage_authority(
        state=fixture.state,
        edit=fixture.edit,
        anchor=fixture.anchor,
        commit=CURRENT_COMMIT,
    )
    handoff.stage_admission(
        anchor=fixture.anchor,
        commit=CURRENT_COMMIT,
        authority=fixture.state,
        context=context,
        decision=decision,
        authenticated=authenticated,
        profile=profile,
    )
    monkeypatch.setattr(
        handoff,
        "load_checkpoint_recovery_profile",
        lambda *args: profile,
    )
    reads: list[str] = []
    live = {"raw": _terminal_archive(terminal)}
    artifact = {
        "id": 3539001,
        "name": f"catalog-terminal-receipt-{profile.source_request_sha256}",
        "expired": False,
        "size_in_bytes": len(live["raw"]),
        "created_at": "2026-09-20T10:11:09.900000Z",
        "digest": "sha256:" + hashlib.sha256(live["raw"]).hexdigest(),
        "workflow_run": {
            "id": SOURCE_RUN_ID,
            "head_sha": SOURCE_COMMIT,
            "head_branch": "main",
            "repository_id": 1232647748,
            "head_repository_id": 1232647748,
        },
    }

    class Client:
        repository = fixture.client.repository

        def __init__(self) -> None:
            self.run = deepcopy(owner.run)
            self.after_run: dict[str, object] | None = None
            self.run_reads = 0
            self.terminal_rows: tuple[dict[str, object], ...] = (artifact,)
            self.stable = True
            self.complete = True

        def get_json(self, path: str) -> tuple[dict[str, object], None]:
            expected = f"/repos/{self.repository}/actions/runs/{SOURCE_RUN_ID}"
            assert path == expected
            self.run_reads += 1
            reads.append("run")
            payload = self.after_run if self.run_reads > 1 and self.after_run else self.run
            return deepcopy(payload), None

        def stable_paginated(self, path: str, *, root: str) -> SimpleNamespace:
            expected = (
                f"/repos/{self.repository}/actions/runs/{SOURCE_RUN_ID}/artifacts"
                f"?name=catalog-terminal-receipt-{profile.source_request_sha256}"
            )
            assert path == expected
            assert root == "artifacts"
            reads.append("terminal-inventory")
            return SimpleNamespace(
                stable=self.stable,
                collection=SimpleNamespace(
                    complete=self.complete,
                    rows=self.terminal_rows,
                ),
            )

    client = Client()

    def signed(_client: object, _root: Path, actual_profile: object) -> None:
        assert actual_profile is profile
        reads.append("source-signature")

    monkeypatch.setattr(handoff, "_read_signed_request", signed)

    def download_archive(artifact_id: int) -> bytes:
        assert artifact_id == artifact["id"]
        reads.append("terminal-download")
        return live["raw"]

    return {
        "fixture": fixture,
        "profile": profile,
        "owner": owner,
        "terminal": terminal,
        "client": client,
        "artifact": artifact,
        "live": live,
        "reads": reads,
        "args": {
            "root": tmp_path,
            "anchor": fixture.anchor,
            "commit": CURRENT_COMMIT,
            "context": context,
            "decision": decision,
            "client": client,
            "read_edit": lambda: fixture.edit,
            "download_archive": download_archive,
        },
    }


def test_profile9_terminal353_handoff_preserves_terminal_and_is_single_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _stage_profile9_terminal(tmp_path, monkeypatch)
    terminal = staged["terminal"]
    assert isinstance(terminal, CatalogTerminalReceiptV1)
    admission = json.loads(
        (tmp_path / ".catalog-fast-gate-handoff" / "admission.json").read_bytes()
    )
    assert admission["recovery"]["terminal"] == terminal.model_dump(mode="json")
    assert admission["recovery"]["owner"]["run_id"] == SOURCE_RUN_ID

    current, edit_id, proof = handoff.consume_admission(**staged["args"])

    assert current == staged["fixture"].state
    assert edit_id == "E_current"
    assert proof is not None
    assert proof.evidence_kind == "failed_owner_with_terminal"
    assert proof.source_issue_number == SOURCE_ISSUE_NUMBER
    assert proof.source_run_id == SOURCE_RUN_ID
    assert staged["reads"] == [
        "source-signature",
        "run",
        "terminal-inventory",
        "terminal-download",
        "run",
    ]
    with pytest.raises(FileExistsError):
        handoff.consume_admission(**staged["args"])
    assert staged["reads"][-1] == "run"


@pytest.mark.parametrize("defect", ["missing_terminal", "mutated_terminal", "live_changed"])
def test_profile9_terminal353_handoff_rejects_missing_or_changed_live_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    staged = _stage_profile9_terminal(tmp_path, monkeypatch)
    client = staged["client"]
    if defect == "missing_terminal":
        client.terminal_rows = ()
        expected = "CATALOG_FAST_GATE_HANDOFF_INVALID"
    elif defect == "mutated_terminal":
        terminal = staged["terminal"]
        assert isinstance(terminal, CatalogTerminalReceiptV1)
        mutated = CatalogTerminalReceiptV1.create(
            **{
                **terminal.model_dump(mode="json", exclude={"receipt_sha256"}),
                "expected_recipe_count": 37257,
            }
        )
        raw = _terminal_archive(mutated)
        staged["live"]["raw"] = raw
        artifact = staged["artifact"]
        artifact["size_in_bytes"] = len(raw)
        artifact["digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
        expected = "CATALOG_FAST_GATE_HANDOFF_INVALID"
    else:
        client.after_run = {**client.run, "head_sha": "0" * 40}
        expected = "CATALOG_FAST_GATE_HANDOFF_INVALID"

    with pytest.raises(ValueError, match=expected):
        handoff.consume_admission(**staged["args"])
