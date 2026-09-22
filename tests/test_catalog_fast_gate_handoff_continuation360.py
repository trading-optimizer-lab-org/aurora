from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_auth as recovery_auth
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import (
    CheckpointRecoveryOwnerAuthenticationV1,
    CheckpointRecoveryPredecessorAuthenticationV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
    verify_checkpoint_failure_owner,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
    CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
    CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
    CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT,
    CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
    CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256,
)
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence
from aurora.infra.sp500_megarun.catalog_reduction_recovery_profile import RecoveryPredecessorBindings
from scripts import catalog_fast_gate_handoff as handoff
from tests.test_catalog_fast_gate_handoff_terminal import _stage_profile9_terminal
from tests.test_catalog_fast_path import NOW


def _stage_profile10(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    staged = _stage_profile9_terminal(tmp_path, monkeypatch)
    profile9 = staged["profile"]
    profile10 = SimpleNamespace(**vars(profile9))
    profile10.source_generation = 8
    profile10.target_generation = 10
    profile10.profile_sha256 = "e" * 64
    profile10.predecessor_bindings = RecoveryPredecessorBindings(
        generation=9,
        request_sha256=CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
        issue_number=CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
        run_id=CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
        run_attempt=CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT,
        protected_commit_sha=CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
        terminal_receipt_sha256=CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256,
    )
    proof9 = verify_checkpoint_failure_owner(
        profile=profile9,
        owner=staged["owner"],
        terminal=staged["terminal"],
    )

    proof10 = CheckpointRecoveryOwnerProofV1(
        **{
            **asdict(proof9),
            "profile_sha256": profile10.profile_sha256,
            "target_generation": 10,
        }
    )
    predecessor_decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED",
        reason_code="CATALOG_FAST_PATH_ADMITTED",
        request_sha256=CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
        submission_key_sha256=staged["owner"].decision.submission_key_sha256,
        campaign_key=profile10.campaign_key,
        prepared_receipt_sha256=staged["owner"].decision.prepared_receipt_sha256,
        selected_workers=60,
        launch_required=True,
        existing_run_id=None,
        decided_at=staged["owner"].decision.decided_at,
        expires_at=staged["owner"].decision.expires_at,
    )
    predecessor_run = dict(staged["owner"].run)
    predecessor_run.update(
        {
            "id": CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
            "run_attempt": CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT,
            "head_sha": CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "failure",
            "event": "issues",
        }
    )
    predecessor_terminal = staged["terminal"].model_copy(
        update={
            "receipt_sha256": CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256,
            "request_sha256": CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
            "engine_run_id": CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
            "run_url": (
                "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
                f"{CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID}"
            ),
        }
    )
    predecessor = CheckpointRecoveryPredecessorAuthenticationV1(
        owner=FastGateOwnerEvidence(
            CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
            predecessor_run,
            predecessor_decision,
            staged["owner"].jobs,
        ),
        terminal=predecessor_terminal,
    )
    request = _successor_request()
    context = {
        "request": request.model_dump(mode="json"),
        "issue_number": 361,
        "protected_commit_sha": staged["args"]["commit"],
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

    admission = tmp_path / ".catalog-fast-gate-handoff" / "admission.json"
    admission.unlink()
    handoff.stage_admission(
        anchor=staged["fixture"].anchor,
        commit=staged["args"]["commit"],
        authority=staged["fixture"].state,
        context=context,
        decision=decision,
        authenticated=CheckpointRecoveryOwnerAuthenticationV1(
            staged["owner"], proof10, staged["terminal"], predecessor
        ),
        profile=profile10,
    )
    monkeypatch.setattr(handoff, "load_checkpoint_recovery_profile", lambda *args: profile10)

    parse_terminal = handoff.parse_catalog_terminal_receipt

    def parse_cached_terminal(value: object) -> object:
        if isinstance(value, dict) and value.get("request_sha256") == CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256:
            return predecessor_terminal
        return parse_terminal(value)

    monkeypatch.setattr(handoff, "parse_catalog_terminal_receipt", parse_cached_terminal)

    def read_signed(_client: object, _root: Path, actual_profile: object) -> None:
        assert actual_profile is profile10
        staged["reads"].append("source-signature-target10")

    monkeypatch.setattr(handoff, "_read_signed_request", read_signed)
    staged["args"]["context"] = context
    staged["args"]["decision"] = decision
    staged["profile10"] = profile10
    staged["proof10"] = proof10
    staged["predecessor"] = predecessor
    return staged


def _successor_request():
    from tests.test_catalog_cloud_authority import signed_request

    return signed_request(
        request_id="018f47a2-6e91-7c34-8000-000000000010",
        launch_generation=10,
        previous_terminal_request_sha256=CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
    )


def test_consume_admission_target10_rechecks_predecessor_before_returning_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _stage_profile10(tmp_path, monkeypatch)
    calls: list[dict[str, object]] = []

    def revalidate(**kwargs: object) -> object:
        calls.append(kwargs)
        return kwargs["cached"]

    monkeypatch.setattr(recovery_auth, "revalidate_checkpoint_recovery_predecessor", revalidate)

    current, edition, proof = handoff.consume_admission(**staged["args"])

    assert current == staged["fixture"].state
    assert edition == "E_current"
    assert proof == staged["proof10"]
    assert len(calls) == 1
    assert calls[0]["profile"] is staged["profile10"]
    assert calls[0]["cached"] == staged["predecessor"]
    assert calls[0]["protected_commit_sha"] == staged["args"]["commit"]
    assert calls[0]["fetch_json"] is staged["client"]
    assert calls[0]["download_artifact"] is staged["args"]["download_archive"]
    assert "checkpoint_control_jobs" not in calls[0]
    request = json.loads((tmp_path / ".catalog-fast-gate-handoff" / "admission.json").read_bytes())["request_sha256"]
    assert request == staged["args"]["decision"].request_sha256
    assert staged["args"]["context"]["request"]["launch_generation"] == 10
    assert (
        staged["args"]["context"]["request"]["previous_terminal_request_sha256"]
        == CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256
    )


def test_consume_admission_target10_closes_on_predecessor_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _stage_profile10(tmp_path, monkeypatch)
    calls: list[dict[str, object]] = []

    def revalidate(**kwargs: object) -> None:
        calls.append(kwargs)
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID")

    monkeypatch.setattr(recovery_auth, "revalidate_checkpoint_recovery_predecessor", revalidate)

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID"):
        handoff.consume_admission(**staged["args"])

    assert len(calls) == 1
    assert calls[0]["profile"] is staged["profile10"]
    assert calls[0]["protected_commit_sha"] == staged["args"]["commit"]


def test_stage_and_consume_target10_close_when_cached_predecessor_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _stage_profile10(tmp_path, monkeypatch)
    admission_path = tmp_path / ".catalog-fast-gate-handoff" / "admission.json"
    admission = json.loads(admission_path.read_bytes())
    admission["recovery"].pop("predecessor")
    admission["content_sha256"] = canonical_sha256(
        {key: value for key, value in admission.items() if key != "content_sha256"}
    )
    admission_path.write_text(
        json.dumps(admission, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="CATALOG_FAST_GATE_HANDOFF_INVALID"):
        handoff.consume_admission(**staged["args"])


@pytest.mark.parametrize("defect", [None, "signature", "run", "run_after", "terminal"])
def test_target10_predecessor_revalidation_closes_on_mutable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str | None
) -> None:
    staged = _stage_profile10(tmp_path, monkeypatch)
    profile = staged["profile10"]
    cached = staged["predecessor"]
    predecessor = profile.predecessor_bindings
    assert predecessor is not None
    request = SimpleNamespace(
        request_sha256=predecessor.request_sha256,
        campaign_key=profile.campaign_key,
        launch_generation=predecessor.generation,
        previous_terminal_request_sha256=profile.source_request_sha256,
    )
    if defect == "signature":
        request.request_sha256 = "b" * 64

    class Client:
        repository = staged["client"].repository

        def __init__(self) -> None:
            self.reads = 0

        def get_json(self, path: str) -> tuple[dict[str, object], None]:
            assert path == (
                f"/repos/{self.repository}/actions/runs/{predecessor.run_id}"
            )
            self.reads += 1
            run = deepcopy(dict(cached.owner.run))
            if defect == "run" or (defect == "run_after" and self.reads == 2):
                run["head_sha"] = "0" * 40
            return run, None

        def stable_paginated(self, path: str, *, root: str) -> object:
            pytest.fail("predecessor handoff must not reread gate/job inventory")

    client = Client()
    terminal = cached.terminal
    if defect == "terminal":
        terminal = terminal.model_copy(update={"observed_recipe_count": 1})
    monkeypatch.setattr(
        recovery_auth,
        "validate_exact_checkpoint_profile",
        lambda _root, actual_profile: actual_profile,
    )
    monkeypatch.setattr(
        recovery_auth,
        "_read_signed_request_for_identity",
        lambda **_kwargs: request,
    )
    monkeypatch.setattr(
        recovery_auth,
        "load_owner_terminal_receipt",
        lambda **_kwargs: terminal,
    )

    monkeypatch.setattr(recovery_auth, "load_fast_gate_owner",
                        lambda **kwargs: pytest.fail("gate ownership must not be downloaded twice"))
    def invoke():
        return recovery_auth.revalidate_checkpoint_recovery_predecessor(
            repo_root=tmp_path,
            repository=client.repository,
            protected_commit_sha=staged["args"]["commit"],
            profile=profile,
            cached=cached,
            fetch_json=client,
            download_artifact=lambda _artifact_id: b"unused",
        )
    if defect is None:
        assert invoke() == cached
        assert client.reads == 2
    else:
        with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID"):
            invoke()


@pytest.mark.parametrize("field,value", [
    ("head_branch", "other"), ("status", "in_progress"),
    ("conclusion", "success"), ("path", ".github/workflows/other.yml"),
    ("event", "workflow_dispatch"), ("repository", {"full_name": "foreign/repo"}),
])
def test_cached_predecessor_run_provenance_is_closed(tmp_path, monkeypatch, field, value):
    staged = _stage_profile10(tmp_path, monkeypatch)
    original = staged["predecessor"]
    run = {**original.owner.run, field: value}
    owner = FastGateOwnerEvidence(original.owner.run_id, run, original.owner.decision, original.owner.jobs)
    with pytest.raises(ValueError, match="PREDECESSOR_AUTH_INVALID"):
        recovery_auth.validate_checkpoint_recovery_predecessor_auth(
            profile=staged["profile10"],
            authenticated=CheckpointRecoveryPredecessorAuthenticationV1(owner, original.terminal),
        )
