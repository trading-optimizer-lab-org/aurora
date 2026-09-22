from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_auth as auth
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
    CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH,
    CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
    CHECKPOINT_RECOVERY_CONTINUATION_PREDECESSOR_GENERATION,
    CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
    CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
    CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT,
    CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
    CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256,
    CHECKPOINT_RECOVERY_INHERITED_PROFILE_SHA256,
    CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256,
    CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256,
    CheckpointRecoveryProfileV1,
    load_checkpoint_recovery_profile,
    load_checkpoint_recovery_profiles,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence


CAMPAIGN_KEY = CHECKPOINT_RECOVERY_CAMPAIGN_KEY
CONFIG_RELATIVE_PATH = Path(CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH)


def _write_config(root: Path, payload: object) -> None:
    path = root / CONFIG_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _profiles_with_continuation(repo_root: Path, tmp_path: Path):
    profile8 = load_checkpoint_recovery_profile(repo_root, CAMPAIGN_KEY, 8)
    profile9 = load_checkpoint_recovery_profile(repo_root, CAMPAIGN_KEY, 9)
    assert profile8 is not None
    assert profile9 is not None
    payload10 = profile9.model_dump(mode="json")
    payload10["target_generation"] = 10
    payload10["source_generation"] = 8
    _write_config(
        tmp_path,
        {
            "schema_version": "1",
            "profiles": [
                profile8.model_dump(mode="json"),
                profile9.model_dump(mode="json"),
                payload10,
            ],
        },
    )
    return (
        profile8,
        profile9,
        load_checkpoint_recovery_profile(tmp_path, CAMPAIGN_KEY, 10),
    )


def test_continuation_profile10_reuses_profile9_source_without_serialized_predecessor(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).parents[1]
    profile8, profile9, profile10 = _profiles_with_continuation(repo_root, tmp_path)

    assert profile10 is not None
    assert profile8.profile_sha256 == CHECKPOINT_RECOVERY_INHERITED_PROFILE_SHA256

    assert profile9.profile_sha256 == "547c89f3fd0fdd132caa37832ed642e1f389b26c4176d61b67f5685a30be1ff9"
    assert profile10.source_generation == 8
    assert profile10.source_request_sha256 == CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256
    assert profile10.source_issue_number == 353
    assert profile10.source_run_id == 35708742966
    assert profile10.source_run_attempt == 1
    assert profile10.source_protected_commit_sha == "9f22f9a1f7c6f2646f888c228a4899d0188f586c"
    assert profile10.source_terminal_receipt_sha256 == CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256
    assert profile10.worker_count == profile9.worker_count == 60
    assert profile10.slot_count == profile9.slot_count == 2
    assert profile10.checkpoint_result_count == profile9.checkpoint_result_count == 18628
    assert profile10.total_checkpoint_count == profile9.total_checkpoint_count == 240
    assert len(profile10.artifacts) == len(profile9.artifacts) == 121
    assert profile10.artifacts == profile9.artifacts
    assert profile10.inherited_profile_sha256 == profile9.inherited_profile_sha256
    assert "predecessor_bindings" not in profile10.model_dump(mode="json")
    assert "source_terminal_receipt_sha256" not in profile10.model_dump(mode="json")

    predecessor = profile10.predecessor_bindings
    assert predecessor is not None
    assert predecessor.generation == CHECKPOINT_RECOVERY_CONTINUATION_PREDECESSOR_GENERATION
    assert predecessor.request_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256
    assert predecessor.issue_number == CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER
    assert predecessor.run_id == CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID
    assert predecessor.run_attempt == CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT
    assert predecessor.protected_commit_sha == CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA
    assert predecessor.terminal_receipt_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256
    assert predecessor.decision_sha256 is None


def test_profile8_and_profile9_canonical_dumps_are_unchanged(tmp_path: Path) -> None:
    repo_root = Path(__file__).parents[1]
    profile8, profile9, _ = _profiles_with_continuation(repo_root, tmp_path)

    for profile in (profile8, profile9):
        assert json.loads(profile.model_dump_json()) == profile.model_dump(mode="json")
        assert "predecessor_bindings" not in profile.model_dump(mode="json")
    assert profile8.profile_sha256 == CHECKPOINT_RECOVERY_INHERITED_PROFILE_SHA256


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_request_sha256", "0" * 64),
        ("source_issue_number", 354),
        ("source_run_id", 1),
        ("source_protected_commit_sha", "0" * 40),
        ("inherited_profile_sha256", "0" * 64),
    ],
)
def test_profile10_source_pins_fail_closed(tmp_path: Path, field: str, value: object) -> None:
    repo_root = Path(__file__).parents[1]
    profile8 = load_checkpoint_recovery_profile(repo_root, CAMPAIGN_KEY, 8)
    profile9 = load_checkpoint_recovery_profile(repo_root, CAMPAIGN_KEY, 9)
    assert profile8 is not None and profile9 is not None
    payload10 = profile9.model_dump(mode="json")
    payload10.update({"target_generation": 10, "source_generation": 8, field: value})
    _write_config(
        tmp_path,
        {
            "schema_version": "1",
            "profiles": [profile8.model_dump(mode="json"), payload10],
        },
    )
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_CONFIG_INVALID"):
        load_checkpoint_recovery_profiles(tmp_path)


def _target10_proof(profile: CheckpointRecoveryProfileV1) -> CheckpointRecoveryOwnerProofV1:
    return CheckpointRecoveryOwnerProofV1(
        profile_sha256=profile.profile_sha256,
        campaign_key=profile.campaign_key,
        target_generation=10,
        source_request_sha256=profile.source_request_sha256,
        source_issue_number=profile.source_issue_number,
        source_run_id=profile.source_run_id,
        source_run_attempt=profile.source_run_attempt,
        source_protected_commit_sha=profile.source_protected_commit_sha,
        source_decision_sha256=profile.source_plan_bindings["decision_sha256"],
        source_finalizer_job_id=123,
        evidence_kind="failed_owner_with_terminal",
    )


def test_target10_owner_proof_separates_source_and_predecessor_pins(tmp_path: Path) -> None:
    repo_root = Path(__file__).parents[1]
    _, _, profile10 = _profiles_with_continuation(repo_root, tmp_path)
    assert profile10 is not None

    proof = _target10_proof(profile10)
    assert proof.source_terminal_receipt_sha256 == CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256
    assert proof.predecessor_bindings == profile10.predecessor_bindings
    assert proof.predecessor_bindings.terminal_receipt_sha256 != proof.source_terminal_receipt_sha256
    serialized = asdict(proof)
    assert "predecessor_bindings" not in serialized
    assert "source_terminal_receipt_sha256" not in serialized

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_SOURCE_IDENTITY_INVALID"):
        CheckpointRecoveryOwnerProofV1(
            **{
                **serialized,
                "source_request_sha256": "0" * 64,
            }
        )


def test_target10_authenticates_fresh_predecessor_owner_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).parents[1]
    _, _, profile10 = _profiles_with_continuation(repo_root, tmp_path)
    assert profile10 is not None
    predecessor = profile10.predecessor_bindings
    assert predecessor is not None

    request = SimpleNamespace(
        request_sha256=predecessor.request_sha256,
        campaign_key=profile10.campaign_key,
        launch_generation=predecessor.generation,
        previous_terminal_request_sha256=profile10.source_request_sha256,
    )
    from tests.test_catalog_fast_gate_handoff_continuation360 import _stage_profile10
    (tmp_path / "typed-handoff").mkdir()
    staged = _stage_profile10(tmp_path / "typed-handoff", monkeypatch)
    owner = staged["predecessor"].owner
    terminal = staged["predecessor"].terminal
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        auth,
        "_read_signed_request_for_identity",
        lambda **kwargs: (calls.append(("request", kwargs)) or request),
    )
    monkeypatch.setattr(
        auth,
        "load_fast_gate_owner",
        lambda **kwargs: (calls.append(("owner", kwargs)) or owner),
    )
    monkeypatch.setattr(
        auth,
        "load_owner_terminal_receipt",
        lambda **kwargs: (calls.append(("terminal", kwargs)) or terminal),
    )

    client = SimpleNamespace(
        repository="trading-optimizer-lab-org/aurora",
        get_json=lambda *args: (None, None),
        stable_paginated=lambda *args, **kwargs: None,
    )
    auth.authenticate_checkpoint_recovery_predecessor(
        repo_root=tmp_path,
        repository="trading-optimizer-lab-org/aurora",
        protected_commit_sha=CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
        profile=profile10,
        fetch_json=client,
        download_artifact=lambda artifact_id: b"unused",
        checkpoint_control_jobs=True,
    )

    assert [name for name, _ in calls] == ["request", "owner", "terminal"]
    owner_kwargs = calls[1][1]
    assert owner_kwargs["issue_number"] == CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER
    assert owner_kwargs["terminal_owner_run_id"] == CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID
    assert owner_kwargs["pinned_owner_run_id"] == CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID
    assert owner_kwargs["approved_commits"] == frozenset({CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA})
    assert owner_kwargs["checkpoint_control_jobs"] is True


def test_target10_auth_rejects_predecessor_terminal_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).parents[1]
    _, _, profile10 = _profiles_with_continuation(repo_root, tmp_path)
    assert profile10 is not None
    predecessor = profile10.predecessor_bindings
    assert predecessor is not None
    request = SimpleNamespace(
        request_sha256=predecessor.request_sha256,
        campaign_key=profile10.campaign_key,
        launch_generation=predecessor.generation,
        previous_terminal_request_sha256=profile10.source_request_sha256,
    )
    owner = FastGateOwnerEvidence(
        run_id=predecessor.run_id,
        run={
            "id": predecessor.run_id,
            "run_attempt": predecessor.run_attempt,
            "head_sha": predecessor.protected_commit_sha,
        },
        decision=SimpleNamespace(
            request_sha256=predecessor.request_sha256,
            campaign_key=profile10.campaign_key,
            decision_sha256="1" * 64,
        ),
        jobs=(
            {"name": "gate", "status": "completed", "conclusion": "success"},
            {"name": "finalize", "status": "completed", "conclusion": "success"},
        ),
    )
    terminal = SimpleNamespace(
        receipt_sha256="0" * 64,
        request_sha256=predecessor.request_sha256,
        campaign_key=profile10.campaign_key,
        state="BLOCKED",
        reason_code="CATALOG_REDUCTION_FAILED",
        expected_recipe_count=37258,
        observed_recipe_count=0,
        result_science_sha256=None,
    )
    monkeypatch.setattr(auth, "_read_signed_request_for_identity", lambda **kwargs: request)
    monkeypatch.setattr(auth, "load_fast_gate_owner", lambda **kwargs: owner)
    monkeypatch.setattr(auth, "load_owner_terminal_receipt", lambda **kwargs: terminal)

    client = SimpleNamespace(
        repository="trading-optimizer-lab-org/aurora",
        get_json=lambda *args: (None, None),
        stable_paginated=lambda *args, **kwargs: None,
    )
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID"):
        auth.authenticate_checkpoint_recovery_predecessor(
            repo_root=tmp_path,
            repository="trading-optimizer-lab-org/aurora",
            protected_commit_sha=CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
            profile=profile10,
            fetch_json=client,
            download_artifact=lambda artifact_id: b"unused",
            checkpoint_control_jobs=True,
        )
