from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import TypedDict, TypeVar, cast

import pytest

from scripts import run_catalog_bootstrap_assistant as bootstrap_runner

from infra.sp500_megarun.catalog_bootstrap_state import (
    CatalogBootstrapEventV1,
    CatalogBootstrapStateV1,
    EventName,
    advance_bootstrap_state,
    canonical_state_bytes,
    initial_bootstrap_state,
    load_bootstrap_state,
    persist_bootstrap_state,
)


COMMIT = "a" * 40
BOOTSTRAP_ID = "bootstrap-20260823-001"
PUBLIC_BINDING_PATHS = (
    "config/catalog_authority_anchor_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_auditor_v1.json",
    "config/catalog_requester_app_permissions_v1.json",
    "config/catalog_requester_public_key_v1.pem",
)


class _RequesterRecoveryFixture(TypedDict):
    root: Path
    broker_root: Path
    source: Path
    first: dict[str, object]
    status: dict[str, object]
    issue: dict[str, object]
    controller: dict[str, object]


_ItemT = TypeVar("_ItemT")
_ResultT = TypeVar("_ResultT")


def _append_then_return(
    items: list[_ItemT], item: _ItemT, result: _ResultT
) -> _ResultT:
    items.append(item)
    return result


def _append_and_get_last(items: list[_ItemT], item: _ItemT) -> _ItemT:
    items.append(item)
    return items[-1]


@pytest.fixture
def isolated_controller_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap_runner, "_disable_controller", lambda: None)


def test_review_environment_loads_the_selected_checkout_in_child_process(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "checkout-with-arbitrary-name"
    (source / "infra").mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "infra" / "__init__.py").write_text("", encoding="utf-8")
    (source / "infra" / "probe.py").write_text(
        'IDENTITY = "selected-checkout"\n', encoding="utf-8"
    )
    stale = tmp_path / "stale"
    (stale / "aurora" / "infra").mkdir(parents=True)
    (stale / "aurora" / "__init__.py").write_text("", encoding="utf-8")
    (stale / "aurora" / "infra" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (stale / "aurora" / "infra" / "probe.py").write_text(
        'IDENTITY = "stale-install"\n', encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(stale))

    environment = bootstrap_runner._review_import_environment(
        tmp_path / "protected",
        source,
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from aurora.infra.probe import IDENTITY; print(IDENTITY)",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "selected-checkout"
    assert environment["PYTHONPATH"] != str(stale)


def event(
    name: EventName, sequence: int, *, bootstrap_id: str = BOOTSTRAP_ID
) -> CatalogBootstrapEventV1:
    return CatalogBootstrapEventV1(
        schema_version="1",
        bootstrap_id=bootstrap_id,
        sequence=sequence,
        name=name,
        protected_commit_sha=COMMIT,
        observed_at="2026-08-23T12:00:00Z",
        evidence_sha256=f"{sequence:064x}",
    )


def test_only_closed_forward_transitions_are_allowed() -> None:
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    state = advance_bootstrap_state(state, event("precheck_passed", 1))
    assert state.phase == "REQUESTER_CREATE_PENDING"
    with pytest.raises(ValueError, match="TRANSITION_INVALID"):
        advance_bootstrap_state(state, event("auditor_installed", 2))


def test_complete_transition_graph_reaches_ready() -> None:
    names: tuple[EventName, ...] = (
        "precheck_passed",
        "requester_created",
        "requester_installed",
        "auditor_created",
        "auditor_installed",
        "public_binding_committed",
        "protected_merge_observed",
        "local_install_verified",
        "github_controls_verified",
        "qualification_passed",
        "agent_restart_verified",
        "final_audit_passed",
    )
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    for sequence, name in enumerate(names, 1):
        state = advance_bootstrap_state(state, event(name, sequence))
    assert state.phase == "READY"
    assert state.sequence == len(names)


def _merge_pending_state():
    names: tuple[EventName, ...] = (
        "precheck_passed",
        "requester_created",
        "requester_installed",
        "auditor_created",
        "auditor_installed",
        "public_binding_committed",
    )
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    for sequence, name in enumerate(names, 1):
        state = advance_bootstrap_state(state, event(name, sequence))
    return state


def _blocked_merge_state():
    return advance_bootstrap_state(
        _merge_pending_state(),
        event("blocked", 7),
    )


def _blocked_local_install_state():
    state = advance_bootstrap_state(
        _blocked_merge_state(),
        event("merge_retry_authorized", 8),
    )
    state = advance_bootstrap_state(state, event("protected_merge_observed", 9))
    return advance_bootstrap_state(state, event("blocked", 10))


def _blocked_second_local_install_state():
    state = _blocked_local_install_state()
    state = advance_bootstrap_state(
        state,
        event("local_install_retry_authorized", 11),
    )
    return advance_bootstrap_state(state, event("blocked", 12))


def _blocked_third_local_install_state():
    state = _blocked_second_local_install_state()
    state = advance_bootstrap_state(
        state,
        event("local_install_retry_authorized", 13),
    )
    return advance_bootstrap_state(state, event("blocked", 14))


def _blocked_fourth_local_install_state():
    state = _blocked_third_local_install_state()
    state = advance_bootstrap_state(
        state,
        event("local_install_retry_authorized", 15),
    )
    return advance_bootstrap_state(state, event("blocked", 16))


def _blocked_fifth_local_install_state():
    state = _blocked_fourth_local_install_state()
    state = advance_bootstrap_state(
        state,
        event("local_install_retry_authorized", 17),
    )
    return advance_bootstrap_state(state, event("blocked", 18))


def _blocked_sixth_local_install_state():
    state = _blocked_fifth_local_install_state()
    state = advance_bootstrap_state(
        state,
        event("local_install_retry_authorized", 19),
    )
    return advance_bootstrap_state(state, event("blocked", 20))


def _blocked_seventh_local_install_state():
    state = _blocked_sixth_local_install_state()
    state = advance_bootstrap_state(
        state,
        event("local_install_retry_authorized", 21),
    )
    return advance_bootstrap_state(state, event("blocked", 22))


def _blocked_github_controls_state():
    state = _blocked_seventh_local_install_state()
    state = advance_bootstrap_state(
        state,
        event("local_install_retry_authorized", 23),
    )
    state = advance_bootstrap_state(state, event("local_install_verified", 24))
    return advance_bootstrap_state(state, event("blocked", 25))


def _blocked_github_controls_second_state():
    state = advance_bootstrap_state(
        _blocked_github_controls_state(),
        event("github_controls_retry_authorized", 26),
    )
    return advance_bootstrap_state(state, event("blocked", 27))


def _blocked_github_controls_third_state():
    state = advance_bootstrap_state(
        _blocked_github_controls_second_state(),
        event("github_controls_retry_authorized", 28),
    )
    return advance_bootstrap_state(state, event("blocked", 29))


def _blocked_github_controls_fourth_state():
    state = advance_bootstrap_state(
        _blocked_github_controls_third_state(),
        event("github_controls_retry_authorized", 30),
    )
    return advance_bootstrap_state(state, event("blocked", 31))


def _blocked_github_controls_fifth_state():
    state = advance_bootstrap_state(
        _blocked_github_controls_fourth_state(),
        event("github_controls_retry_authorized", 32),
    )
    return advance_bootstrap_state(state, event("blocked", 33))


def _blocked_github_controls_sixth_state():
    state = advance_bootstrap_state(
        _blocked_github_controls_fifth_state(),
        event("github_controls_retry_authorized", 34),
    )
    return advance_bootstrap_state(state, event("blocked", 35))


def _blocked_github_controls_seventh_state():
    state = advance_bootstrap_state(
        _blocked_github_controls_sixth_state(),
        event("github_controls_retry_authorized", 36),
    )
    return advance_bootstrap_state(state, event("blocked", 37))


def _blocked_github_controls_eighth_state():
    state = advance_bootstrap_state(
        _blocked_github_controls_seventh_state(),
        event("github_controls_retry_authorized", 38),
    )
    return advance_bootstrap_state(state, event("blocked", 39))


def _blocked_github_controls_ninth_state():
    state = advance_bootstrap_state(
        _blocked_github_controls_eighth_state(),
        event("github_controls_retry_authorized", 40),
    )
    return advance_bootstrap_state(state, event("blocked", 41))


def test_only_exact_merge_retry_can_leave_terminal_blocked_state() -> None:
    blocked = _blocked_merge_state()
    assert blocked.phase == "BLOCKED"

    resumed = advance_bootstrap_state(blocked, event("merge_retry_authorized", 8))
    assert resumed.phase == "MERGE_PENDING"
    assert resumed.sequence == 8

    precheck = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    with pytest.raises(ValueError, match="TRANSITION_INVALID"):
        advance_bootstrap_state(precheck, event("merge_retry_authorized", 1))


def _qualification_blocked_receipt() -> dict[str, object]:
    return {
        "controller_enabled_readback": False,
        "phase": "QUALIFICATION_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_WORKFLOW_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }


def _qualification_ticket_missing_blocked_receipt() -> dict[str, object]:
    return {
        "controller_enabled_readback": False,
        "phase": "QUALIFICATION_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_QUALIFICATION_TICKET_MISSING",
        "result": "BLOCKED",
        "schema_version": "1",
    }


def _qualification_pending_state_before_block() -> CatalogBootstrapStateV1:
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    names: tuple[EventName, ...] = (
        "precheck_passed",
        "requester_created",
        "requester_installed",
        "auditor_created",
        "auditor_installed",
        "public_binding_committed",
        "protected_merge_observed",
        "local_install_verified",
        "github_controls_verified",
    )
    for sequence, name in enumerate(names, 1):
        state = advance_bootstrap_state(state, event(name, sequence))
    for sequence in range(10, 43, 2):
        state = advance_bootstrap_state(state, event("blocked", sequence))
        state = advance_bootstrap_state(
            state,
            event("qualification_retry_authorized", sequence + 1),
        )
    assert state.phase == "QUALIFICATION_PENDING"
    assert state.sequence == 43
    return state


def _blocked_qualification_state(
    sequence: int = 44,
    *,
    blocked: dict[str, object] | None = None,
    event_matches: bool = True,
) -> CatalogBootstrapStateV1:
    state = _qualification_pending_state_before_block()
    if sequence != 44:
        return state.model_copy(update={"phase": "BLOCKED", "sequence": sequence})
    blocked = _qualification_blocked_receipt() if blocked is None else blocked
    assert state.last_observed_at is not None
    blocked_event = CatalogBootstrapEventV1(
        schema_version="1",
        bootstrap_id=state.bootstrap_id,
        sequence=44,
        name="blocked",
        protected_commit_sha=state.protected_commit_sha,
        observed_at=state.last_observed_at,
        evidence_sha256=hashlib.sha256(
            bootstrap_runner._canonical(blocked)
        ).hexdigest(),
    )
    state = advance_bootstrap_state(state, blocked_event)
    if not event_matches:
        state = state.model_copy(
            update={
                "applied_event_sha256s": (
                    *state.applied_event_sha256s[:-1],
                    "f" * 64,
                )
            }
        )
    return state


def _blocked_after_qualification_ticket_missing() -> CatalogBootstrapStateV1:
    first_blocked = _blocked_qualification_state()
    pending = advance_bootstrap_state(
        first_blocked,
        event("qualification_retry_authorized", 45),
    )
    blocked = _qualification_ticket_missing_blocked_receipt()
    assert pending.last_observed_at is not None
    return advance_bootstrap_state(
        pending,
        CatalogBootstrapEventV1(
            schema_version="1",
            bootstrap_id=pending.bootstrap_id,
            sequence=46,
            name="blocked",
            protected_commit_sha=pending.protected_commit_sha,
            observed_at=pending.last_observed_at,
            evidence_sha256=hashlib.sha256(
                bootstrap_runner._canonical(blocked)
            ).hexdigest(),
        ),
    )


def _write_qualification_failure_fixture(
    root: Path,
    *,
    state: CatalogBootstrapStateV1 | None = None,
    blocked: dict[str, object] | None = None,
    legacy_refresh: bool = False,
) -> Path:
    blocked = _qualification_blocked_receipt() if blocked is None else blocked
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        state or _blocked_qualification_state(blocked=blocked),
    )
    receipts = root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    blocked_path = receipts / "controller-bootstrap-blocked-v1.json"
    blocked_path.write_bytes(bootstrap_runner._canonical(blocked) + b"\n")
    if legacy_refresh:
        refresh_path = (
            receipts
            / "controller-bootstrap-runtime-upgrade-refresh-blocked-v1.json"
        )
        refresh = {**blocked, "state_preserved_for_retry": True}
        refresh_path.write_bytes(bootstrap_runner._canonical(refresh) + b"\n")
    return blocked_path


def test_only_exact_qualification_retry_can_leave_terminal_blocked_state() -> None:
    blocked = _blocked_qualification_state()

    resumed = advance_bootstrap_state(
        blocked,
        event("qualification_retry_authorized", 45),
    )

    assert resumed.phase == "QUALIFICATION_PENDING"
    assert resumed.sequence == 45


def test_ticket_missing_qualification_recovers_only_after_ticket_is_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    blocked = _qualification_ticket_missing_blocked_receipt()
    _write_qualification_failure_fixture(
        root,
        state=_blocked_after_qualification_ticket_missing(),
        blocked=blocked,
    )
    broker_root = tmp_path / "broker"
    ticket_path = (
        broker_root
        / "launch-tickets"
        / "controller-bootstrap-qualification-v1.ticket.json"
    )
    ticket_path.parent.mkdir(parents=True)
    ticket_path.write_bytes(b'{"validated":true}\n')
    calls: list[str] = []

    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "BROKER_ROOT", broker_root)
    monkeypatch.setattr(
        bootstrap_runner,
        "_disable_controller",
        lambda: calls.append("disable"),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_wait_for_requester_ticket",
        lambda: calls.append("ticket_valid"),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_runtime_commit",
        lambda _root: _append_then_return(calls, "runtime_valid", COMMIT),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_refresh_interrupted_runtime_controls",
        lambda *_args, **_kwargs: pytest.fail("ticket recovery refreshed controls"),
    )

    assert bootstrap_runner._resume_transient_qualification_block(root) is True

    resumed = load_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json"
    )
    assert resumed.phase == "QUALIFICATION_PENDING"
    assert resumed.sequence == 47
    assert calls == ["disable", "ticket_valid", "runtime_valid"]


def test_ticket_missing_qualification_stays_blocked_while_ticket_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    blocked = _qualification_ticket_missing_blocked_receipt()
    _write_qualification_failure_fixture(
        root,
        state=_blocked_after_qualification_ticket_missing(),
        blocked=blocked,
    )
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    before = state_path.read_bytes()
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "_disable_controller", lambda: None)
    monkeypatch.setattr(
        bootstrap_runner,
        "_wait_for_requester_ticket",
        lambda: (_ for _ in ()).throw(
            ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_TICKET_MISSING")
        ),
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_QUALIFICATION_TICKET_MISSING",
    ):
        bootstrap_runner._resume_transient_qualification_block(root)

    assert state_path.read_bytes() == before


def test_recover_real_qualification_block_archives_unseen_dispatch_before_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    _write_interrupted_refresh_fixture(root)
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked_path.write_bytes(
        bootstrap_runner._canonical(_qualification_blocked_receipt()) + b"\n"
    )
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    blocked_event_sha = load_bootstrap_state(state_path).applied_event_sha256s[-1]
    old_commit = "b" * 40
    checkpoint = bootstrap_runner._new_qualification_checkpoint(
        protected_commit_sha=old_commit,
        github_controls_operation_sha256="1" * 64,
        activity_baseline_sha256="2" * 64,
        steps=[],
    )
    checkpoint_path = root / bootstrap_runner.QUALIFICATION_CHECKPOINT_FILENAME
    checkpoint_bytes = bootstrap_runner._canonical(checkpoint) + b"\n"
    checkpoint_path.write_bytes(checkpoint_bytes)
    checkpoint_sha = hashlib.sha256(checkpoint_bytes).hexdigest()
    step_name = "github_controls_runtime_upgrade_live_1"
    intent = bootstrap_runner._new_qualification_dispatch_intent(
        step_name=step_name,
        workflow="catalog-live-controls-qualification.yml",
        protected_commit_sha=COMMIT,
        baseline_run_ids={101},
    )
    intent_path = bootstrap_runner._qualification_commit_scoped_intent_path(
        root, step_name, COMMIT
    )
    intent_bytes = bootstrap_runner._canonical(intent) + b"\n"
    intent_path.write_bytes(intent_bytes)
    intent_sha = hashlib.sha256(intent_bytes).hexdigest()
    refresh_path = root / "runtime-upgrade-controls-refresh-v1.json"
    disabled: list[Path] = []
    advanced: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(
        bootstrap_runner,
        "_disable_controller",
        lambda: disabled.append(root),
    )

    monkeypatch.setattr(
        bootstrap_runner,
        "_runtime_commit",
        lambda _root, **_kwargs: COMMIT,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda command, **_kwargs: "" if command[1:3] == [
            "status",
            "--porcelain=v1",
        ] else COMMIT,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_idempotent_resume_github_authorization",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_list_workflow_runs",
        lambda _workflow: [{"databaseId": 101}],
    )

    def fake_prepare(
        installed_root: Path,
        commit: str,
        *,
        live_step_name: str,
        controller_already_disabled: bool = False,
    ) -> dict[str, object]:
        assert installed_root == root
        assert commit == COMMIT
        assert live_step_name == "github_controls_runtime_upgrade_live_1"
        assert controller_already_disabled is True
        assert not intent_path.exists()
        assert len(list(root.glob("qdr-*.json"))) == 1
        receipt: dict[str, object] = {"protected_commit_sha": commit}
        (installed_root / "github-controls-operation-v1.json").write_bytes(
            bootstrap_runner._canonical(receipt) + b"\n"
        )
        return receipt

    monkeypatch.setattr(
        bootstrap_runner,
        "_prepare_github_controls_operation",
        fake_prepare,
    )
    original_advance = bootstrap_runner._advance

    def capture_advance(
        installed_root: Path,
        state: CatalogBootstrapStateV1,
        name: str,
        evidence: object,
    ) -> None:
        advanced.append((name, cast(dict[str, object], evidence)))
        original_advance(installed_root, state, cast(EventName, name), evidence)

    monkeypatch.setattr(bootstrap_runner, "_advance", capture_advance)

    assert bootstrap_runner._resume_transient_qualification_block(root) is True

    resumed = load_bootstrap_state(state_path)
    assert resumed.phase == "QUALIFICATION_PENDING"
    assert resumed.sequence == 45
    assert disabled == [root]
    assert not checkpoint_path.exists()
    archives = list(root.glob("qualification-substeps-v1.checkpoint.archived-*.json"))
    assert len(archives) == 1
    assert old_commit in archives[0].name
    assert checkpoint_sha in archives[0].name
    assert archives[0].read_bytes() == checkpoint_bytes
    assert not intent_path.exists()
    intent_archives = list(root.glob("qdr-*.json"))
    assert len(intent_archives) == 1
    assert intent_sha in intent_archives[0].name
    assert intent_archives[0].read_bytes() == intent_bytes
    assert not (
        root / "receipts/controller-bootstrap-runtime-upgrade-refresh-blocked-v1.json"
    ).exists()
    assert advanced[0][0] == "qualification_retry_authorized"
    evidence = advanced[0][1]
    assert evidence["blocked_receipt_sha256"] == hashlib.sha256(
        blocked_path.read_bytes()
    ).hexdigest()
    assert evidence["runtime_commit_sha"] == COMMIT
    assert evidence["runtime_upgrade_refresh_receipt_sha256"] == hashlib.sha256(
        refresh_path.read_bytes()
    ).hexdigest()
    assert evidence["archived_qualification_checkpoint_sha256"] == checkpoint_sha
    assert evidence["archived_qualification_dispatch_intent_sha256s"] == [intent_sha]
    assert bootstrap_runner._archive_retryable_qualification_dispatch_intents(
        root,
        protected_commit_sha=COMMIT,
        recovery_event_sha256=blocked_event_sha,
    ) == [intent_sha]
    assert (
        bootstrap_runner._archive_stale_qualification_checkpoint(
            root,
            protected_commit_sha=COMMIT,
            recovery_event_sha256=blocked_event_sha,
        )
        == checkpoint_sha
    )


@pytest.mark.parametrize(
    ("status", "conclusion", "expected_archived"),
    (
        ("queued", None, False),
        ("in_progress", None, False),
        ("completed", "success", False),
        ("completed", "failure", True),
    ),
)
def test_qualification_retry_preserves_live_or_successful_dispatch(
    status: str,
    conclusion: str | None,
    expected_archived: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "protected"
    root.mkdir()
    step_name = "github_controls_runtime_upgrade_live_1"
    workflow = "catalog-live-controls-qualification.yml"
    intent = bootstrap_runner._new_qualification_dispatch_intent(
        step_name=step_name,
        workflow=workflow,
        protected_commit_sha=COMMIT,
        baseline_run_ids={101},
    )
    intent_path = bootstrap_runner._qualification_commit_scoped_intent_path(
        root, step_name, COMMIT
    )
    intent_path.write_bytes(bootstrap_runner._canonical(intent) + b"\n")
    monkeypatch.setattr(
        bootstrap_runner,
        "_list_workflow_runs",
        lambda _workflow: [
            {
                "databaseId": 101,
            },
            {
                "databaseId": 202,
                "headSha": COMMIT,
                "event": "workflow_dispatch",
                "status": status,
                "conclusion": conclusion,
                "path": f".github/workflows/{workflow}",
            },
        ],
    )

    archived = bootstrap_runner._archive_retryable_qualification_dispatch_intents(
        root,
        protected_commit_sha=COMMIT,
        recovery_event_sha256="c" * 64,
    )

    assert bool(archived) is expected_archived
    assert intent_path.exists() is not expected_archived


def test_qualification_retry_rejects_wrong_identity_before_archiving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "protected"
    root.mkdir()
    step_name = "github_controls_runtime_upgrade_live_1"
    workflow = "catalog-live-controls-qualification.yml"
    intent = bootstrap_runner._new_qualification_dispatch_intent(
        step_name=step_name,
        workflow=workflow,
        protected_commit_sha=COMMIT,
        baseline_run_ids={101},
    )
    intent_path = bootstrap_runner._qualification_commit_scoped_intent_path(
        root, step_name, COMMIT
    )
    intent_bytes = bootstrap_runner._canonical(intent) + b"\n"
    intent_path.write_bytes(intent_bytes)
    monkeypatch.setattr(
        bootstrap_runner,
        "_list_workflow_runs",
        lambda _workflow: [
            {"databaseId": 101},
            {
                "databaseId": 202,
                "headSha": "b" * 40,
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "failure",
                "path": f".github/workflows/{workflow}",
            },
        ],
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_QUALIFICATION_RUN_IDENTITY_AMBIGUOUS",
    ):
        bootstrap_runner._archive_retryable_qualification_dispatch_intents(
            root,
            protected_commit_sha=COMMIT,
            recovery_event_sha256="c" * 64,
        )

    assert intent_path.read_bytes() == intent_bytes
    assert list(root.glob("qdr-*.json")) == []


def test_recover_blocked_generic_upgrade_versions_refresh_and_preserves_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    _write_interrupted_refresh_fixture(root)
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked_path.write_bytes(
        bootstrap_runner._canonical(_qualification_blocked_receipt()) + b"\n"
    )
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    old_commit = "4" * 40
    base_operation = _idempotent_resume_repair_operation(
        prior_merge="3" * 40,
        repair_head="5" * 40,
        repair_merge=old_commit,
    )
    base_operation_path = (
        root / "github-controls-idempotent-resume-repair-operation-v1.json"
    )
    base_operation_path.write_bytes(
        bootstrap_runner._canonical(base_operation) + b"\n"
    )
    followup_operation = _idempotent_resume_followup_repair_operation(
        prior_merge=old_commit,
        base_commit=old_commit,
        repair_head="6" * 40,
        repair_merge="7" * 40,
    )
    followup_operation_path = (
        root / "github-controls-idempotent-resume-followup-repair-operation-v1.json"
    )
    followup_operation_path.write_bytes(
        bootstrap_runner._canonical(followup_operation) + b"\n"
    )
    catchup_operation = _idempotent_resume_catchup_repair_operation(
        prior_merge="7" * 40,
        repair_head="8" * 40,
        repair_merge="9" * 40,
    )
    catchup_operation_path = (
        root / "github-controls-idempotent-resume-catchup-repair-operation-v1.json"
    )
    catchup_operation_path.write_bytes(
        bootstrap_runner._canonical(catchup_operation) + b"\n"
    )
    upgrade_operation = _idempotent_resume_upgrade_repair_operation(
        upgrade_index=13,
        prior_merge="9" * 40,
        repair_head="b" * 40,
        repair_merge=COMMIT,
        pr_number=198,
    )
    upgrade_operation_path = (
        root / "github-controls-idempotent-resume-upgrade-13-operation-v1.json"
    )
    upgrade_operation_path.write_bytes(
        bootstrap_runner._canonical(upgrade_operation) + b"\n"
    )

    retry10_path = root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json"
    retry10 = cast(dict[str, object], json.loads(retry10_path.read_bytes()))
    retry12_path = root / "receipts/controller-bootstrap-github-controls-retry-12-v1.json"
    retry12_path.write_bytes(bootstrap_runner._canonical(retry10) + b"\n")
    retry13 = {
        **retry10,
        "idempotent_resume_upgrade_index": 13,
        "idempotent_resume_upgrade_merge_commit_sha": COMMIT,
        "idempotent_resume_upgrade_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(upgrade_operation)
        ).hexdigest(),
        "idempotent_resume_upgrade_pr_number": 198,
        "prior_retry_receipt_sha256": hashlib.sha256(
            retry12_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": "9" * 40,
    }
    retry13_path = root / "receipts/controller-bootstrap-github-controls-retry-13-v1.json"
    retry13_path.write_bytes(bootstrap_runner._canonical(retry13) + b"\n")

    controls_path = root / "github-controls-operation-v1.json"
    old_controls = controls_path.read_bytes()
    backup_path = root / "github-controls-operation-before-runtime-upgrade-v1.json"
    backup_path.write_bytes(old_controls)
    legacy_refresh_path = root / "runtime-upgrade-controls-refresh-v1.json"
    legacy_refresh = {
        "bootstrap_id": BOOTSTRAP_ID,
        "prior_controls_operation_sha256": hashlib.sha256(old_controls).hexdigest(),
        "protected_commit_sha": old_commit,
        "refreshed_controls_operation_sha256": hashlib.sha256(old_controls).hexdigest(),
        "runtime_upgrade_operation_sha256": hashlib.sha256(
            base_operation_path.read_bytes()
        ).hexdigest(),
        "schema_version": "1",
    }
    legacy_bytes = bootstrap_runner._canonical(legacy_refresh) + b"\n"
    legacy_refresh_path.write_bytes(legacy_bytes)

    checkpoint = bootstrap_runner._new_qualification_checkpoint(
        protected_commit_sha=old_commit,
        github_controls_operation_sha256="1" * 64,
        activity_baseline_sha256="2" * 64,
        steps=[],
    )
    checkpoint_path = root / bootstrap_runner.QUALIFICATION_CHECKPOINT_FILENAME
    checkpoint_bytes = bootstrap_runner._canonical(checkpoint) + b"\n"
    checkpoint_path.write_bytes(checkpoint_bytes)
    checkpoint_sha = hashlib.sha256(checkpoint_bytes).hexdigest()
    advanced: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "_disable_controller", lambda: None)

    real_validate_refresh = bootstrap_runner._validated_runtime_upgrade_refresh

    def fake_runtime_commit(
        installed_root: Path,
        *,
        allow_pending_idempotent_resume: bool = False,
    ) -> str:
        if allow_pending_idempotent_resume:
            return COMMIT
        real_validate_refresh(
            installed_root,
            upgrade_operation,
            retry13,
            (old_commit,),
            operation_path=upgrade_operation_path,
            error_code="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REFRESH_INVALID",
        )
        return COMMIT

    monkeypatch.setattr(
        bootstrap_runner,
        "_runtime_commit",
        fake_runtime_commit,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda command, **_kwargs: ""
        if command[1:3] == ["status", "--porcelain=v1"]
        else COMMIT,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_idempotent_resume_github_authorization",
        lambda *_args, **_kwargs: None,
    )

    def fake_prepare(
        installed_root: Path,
        commit: str,
        *,
        live_step_name: str,
        controller_already_disabled: bool = False,
    ) -> dict[str, object]:
        assert installed_root == root
        assert commit == COMMIT
        assert live_step_name == "github_controls_runtime_upgrade_live_1"
        assert controller_already_disabled is True
        receipt: dict[str, object] = {"protected_commit_sha": commit}
        controls_path.write_bytes(bootstrap_runner._canonical(receipt) + b"\n")
        return receipt

    monkeypatch.setattr(
        bootstrap_runner,
        "_prepare_github_controls_operation",
        fake_prepare,
    )
    original_advance = bootstrap_runner._advance

    def capture_advance(
        installed_root: Path,
        state: CatalogBootstrapStateV1,
        name: str,
        evidence: object,
    ) -> None:
        advanced.append((name, cast(dict[str, object], evidence)))
        original_advance(installed_root, state, cast(EventName, name), evidence)

    monkeypatch.setattr(bootstrap_runner, "_advance", capture_advance)

    assert bootstrap_runner._resume_transient_qualification_block(root) is True

    versioned_refresh_path = root / "runtime-upgrade-controls-refresh-13-v1.json"
    assert versioned_refresh_path.is_file()
    assert legacy_refresh_path.read_bytes() == legacy_bytes
    assert advanced[0][0] == "qualification_retry_authorized"
    evidence = advanced[0][1]
    assert evidence["runtime_upgrade_refresh_receipt_sha256"] == hashlib.sha256(
        versioned_refresh_path.read_bytes()
    ).hexdigest()
    assert evidence["runtime_upgrade_refresh_receipt_sha256"] != hashlib.sha256(
        legacy_bytes
    ).hexdigest()
    assert evidence["archived_qualification_checkpoint_sha256"] == checkpoint_sha

    state_after_recovery = state_path.read_bytes()
    versioned_bytes = versioned_refresh_path.read_bytes()
    assert bootstrap_runner._resume_transient_qualification_block(root) is False
    assert state_path.read_bytes() == state_after_recovery
    assert versioned_refresh_path.read_bytes() == versioned_bytes
    assert legacy_refresh_path.read_bytes() == legacy_bytes


def test_recover_blocked_upgrade_20_versions_backup_and_preserves_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    _write_interrupted_refresh_fixture(root)
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked_path.write_bytes(
        bootstrap_runner._canonical(_qualification_blocked_receipt()) + b"\n"
    )
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    current_runtime = "4" * 40
    latest_runtime = "f" * 40
    base_operation = _idempotent_resume_repair_operation(
        prior_merge="1" * 40,
        repair_head="2" * 40,
        repair_merge="2" * 40,
    )
    (root / "github-controls-idempotent-resume-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(base_operation) + b"\n"
    )
    followup_operation = _idempotent_resume_followup_repair_operation(
        prior_merge="2" * 40,
        base_commit="2" * 40,
        repair_head="3" * 40,
        repair_merge="3" * 40,
    )
    (
        root / "github-controls-idempotent-resume-followup-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(followup_operation) + b"\n")
    catchup_operation = _idempotent_resume_catchup_repair_operation(
        prior_merge="3" * 40,
        repair_head="4" * 40,
        repair_merge="4" * 40,
    )
    (
        root / "github-controls-idempotent-resume-catchup-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(catchup_operation) + b"\n")
    retry10_path = root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json"
    retry10 = cast(dict[str, object], json.loads(retry10_path.read_bytes()))
    for retry_index in (11, 12):
        (
            root
            / f"receipts/controller-bootstrap-github-controls-retry-{retry_index}-v1.json"
        ).write_bytes(bootstrap_runner._canonical(retry10) + b"\n")
    latest_operation: dict[str, object] = {}
    latest_retry: dict[str, object] = {}
    latest_operation_path = (
        root / "github-controls-idempotent-resume-upgrade-20-operation-v1.json"
    )
    for upgrade_index in range(13, 21):
        prior_runtime = (
            current_runtime
            if upgrade_index == 13
            else f"{upgrade_index - 9:x}" * 40
        )
        merge_runtime = (
            latest_runtime
            if upgrade_index == 20
            else f"{upgrade_index - 8:x}" * 40
        )
        operation = _idempotent_resume_upgrade_repair_operation(
            upgrade_index=upgrade_index,
            prior_merge=prior_runtime,
            repair_head=f"{upgrade_index - 7:x}" * 40,
            repair_merge=merge_runtime,
            pr_number=200 + upgrade_index,
        )
        operation_path = (
            root
            / f"github-controls-idempotent-resume-upgrade-{upgrade_index}-operation-v1.json"
        )
        operation_path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")
        retry = {
            **retry10,
            "idempotent_resume_upgrade_index": upgrade_index,
            "idempotent_resume_upgrade_merge_commit_sha": merge_runtime,
            "idempotent_resume_upgrade_operation_sha256": hashlib.sha256(
                bootstrap_runner._canonical(operation)
            ).hexdigest(),
            "idempotent_resume_upgrade_pr_number": 200 + upgrade_index,
            "prior_runtime_commit_sha": prior_runtime,
        }
        retry_path = (
            root
            / f"receipts/controller-bootstrap-github-controls-retry-{upgrade_index}-v1.json"
        )
        retry_path.write_bytes(bootstrap_runner._canonical(retry) + b"\n")
        if upgrade_index == 20:
            latest_operation = operation
            latest_retry = retry
    controls_path = root / "github-controls-operation-v1.json"
    controls_path.write_bytes(
        bootstrap_runner._canonical({"protected_commit_sha": current_runtime}) + b"\n"
    )
    controls_before = controls_path.read_bytes()
    legacy_backup_path = root / "github-controls-operation-before-runtime-upgrade-v1.json"
    legacy_backup_bytes = (
        bootstrap_runner._canonical({"protected_commit_sha": "3" * 40}) + b"\n"
    )
    legacy_backup_path.write_bytes(legacy_backup_bytes)
    checkpoint = bootstrap_runner._new_qualification_checkpoint(
        protected_commit_sha="9" * 40,
        github_controls_operation_sha256="1" * 64,
        activity_baseline_sha256="2" * 64,
        steps=[],
    )
    checkpoint_path = root / bootstrap_runner.QUALIFICATION_CHECKPOINT_FILENAME
    checkpoint_path.write_bytes(bootstrap_runner._canonical(checkpoint) + b"\n")
    source = root / "source"
    calls: list[str] = []

    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "_disable_controller", lambda: None)
    monkeypatch.setattr(
        bootstrap_runner,
        "_context",
        lambda _root: {
            "repository": bootstrap_runner.REPOSITORY,
            "source_commit_sha": latest_runtime,
            "source_root": str(source),
        },
    )

    real_validate_refresh = bootstrap_runner._validated_runtime_upgrade_refresh

    def fake_runtime_commit(
        installed_root: Path,
        *,
        allow_pending_idempotent_resume: bool = False,
    ) -> str:
        if allow_pending_idempotent_resume:
            return latest_runtime
        real_validate_refresh(
            installed_root,
            latest_operation,
            latest_retry,
            (current_runtime,),
            operation_path=latest_operation_path,
            error_code="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REFRESH_INVALID",
        )
        return latest_runtime

    monkeypatch.setattr(bootstrap_runner, "_runtime_commit", fake_runtime_commit)
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda command, **_kwargs: ""
        if command[1:3] == ["status", "--porcelain=v1"]
        else latest_runtime,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_idempotent_resume_github_authorization",
        lambda *_args, **_kwargs: None,
    )

    def fake_prepare(
        installed_root: Path,
        commit: str,
        *,
        live_step_name: str,
        controller_already_disabled: bool = False,
    ) -> dict[str, object]:
        calls.append(live_step_name)
        assert controller_already_disabled is True
        receipt: dict[str, object] = {"protected_commit_sha": commit}
        controls_path.write_bytes(bootstrap_runner._canonical(receipt) + b"\n")
        return receipt

    monkeypatch.setattr(bootstrap_runner, "_prepare_github_controls_operation", fake_prepare)

    assert bootstrap_runner._resume_transient_qualification_block(root) is True

    versioned_backup_path = (
        root / "github-controls-operation-before-runtime-upgrade-20-v1.json"
    )
    versioned_refresh_path = root / "runtime-upgrade-controls-refresh-20-v1.json"
    assert versioned_backup_path.read_bytes() == controls_before
    assert legacy_backup_path.read_bytes() == legacy_backup_bytes
    assert versioned_refresh_path.is_file()
    assert calls == ["github_controls_runtime_upgrade_live_1"]

    state_after_recovery = state_path.read_bytes()
    backup_after_recovery = versioned_backup_path.read_bytes()
    refresh_after_recovery = versioned_refresh_path.read_bytes()
    legacy_after_recovery = legacy_backup_path.read_bytes()
    assert bootstrap_runner._resume_transient_qualification_block(root) is False
    assert state_path.read_bytes() == state_after_recovery
    assert versioned_backup_path.read_bytes() == backup_after_recovery
    assert versioned_refresh_path.read_bytes() == refresh_after_recovery
    assert legacy_backup_path.read_bytes() == legacy_after_recovery


def test_qualification_recovery_rejects_a_block_event_mismatch_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    _write_qualification_failure_fixture(
        root,
        state=_blocked_qualification_state(event_matches=False),
        legacy_refresh=True,
    )
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    before = state_path.read_bytes()
    calls: list[str] = []
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(
        bootstrap_runner, "_disable_controller", lambda: calls.append("disable")
    )
    monkeypatch.setattr(
        bootstrap_runner, "_runtime_commit", lambda _root: COMMIT
    )

    assert bootstrap_runner._resume_transient_qualification_block(root) is False
    assert state_path.read_bytes() == before
    assert calls == ["disable"]


def test_qualification_recovery_rejects_wrong_reason_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    blocked = _qualification_blocked_receipt()
    blocked["reason_code"] = "CATALOG_BOOTSTRAP_PHASE_FAILED"
    _write_qualification_failure_fixture(root, blocked=blocked)
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    before = state_path.read_bytes()
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_qualification_block(root) is False
    assert state_path.read_bytes() == before


def test_versioned_refresh_rejects_reparse_entry_without_legacy_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    versioned_path = root / "runtime-upgrade-controls-refresh-13-v1.json"
    original_lstat = Path.lstat

    def fake_lstat(path: Path) -> object:
        if path == versioned_path:
            return SimpleNamespace(st_mode=0, st_nlink=1)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(
        bootstrap_runner,
        "_is_reparse_path",
        lambda path: path == versioned_path,
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_CHECKPOINT_PATH_INVALID",
    ):
        bootstrap_runner._runtime_upgrade_refresh_path(root, 13)


def test_runtime_backup_selector_falls_back_only_when_versioned_is_absent(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "github-controls-operation-before-runtime-upgrade-v1.json"
    versioned_path = tmp_path / "github-controls-operation-before-runtime-upgrade-20-v1.json"
    legacy_path.write_bytes(b"legacy")

    assert bootstrap_runner._runtime_upgrade_backup_path(tmp_path, None) == legacy_path
    assert bootstrap_runner._runtime_upgrade_backup_path(tmp_path, 20) == legacy_path
    assert (
        bootstrap_runner._runtime_upgrade_backup_path(tmp_path, 20, for_write=True)
        == versioned_path
    )

    versioned_path.write_bytes(b"versioned")
    assert bootstrap_runner._runtime_upgrade_backup_path(tmp_path, 20) == versioned_path


@pytest.mark.parametrize("invalid_index", [20.0, True])
def test_runtime_backup_selector_requires_strict_integer_upgrade_index(
    tmp_path: Path,
    invalid_index: object,
) -> None:
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REPAIR_INVALID",
    ):
        bootstrap_runner._runtime_upgrade_backup_path(tmp_path, invalid_index)


def test_versioned_backup_rejects_reparse_entry_without_legacy_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versioned_path = (
        tmp_path / "github-controls-operation-before-runtime-upgrade-20-v1.json"
    )
    legacy_path = tmp_path / "github-controls-operation-before-runtime-upgrade-v1.json"
    legacy_path.write_bytes(b"legacy")
    original_lstat = Path.lstat

    def fake_lstat(path: Path) -> object:
        if path == versioned_path:
            return SimpleNamespace(st_mode=0, st_nlink=1)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(
        bootstrap_runner,
        "_is_reparse_path",
        lambda path: path == versioned_path,
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_CHECKPOINT_PATH_INVALID",
    ):
        bootstrap_runner._runtime_upgrade_backup_path(tmp_path, 20)


def _write_interrupted_refresh_fixture(
    root: Path,
    *,
    interrupted_phase: str = "QUALIFICATION_PENDING",
    interrupted_sequence: int = 43,
) -> tuple[Path, Path, Path]:
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    blocked_state = _blocked_qualification_state()
    persist_bootstrap_state(state_path, blocked_state)
    interrupted_state_path = (
        root / "state/catalog-bootstrap-interrupted-state-v1.json"
    )
    interrupted_state = _qualification_pending_state_before_block()
    assert (
        interrupted_state.applied_event_sha256s
        == blocked_state.applied_event_sha256s[:-1]
    )
    persist_bootstrap_state(interrupted_state_path, interrupted_state)
    baseline: dict[str, object] = {
        "heavy_run_ids": [],
        "request_issue_numbers": [],
    }
    baseline_path = root / "github-activity-baseline-v1.json"
    baseline_path.write_bytes(bootstrap_runner._canonical(baseline) + b"\n")
    receipts = root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    retry = {
        "activity_baseline_sha256": hashlib.sha256(
            bootstrap_runner._canonical(baseline)
        ).hexdigest(),
        "bootstrap_id": BOOTSTRAP_ID,
        "interrupted_phase": interrupted_phase,
        "interrupted_sequence": interrupted_sequence,
        "interrupted_state_sha256": hashlib.sha256(
            interrupted_state_path.read_bytes()
        ).hexdigest(),
    }
    (receipts / "controller-bootstrap-github-controls-retry-10-v1.json").write_bytes(
        bootstrap_runner._canonical(retry) + b"\n"
    )
    operation = {
        "merge_commit_sha": COMMIT,
        "prior_runtime_commit_sha": "4" * 40,
    }
    operation_path = root / "github-controls-idempotent-resume-repair-operation-v1.json"
    operation_path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")
    controls_path = root / "github-controls-operation-v1.json"
    controls_path.write_bytes(
        bootstrap_runner._canonical({"protected_commit_sha": "4" * 40}) + b"\n"
    )
    tmp_path_for_refresh = root / "source"
    tmp_path_for_refresh.mkdir()
    (root / "install-context-v1.json").write_bytes(
        bootstrap_runner._canonical(
            {
                "repository": bootstrap_runner.REPOSITORY,
                "source_commit_sha": COMMIT,
                "source_root": str(tmp_path_for_refresh),
            }
        )
        + b"\n"
    )
    return state_path, controls_path, root / "runtime-upgrade-controls-refresh-v1.json"


@pytest.mark.parametrize(
    ("interrupted_phase", "interrupted_sequence"),
    (("MERGE_PENDING", 43), ("QUALIFICATION_PENDING", 42)),
)
def test_blocked_qualification_refresh_rejects_wrong_interrupted_identity(
    interrupted_phase: str,
    interrupted_sequence: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "protected"
    state_path, controls_path, refresh_path = _write_interrupted_refresh_fixture(
        root,
        interrupted_phase=interrupted_phase,
        interrupted_sequence=interrupted_sequence,
    )
    before = state_path.read_bytes()
    monkeypatch.setattr(
        bootstrap_runner,
        "_runtime_commit",
        lambda *_args, **_kwargs: pytest.fail("refresh must reject before runtime lookup"),
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_RETRY_INVALID",
    ):
        bootstrap_runner._refresh_interrupted_runtime_controls(
            root, allow_blocked_recovery=True
        )
    assert state_path.read_bytes() == before
    assert controls_path.read_bytes() == (
        bootstrap_runner._canonical({"protected_commit_sha": "4" * 40}) + b"\n"
    )
    assert not refresh_path.exists()


def test_blocked_qualification_refresh_rejects_wrong_interrupted_state_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "protected"
    state_path, controls_path, refresh_path = _write_interrupted_refresh_fixture(root)
    retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json"
    )
    retry = json.loads(retry_path.read_bytes())
    retry["interrupted_state_sha256"] = "3" * 64
    retry_path.write_bytes(bootstrap_runner._canonical(retry) + b"\n")
    before = state_path.read_bytes()
    monkeypatch.setattr(
        bootstrap_runner,
        "_runtime_commit",
        lambda *_args, **_kwargs: pytest.fail("invalid state hash reached runtime lookup"),
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_RETRY_INVALID",
    ):
        bootstrap_runner._refresh_interrupted_runtime_controls(
            root, allow_blocked_recovery=True
        )

    assert state_path.read_bytes() == before
    assert controls_path.read_bytes() == (
        bootstrap_runner._canonical({"protected_commit_sha": "4" * 40}) + b"\n"
    )
    assert not refresh_path.exists()


def test_qualification_recovery_rejects_corrupt_checkpoint_before_advance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    _write_qualification_failure_fixture(root)
    checkpoint_path = root / bootstrap_runner.QUALIFICATION_CHECKPOINT_FILENAME
    checkpoint_path.write_bytes(b'{"schema_version":"1"')
    original_checkpoint = checkpoint_path.read_bytes()
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    before = state_path.read_bytes()
    refresh_path = root / "runtime-upgrade-controls-refresh-v1.json"
    refresh_path.write_bytes(
        bootstrap_runner._canonical({"protected_commit_sha": COMMIT}) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "_disable_controller", lambda: None)
    monkeypatch.setattr(
        bootstrap_runner,
        "_refresh_interrupted_runtime_controls",
        lambda *_args, **_kwargs: COMMIT,
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_INVALID",
    ):
        bootstrap_runner._resume_transient_qualification_block(root)
    assert state_path.read_bytes() == before
    assert checkpoint_path.read_bytes() == original_checkpoint
    assert not list(root.glob("qualification-substeps-v1.checkpoint.archived-*.json"))


def test_qualification_recovery_rejects_checkpoint_from_current_runtime(
    tmp_path: Path,
) -> None:
    root = tmp_path / "protected"
    root.mkdir()
    checkpoint = bootstrap_runner._new_qualification_checkpoint(
        protected_commit_sha=COMMIT,
        github_controls_operation_sha256="1" * 64,
        activity_baseline_sha256="2" * 64,
        steps=[],
    )
    checkpoint_path = root / bootstrap_runner.QUALIFICATION_CHECKPOINT_FILENAME
    checkpoint_bytes = bootstrap_runner._canonical(checkpoint) + b"\n"
    checkpoint_path.write_bytes(checkpoint_bytes)

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_NOT_STALE",
    ):
        bootstrap_runner._archive_stale_qualification_checkpoint(
            root,
            protected_commit_sha=COMMIT,
            recovery_event_sha256="3" * 64,
        )

    assert checkpoint_path.read_bytes() == checkpoint_bytes
    assert not list(root.glob("qualification-substeps-v1.checkpoint.archived-*.json"))


@pytest.mark.parametrize(
    "step_name", tuple(bootstrap_runner._DISPATCH_INTENT_STEP_WORKFLOWS)
)
def test_all_qualification_steps_scope_legacy_intents_by_commit(
    step_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "installed"
    root.mkdir()
    workflow = bootstrap_runner._DISPATCH_INTENT_STEP_WORKFLOWS[step_name]
    prior_commit = "b" * 40
    legacy_intent = bootstrap_runner._new_qualification_dispatch_intent(
        step_name=step_name,
        workflow=workflow,
        protected_commit_sha=prior_commit,
        baseline_run_ids={101},
    )
    legacy_path = root / f"qualification-dispatch-{step_name}-v1.intent.json"
    legacy_bytes = bootstrap_runner._canonical(legacy_intent) + b"\n"
    legacy_path.write_bytes(legacy_bytes)
    expected_run = {
        "databaseId": 202,
        "headSha": COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "url": "https://example.test/runs/202",
    }
    dispatches: list[tuple[str, str, set[int] | None]] = []
    monkeypatch.setattr(
        bootstrap_runner,
        "_list_workflow_runs",
        lambda _workflow: [{"databaseId": 101}],
    )

    def fake_dispatch(
        observed_workflow: str,
        observed_commit: str,
        *,
        baseline_run_ids: set[int] | None = None,
    ) -> dict[str, object]:
        dispatches.append((observed_workflow, observed_commit, baseline_run_ids))
        return expected_run

    monkeypatch.setattr(bootstrap_runner, "_dispatch_workflow", fake_dispatch)

    observed = bootstrap_runner._run_qualification_workflow_step(
        root, step_name, COMMIT
    )

    current_path = root / f"qualification-dispatch-{step_name}-{COMMIT}-v1.intent.json"
    assert observed == expected_run
    assert legacy_path.read_bytes() == legacy_bytes
    assert current_path.is_file()
    assert dispatches == [(workflow, COMMIT, {101})]


def test_qualification_recovery_rejects_wrong_sequence_without_mutating_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    _write_qualification_failure_fixture(
        root, state=_blocked_qualification_state(sequence=43)
    )
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    before = state_path.read_bytes()
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_qualification_block(root) is False
    assert state_path.read_bytes() == before


def test_main_retries_qualification_before_other_blocked_recoveries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{}\n", encoding="utf-8")
    blocked = _blocked_qualification_state()
    pending = blocked.model_copy(
        update={"phase": "QUALIFICATION_PENDING", "sequence": 45}
    )
    ready = pending.model_copy(update={"phase": "READY", "sequence": 56})
    observed_states = iter((blocked, blocked, pending, pending, ready))
    recoveries: list[str] = []
    phases: list[str] = []

    monkeypatch.setattr(
        bootstrap_runner,
        "load_bootstrap_state",
        lambda _path: next(observed_states),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_qualification_block",
        lambda _root: _append_then_return(recoveries, "qualification", True),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_merge_block",
        lambda _root: _append_then_return(recoveries, "merge", False),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_local_install_block",
        lambda _root: _append_then_return(recoveries, "local", False),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_github_controls_block",
        lambda _root: _append_then_return(recoveries, "github", False),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "run_phase",
        lambda phase, _root: phases.append(phase),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["catalog-bootstrap-assistant", "--installed-root", str(root)],
    )

    assert bootstrap_runner.main() == 0
    assert recoveries == ["qualification"]
    assert phases == ["QUALIFICATION_PENDING"]


def _local_install_repair_operation(
    *,
    binding_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": binding_merge,
        "branch": "codex/catalog-local-install-recovery-123456789abc",
        "changed_paths": list(bootstrap_runner._LOCAL_INSTALL_REPAIR_PATHS),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "9" * 64,
        "pr_number": 165,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _local_install_followup_repair_operation(
    *,
    repair_merge: str,
    followup_head: str,
    followup_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": repair_merge,
        "branch": "codex/catalog-local-install-followup-abcdef123456",
        "changed_paths": list(
            bootstrap_runner._LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS
        ),
        "head_commit_sha": followup_head,
        "merge_commit_sha": followup_merge,
        "patch_sha256": "8" * 64,
        "pr_number": 166,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _local_install_compat_repair_operation(
    *,
    followup_merge: str,
    compat_head: str,
    compat_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": followup_merge,
        "branch": "codex/catalog-local-install-compat-fedcba654321",
        "changed_paths": list(
            bootstrap_runner._LOCAL_INSTALL_COMPAT_REPAIR_PATHS
        ),
        "head_commit_sha": compat_head,
        "merge_commit_sha": compat_merge,
        "patch_sha256": "7" * 64,
        "pr_number": 167,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _local_install_account_repair_operation(
    *,
    compat_merge: str,
    account_head: str,
    account_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": compat_merge,
        "branch": "codex/catalog-local-install-account-012345abcdef",
        "changed_paths": list(
            bootstrap_runner._LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS
        ),
        "head_commit_sha": account_head,
        "merge_commit_sha": account_merge,
        "patch_sha256": "6" * 64,
        "pr_number": 168,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _local_install_verifier_repair_operation(
    *,
    account_merge: str,
    verifier_head: str,
    verifier_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": account_merge,
        "branch": "codex/catalog-local-install-verifier-abcdef012345",
        "changed_paths": list(
            bootstrap_runner._LOCAL_INSTALL_VERIFIER_REPAIR_PATHS
        ),
        "head_commit_sha": verifier_head,
        "merge_commit_sha": verifier_merge,
        "patch_sha256": "5" * 64,
        "pr_number": 169,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _local_install_acl_repair_operation(
    *,
    verifier_merge: str,
    acl_head: str,
    acl_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": verifier_merge,
        "branch": "codex/catalog-local-install-acl-123456abcdef",
        "changed_paths": list(bootstrap_runner._LOCAL_INSTALL_ACL_REPAIR_PATHS),
        "head_commit_sha": acl_head,
        "merge_commit_sha": acl_merge,
        "patch_sha256": "4" * 64,
        "pr_number": 170,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _local_install_task_identity_repair_operation(
    *,
    acl_merge: str,
    task_identity_head: str,
    task_identity_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": acl_merge,
        "branch": "codex/catalog-local-install-task-identity-fedcba654321",
        "changed_paths": list(
            bootstrap_runner._LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS
        ),
        "head_commit_sha": task_identity_head,
        "merge_commit_sha": task_identity_merge,
        "patch_sha256": "3" * 64,
        "pr_number": 171,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _local_install_task_identity_followup_repair_operation(
    *,
    task_identity_merge: str,
    followup_head: str,
    followup_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": task_identity_merge,
        "branch": "codex/catalog-local-install-task-identity-followup-012345fedcba",
        "changed_paths": list(
            bootstrap_runner._LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS
        ),
        "head_commit_sha": followup_head,
        "merge_commit_sha": followup_merge,
        "patch_sha256": "2" * 64,
        "pr_number": 172,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _github_controls_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-github-controls-recovery-abcdef123456",
        "changed_paths": list(bootstrap_runner._GITHUB_CONTROLS_REPAIR_PATHS),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "1" * 64,
        "pr_number": 173,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _github_controls_followup_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-github-controls-followup-123456abcdef",
        "changed_paths": list(
            bootstrap_runner._GITHUB_CONTROLS_FOLLOWUP_REPAIR_PATHS
        ),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "9" * 64,
        "pr_number": 174,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _github_controls_enterprise_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-enterprise-billing-recovery",
        "changed_paths": list(
            bootstrap_runner._GITHUB_CONTROLS_ENTERPRISE_REPAIR_PATHS
        ),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "8" * 64,
        "pr_number": 175,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _github_controls_billing_token_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-billing-audit-token-recovery",
        "changed_paths": list(
            bootstrap_runner._GITHUB_CONTROLS_BILLING_TOKEN_REPAIR_PATHS
        ),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "7" * 64,
        "pr_number": 176,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def test_billing_token_repair_receipt_stays_bound_to_pr176_paths(
    tmp_path: Path,
) -> None:
    legacy_paths = [
        ".github/workflows/catalog-live-controls-audit.yml",
        "config/catalog_github_auditor_v1.json",
        "config/catalog_github_controls_v1.json",
        "infra/sp500_megarun/catalog_github_controls.py",
        "infra/sp500_megarun/catalog_requester_broker_cli.py",
        "infra/sp500_megarun/catalog_requester_cli.py",
        "schemas/catalog_github_auditor_v1.schema.json",
        "schemas/catalog_github_controls_v1.schema.json",
        "scripts/audit_catalog_agent_capabilities.ps1",
        "scripts/audit_catalog_github_controls.py",
        "scripts/run_catalog_bootstrap_assistant.py",
        "tests/test_catalog_bootstrap_assistant.py",
        "tests/test_catalog_controller_workflows.py",
        "tests/test_catalog_github_controls.py",
        "tests/test_catalog_requester_packaging.py",
    ]
    prior_repair: dict[str, object] = {"merge_commit_sha": "5" * 40}
    operation = {
        "base_commit_sha": "5" * 40,
        "branch": "codex/catalog-billing-audit-token-recovery",
        "changed_paths": legacy_paths,
        "head_commit_sha": "6" * 40,
        "merge_commit_sha": "7" * 40,
        "patch_sha256": "8" * 64,
        "pr_number": 176,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }
    path = tmp_path / "github-controls-billing-token-repair-operation-v1.json"
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")

    assert bootstrap_runner._validated_github_controls_billing_token_repair(
        tmp_path, prior_repair
    ) == operation

    operation["changed_paths"] = [
        ".github/actions/catalog-live-controls-audit/action.yml",
        *legacy_paths[1:],
    ]
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BILLING_TOKEN_INVALID",
    ):
        bootstrap_runner._validated_github_controls_billing_token_repair(
            tmp_path, prior_repair
        )

    operation["changed_paths"] = legacy_paths
    operation["pr_number"] = 177
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BILLING_TOKEN_INVALID",
    ):
        bootstrap_runner._validated_github_controls_billing_token_repair(
            tmp_path, prior_repair
        )


def _github_controls_stable_precondition_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-controls-stable-state-precondition",
        "changed_paths": list(
            bootstrap_runner._GITHUB_CONTROLS_STABLE_PRECONDITION_REPAIR_PATHS
        ),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "6" * 64,
        "pr_number": 177,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _github_controls_cache_retention_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-cache-retention-limit-recovery",
        "changed_paths": list(
            bootstrap_runner._GITHUB_CONTROLS_CACHE_RETENTION_REPAIR_PATHS
        ),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "5" * 64,
        "pr_number": 178,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _github_controls_storage_audit_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-storage-audit-recovery",
        "changed_paths": list(
            bootstrap_runner._GITHUB_CONTROLS_STORAGE_AUDIT_REPAIR_PATHS
        ),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "4" * 64,
        "pr_number": 179,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def test_storage_audit_repair_receipt_stays_bound_to_pr179_paths(
    tmp_path: Path,
) -> None:
    historical_paths = [
        ".github/workflows/catalog-live-controls-audit.yml",
        "config/catalog_campaign_definitions/sp500-optimized-catalog-v1.manifest.json",
        "scripts/audit_catalog_github_controls.py",
        "scripts/run_catalog_artifact_keeper.py",
        "scripts/run_catalog_bootstrap_assistant.py",
        "tests/test_catalog_bootstrap_assistant.py",
        "tests/test_catalog_controller_workflows.py",
        "tests/test_catalog_github_controls.py",
        "tests/test_sp500_catalog_optimized_engine.py",
    ]
    prior_repair: dict[str, object] = {"merge_commit_sha": "5" * 40}
    operation = {
        "base_commit_sha": "5" * 40,
        "branch": "codex/catalog-storage-audit-recovery",
        "changed_paths": historical_paths,
        "head_commit_sha": "6" * 40,
        "merge_commit_sha": "7" * 40,
        "patch_sha256": "8" * 64,
        "pr_number": 179,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }
    path = tmp_path / "github-controls-storage-audit-repair-operation-v1.json"
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")

    assert bootstrap_runner._validated_github_controls_storage_audit_repair(
        tmp_path, prior_repair
    ) == operation

    operation["changed_paths"] = [
        ".github/actions/catalog-live-controls-audit/action.yml",
        *historical_paths[1:],
    ]
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STORAGE_AUDIT_INVALID",
    ):
        bootstrap_runner._validated_github_controls_storage_audit_repair(
            tmp_path, prior_repair
        )

    operation["changed_paths"] = historical_paths
    operation["pr_number"] = 180
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_GITHUB_CONTROLS_STORAGE_AUDIT_INVALID",
    ):
        bootstrap_runner._validated_github_controls_storage_audit_repair(
            tmp_path, prior_repair
        )


def _github_controls_audit_throughput_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-controls-audit-throughput",
        "changed_paths": list(
            bootstrap_runner._GITHUB_CONTROLS_AUDIT_THROUGHPUT_REPAIR_PATHS
        ),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "3" * 64,
        "pr_number": 180,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _github_controls_package_token_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-windows-receipt-recovery",
        "changed_paths": list(
            bootstrap_runner._GITHUB_CONTROLS_PACKAGE_TOKEN_REPAIR_PATHS
        ),
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "2" * 64,
        "pr_number": 188,
        "prior_runtime_commit_sha": prior_merge,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "GTBI V7 stage-two required",
        "schema_version": "1",
    }


def _idempotent_resume_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-bootstrap-idempotent-resume",
        "changed_paths": [
            "scripts/run_catalog_bootstrap_assistant.py",
            "tests/test_catalog_bootstrap_assistant.py",
        ],
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "1" * 64,
        "pr_number": 194,
        "prior_runtime_commit_sha": prior_merge,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "catalog-controller-policy",
        "schema_version": "1",
    }


def _idempotent_resume_followup_repair_operation(
    *,
    prior_merge: str,
    base_commit: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": base_commit,
        "branch": "codex/catalog-bootstrap-runtime-followup",
        "changed_paths": [
            "scripts/run_catalog_bootstrap_assistant.py",
            "tests/test_catalog_bootstrap_assistant.py",
        ],
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "2" * 64,
        "pr_number": 196,
        "prior_runtime_commit_sha": prior_merge,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "catalog-controller-policy",
        "schema_version": "1",
    }


def _idempotent_resume_catchup_repair_operation(
    *,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": "codex/catalog-bootstrap-runtime-catchup",
        "changed_paths": [
            "scripts/run_catalog_bootstrap_assistant.py",
            "tests/test_catalog_bootstrap_assistant.py",
        ],
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "3" * 64,
        "pr_number": 197,
        "prior_runtime_commit_sha": prior_merge,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "catalog-controller-policy",
        "schema_version": "1",
    }


def _idempotent_resume_upgrade_repair_operation(
    *,
    upgrade_index: int,
    prior_merge: str,
    repair_head: str,
    repair_merge: str,
    pr_number: int,
) -> dict[str, object]:
    return {
        "base_commit_sha": prior_merge,
        "branch": f"codex/catalog-runtime-upgrade-{upgrade_index}",
        "changed_paths": [
            "scripts/run_catalog_bootstrap_assistant.py",
            "tests/test_catalog_bootstrap_assistant.py",
        ],
        "head_commit_sha": repair_head,
        "merge_commit_sha": repair_merge,
        "patch_sha256": "4" * 64,
        "pr_number": pr_number,
        "prior_runtime_commit_sha": prior_merge,
        "repository": bootstrap_runner.REPOSITORY,
        "required_check": "catalog-controller-policy",
        "schema_version": "1",
        "upgrade_index": upgrade_index,
    }


def test_only_exact_local_install_retry_returns_to_local_install_phase() -> None:
    blocked = _blocked_local_install_state()

    resumed = advance_bootstrap_state(
        blocked,
        event("local_install_retry_authorized", 11),
    )

    assert resumed.phase == "LOCAL_INSTALL_PENDING"
    assert resumed.sequence == 11

    blocked_again = advance_bootstrap_state(resumed, event("blocked", 12))
    resumed_again = advance_bootstrap_state(
        blocked_again,
        event("local_install_retry_authorized", 13),
    )
    assert resumed_again.phase == "LOCAL_INSTALL_PENDING"
    assert resumed_again.sequence == 13

    blocked_third = advance_bootstrap_state(
        resumed_again,
        event("blocked", 14),
    )
    resumed_third = advance_bootstrap_state(
        blocked_third,
        event("local_install_retry_authorized", 15),
    )
    assert resumed_third.phase == "LOCAL_INSTALL_PENDING"
    assert resumed_third.sequence == 15

    blocked_fourth = advance_bootstrap_state(
        resumed_third,
        event("blocked", 16),
    )
    resumed_fourth = advance_bootstrap_state(
        blocked_fourth,
        event("local_install_retry_authorized", 17),
    )
    assert resumed_fourth.phase == "LOCAL_INSTALL_PENDING"
    assert resumed_fourth.sequence == 17

    blocked_fifth = advance_bootstrap_state(
        resumed_fourth,
        event("blocked", 18),
    )
    resumed_fifth = advance_bootstrap_state(
        blocked_fifth,
        event("local_install_retry_authorized", 19),
    )
    assert resumed_fifth.phase == "LOCAL_INSTALL_PENDING"
    assert resumed_fifth.sequence == 19

    blocked_sixth = advance_bootstrap_state(
        resumed_fifth,
        event("blocked", 20),
    )
    resumed_sixth = advance_bootstrap_state(
        blocked_sixth,
        event("local_install_retry_authorized", 21),
    )
    assert resumed_sixth.phase == "LOCAL_INSTALL_PENDING"
    assert resumed_sixth.sequence == 21

    blocked_seventh = advance_bootstrap_state(
        resumed_sixth,
        event("blocked", 22),
    )
    resumed_seventh = advance_bootstrap_state(
        blocked_seventh,
        event("local_install_retry_authorized", 23),
    )
    assert resumed_seventh.phase == "LOCAL_INSTALL_PENDING"
    assert resumed_seventh.sequence == 23

    controls_pending = advance_bootstrap_state(
        resumed_seventh,
        event("local_install_verified", 24),
    )
    controls_blocked = advance_bootstrap_state(
        controls_pending,
        event("blocked", 25),
    )
    controls_resumed = advance_bootstrap_state(
        controls_blocked,
        event("github_controls_retry_authorized", 26),
    )
    assert controls_resumed.phase == "GITHUB_CONTROLS_PENDING"
    assert controls_resumed.sequence == 26


def test_second_local_install_block_enters_protected_recovery(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_second_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    with pytest.raises(FileNotFoundError):
        bootstrap_runner._resume_transient_local_install_block(root)


def test_third_local_install_block_enters_protected_recovery(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_third_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    with pytest.raises(FileNotFoundError):
        bootstrap_runner._resume_transient_local_install_block(root)


def test_fourth_local_install_block_enters_protected_recovery(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_fourth_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    with pytest.raises(FileNotFoundError):
        bootstrap_runner._resume_transient_local_install_block(root)


def test_fifth_local_install_block_enters_protected_recovery(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_fifth_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    with pytest.raises(FileNotFoundError):
        bootstrap_runner._resume_transient_local_install_block(root)


def test_sixth_local_install_block_enters_protected_recovery(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_sixth_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    with pytest.raises(FileNotFoundError):
        bootstrap_runner._resume_transient_local_install_block(root)


def test_seventh_local_install_block_enters_protected_recovery(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_seventh_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    with pytest.raises(FileNotFoundError):
        bootstrap_runner._resume_transient_local_install_block(root)


def test_github_controls_block_waits_for_protected_recovery_receipt(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_second_github_controls_block_waits_for_enterprise_repair_receipt(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_second_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_third_github_controls_block_waits_for_stable_precondition_receipt(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_third_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_fourth_github_controls_block_waits_for_cache_retention_receipt(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_fourth_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_fifth_github_controls_block_waits_for_storage_audit_receipt(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_fifth_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_sixth_github_controls_block_waits_for_audit_throughput_receipt(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_sixth_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_PHASE_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_audit_throughput_repair_operation_is_validated(tmp_path: Path) -> None:
    prior: dict[str, object] = {"merge_commit_sha": "a" * 40}
    operation = _github_controls_audit_throughput_repair_operation(
        prior_merge="a" * 40,
        repair_head="b" * 40,
        repair_merge="c" * 40,
    )
    path = tmp_path / "github-controls-audit-throughput-repair-operation-v1.json"
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")

    assert (
        bootstrap_runner._validated_github_controls_audit_throughput_repair(
            tmp_path,
            prior,
        )
        == operation
    )


def test_package_token_repair_operation_is_validated(tmp_path: Path) -> None:
    prior: dict[str, object] = {"merge_commit_sha": "a" * 40}
    operation = _github_controls_package_token_repair_operation(
        prior_merge="a" * 40,
        repair_head="b" * 40,
        repair_merge="c" * 40,
    )
    path = tmp_path / "github-controls-package-token-repair-operation-v1.json"
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")

    assert (
        bootstrap_runner._validated_github_controls_package_token_repair(
            tmp_path,
            prior,
        )
        == operation
    )


def test_seventh_github_controls_block_waits_for_package_token_receipt(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_seventh_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_WORKFLOW_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_github_controls_recovery_rejects_any_other_install_root(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", tmp_path / "other")

    with pytest.raises(ValueError, match="CATALOG_BOOTSTRAP_ROOT_INVALID"):
        bootstrap_runner._resume_transient_github_controls_block(root)


def test_github_controls_recovery_binds_receipt_to_exact_blocked_state(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    retry = {
        "blocked_state_sha256": "0" * 64,
        "github_controls_merge_commit_sha": "a" * 40,
    }
    (root / "receipts/controller-bootstrap-github-controls-retry-v1.json").write_bytes(
        bootstrap_runner._canonical(retry) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "_runtime_commit", lambda _root: "a" * 40)

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BLOCK_STATE_INVALID",
    ):
        bootstrap_runner._resume_transient_github_controls_block(root)


def test_github_controls_repair_graph_rejects_wrong_patch(
    tmp_path: Path, monkeypatch
) -> None:
    operation = _github_controls_repair_operation(
        prior_merge="a" * 40,
        repair_head="b" * 40,
        repair_merge="c" * 40,
    )

    def fake_run(arguments: list[str], *, cwd: Path) -> str:
        assert cwd == tmp_path
        if arguments == [
            "git", "rev-list", "--parents", "-n", "1", "c" * 40
        ]:
            return " ".join(("c" * 40, "a" * 40, "b" * 40))
        raise AssertionError(arguments)

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(
        bootstrap_runner,
        "_github_controls_repair_patch_sha256",
        lambda *_args: "f" * 64,
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_PATCH_INVALID",
    ):
        bootstrap_runner._verify_github_controls_repair_graph(
            tmp_path, operation
        )


def test_github_controls_repair_graph_accepts_verified_linear_merge(
    tmp_path: Path, monkeypatch
) -> None:
    operation = _github_controls_cache_retention_repair_operation(
        prior_merge="a" * 40,
        repair_head="b" * 40,
        repair_merge="c" * 40,
    )

    def fake_run(arguments: list[str], *, cwd: Path) -> str:
        assert cwd == tmp_path
        assert arguments == [
            "git", "rev-list", "--parents", "-n", "1", "c" * 40
        ]
        return " ".join(("c" * 40, "a" * 40))

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(
        bootstrap_runner,
        "_github_controls_repair_patch_sha256",
        lambda _source, base, target, _paths: (
            "5" * 64
            if base == "a" * 40 and target in {"b" * 40, "c" * 40}
            else "0" * 64
        ),
    )

    bootstrap_runner._verify_github_controls_repair_graph(tmp_path, operation)


def test_github_controls_repair_graph_accepts_verified_cumulative_linear_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = _github_controls_cache_retention_repair_operation(
        prior_merge="a" * 40,
        repair_head="b" * 40,
        repair_merge="c" * 40,
    )
    pull_request_base = "d" * 40
    ancestry_calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, cwd: Path) -> str:
        assert cwd == tmp_path
        assert arguments == [
            "git",
            "rev-list",
            "--parents",
            "-n",
            "1",
            "c" * 40,
        ]
        return " ".join(("c" * 40, pull_request_base))

    def fake_subprocess_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        ancestry_calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(bootstrap_runner.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(
        bootstrap_runner,
        "_github_controls_repair_patch_sha256",
        lambda _source, base, target, _paths: (
            "5" * 64
            if base == "a" * 40 and target in {"b" * 40, "c" * 40}
            else "0" * 64
        ),
    )

    bootstrap_runner._verify_github_controls_repair_graph(
        tmp_path,
        operation,
        patch_base_commit="a" * 40,
        pull_request_base_commit=pull_request_base,
    )

    assert ancestry_calls == [
        ["git", "merge-base", "--is-ancestor", "a" * 40, pull_request_base]
    ]


def test_post_install_verification_uses_installed_requester_key(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    broker = tmp_path / "broker"
    (root / "secrets").mkdir(parents=True)
    (broker / "secrets").mkdir(parents=True)
    (root / "requester-public-v1.json").write_text(
        '{"app_id":11,"installation_id":101}\n', encoding="utf-8"
    )
    (root / "auditor-public-v1.json").write_text(
        '{"app_id":22,"installation_id":202}\n', encoding="utf-8"
    )
    (broker / "secrets/requester-private-key.pem").write_bytes(b"requester")
    (root / "secrets/auditor-pending.pem").write_bytes(b"auditor")
    manifests = SimpleNamespace(requester=object(), auditor=object())
    observed_keys: list[bytes] = []

    class FakeClient:
        def __init__(self, *, app_id: int, private_key_pem: bytearray) -> None:
            self.app_id = app_id
            observed_keys.append(bytes(private_key_pem))

        def find_exact_installation(self, _manifest: object) -> object:
            return SimpleNamespace(
                installation_id=101 if self.app_id == 11 else 202
            )

        def close(self) -> None:
            pass

    monkeypatch.setattr(bootstrap_runner, "BROKER_ROOT", broker)
    monkeypatch.setattr(bootstrap_runner, "_manifests", lambda: manifests)
    monkeypatch.setattr(
        bootstrap_runner, "CatalogBootstrapGitHubClient", FakeClient
    )

    assert bootstrap_runner._verify_post_install_installations(root) == {
        "auditor": 202,
        "requester": 101,
    }
    assert observed_keys == [b"requester", b"auditor"]
    assert (
        "_verify_post_install_installations"
        in bootstrap_runner._resume_transient_github_controls_block.__code__.co_names
    )


def test_post_install_recovery_accepts_auditor_secret_already_uploaded(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    broker = tmp_path / "broker"
    (root / "secrets").mkdir(parents=True)
    (broker / "secrets").mkdir(parents=True)
    (root / "requester-public-v1.json").write_text(
        '{"app_id":11,"installation_id":101}\n', encoding="utf-8"
    )
    (root / "auditor-public-v1.json").write_text(
        '{"app_id":22,"installation_id":202}\n', encoding="utf-8"
    )
    (broker / "secrets/requester-private-key.pem").write_bytes(b"requester")
    manifests = SimpleNamespace(requester=object(), auditor=object())

    class FakeClient:
        def __init__(self, *, app_id: int, private_key_pem: bytearray) -> None:
            assert app_id == 11
            assert bytes(private_key_pem) == b"requester"

        def find_exact_installation(self, _manifest: object) -> object:
            return SimpleNamespace(installation_id=101)

        def close(self) -> None:
            pass

    monkeypatch.setattr(bootstrap_runner, "BROKER_ROOT", broker)
    monkeypatch.setattr(bootstrap_runner, "_manifests", lambda: manifests)
    monkeypatch.setattr(
        bootstrap_runner, "CatalogBootstrapGitHubClient", FakeClient
    )
    monkeypatch.setattr(
        bootstrap_runner, "_protected_environment_secret_exists", lambda: True
    )

    assert bootstrap_runner._verify_post_install_installations(
        root, allow_uploaded_auditor=True
    ) == {"auditor": 202, "requester": 101}


def test_prepare_auditor_secret_reuses_only_proven_protected_secret(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    (root / "receipts").mkdir(parents=True)
    (
        root / "receipts/controller-bootstrap-github-controls-retry-9-v1.json"
    ).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        bootstrap_runner, "_protected_environment_secret_exists", lambda: True
    )

    assert bootstrap_runner._prepare_auditor_secret(root) == {
        "name": "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
        "status": "preserved",
    }


def test_protected_environment_secret_names_require_exact_unique_rows(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda _args: json.dumps(
            [
                {"name": "AURORA_CATALOG_AUDITOR_PRIVATE_KEY"},
                {"name": "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN"},
            ]
        ),
    )

    assert bootstrap_runner._protected_environment_secret_names() == frozenset(
        {
            "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
            "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
        }
    )

    for invalid in (
        {"name": "not-a-list"},
        [{"name": "duplicate"}, {"name": "duplicate"}],
        [{"name": "valid", "value": "must-not-be-returned"}],
        [{"name": ""}],
    ):
        monkeypatch.setattr(
            bootstrap_runner, "_run", lambda _args, value=invalid: json.dumps(value)
        )
        with pytest.raises(
            ValueError,
            match="^CATALOG_BOOTSTRAP_ENVIRONMENT_SECRET_LIST_INVALID$",
        ):
            bootstrap_runner._protected_environment_secret_names()

    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda _args: '[{"name":"first","name":"second"}]',
    )
    with pytest.raises(
        ValueError,
        match="^CATALOG_BOOTSTRAP_ENVIRONMENT_SECRET_LIST_INVALID$",
    ):
        bootstrap_runner._protected_environment_secret_names()


def test_required_environment_secrets_fail_closed_with_exact_missing_names(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        bootstrap_runner,
        "_protected_environment_secret_names",
        lambda: frozenset({"AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN"}),
    )

    with pytest.raises(ValueError) as error:
        bootstrap_runner._require_protected_environment_secrets(
            frozenset(
                {
                    "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
                    "AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN",
                    "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN",
                }
            )
        )

    assert str(error.value) == (
        "CATALOG_BOOTSTRAP_AUDITOR_ENVIRONMENT_SECRETS_MISSING:"
        "AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN,"
        "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN"
    )


def test_required_environment_secret_gate_returns_no_sensitive_metadata(
    monkeypatch,
) -> None:
    required = frozenset(
        {
            "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
            "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
        }
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_protected_environment_secret_names",
        lambda: required,
    )

    assert cast(
        object,
        bootstrap_runner._require_protected_environment_secrets(required),
    ) is None


def test_github_controls_receipt_source_does_not_persist_secret_names() -> None:
    source = inspect.getsource(bootstrap_runner.apply_github_controls)

    assert '"auditor_secret_name"' not in source
    assert 'proof.get("name")' not in source


def test_safe_blocked_reason_preserves_only_allowlisted_missing_secret_names() -> None:
    safe = ValueError(
        "CATALOG_BOOTSTRAP_AUDITOR_ENVIRONMENT_SECRETS_MISSING:"
        "AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN,"
        "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN"
    )

    assert bootstrap_runner._safe_blocked_reason(safe, "fallback") == str(safe)
    assert (
        bootstrap_runner._safe_blocked_reason(
            ValueError(
                "CATALOG_BOOTSTRAP_AUDITOR_ENVIRONMENT_SECRETS_MISSING:"
                "ATTACKER_TOKEN"
            ),
            "fallback",
        )
        == "fallback"
    )
    assert (
        bootstrap_runner._safe_blocked_reason(
            ValueError("password=do-not-persist"), "fallback"
        )
        == "fallback"
    )


def test_github_controls_require_external_secrets_before_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    source = tmp_path / "source"
    (source / "config").mkdir(parents=True)
    (source / "config/catalog_authority_anchor_v1.json").write_text(
        '{"issue_number":1,"production_enabled":true}\n', encoding="utf-8"
    )
    root.mkdir(exist_ok=True)
    (root / "auditor-public-v1.json").write_text(
        '{"app_id":2}\n', encoding="utf-8"
    )
    monkeypatch.setattr(bootstrap_runner, "load_bootstrap_state", lambda _path: object())
    monkeypatch.setattr(
        bootstrap_runner, "_context", lambda _root: {"source_root": str(source)}
    )
    monkeypatch.setattr(bootstrap_runner, "_runtime_commit", lambda _root: "a" * 40)
    monkeypatch.setattr(
        bootstrap_runner,
        "_require_protected_environment_secrets",
        lambda _required: (_ for _ in ()).throw(ValueError("missing")),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_disable_controller",
        lambda: pytest.fail("controller must not be mutated"),
    )

    with pytest.raises(ValueError, match="^missing$"):
        bootstrap_runner.apply_github_controls(root)


def test_github_controls_require_all_secrets_before_live_qualification(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    source = tmp_path / "source"
    receipts = root / "receipts"
    (source / "config").mkdir(parents=True)
    receipts.mkdir(parents=True)
    (source / "config/catalog_authority_anchor_v1.json").write_text(
        '{"issue_number":1,"production_enabled":true}\n', encoding="utf-8"
    )
    (root / "auditor-public-v1.json").write_text(
        '{"app_id":2}\n', encoding="utf-8"
    )
    dry = {"current_state_sha256": "b" * 64, "mode": "dry_run"}
    applied = {"bootstrap_controls_prepared": True, "mode": "apply"}
    (receipts / "github-controls-dry-run-v1.json").write_bytes(
        bootstrap_runner._canonical(dry) + b"\n"
    )
    (receipts / "github-controls-apply-v1.json").write_bytes(
        bootstrap_runner._canonical(applied) + b"\n"
    )
    requirements: list[frozenset[str]] = []

    def require(required: frozenset[str]) -> dict[str, object]:
        requirements.append(required)
        if len(requirements) == 2:
            raise ValueError("missing-final")
        return {"environment": "catalog-production", "present": sorted(required)}

    monkeypatch.setattr(bootstrap_runner, "load_bootstrap_state", lambda _path: object())
    monkeypatch.setattr(
        bootstrap_runner, "_context", lambda _root: {"source_root": str(source)}
    )
    monkeypatch.setattr(bootstrap_runner, "_runtime_commit", lambda _root: "a" * 40)
    monkeypatch.setattr(bootstrap_runner, "_disable_controller", lambda: None)
    monkeypatch.setattr(bootstrap_runner, "_set_repository_variable", lambda *_args: None)
    monkeypatch.setattr(
        bootstrap_runner,
        "_prepare_auditor_secret",
        lambda _root: {"name": bootstrap_runner.AUDITOR_SECRET},
    )
    monkeypatch.setattr(
        bootstrap_runner, "_require_protected_environment_secrets", require
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_run_live_qualification",
        lambda *_args, **_kwargs: pytest.fail("live qualification must not run"),
    )

    with pytest.raises(ValueError, match="^missing-final$"):
        bootstrap_runner.apply_github_controls(root)

    assert requirements == [
        bootstrap_runner.PROTECTED_ENVIRONMENT_EXTERNAL_SECRETS,
        bootstrap_runner.PROTECTED_ENVIRONMENT_REQUIRED_SECRETS,
    ]


def test_existing_bootstrap_control_receipts_are_reused_only_when_canonical(
    tmp_path: Path,
) -> None:
    root = tmp_path / "protected"
    receipts = root / "receipts"
    receipts.mkdir(parents=True)
    dry = {"current_state_sha256": "a" * 64, "mode": "dry_run"}
    applied = {"bootstrap_controls_prepared": True, "mode": "apply"}
    (receipts / "github-controls-dry-run-v1.json").write_bytes(
        bootstrap_runner._canonical(dry) + b"\r\n"
    )
    (receipts / "github-controls-apply-v1.json").write_bytes(
        bootstrap_runner._canonical(applied) + b"\r\n"
    )

    assert bootstrap_runner._validated_existing_github_control_receipts(
        root
    ) == (dry, applied)


def test_eighth_github_controls_block_waits_for_idempotent_retry(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_eighth_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_ninth_github_controls_block_waits_for_windows_receipt_retry(
    tmp_path: Path, monkeypatch, isolated_controller_shutdown: None
) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_github_controls_ninth_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RECEIPTS_INVALID",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)

    assert bootstrap_runner._resume_transient_github_controls_block(root) is False


def test_local_install_recovery_rejects_context_not_bound_to_repair(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    source = tmp_path / "source"
    source.mkdir(parents=True)
    binding_merge = "b" * 40
    repair_head = "e" * 40
    repair_merge = "f" * 40
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    context = {
        "repository": bootstrap_runner.REPOSITORY,
        "source_commit_sha": "d" * 40,
        "source_root": str(source),
    }
    (root / "install-context-v1.json").write_bytes(
        bootstrap_runner._canonical(context) + b"\n"
    )
    operation = {
        "binding_commit_sha": "c" * 40,
        "branch": "catalog/bootstrap-binding-123456789abc",
        "merge_commit_sha": binding_merge,
        "pr_number": 163,
        "review_rounds_sha256": "d" * 64,
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(operation) + b"\n"
    )
    repair = _local_install_repair_operation(
        binding_merge=binding_merge,
        repair_head=repair_head,
        repair_merge=repair_merge,
    )
    (root / "local-install-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(repair) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    calls: list[list[str]] = []

    def allow_only_controller_shutdown(args: list[str], **_kwargs: object) -> str:
        calls.append(args)
        assert args[:2] == ["gh", "variable"]
        assert args[2] in {"get", "set"}
        assert args[3] in {
            bootstrap_runner.ARMED_VARIABLE,
            bootstrap_runner.CONTROLLER_VARIABLE,
        }
        if args[2] == "set":
            assert args[4:6] == ["--body", "false"]
            return ""
        return "false"

    monkeypatch.setattr(bootstrap_runner, "_run", allow_only_controller_shutdown)

    with pytest.raises(ValueError, match="LOCAL_RETRY_CONTEXT_INVALID"):
        bootstrap_runner._resume_transient_local_install_block(root)
    assert [(args[2], args[3]) for args in calls] == [
        ("set", bootstrap_runner.ARMED_VARIABLE),
        ("get", bootstrap_runner.ARMED_VARIABLE),
        ("set", bootstrap_runner.CONTROLLER_VARIABLE),
        ("get", bootstrap_runner.CONTROLLER_VARIABLE),
    ]


def test_recover_exact_clean_local_install_block_through_protected_repair(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    source = tmp_path / "source"
    source.mkdir(parents=True)
    staging = tmp_path / "staging"
    staging.mkdir()
    agent_root = tmp_path / "agent"
    broker_root = tmp_path / "broker"
    binding_merge = "b" * 40
    repair_head = "e" * 40
    repair_merge = "f" * 40
    binding_branch = "catalog/bootstrap-binding-123456789abc"
    repair_branch = "codex/catalog-local-install-recovery-123456789abc"
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    persist_bootstrap_state(state_path, _blocked_local_install_state())
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    context = {
        "repository": bootstrap_runner.REPOSITORY,
        "source_commit_sha": repair_merge,
        "source_root": str(source),
    }
    (root / "install-context-v1.json").write_bytes(
        bootstrap_runner._canonical(context) + b"\n"
    )
    operation = {
        "binding_commit_sha": "c" * 40,
        "branch": binding_branch,
        "merge_commit_sha": binding_merge,
        "pr_number": 163,
        "review_rounds_sha256": "d" * 64,
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(operation) + b"\n"
    )
    repair = _local_install_repair_operation(
        binding_merge=binding_merge,
        repair_head=repair_head,
        repair_merge=repair_merge,
    )
    (root / "local-install-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(repair) + b"\n"
    )
    baseline: dict[str, list[int]] = {
        "heavy_run_ids": [],
        "request_issue_numbers": [],
    }
    (root / "github-activity-baseline-v1.json").write_bytes(
        bootstrap_runner._canonical(baseline) + b"\n"
    )
    (root / "secrets").mkdir()
    (root / "secrets/requester-pending.pem").write_bytes(b"test-pending-key")

    calls: list[list[str]] = []

    def fake_fixed_run(args: list[str], **_kwargs: object) -> str:
        calls.append(args)
        if args[:3] == ["gh", "variable", "set"]:
            assert args[3] in {
                bootstrap_runner.ARMED_VARIABLE,
                bootstrap_runner.CONTROLLER_VARIABLE,
            }
            assert args[4:6] == ["--body", "false"]
            return ""
        if args == ["git", "fetch", "origin", "main"]:
            return ""
        if args == ["git", "rev-parse", "HEAD"]:
            return repair_merge
        if args == ["git", "rev-parse", "origin/main"]:
            return repair_merge
        if args == ["git", "rev-parse", f"{repair_merge}^1"]:
            return binding_merge
        if args == ["git", "rev-parse", f"{repair_merge}^2"]:
            return repair_head
        if args == ["git", "remote", "get-url", "origin"]:
            return "https://github.com/trading-optimizer-lab-org/aurora.git"
        if args == ["git", "status", "--porcelain=v1", "--untracked-files=no"]:
            return ""
        if args == ["git", "branch", "--show-current"]:
            return "main"
        if args[:3] == ["git", "diff", "--name-only"]:
            return "\n".join(bootstrap_runner._LOCAL_INSTALL_REPAIR_PATHS)
        if args[:3] == ["gh", "variable", "get"]:
            return "false"
        if args[:3] == ["gh", "pr", "view"] and args[3] == "163":
            return json.dumps(
                {
                    "baseRefName": "main",
                    "headRefName": binding_branch,
                    "mergeCommit": {"oid": binding_merge},
                    "state": "MERGED",
                }
            )
        if args[:3] == ["gh", "pr", "view"] and args[3] == "165":
            return json.dumps(
                {
                    "baseRefName": "main",
                    "headRefName": repair_branch,
                    "headRefOid": repair_head,
                    "mergeCommit": {"oid": repair_merge},
                    "state": "MERGED",
                }
            )
        if args[:3] == ["gh", "pr", "diff"]:
            return "\n".join(bootstrap_runner._LOCAL_INSTALL_REPAIR_PATHS)
        raise AssertionError(f"unexpected command: {args}")

    def fake_process(args: list[str], **_kwargs: object):
        assert args == [
            "git",
            "merge-base",
            "--is-ancestor",
            COMMIT,
            binding_merge,
        ]
        return subprocess.CompletedProcess(args=args, returncode=0)

    checked_prs: list[str] = []
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "BOOTSTRAP_STAGING_ROOT", staging)
    monkeypatch.setattr(bootstrap_runner, "AGENT_ROOT", agent_root)
    monkeypatch.setattr(bootstrap_runner, "BROKER_ROOT", broker_root)
    monkeypatch.setattr(bootstrap_runner, "_run", fake_fixed_run)
    monkeypatch.setattr(bootstrap_runner.subprocess, "run", fake_process)
    monkeypatch.setattr(
        bootstrap_runner,
        "_local_install_repair_patch_sha256",
        lambda *_args: "9" * 64,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_wait_for_required_checks",
        lambda pr, _source: checked_prs.append(pr),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_existing_installations",
        lambda _root: {"auditor": 2, "requester": 1},
    )
    monkeypatch.setattr(bootstrap_runner, "_github_activity_snapshot", lambda: baseline)

    assert bootstrap_runner._resume_transient_local_install_block(root) is True
    resumed = load_bootstrap_state(state_path)
    assert resumed.phase == "LOCAL_INSTALL_PENDING"
    assert resumed.sequence == 11
    recovery_path = root / "receipts/controller-bootstrap-local-install-retry-v1.json"
    recovery = json.loads(recovery_path.read_text("utf-8"))
    assert recovery["public_binding_merge_commit_sha"] == binding_merge
    assert recovery["repair_merge_commit_sha"] == repair_merge
    assert recovery["bootstrap_source_commit_sha"] == COMMIT
    assert checked_prs == ["165"]
    assert not any(command[:3] == ["gh", "pr", "merge"] for command in calls)


def test_local_install_recovery_rejects_partial_staging_before_any_command(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    source = tmp_path / "source"
    source.mkdir(parents=True)
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "partial-output").write_text("unexpected", encoding="utf-8")
    binding_merge = "b" * 40
    repair_head = "e" * 40
    repair_merge = "f" * 40
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    blocked = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked) + b"\n"
    )
    context = {
        "repository": bootstrap_runner.REPOSITORY,
        "source_commit_sha": repair_merge,
        "source_root": str(source),
    }
    (root / "install-context-v1.json").write_bytes(
        bootstrap_runner._canonical(context) + b"\n"
    )
    operation = {
        "binding_commit_sha": "c" * 40,
        "branch": "catalog/bootstrap-binding-123456789abc",
        "merge_commit_sha": binding_merge,
        "pr_number": 163,
        "review_rounds_sha256": "d" * 64,
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(operation) + b"\n"
    )
    repair = _local_install_repair_operation(
        binding_merge=binding_merge,
        repair_head=repair_head,
        repair_merge=repair_merge,
    )
    (root / "local-install-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(repair) + b"\n"
    )

    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "BOOTSTRAP_STAGING_ROOT", staging)
    monkeypatch.setattr(bootstrap_runner, "AGENT_ROOT", tmp_path / "agent")
    monkeypatch.setattr(bootstrap_runner, "BROKER_ROOT", tmp_path / "broker")
    calls: list[list[str]] = []

    def allow_only_controller_shutdown(args: list[str], **_kwargs: object) -> str:
        calls.append(args)
        assert args[:2] == ["gh", "variable"]
        assert args[2] in {"get", "set"}
        assert args[3] in {
            bootstrap_runner.ARMED_VARIABLE,
            bootstrap_runner.CONTROLLER_VARIABLE,
        }
        if args[2] == "set":
            assert args[4:6] == ["--body", "false"]
            return ""
        return "false"

    monkeypatch.setattr(bootstrap_runner, "_run", allow_only_controller_shutdown)

    with pytest.raises(ValueError, match="LOCAL_RETRY_PARTIAL_INSTALL"):
        bootstrap_runner._resume_transient_local_install_block(root)
    assert [(args[2], args[3]) for args in calls] == [
        ("set", bootstrap_runner.ARMED_VARIABLE),
        ("get", bootstrap_runner.ARMED_VARIABLE),
        ("set", bootstrap_runner.CONTROLLER_VARIABLE),
        ("get", bootstrap_runner.CONTROLLER_VARIABLE),
    ]


def test_runtime_commit_defaults_to_the_public_binding(tmp_path: Path) -> None:
    root = tmp_path / "protected"
    binding_merge = "b" * 40
    binding = {
        "binding_commit_sha": "c" * 40,
        "branch": "catalog/bootstrap-binding-123456789abc",
        "merge_commit_sha": binding_merge,
        "pr_number": 163,
        "review_rounds_sha256": "d" * 64,
    }
    (root / "receipts").mkdir(parents=True)
    (root / "public-binding-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(binding) + b"\n"
    )

    assert bootstrap_runner._runtime_commit(root) == binding_merge


def test_runtime_commit_uses_the_verified_repair_receipt(tmp_path: Path) -> None:
    root = tmp_path / "protected"
    (root / "receipts").mkdir(parents=True)
    binding_merge = "b" * 40
    repair_head = "e" * 40
    repair_merge = "f" * 40
    binding = {
        "binding_commit_sha": "c" * 40,
        "branch": "catalog/bootstrap-binding-123456789abc",
        "merge_commit_sha": binding_merge,
        "pr_number": 163,
        "review_rounds_sha256": "d" * 64,
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(binding) + b"\n"
    )
    repair = _local_install_repair_operation(
        binding_merge=binding_merge,
        repair_head=repair_head,
        repair_merge=repair_merge,
    )
    repair_path = root / "local-install-repair-operation-v1.json"
    repair_path.write_bytes(bootstrap_runner._canonical(repair) + b"\n")
    retry = {
        "activity_baseline_sha256": "1" * 64,
        "blocked_state_sha256": "2" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "public_binding_merge_commit_sha": binding_merge,
        "repair_merge_commit_sha": repair_merge,
        "repair_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(repair)
        ).hexdigest(),
        "repair_pr_number": 165,
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-local-install-retry-v1.json").write_bytes(
        bootstrap_runner._canonical(retry) + b"\n"
    )

    assert bootstrap_runner._runtime_commit(root) == repair_merge


def test_runtime_commit_uses_the_verified_followup_repair_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "protected"
    (root / "receipts").mkdir(parents=True)
    binding_merge = "b" * 40
    repair_head = "e" * 40
    repair_merge = "f" * 40
    followup_head = "1" * 40
    followup_merge = "2" * 40
    binding = {
        "binding_commit_sha": "c" * 40,
        "branch": "catalog/bootstrap-binding-123456789abc",
        "merge_commit_sha": binding_merge,
        "pr_number": 163,
        "review_rounds_sha256": "d" * 64,
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(binding) + b"\n"
    )
    repair = _local_install_repair_operation(
        binding_merge=binding_merge,
        repair_head=repair_head,
        repair_merge=repair_merge,
    )
    repair_path = root / "local-install-repair-operation-v1.json"
    repair_path.write_bytes(bootstrap_runner._canonical(repair) + b"\n")
    first_retry = {
        "activity_baseline_sha256": "1" * 64,
        "blocked_state_sha256": "2" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "public_binding_merge_commit_sha": binding_merge,
        "repair_merge_commit_sha": repair_merge,
        "repair_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(repair)
        ).hexdigest(),
        "repair_pr_number": 165,
        "schema_version": "1",
    }
    first_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-v1.json"
    )
    first_retry_path.write_bytes(
        bootstrap_runner._canonical(first_retry) + b"\n"
    )
    followup = _local_install_followup_repair_operation(
        repair_merge=repair_merge,
        followup_head=followup_head,
        followup_merge=followup_merge,
    )
    (root / "local-install-followup-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(followup) + b"\n"
    )
    second_retry = {
        "activity_baseline_sha256": "3" * 64,
        "blocked_state_sha256": "4" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "followup_merge_commit_sha": followup_merge,
        "followup_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(followup)
        ).hexdigest(),
        "followup_pr_number": 166,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            first_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": repair_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-local-install-retry-2-v1.json"
    ).write_bytes(bootstrap_runner._canonical(second_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == followup_merge

def test_runtime_commit_uses_the_verified_compat_repair_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "protected"
    (root / "receipts").mkdir(parents=True)
    binding_merge = "b" * 40
    repair_head = "e" * 40
    repair_merge = "f" * 40
    followup_head = "1" * 40
    followup_merge = "2" * 40
    compat_head = "3" * 40
    compat_merge = "4" * 40
    binding = {
        "binding_commit_sha": "c" * 40,
        "branch": "catalog/bootstrap-binding-123456789abc",
        "merge_commit_sha": binding_merge,
        "pr_number": 163,
        "review_rounds_sha256": "d" * 64,
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(binding) + b"\n"
    )
    repair = _local_install_repair_operation(
        binding_merge=binding_merge,
        repair_head=repair_head,
        repair_merge=repair_merge,
    )
    (root / "local-install-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(repair) + b"\n"
    )
    first_retry = {
        "activity_baseline_sha256": "1" * 64,
        "blocked_state_sha256": "2" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "public_binding_merge_commit_sha": binding_merge,
        "repair_merge_commit_sha": repair_merge,
        "repair_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(repair)
        ).hexdigest(),
        "repair_pr_number": 165,
        "schema_version": "1",
    }
    first_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-v1.json"
    )
    first_retry_path.write_bytes(
        bootstrap_runner._canonical(first_retry) + b"\n"
    )
    followup = _local_install_followup_repair_operation(
        repair_merge=repair_merge,
        followup_head=followup_head,
        followup_merge=followup_merge,
    )
    (root / "local-install-followup-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(followup) + b"\n"
    )
    second_retry = {
        "activity_baseline_sha256": "3" * 64,
        "blocked_state_sha256": "4" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "followup_merge_commit_sha": followup_merge,
        "followup_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(followup)
        ).hexdigest(),
        "followup_pr_number": 166,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            first_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": repair_merge,
        "schema_version": "1",
    }
    second_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-2-v1.json"
    )
    second_retry_path.write_bytes(
        bootstrap_runner._canonical(second_retry) + b"\n"
    )
    compat = _local_install_compat_repair_operation(
        followup_merge=followup_merge,
        compat_head=compat_head,
        compat_merge=compat_merge,
    )
    (root / "local-install-compat-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(compat) + b"\n"
    )
    third_retry = {
        "activity_baseline_sha256": "5" * 64,
        "blocked_state_sha256": "6" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "compat_merge_commit_sha": compat_merge,
        "compat_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(compat)
        ).hexdigest(),
        "compat_pr_number": 167,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            second_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": followup_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-local-install-retry-3-v1.json"
    ).write_bytes(bootstrap_runner._canonical(third_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == compat_merge

    account_head = "5" * 40
    account_merge = "6" * 40
    account = _local_install_account_repair_operation(
        compat_merge=compat_merge,
        account_head=account_head,
        account_merge=account_merge,
    )
    (root / "local-install-account-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(account) + b"\n"
    )
    third_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-3-v1.json"
    )
    fourth_retry = {
        "account_merge_commit_sha": account_merge,
        "account_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(account)
        ).hexdigest(),
        "account_pr_number": 168,
        "activity_baseline_sha256": "7" * 64,
        "blocked_state_sha256": "8" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            third_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": compat_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-local-install-retry-4-v1.json"
    ).write_bytes(bootstrap_runner._canonical(fourth_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == account_merge

    verifier_head = "7" * 40
    verifier_merge = "8" * 40
    verifier = _local_install_verifier_repair_operation(
        account_merge=account_merge,
        verifier_head=verifier_head,
        verifier_merge=verifier_merge,
    )
    (root / "local-install-verifier-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(verifier) + b"\n"
    )
    fourth_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-4-v1.json"
    )
    fifth_retry = {
        "activity_baseline_sha256": "9" * 64,
        "blocked_state_sha256": "a" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            fourth_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": account_merge,
        "schema_version": "1",
        "verifier_merge_commit_sha": verifier_merge,
        "verifier_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(verifier)
        ).hexdigest(),
        "verifier_pr_number": 169,
    }
    (
        root / "receipts/controller-bootstrap-local-install-retry-5-v1.json"
    ).write_bytes(bootstrap_runner._canonical(fifth_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == verifier_merge

    acl_head = "9" * 40
    acl_merge = "a" * 40
    acl = _local_install_acl_repair_operation(
        verifier_merge=verifier_merge,
        acl_head=acl_head,
        acl_merge=acl_merge,
    )
    (root / "local-install-acl-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(acl) + b"\n"
    )
    fifth_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-5-v1.json"
    )
    sixth_retry = {
        "acl_merge_commit_sha": acl_merge,
        "acl_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(acl)
        ).hexdigest(),
        "acl_pr_number": 170,
        "activity_baseline_sha256": "b" * 64,
        "blocked_state_sha256": "c" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            fifth_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": verifier_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-local-install-retry-6-v1.json"
    ).write_bytes(bootstrap_runner._canonical(sixth_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == acl_merge

    task_identity_head = "b" * 40
    task_identity_merge = "c" * 40
    task_identity = _local_install_task_identity_repair_operation(
        acl_merge=acl_merge,
        task_identity_head=task_identity_head,
        task_identity_merge=task_identity_merge,
    )
    (
        root / "local-install-task-identity-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(task_identity) + b"\n")
    assert bootstrap_runner._runtime_commit(root) == task_identity_merge

    task_identity_followup_head = "d" * 40
    task_identity_followup_merge = "e" * 40
    task_identity_followup = (
        _local_install_task_identity_followup_repair_operation(
            task_identity_merge=task_identity_merge,
            followup_head=task_identity_followup_head,
            followup_merge=task_identity_followup_merge,
        )
    )
    (
        root / "local-install-task-identity-followup-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(task_identity_followup) + b"\n")
    sixth_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-6-v1.json"
    )
    seventh_retry = {
        "activity_baseline_sha256": "f" * 64,
        "blocked_state_sha256": "1" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            sixth_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": task_identity_merge,
        "schema_version": "1",
        "task_identity_followup_merge_commit_sha": task_identity_followup_merge,
        "task_identity_followup_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(task_identity_followup)
        ).hexdigest(),
        "task_identity_followup_pr_number": 172,
    }
    (
        root / "receipts/controller-bootstrap-local-install-retry-7-v1.json"
    ).write_bytes(bootstrap_runner._canonical(seventh_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == task_identity_followup_merge

    github_controls_head = "f" * 40
    github_controls_merge = "1" * 40
    github_controls = _github_controls_repair_operation(
        prior_merge=task_identity_followup_merge,
        repair_head=github_controls_head,
        repair_merge=github_controls_merge,
    )
    (root / "github-controls-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(github_controls) + b"\n"
    )
    seventh_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-7-v1.json"
    )
    github_controls_retry = {
        "activity_baseline_sha256": "2" * 64,
        "blocked_state_sha256": "3" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "github_controls_merge_commit_sha": github_controls_merge,
        "github_controls_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(github_controls)
        ).hexdigest(),
        "github_controls_pr_number": 173,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            seventh_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": task_identity_followup_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-v1.json"
    ).write_bytes(bootstrap_runner._canonical(github_controls_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == github_controls_merge

    followup_head = "2" * 40
    followup_merge = "3" * 40
    github_controls_followup = _github_controls_followup_repair_operation(
        prior_merge=github_controls_merge,
        repair_head=followup_head,
        repair_merge=followup_merge,
    )
    (root / "github-controls-followup-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(github_controls_followup) + b"\n"
    )
    github_controls_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-v1.json"
    )
    github_controls_followup_retry = {
        "activity_baseline_sha256": "4" * 64,
        "blocked_state_sha256": "5" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "followup_merge_commit_sha": followup_merge,
        "followup_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(github_controls_followup)
        ).hexdigest(),
        "followup_pr_number": 174,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            github_controls_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": github_controls_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-2-v1.json"
    ).write_bytes(
        bootstrap_runner._canonical(github_controls_followup_retry) + b"\n"
    )

    assert bootstrap_runner._runtime_commit(root) == followup_merge

    enterprise_head = "4" * 40
    enterprise_merge = "5" * 40
    enterprise_operation = _github_controls_enterprise_repair_operation(
        prior_merge=followup_merge,
        repair_head=enterprise_head,
        repair_merge=enterprise_merge,
    )
    (root / "github-controls-enterprise-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(enterprise_operation) + b"\n"
    )
    followup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-2-v1.json"
    )
    enterprise_retry = {
        "activity_baseline_sha256": "6" * 64,
        "blocked_state_sha256": "7" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "enterprise_merge_commit_sha": enterprise_merge,
        "enterprise_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(enterprise_operation)
        ).hexdigest(),
        "enterprise_pr_number": 175,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            followup_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": followup_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-3-v1.json"
    ).write_bytes(bootstrap_runner._canonical(enterprise_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == enterprise_merge

    billing_token_head = "6" * 40
    billing_token_merge = "7" * 40
    billing_token_operation = _github_controls_billing_token_repair_operation(
        prior_merge=enterprise_merge,
        repair_head=billing_token_head,
        repair_merge=billing_token_merge,
    )
    (
        root / "github-controls-billing-token-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(billing_token_operation) + b"\n")
    enterprise_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-3-v1.json"
    )
    billing_token_retry = {
        "activity_baseline_sha256": "8" * 64,
        "billing_token_merge_commit_sha": billing_token_merge,
        "billing_token_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(billing_token_operation)
        ).hexdigest(),
        "billing_token_pr_number": 176,
        "blocked_state_sha256": "9" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            enterprise_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": enterprise_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-4-v1.json"
    ).write_bytes(bootstrap_runner._canonical(billing_token_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == billing_token_merge

    stable_head = "8" * 40
    stable_merge = "9" * 40
    stable_operation = _github_controls_stable_precondition_repair_operation(
        prior_merge=billing_token_merge,
        repair_head=stable_head,
        repair_merge=stable_merge,
    )
    (
        root / "github-controls-stable-precondition-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(stable_operation) + b"\n")
    billing_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-4-v1.json"
    )
    stable_retry = {
        "activity_baseline_sha256": "a" * 64,
        "blocked_state_sha256": "b" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            billing_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": billing_token_merge,
        "schema_version": "1",
        "stable_precondition_merge_commit_sha": stable_merge,
        "stable_precondition_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(stable_operation)
        ).hexdigest(),
        "stable_precondition_pr_number": 177,
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-5-v1.json"
    ).write_bytes(bootstrap_runner._canonical(stable_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == stable_merge

    cache_head = "a" * 40
    cache_merge = "b" * 40
    cache_operation = _github_controls_cache_retention_repair_operation(
        prior_merge=stable_merge,
        repair_head=cache_head,
        repair_merge=cache_merge,
    )
    (
        root / "github-controls-cache-retention-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(cache_operation) + b"\n")
    stable_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-5-v1.json"
    )
    cache_retry = {
        "activity_baseline_sha256": "c" * 64,
        "blocked_state_sha256": "d" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "cache_retention_merge_commit_sha": cache_merge,
        "cache_retention_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(cache_operation)
        ).hexdigest(),
        "cache_retention_pr_number": 178,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            stable_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": stable_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-6-v1.json"
    ).write_bytes(bootstrap_runner._canonical(cache_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == cache_merge

    storage_head = "c" * 40
    storage_merge = "d" * 40
    storage_operation = _github_controls_storage_audit_repair_operation(
        prior_merge=cache_merge,
        repair_head=storage_head,
        repair_merge=storage_merge,
    )
    (
        root / "github-controls-storage-audit-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(storage_operation) + b"\n")
    cache_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-6-v1.json"
    )
    storage_retry = {
        "activity_baseline_sha256": "e" * 64,
        "blocked_state_sha256": "f" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            cache_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": cache_merge,
        "schema_version": "1",
        "storage_audit_merge_commit_sha": storage_merge,
        "storage_audit_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(storage_operation)
        ).hexdigest(),
        "storage_audit_pr_number": 179,
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-7-v1.json"
    ).write_bytes(bootstrap_runner._canonical(storage_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == storage_merge

    throughput_head = "e" * 40
    throughput_merge = "f" * 40
    throughput_operation = _github_controls_audit_throughput_repair_operation(
        prior_merge=storage_merge,
        repair_head=throughput_head,
        repair_merge=throughput_merge,
    )
    (
        root / "github-controls-audit-throughput-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(throughput_operation) + b"\n")
    storage_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-7-v1.json"
    )
    throughput_retry = {
        "activity_baseline_sha256": "1" * 64,
        "audit_throughput_merge_commit_sha": throughput_merge,
        "audit_throughput_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(throughput_operation)
        ).hexdigest(),
        "audit_throughput_pr_number": 180,
        "blocked_state_sha256": "2" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "prior_retry_receipt_sha256": hashlib.sha256(
            storage_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": storage_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-8-v1.json"
    ).write_bytes(bootstrap_runner._canonical(throughput_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == throughput_merge

    package_token_head = "2" * 40
    package_token_merge = "3" * 40
    package_token_operation = _github_controls_package_token_repair_operation(
        prior_merge=throughput_merge,
        repair_head=package_token_head,
        repair_merge=package_token_merge,
    )
    (
        root / "github-controls-package-token-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(package_token_operation) + b"\n")
    throughput_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-8-v1.json"
    )
    package_token_retry = {
        "activity_baseline_sha256": "4" * 64,
        "blocked_state_sha256": "5" * 64,
        "bootstrap_source_commit_sha": COMMIT,
        "installations": {"auditor": 2, "requester": 1},
        "package_token_merge_commit_sha": package_token_merge,
        "package_token_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(package_token_operation)
        ).hexdigest(),
        "package_token_pr_number": 188,
        "prior_retry_receipt_sha256": hashlib.sha256(
            throughput_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": throughput_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-9-v1.json"
    ).write_bytes(bootstrap_runner._canonical(package_token_retry) + b"\n")

    assert bootstrap_runner._runtime_commit(root) == package_token_merge

    resume_head = "4" * 40
    resume_merge = "5" * 40
    resume_operation = _idempotent_resume_repair_operation(
        prior_merge=package_token_merge,
        repair_head=resume_head,
        repair_merge=resume_merge,
    )
    (root / "github-controls-idempotent-resume-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(resume_operation) + b"\n"
    )
    package_token_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-9-v1.json"
    )
    resume_retry = {
        "activity_baseline_sha256": "6" * 64,
        "bootstrap_id": BOOTSTRAP_ID,
        "bootstrap_source_commit_sha": COMMIT,
        "idempotent_resume_merge_commit_sha": resume_merge,
        "idempotent_resume_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(resume_operation)
        ).hexdigest(),
        "idempotent_resume_pr_number": 194,
        "installations": {"auditor": 2, "requester": 1},
        "interrupted_phase": "QUALIFICATION_PENDING",
        "interrupted_sequence": 43,
        "interrupted_state_sha256": "7" * 64,
        "prior_retry_receipt_sha256": hashlib.sha256(
            package_token_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": package_token_merge,
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json").write_bytes(
        bootstrap_runner._canonical(resume_retry) + b"\n"
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_REFRESH_INVALID",
    ):
        bootstrap_runner._runtime_commit(root)

    prior_controls = {"protected_commit_sha": package_token_merge}
    refreshed_controls = {"protected_commit_sha": resume_merge}
    prior_controls_path = root / "github-controls-operation-before-runtime-upgrade-v1.json"
    controls_path = root / "github-controls-operation-v1.json"
    prior_controls_path.write_bytes(bootstrap_runner._canonical(prior_controls) + b"\n")
    controls_path.write_bytes(bootstrap_runner._canonical(refreshed_controls) + b"\n")
    refresh = {
        "bootstrap_id": BOOTSTRAP_ID,
        "prior_controls_operation_sha256": hashlib.sha256(
            prior_controls_path.read_bytes()
        ).hexdigest(),
        "protected_commit_sha": resume_merge,
        "refreshed_controls_operation_sha256": hashlib.sha256(
            controls_path.read_bytes()
        ).hexdigest(),
        "runtime_upgrade_operation_sha256": hashlib.sha256(
            (root / "github-controls-idempotent-resume-repair-operation-v1.json").read_bytes()
        ).hexdigest(),
        "schema_version": "1",
    }
    (root / "runtime-upgrade-controls-refresh-v1.json").write_bytes(
        bootstrap_runner._canonical(refresh) + b"\n"
    )

    assert bootstrap_runner._runtime_commit(root) == resume_merge

    followup_base = "6" * 40
    followup_head = "7" * 40
    followup_merge = "8" * 40
    followup_operation = _idempotent_resume_followup_repair_operation(
        prior_merge=resume_merge,
        base_commit=followup_base,
        repair_head=followup_head,
        repair_merge=followup_merge,
    )
    followup_operation_path = (
        root / "github-controls-idempotent-resume-followup-repair-operation-v1.json"
    )
    followup_operation_path.write_bytes(
        bootstrap_runner._canonical(followup_operation) + b"\n"
    )
    resume_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json"
    )
    followup_retry = {
        "activity_baseline_sha256": "8" * 64,
        "bootstrap_id": BOOTSTRAP_ID,
        "bootstrap_source_commit_sha": COMMIT,
        "idempotent_resume_followup_merge_commit_sha": followup_merge,
        "idempotent_resume_followup_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(followup_operation)
        ).hexdigest(),
        "idempotent_resume_followup_pr_number": 196,
        "installations": {"auditor": 2, "requester": 1},
        "interrupted_phase": "QUALIFICATION_PENDING",
        "interrupted_sequence": 43,
        "interrupted_state_sha256": "9" * 64,
        "prior_retry_receipt_sha256": hashlib.sha256(
            resume_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": resume_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-11-v1.json"
    ).write_bytes(bootstrap_runner._canonical(followup_retry) + b"\n")

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_FOLLOWUP_REFRESH_INVALID",
    ):
        bootstrap_runner._runtime_commit(root)

    prior_controls = {"protected_commit_sha": package_token_merge}
    refreshed_controls = {"protected_commit_sha": followup_merge}
    prior_controls_path.write_bytes(bootstrap_runner._canonical(prior_controls) + b"\n")
    controls_path.write_bytes(bootstrap_runner._canonical(refreshed_controls) + b"\n")
    followup_refresh = {
        "bootstrap_id": BOOTSTRAP_ID,
        "prior_controls_operation_sha256": hashlib.sha256(
            prior_controls_path.read_bytes()
        ).hexdigest(),
        "protected_commit_sha": followup_merge,
        "refreshed_controls_operation_sha256": hashlib.sha256(
            controls_path.read_bytes()
        ).hexdigest(),
        "runtime_upgrade_operation_sha256": hashlib.sha256(
            followup_operation_path.read_bytes()
        ).hexdigest(),
        "schema_version": "1",
    }
    (root / "runtime-upgrade-controls-refresh-v1.json").write_bytes(
        bootstrap_runner._canonical(followup_refresh) + b"\n"
    )

    assert bootstrap_runner._runtime_commit(root) == followup_merge

    catchup_head = "9" * 40
    catchup_merge = "a" * 40
    catchup_operation = _idempotent_resume_catchup_repair_operation(
        prior_merge=followup_merge,
        repair_head=catchup_head,
        repair_merge=catchup_merge,
    )
    catchup_operation_path = (
        root / "github-controls-idempotent-resume-catchup-repair-operation-v1.json"
    )
    catchup_operation_path.write_bytes(
        bootstrap_runner._canonical(catchup_operation) + b"\n"
    )
    followup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-11-v1.json"
    )
    catchup_retry = {
        "activity_baseline_sha256": "b" * 64,
        "bootstrap_id": BOOTSTRAP_ID,
        "bootstrap_source_commit_sha": COMMIT,
        "idempotent_resume_catchup_merge_commit_sha": catchup_merge,
        "idempotent_resume_catchup_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(catchup_operation)
        ).hexdigest(),
        "idempotent_resume_catchup_pr_number": 197,
        "installations": {"auditor": 2, "requester": 1},
        "interrupted_phase": "QUALIFICATION_PENDING",
        "interrupted_sequence": 43,
        "interrupted_state_sha256": "c" * 64,
        "prior_retry_receipt_sha256": hashlib.sha256(
            followup_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": followup_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-12-v1.json"
    ).write_bytes(bootstrap_runner._canonical(catchup_retry) + b"\n")

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CATCHUP_REFRESH_INVALID",
    ):
        bootstrap_runner._runtime_commit(root)

    refreshed_controls = {"protected_commit_sha": catchup_merge}
    controls_path.write_bytes(bootstrap_runner._canonical(refreshed_controls) + b"\n")
    catchup_refresh = {
        "bootstrap_id": BOOTSTRAP_ID,
        "prior_controls_operation_sha256": hashlib.sha256(
            prior_controls_path.read_bytes()
        ).hexdigest(),
        "protected_commit_sha": catchup_merge,
        "refreshed_controls_operation_sha256": hashlib.sha256(
            controls_path.read_bytes()
        ).hexdigest(),
        "runtime_upgrade_operation_sha256": hashlib.sha256(
            catchup_operation_path.read_bytes()
        ).hexdigest(),
        "schema_version": "1",
    }
    (root / "runtime-upgrade-controls-refresh-v1.json").write_bytes(
        bootstrap_runner._canonical(catchup_refresh) + b"\n"
    )

    assert bootstrap_runner._runtime_commit(root) == catchup_merge

    upgrade_merge = "d" * 40
    upgrade_operation = _idempotent_resume_upgrade_repair_operation(
        upgrade_index=13,
        prior_merge=catchup_merge,
        repair_head="c" * 40,
        repair_merge=upgrade_merge,
        pr_number=198,
    )
    upgrade_operation_path = (
        root / "github-controls-idempotent-resume-upgrade-13-operation-v1.json"
    )
    upgrade_operation_path.write_bytes(
        bootstrap_runner._canonical(upgrade_operation) + b"\n"
    )
    catchup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-12-v1.json"
    )
    upgrade_retry = {
        "activity_baseline_sha256": "d" * 64,
        "bootstrap_id": BOOTSTRAP_ID,
        "bootstrap_source_commit_sha": COMMIT,
        "idempotent_resume_upgrade_index": 13,
        "idempotent_resume_upgrade_merge_commit_sha": upgrade_merge,
        "idempotent_resume_upgrade_operation_sha256": hashlib.sha256(
            bootstrap_runner._canonical(upgrade_operation)
        ).hexdigest(),
        "idempotent_resume_upgrade_pr_number": 198,
        "installations": {"auditor": 2, "requester": 1},
        "interrupted_phase": "QUALIFICATION_PENDING",
        "interrupted_sequence": 43,
        "interrupted_state_sha256": "e" * 64,
        "prior_retry_receipt_sha256": hashlib.sha256(
            catchup_retry_path.read_bytes()
        ).hexdigest(),
        "prior_runtime_commit_sha": catchup_merge,
        "schema_version": "1",
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-13-v1.json"
    ).write_bytes(bootstrap_runner._canonical(upgrade_retry) + b"\n")

    upgrade_operation["upgrade_index"] = 13.0
    upgrade_operation_path.write_bytes(
        bootstrap_runner._canonical(upgrade_operation) + b"\n"
    )
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REPAIR_INVALID",
    ):
        bootstrap_runner._runtime_commit(root)
    upgrade_operation["upgrade_index"] = 13
    upgrade_operation_path.write_bytes(
        bootstrap_runner._canonical(upgrade_operation) + b"\n"
    )

    upgrade_retry["idempotent_resume_upgrade_index"] = 13.0
    upgrade_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-13-v1.json"
    )
    upgrade_retry_path.write_bytes(
        bootstrap_runner._canonical(upgrade_retry) + b"\n"
    )
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_RETRY_INVALID",
    ):
        bootstrap_runner._runtime_commit(root)
    upgrade_retry["idempotent_resume_upgrade_index"] = 13
    upgrade_retry_path.write_bytes(
        bootstrap_runner._canonical(upgrade_retry) + b"\n"
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REFRESH_INVALID",
    ):
        bootstrap_runner._runtime_commit(root)

    refreshed_controls = {"protected_commit_sha": upgrade_merge}
    controls_path.write_bytes(bootstrap_runner._canonical(refreshed_controls) + b"\n")
    upgrade_refresh = {
        "bootstrap_id": BOOTSTRAP_ID,
        "prior_controls_operation_sha256": hashlib.sha256(
            prior_controls_path.read_bytes()
        ).hexdigest(),
        "protected_commit_sha": upgrade_merge,
        "refreshed_controls_operation_sha256": hashlib.sha256(
            controls_path.read_bytes()
        ).hexdigest(),
        "runtime_upgrade_operation_sha256": hashlib.sha256(
            upgrade_operation_path.read_bytes()
        ).hexdigest(),
        "schema_version": "1",
    }
    (root / "runtime-upgrade-controls-refresh-v1.json").write_bytes(
        bootstrap_runner._canonical(upgrade_refresh) + b"\n"
    )

    assert bootstrap_runner._runtime_commit(root) == upgrade_merge

    gapped_operation_path = (
        root / "github-controls-idempotent-resume-upgrade-15-operation-v1.json"
    )
    gapped_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-15-v1.json"
    )
    gapped_operation_path.write_text("{}\n", encoding="utf-8")
    gapped_retry_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_RETRY_INVALID",
    ):
        bootstrap_runner._runtime_commit(root)
    gapped_operation_path.unlink()
    gapped_retry_path.unlink()

    resume_retry["prior_retry_receipt_sha256"] = "0" * 64
    (root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json").write_bytes(
        bootstrap_runner._canonical(resume_retry) + b"\n"
    )
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_RETRY_INVALID",
    ):
        bootstrap_runner._runtime_commit(root)


@pytest.mark.parametrize(
    "paths",
    [
        ["../escape.py"],
        ["scripts\\escape.py"],
        ["scripts/ok.py", "scripts/ok.py"],
        ["outside/file.py"],
        ["tests/z.py", "scripts/a.py"],
    ],
)
def test_idempotent_resume_paths_fail_closed(paths: list[str]) -> None:
    assert bootstrap_runner._valid_idempotent_resume_paths(paths) is False


def test_idempotent_resume_github_authorization_binds_pr_check_paths_and_graph(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operation = _idempotent_resume_repair_operation(
        prior_merge="3" * 40,
        repair_head="4" * 40,
        repair_merge="5" * 40,
    )
    observed_paths = tuple(cast(list[str], operation["changed_paths"]))
    graph_calls: list[dict[str, object]] = []

    def fake_run(command: list[str], *, cwd: Path, **_kwargs: object) -> str:
        assert cwd == tmp_path
        if command[:3] == ["gh", "pr", "view"]:
            return json.dumps(
                {
                    "baseRefName": "main",
                    "baseRefOid": operation["base_commit_sha"],
                    "headRefName": operation["branch"],
                    "headRefOid": operation["head_commit_sha"],
                    "isDraft": False,
                    "mergeCommit": {"oid": operation["merge_commit_sha"]},
                    "number": operation["pr_number"],
                    "state": "MERGED",
                }
            )
        if command[:3] == ["gh", "pr", "checks"]:
            return json.dumps(
                [
                    {
                        "bucket": "pass",
                        "name": "catalog-controller-policy",
                        "state": "SUCCESS",
                    }
                ]
            )
        if command == ["git", "rev-parse", "origin/main"]:
            return str(operation["merge_commit_sha"])
        raise AssertionError(command)

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(
        bootstrap_runner,
        "_git_changed_paths",
        lambda *_args: observed_paths,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_github_controls_repair_graph",
        lambda _source, value: graph_calls.append(value),
    )

    bootstrap_runner._verify_idempotent_resume_github_authorization(tmp_path, operation)

    assert graph_calls == [operation]

    operation["changed_paths"] = ["config/unrelated.json"]
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_PATHS_INVALID",
    ):
        bootstrap_runner._verify_idempotent_resume_github_authorization(tmp_path, operation)


def test_idempotent_resume_followup_authorization_uses_cumulative_runtime_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operation = _idempotent_resume_followup_repair_operation(
        prior_merge="3" * 40,
        base_commit="4" * 40,
        repair_head="5" * 40,
        repair_merge="6" * 40,
    )
    observed_paths = tuple(cast(list[str], operation["changed_paths"]))
    path_calls: list[tuple[str, str]] = []
    graph_calls: list[tuple[dict[str, object], str | None]] = []

    def fake_run(command: list[str], *, cwd: Path, **_kwargs: object) -> str:
        assert cwd == tmp_path
        if command[:3] == ["gh", "pr", "view"]:
            return json.dumps(
                {
                    "baseRefName": "main",
                    "baseRefOid": operation["base_commit_sha"],
                    "headRefName": operation["branch"],
                    "headRefOid": operation["head_commit_sha"],
                    "isDraft": False,
                    "mergeCommit": {"oid": operation["merge_commit_sha"]},
                    "number": operation["pr_number"],
                    "state": "MERGED",
                }
            )
        if command[:3] == ["gh", "pr", "checks"]:
            return json.dumps(
                [
                    {
                        "bucket": "pass",
                        "name": "catalog-controller-policy",
                        "state": "SUCCESS",
                    }
                ]
            )
        if command == ["git", "rev-parse", "origin/main"]:
            return str(operation["merge_commit_sha"])
        raise AssertionError(command)

    def fake_paths(_source: Path, base: str, head: str) -> tuple[str, ...]:
        path_calls.append((base, head))
        return observed_paths

    def fake_graph(
        _source: Path,
        value: dict[str, object],
        *,
        patch_base_commit: str | None = None,
    ) -> None:
        graph_calls.append((value, patch_base_commit))

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(bootstrap_runner, "_git_changed_paths", fake_paths)
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_github_controls_repair_graph",
        fake_graph,
    )

    bootstrap_runner._verify_idempotent_resume_github_authorization(tmp_path, operation)

    assert path_calls == [
        (str(operation["prior_runtime_commit_sha"]), str(operation["head_commit_sha"]))
    ]
    assert graph_calls == [
        (operation, str(operation["prior_runtime_commit_sha"]))
    ]


def test_generic_runtime_upgrade_authorization_binds_its_own_pr_and_runtime_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operation = _idempotent_resume_upgrade_repair_operation(
        upgrade_index=13,
        prior_merge="3" * 40,
        repair_head="4" * 40,
        repair_merge="5" * 40,
        pr_number=198,
    )
    observed_paths = tuple(cast(list[str], operation["changed_paths"]))
    pull_request_base = "6" * 40
    path_calls: list[tuple[str, str]] = []
    graph_calls: list[tuple[dict[str, object], str | None, str | None]] = []

    def fake_run(command: list[str], *, cwd: Path, **_kwargs: object) -> str:
        assert cwd == tmp_path
        if command[:3] == ["gh", "pr", "view"]:
            return json.dumps(
                {
                    "baseRefName": "main",
                    "baseRefOid": pull_request_base,
                    "headRefName": operation["branch"],
                    "headRefOid": operation["head_commit_sha"],
                    "isDraft": False,
                    "mergeCommit": {"oid": operation["merge_commit_sha"]},
                    "number": operation["pr_number"],
                    "state": "MERGED",
                }
            )
        if command[:3] == ["gh", "pr", "checks"]:
            return json.dumps(
                [
                    {
                        "bucket": "pass",
                        "name": "catalog-controller-policy",
                        "state": "SUCCESS",
                    }
                ]
            )
        if command == ["git", "rev-parse", "origin/main"]:
            return str(operation["merge_commit_sha"])
        raise AssertionError(command)

    def fake_paths(_source: Path, base: str, head: str) -> tuple[str, ...]:
        path_calls.append((base, head))
        return observed_paths

    def fake_graph(
        _source: Path,
        value: dict[str, object],
        *,
        patch_base_commit: str | None = None,
        pull_request_base_commit: str | None = None,
    ) -> None:
        graph_calls.append((value, patch_base_commit, pull_request_base_commit))

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(bootstrap_runner, "_git_changed_paths", fake_paths)
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_github_controls_repair_graph",
        fake_graph,
    )

    bootstrap_runner._verify_idempotent_resume_github_authorization(tmp_path, operation)

    assert path_calls == [
        (str(operation["prior_runtime_commit_sha"]), str(operation["head_commit_sha"]))
    ]
    assert graph_calls == [
        (
            operation,
            str(operation["prior_runtime_commit_sha"]),
            pull_request_base,
        )
    ]


def test_prior_generic_upgrade_must_be_ancestor_of_the_protected_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operation = _idempotent_resume_upgrade_repair_operation(
        upgrade_index=13,
        prior_merge="3" * 40,
        repair_head="4" * 40,
        repair_merge="5" * 40,
        pr_number=198,
    )
    protected_main = "6" * 40
    ancestry_calls: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path, **_kwargs: object) -> str:
        assert cwd == tmp_path
        if command[:3] == ["gh", "pr", "view"]:
            return json.dumps(
                {
                    "baseRefName": "main",
                    "baseRefOid": operation["base_commit_sha"],
                    "headRefName": operation["branch"],
                    "headRefOid": operation["head_commit_sha"],
                    "isDraft": False,
                    "mergeCommit": {"oid": operation["merge_commit_sha"]},
                    "number": operation["pr_number"],
                    "state": "MERGED",
                }
            )
        if command[:3] == ["gh", "pr", "checks"]:
            return json.dumps(
                [
                    {
                        "bucket": "pass",
                        "name": "catalog-controller-policy",
                        "state": "SUCCESS",
                    }
                ]
            )
        if command == ["git", "rev-parse", "origin/main"]:
            return protected_main
        if command[:3] == ["git", "merge-base", "--is-ancestor"]:
            ancestry_calls.append(command)
            return ""
        raise AssertionError(command)

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(
        bootstrap_runner,
        "_git_changed_paths",
        lambda *_args: tuple(cast(list[str], operation["changed_paths"])),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_github_controls_repair_graph",
        lambda *_args, **_kwargs: None,
    )

    bootstrap_runner._verify_idempotent_resume_github_authorization(
        tmp_path,
        operation,
        protected_main_commit_sha=protected_main,
    )

    assert ancestry_calls == [
        [
            "git",
            "merge-base",
            "--is-ancestor",
            str(operation["merge_commit_sha"]),
            protected_main,
        ]
    ]


def test_generic_runtime_upgrade_rejects_numeric_commit_or_hash_fields(
    tmp_path: Path,
) -> None:
    operation = _idempotent_resume_upgrade_repair_operation(
        upgrade_index=13,
        prior_merge="3" * 40,
        repair_head="4" * 40,
        repair_merge="5" * 40,
        pr_number=198,
    )
    operation["head_commit_sha"] = int("4" * 40)
    path = (
        tmp_path / "github-controls-idempotent-resume-upgrade-13-operation-v1.json"
    )
    path.write_bytes(bootstrap_runner._canonical(operation) + b"\n")

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REPAIR_INVALID",
    ):
        bootstrap_runner._validated_idempotent_resume_upgrade_repair(
            tmp_path,
            13,
            {"merge_commit_sha": "3" * 40},
        )


@pytest.mark.parametrize("invalid_index", [13.0, True])
def test_runtime_refresh_selector_requires_strict_integer_upgrade_index(
    tmp_path: Path,
    invalid_index: object,
) -> None:
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_REPAIR_INVALID",
    ):
        bootstrap_runner._runtime_upgrade_refresh_path(tmp_path, invalid_index)


def test_idempotent_resume_github_authorization_rejects_unmerged_pr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operation = _idempotent_resume_repair_operation(
        prior_merge="3" * 40,
        repair_head="4" * 40,
        repair_merge="5" * 40,
    )

    def fake_run(command: list[str], *, cwd: Path, **_kwargs: object) -> str:
        assert cwd == tmp_path
        if command[:3] == ["gh", "pr", "view"]:
            return json.dumps(
                {
                    "baseRefName": "main",
                    "baseRefOid": operation["base_commit_sha"],
                    "headRefName": operation["branch"],
                    "headRefOid": operation["head_commit_sha"],
                    "isDraft": False,
                    "mergeCommit": None,
                    "number": operation["pr_number"],
                    "state": "OPEN",
                }
            )
        if command[:3] == ["gh", "pr", "checks"]:
            return "[]"
        raise AssertionError(command)

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_GITHUB_INVALID",
    ):
        bootstrap_runner._verify_idempotent_resume_github_authorization(tmp_path, operation)


def test_runtime_upgrade_control_refresh_is_idempotent_and_preserves_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "installed"
    (root / "state").mkdir(parents=True)
    (root / "receipts").mkdir()
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    state_document = {
        "bootstrap_id": BOOTSTRAP_ID,
        "phase": "QUALIFICATION_PENDING",
        "sequence": 43,
    }
    state_path.write_bytes(bootstrap_runner._canonical(state_document) + b"\n")
    original_state = state_path.read_bytes()
    baseline: dict[str, object] = {
        "heavy_run_ids": [],
        "request_issue_numbers": [],
    }
    (root / "github-activity-baseline-v1.json").write_bytes(
        bootstrap_runner._canonical(baseline) + b"\n"
    )
    prior_runtime = "3" * 40
    intermediate_runtime = "4" * 40
    followup_runtime = "5" * 40
    catchup_runtime = "6" * 40
    first_generic_runtime = "7" * 40
    protected_commit = "8" * 40
    retry = {
        "activity_baseline_sha256": hashlib.sha256(
            bootstrap_runner._canonical(baseline)
        ).hexdigest(),
        "bootstrap_id": BOOTSTRAP_ID,
        "interrupted_phase": "QUALIFICATION_PENDING",
        "interrupted_sequence": 43,
        "interrupted_state_sha256": hashlib.sha256(original_state).hexdigest(),
    }
    (root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json").write_bytes(
        bootstrap_runner._canonical(retry) + b"\n"
    )
    upgrade_operation = {
        "prior_runtime_commit_sha": prior_runtime,
    }
    (root / "github-controls-idempotent-resume-repair-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(upgrade_operation) + b"\n"
    )
    followup_operation = {
        "merge_commit_sha": followup_runtime,
        "prior_runtime_commit_sha": intermediate_runtime,
    }
    (
        root / "github-controls-idempotent-resume-followup-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(followup_operation) + b"\n")
    followup_retry = {
        "activity_baseline_sha256": retry["activity_baseline_sha256"],
        "bootstrap_id": BOOTSTRAP_ID,
        "interrupted_phase": "QUALIFICATION_PENDING",
        "interrupted_sequence": 43,
        "interrupted_state_sha256": retry["interrupted_state_sha256"],
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-11-v1.json"
    ).write_bytes(bootstrap_runner._canonical(followup_retry) + b"\n")
    catchup_operation = {
        "merge_commit_sha": catchup_runtime,
        "prior_runtime_commit_sha": followup_runtime,
    }
    (
        root / "github-controls-idempotent-resume-catchup-repair-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(catchup_operation) + b"\n")
    catchup_retry = {
        "activity_baseline_sha256": retry["activity_baseline_sha256"],
        "bootstrap_id": BOOTSTRAP_ID,
        "interrupted_phase": "QUALIFICATION_PENDING",
        "interrupted_sequence": 43,
        "interrupted_state_sha256": retry["interrupted_state_sha256"],
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-12-v1.json"
    ).write_bytes(bootstrap_runner._canonical(catchup_retry) + b"\n")
    generic_operation = {
        "merge_commit_sha": first_generic_runtime,
        "prior_runtime_commit_sha": catchup_runtime,
    }
    (
        root / "github-controls-idempotent-resume-upgrade-13-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(generic_operation) + b"\n")
    generic_retry = {
        "activity_baseline_sha256": retry["activity_baseline_sha256"],
        "bootstrap_id": BOOTSTRAP_ID,
        "interrupted_phase": "QUALIFICATION_PENDING",
        "interrupted_sequence": 43,
        "interrupted_state_sha256": retry["interrupted_state_sha256"],
    }
    (
        root / "receipts/controller-bootstrap-github-controls-retry-13-v1.json"
    ).write_bytes(bootstrap_runner._canonical(generic_retry) + b"\n")
    final_generic_operation = {
        "merge_commit_sha": protected_commit,
        "prior_runtime_commit_sha": first_generic_runtime,
    }
    (
        root / "github-controls-idempotent-resume-upgrade-14-operation-v1.json"
    ).write_bytes(bootstrap_runner._canonical(final_generic_operation) + b"\n")
    (
        root / "receipts/controller-bootstrap-github-controls-retry-14-v1.json"
    ).write_bytes(bootstrap_runner._canonical(generic_retry) + b"\n")
    old_controls = {"protected_commit_sha": prior_runtime}
    controls_path = root / "github-controls-operation-v1.json"
    controls_path.write_bytes(bootstrap_runner._canonical(old_controls) + b"\n")
    source = tmp_path / "source"
    source.mkdir()
    calls: list[str] = []

    monkeypatch.setattr(
        bootstrap_runner,
        "load_bootstrap_state",
        lambda _path: SimpleNamespace(
            phase="QUALIFICATION_PENDING",
            sequence=43,
        ),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_runtime_commit",
        lambda _root, **_kwargs: protected_commit,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_context",
        lambda _root: {
            "repository": bootstrap_runner.REPOSITORY,
            "source_commit_sha": protected_commit,
            "source_root": str(source),
        },
    )

    def fake_run(command: list[str], **_kwargs: object) -> str:
        if command[1:3] == ["rev-parse", "origin/main"]:
            return protected_commit
        if command[1:3] == ["status", "--porcelain=v1"]:
            return ""
        return protected_commit

    def fake_prepare(
        installed_root: Path,
        commit: str,
        *,
        live_step_name: str,
    ) -> dict[str, object]:
        calls.append(live_step_name)
        receipt: dict[str, object] = {"protected_commit_sha": commit}
        (installed_root / "github-controls-operation-v1.json").write_bytes(
            bootstrap_runner._canonical(receipt) + b"\n"
        )
        return receipt

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)

    rejected_authorizations: list[
        tuple[Path, dict[str, object], str | None]
    ] = []

    def reject_authorization(
        checkout: Path,
        operation: dict[str, object],
        *,
        protected_main_commit_sha: str | None = None,
    ) -> None:
        rejected_authorizations.append(
            (checkout, operation, protected_main_commit_sha)
        )
        raise ValueError("authorization-rejected")

    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_idempotent_resume_github_authorization",
        reject_authorization,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_prepare_github_controls_operation",
        fake_prepare,
    )

    with pytest.raises(ValueError, match="authorization-rejected"):
        bootstrap_runner._refresh_interrupted_runtime_controls(root)

    assert rejected_authorizations == [
        (source, generic_operation, protected_commit)
    ]
    assert calls == []
    assert controls_path.read_bytes() == bootstrap_runner._canonical(old_controls) + b"\n"
    assert not (root / "github-controls-operation-before-runtime-upgrade-v1.json").exists()
    assert not (root / "runtime-upgrade-controls-refresh-v1.json").exists()
    assert state_path.read_bytes() == original_state

    verified_authorizations: list[
        tuple[Path, dict[str, object], str | None]
    ] = []
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_idempotent_resume_github_authorization",
        lambda checkout, operation, protected_main_commit_sha=None: (
            verified_authorizations.append(
                (checkout, operation, protected_main_commit_sha)
            )
        ),
    )
    unrelated_controls = {"protected_commit_sha": "9" * 40}
    controls_path.write_bytes(
        bootstrap_runner._canonical(unrelated_controls) + b"\n"
    )
    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_CONTROLS_INVALID",
    ):
        bootstrap_runner._refresh_interrupted_runtime_controls(root)
    assert calls == []

    controls_path.write_bytes(bootstrap_runner._canonical(old_controls) + b"\n")
    bootstrap_runner._refresh_interrupted_runtime_controls(root)
    bootstrap_runner._refresh_interrupted_runtime_controls(root)

    assert verified_authorizations == [
        (source, generic_operation, protected_commit),
        (source, final_generic_operation, protected_commit),
        (source, generic_operation, protected_commit),
        (source, final_generic_operation, protected_commit),
        (source, generic_operation, protected_commit),
        (source, final_generic_operation, protected_commit),
    ]
    assert calls == ["github_controls_runtime_upgrade_live_1"]
    assert state_path.read_bytes() == original_state
    assert (root / "runtime-upgrade-controls-refresh-v1.json").is_file()


@pytest.mark.parametrize(
    "operation_indexes,retry_indexes",
    [
        ([13], []),
        ([14], [14]),
        ([129], [129]),
    ],
)
def test_runtime_upgrade_control_refresh_rejects_partial_or_gapped_generic_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation_indexes: list[int],
    retry_indexes: list[int],
) -> None:
    root = tmp_path / "installed"
    (root / "receipts").mkdir(parents=True)
    (
        root / "receipts/controller-bootstrap-github-controls-retry-10-v1.json"
    ).write_text("{}\n", encoding="utf-8")
    for index in operation_indexes:
        (
            root
            / f"github-controls-idempotent-resume-upgrade-{index}-operation-v1.json"
        ).write_text("{}\n", encoding="utf-8")
    for index in retry_indexes:
        (
            root
            / f"receipts/controller-bootstrap-github-controls-retry-{index}-v1.json"
        ).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        bootstrap_runner,
        "load_bootstrap_state",
        lambda _path: SimpleNamespace(
            phase="QUALIFICATION_PENDING",
            sequence=43,
        ),
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_BOOTSTRAP_IDEMPOTENT_RESUME_UPGRADE_RETRY_INVALID",
    ):
        bootstrap_runner._refresh_interrupted_runtime_controls(root)


def test_post_repair_phases_all_use_the_runtime_commit() -> None:
    for handler in (
        bootstrap_runner.install_local_components,
        bootstrap_runner.apply_github_controls,
        bootstrap_runner.run_qualifications,
        bootstrap_runner.perform_final_audit,
    ):
        assert "_runtime_commit" in handler.__code__.co_names


def test_bootstrap_installer_closes_with_explicit_success() -> None:
    installer = (
        Path(__file__).resolve().parents[1]
        / "scripts/install_catalog_bootstrap_assistant.ps1"
    )

    assert installer.read_text("utf-8").rstrip().endswith(
        "$Receipt | ConvertTo-Json -Compress\nexit 0"
    )


def test_main_tries_local_recovery_after_merge_recovery_declines(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{}\n", encoding="utf-8")
    blocked = _blocked_local_install_state()
    ready = blocked.model_copy(update={"phase": "READY", "sequence": 11})
    observed_states = iter((blocked, blocked, ready))
    recoveries: list[str] = []

    monkeypatch.setattr(
        bootstrap_runner,
        "load_bootstrap_state",
        lambda _path: next(observed_states),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_qualification_block",
        lambda _root: False,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_merge_block",
        lambda _root: _append_then_return(recoveries, "merge", False),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_local_install_block",
        lambda _root: _append_then_return(recoveries, "local", True),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["catalog-bootstrap-assistant", "--installed-root", str(root)],
    )

    assert bootstrap_runner.main() == 0
    assert recoveries == ["merge", "local"]


def test_main_reports_the_actual_phase_when_local_recovery_fails(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{}\n", encoding="utf-8")
    (root / "receipts").mkdir(parents=True)
    blocked_receipt = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(blocked_receipt) + b"\n"
    )
    blocked = _blocked_local_install_state()

    monkeypatch.setattr(
        bootstrap_runner,
        "load_bootstrap_state",
        lambda _path: blocked,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_merge_block",
        lambda _root: False,
    )

    def fail_local_recovery(_root: Path) -> bool:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_FAILED")

    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_local_install_block",
        fail_local_recovery,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_set_repository_variable",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["catalog-bootstrap-assistant", "--installed-root", str(root)],
    )

    assert bootstrap_runner.main() == 2
    receipt = json.loads(
        (
            root
            / "receipts/controller-bootstrap-recovery-blocked-v1.json"
        ).read_text("utf-8")
    )
    assert receipt["phase"] == "LOCAL_INSTALL_PENDING"
    assert receipt["reason_code"] == "CATALOG_BOOTSTRAP_LOCAL_RETRY_FAILED"


def test_required_check_wait_tolerates_registration_race(monkeypatch) -> None:
    results = iter(
        (
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="no required checks reported on the branch",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=8,
                stdout=json.dumps(
                    [
                        {
                            "bucket": "pending",
                            "name": "GTBI V7 stage-two required",
                            "state": "IN_PROGRESS",
                        }
                    ]
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "bucket": "pass",
                            "name": "GTBI V7 stage-two required",
                            "state": "SUCCESS",
                        }
                    ]
                ),
                stderr="",
            ),
        )
    )
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object):
        calls.append(args)
        return next(results)

    monkeypatch.setattr(bootstrap_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(bootstrap_runner.time, "sleep", lambda _seconds: None)

    observed = bootstrap_runner._wait_for_required_checks(
        "163", Path("C:/source"), timeout_seconds=30, poll_seconds=0
    )

    assert observed == (
        {
            "bucket": "pass",
            "name": "GTBI V7 stage-two required",
            "state": "SUCCESS",
        },
    )
    assert len(calls) == 3


def test_required_check_failure_never_retries_or_merges(monkeypatch) -> None:
    result = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout=json.dumps(
            [
                {
                    "bucket": "fail",
                    "name": "GTBI V7 stage-two required",
                    "state": "FAILURE",
                }
            ]
        ),
        stderr="",
    )
    calls = 0

    def fake_run(_args: list[str], **_kwargs: object):
        nonlocal calls
        calls += 1
        return result

    monkeypatch.setattr(bootstrap_runner.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="BOOTSTRAP_PR_REQUIRED_CHECK_FAILED"):
        bootstrap_runner._wait_for_required_checks("163", Path("C:/source"))
    assert calls == 1


def test_required_check_cannot_be_substituted(monkeypatch) -> None:
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(
            [
                {
                    "bucket": "pass",
                    "name": "unrelated-check",
                    "state": "SUCCESS",
                }
            ]
        ),
        stderr="",
    )
    monkeypatch.setattr(bootstrap_runner.subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(ValueError, match="BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID"):
        bootstrap_runner._wait_for_required_checks("163", Path("C:/source"))


def test_qualification_checkpoint_write_is_exclusive_and_exact(
    tmp_path: Path,
) -> None:
    path = tmp_path / "qualification-substeps-v1.checkpoint.json"
    first = {"schema_version": "1", "value": "first"}
    second = {"schema_version": "1", "value": "second"}

    digest = bootstrap_runner._write_exact_canonical_checkpoint(path, first)

    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    original = path.read_bytes()
    with pytest.raises(ValueError, match="CHECKPOINT_CONFLICT"):
        bootstrap_runner._write_exact_canonical_checkpoint(path, second)
    assert path.read_bytes() == original

    linked = tmp_path / "linked-checkpoint.json"
    linked.write_bytes(original)
    path.unlink()
    try:
        path.hardlink_to(linked)
    except (OSError, NotImplementedError):
        pytest.skip("hard links are unavailable in this Windows test environment")
    with pytest.raises(ValueError, match="CHECKPOINT_PATH_INVALID"):
        bootstrap_runner._write_exact_canonical_checkpoint(path, first)


def test_first_checkpoint_write_recovers_crash_before_atomic_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "first-checkpoint.json"
    value = {"schema_version": "1", "value": "sealed"}
    original_publish = bootstrap_runner._publish_checkpoint_temp
    original_fsync = bootstrap_runner.os.fsync
    flushed = False

    def record_fsync(descriptor: int) -> None:
        nonlocal flushed
        original_fsync(descriptor)
        flushed = True

    def crash_before_publish(
        source: Path, destination: Path, *, replace_existing: bool
    ) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.parent == destination_path.parent == path.parent
        assert destination_path == path
        assert source_path != path
        assert source_path.read_bytes() == bootstrap_runner._canonical(value) + b"\n"
        assert replace_existing is False
        assert flushed is True
        assert not path.exists()
        raise SystemExit("FAULT_AFTER_TEMP_FSYNC")

    monkeypatch.setattr(bootstrap_runner.os, "fsync", record_fsync)
    monkeypatch.setattr(
        bootstrap_runner, "_publish_checkpoint_temp", crash_before_publish
    )

    with pytest.raises(SystemExit, match="FAULT_AFTER_TEMP_FSYNC"):
        bootstrap_runner._write_exact_canonical_checkpoint(path, value)

    temporary = list(tmp_path.glob(f".{path.name}.*.tmp"))
    assert len(temporary) == 1
    assert temporary[0].read_bytes() == bootstrap_runner._canonical(value) + b"\n"

    monkeypatch.setattr(
        bootstrap_runner, "_publish_checkpoint_temp", original_publish
    )
    monkeypatch.setattr(bootstrap_runner.os, "fsync", original_fsync)
    digest = bootstrap_runner._write_exact_canonical_checkpoint(path, value)

    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.read_bytes() == bootstrap_runner._canonical(value) + b"\n"
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_first_checkpoint_write_cleans_safe_temp_after_publish_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "failed-checkpoint.json"
    value = {"schema_version": "1", "value": "sealed"}

    def fail_publish(
        _source: Path, _destination: Path, *, replace_existing: bool
    ) -> None:
        assert replace_existing is False
        raise OSError("publication failed")

    monkeypatch.setattr(bootstrap_runner, "_publish_checkpoint_temp", fail_publish)

    with pytest.raises(ValueError, match="CHECKPOINT_WRITE_FAILED"):
        bootstrap_runner._write_exact_canonical_checkpoint(path, value)

    assert not path.exists()
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_checkpoint_lock_rejects_hardlink_before_any_write(tmp_path: Path) -> None:
    checkpoint = tmp_path / "locked-checkpoint.json"
    lock_path = checkpoint.with_name(f".{checkpoint.name}.lock")
    lock_source = tmp_path / "lock-source"
    lock_source.write_bytes(b"0")
    try:
        lock_path.hardlink_to(lock_source)
    except (OSError, NotImplementedError):
        pytest.skip("hard links are unavailable in this Windows test environment")

    with pytest.raises(ValueError, match="CHECKPOINT_LOCK_INVALID"):
        bootstrap_runner._write_exact_canonical_checkpoint(
            checkpoint, {"schema_version": "1"}
        )
    assert not checkpoint.exists()


def test_checkpoint_lock_excludes_another_process(tmp_path: Path) -> None:
    assert hasattr(bootstrap_runner, "_exclusive_checkpoint_lock"), (
        "checkpoint writes need a real cross-process lock"
    )
    checkpoint = tmp_path / "process-checkpoint.json"
    repository = Path(__file__).resolve().parents[1]
    child = (
        "from pathlib import Path\n"
        "import sys\n"
        "from scripts import run_catalog_bootstrap_assistant as runner\n"
        "try:\n"
        "    with runner._exclusive_checkpoint_lock("
        "Path(sys.argv[1]), timeout_seconds=0.2):\n"
        "        raise SystemExit(3)\n"
        "except ValueError as exc:\n"
        "    print(str(exc))\n"
        "    raise SystemExit(0 if str(exc) == "
        "'CATALOG_BOOTSTRAP_CHECKPOINT_LOCKED' else 4)\n"
    )

    with bootstrap_runner._exclusive_checkpoint_lock(checkpoint):
        result = subprocess.run(
            [sys.executable, "-c", child, str(checkpoint)],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CATALOG_BOOTSTRAP_CHECKPOINT_LOCKED"


def test_checkpoint_revision_cas_rejects_stale_process(tmp_path: Path) -> None:
    assert hasattr(bootstrap_runner, "_exclusive_checkpoint_lock"), (
        "checkpoint revisions need a real cross-process lock"
    )
    checkpoint = tmp_path / "revision-checkpoint.json"
    ready = tmp_path / "child-ready"
    previous = {"schema_version": "1", "revision": "previous"}
    candidate = {"schema_version": "1", "revision": "candidate"}
    competing = {"schema_version": "1", "revision": "competing"}
    checkpoint.write_bytes(bootstrap_runner._canonical(previous) + b"\n")
    repository = Path(__file__).resolve().parents[1]
    child = (
        "import json\n"
        "from pathlib import Path\n"
        "import sys\n"
        "from scripts import run_catalog_bootstrap_assistant as runner\n"
        "path = Path(sys.argv[1])\n"
        "Path(sys.argv[2]).write_text('ready', encoding='utf-8')\n"
        "try:\n"
        "    runner._write_qualification_checkpoint_revision("
        "path, json.loads(sys.argv[3]), json.loads(sys.argv[4]))\n"
        "except ValueError as exc:\n"
        "    print(str(exc))\n"
        "    raise SystemExit(0 if str(exc) == "
        "'CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_CONFLICT' else 4)\n"
        "raise SystemExit(3)\n"
    )

    with bootstrap_runner._exclusive_checkpoint_lock(checkpoint):
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                child,
                str(checkpoint),
                str(ready),
                json.dumps(candidate, separators=(",", ":"), sort_keys=True),
                json.dumps(previous, separators=(",", ":"), sort_keys=True),
            ],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        checkpoint.write_bytes(bootstrap_runner._canonical(competing) + b"\n")

    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, stderr
    assert stdout.strip() == "CATALOG_BOOTSTRAP_QUALIFICATION_CHECKPOINT_CONFLICT"
    assert checkpoint.read_bytes() == bootstrap_runner._canonical(competing) + b"\n"


def test_requester_qualification_uses_terminal_status_without_ticket(
    tmp_path: Path, monkeypatch
) -> None:
    broker_root = tmp_path / "broker"
    status_dir = broker_root / "campaign-status"
    status_dir.mkdir(parents=True)
    request_id = "018f47a2-6e91-7c34-8000-000000000001"
    request_payload = {
        "schema_version": "1",
        "request_id": request_id,
        "campaign_key": "controller-bootstrap-qualification-v1",
        "launch_generation": 1,
        "launch_ticket_sha256": "3" * 64,
        "previous_terminal_request_sha256": None,
        "campaign_definition_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        "free_resources_only": True,
        "automatic_recovery": True,
        "max_same_failure_count": 3,
        "requester_public_key_sha256": "c" * 64,
        "requester_attestation_algorithm": "rsa-pss-sha256-v1",
        "requester_attestation_b64": "A" * 300,
    }
    request_sha256 = hashlib.sha256(
        bootstrap_runner._canonical(request_payload)
    ).hexdigest()
    status = {
        "schema_version": "1",
        "campaign_key": "controller-bootstrap-qualification-v1",
        "state": "terminal",
        "launch_generation": 1,
        "launch_ticket_sha256": "3" * 64,
        "submission_key_sha256": "1" * 64,
        "request_id": request_id,
        "request_sha256": request_sha256,
        "issue_number": 123,
        "last_github_checked_at": "2026-08-25T10:00:00Z",
        "updated_at": "2026-08-25T10:00:00Z",
        "status_sha256": "0" * 64,
    }
    status["status_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(status)
    ).hexdigest()
    (status_dir / "controller-bootstrap-qualification-v1.status.json").write_bytes(
        bootstrap_runner._canonical(status) + b"\n"
    )
    root = tmp_path / "installed"
    root.mkdir()
    (root / "requester-public-v1.json").write_bytes(
        bootstrap_runner._canonical(
            {"app_slug": "aurora-catalog-request-f10c7b40e1"}
        )
        + b"\n"
    )
    first = {
        "schema_version": "1",
        "status": "existing",
        "reason_code": "REQUEST_ALREADY_EXISTS",
        "submission_key_sha256": "1" * 64,
        "request_id": request_id,
        "campaign_key": "controller-bootstrap-qualification-v1",
        "launch_generation": 1,
        "issue_number": 123,
        "request_sha256": request_sha256,
        "observed_at": "2026-08-25T10:01:00Z",
        "receipt_sha256": "0" * 64,
    }
    first["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(first)
    ).hexdigest()
    issue = {
        "number": 123,
        "state": "closed",
        "state_reason": "completed",
        "html_url": f"https://github.com/{bootstrap_runner.REPOSITORY}/issues/123",
        "title": f"[AURORA CATALOG RUN REQUEST] {request_id}",
        "body": "```json\n"
        + bootstrap_runner._canonical(request_payload).decode()
        + "\n```\n",
        "user": {"login": "aurora-catalog-request-f10c7b40e1[bot]"},
        "closed_by": {"login": "github-actions[bot]"},
    }
    controller = {
        "schema_version": "1",
        "issue_number": 123,
        "state": "BLOCKED",
        "reason_code": "CATALOG_CONTROLLER_DISABLED",
        "writer_job_id": "report_nonexecuting_decision",
        "request_sha256": request_sha256,
        "receipt_sha256": "0" * 64,
    }
    controller["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(
            {key: value for key, value in controller.items() if key != "receipt_sha256"}
        )
    ).hexdigest()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(bootstrap_runner, "BROKER_ROOT", broker_root)
    monkeypatch.setattr(
        bootstrap_runner,
        "_context",
        lambda _root: {
            "repository": bootstrap_runner.REPOSITORY,
            "source_commit_sha": COMMIT,
            "source_root": str(tmp_path / "source"),
        },
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_invoke_bootstrap_request",
        lambda _source: _append_then_return(calls, first, first),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_parse_terminal_controller_receipt",
        lambda _issue: controller,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
            lambda args, **_kwargs: json.dumps(issue)
            if args[:2] == ["gh", "api"]
            and args[2] == f"/repos/{bootstrap_runner.REPOSITORY}/issues/123"
            else pytest.fail(f"unexpected command: {args}"),
    )
    clock = iter((0.0, 301.0))
    monkeypatch.setattr(bootstrap_runner.time, "monotonic", lambda: next(clock))

    result = bootstrap_runner._run_requester_qualification(
        root, tmp_path / "source"
    )

    assert result["issue_number"] == 123
    assert len(calls) == 2
    assert not (broker_root / "launch-tickets").exists()


def _qualification_pending_root(tmp_path: Path) -> Path:
    root = tmp_path / "qualification-root"
    root.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    names: tuple[EventName, ...] = (
        "precheck_passed",
        "requester_created",
        "requester_installed",
        "auditor_created",
        "auditor_installed",
        "public_binding_committed",
        "protected_merge_observed",
        "local_install_verified",
        "github_controls_verified",
    )
    for sequence, name in enumerate(names, 1):
        state = advance_bootstrap_state(state, event(name, sequence))
    persist_bootstrap_state(root / "state/catalog-bootstrap-state-v1.json", state)
    controls = {
        "protected_commit_sha": COMMIT,
        "apply_receipt_sha256": "1" * 64,
        "auditor_secret_name": "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
        "first_live_qualification": _fake_live_receipt(100),
    }
    baseline: dict[str, list[int]] = {
        "request_issue_numbers": [],
        "heavy_run_ids": [],
    }
    (root / "github-controls-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(controls) + b"\n"
    )
    (root / "github-activity-baseline-v1.json").write_bytes(
        bootstrap_runner._canonical(baseline) + b"\n"
    )
    return root


def _fake_live_receipt(run_id: int) -> dict[str, object]:
    identity = {
        "schema_version": "1",
        "observer_context": "live_qualification",
        "protected_commit_sha": COMMIT,
        "admission_receipt_sha256": f"{run_id:064x}",
        "terminal_receipt_sha256": f"{run_id + 1:064x}",
    }
    receipt = {
        **identity,
        "receipt_sha256": hashlib.sha256(
            bootstrap_runner._canonical(identity)
        ).hexdigest(),
    }
    return {
        "run_id": run_id,
        "run_url": f"https://example.test/runs/{run_id}",
        "file_sha256": hashlib.sha256(
            bootstrap_runner._canonical(receipt) + b"\n"
        ).hexdigest(),
        "receipt": receipt,
    }


_QUALIFICATION_WORKFLOW_DISPLAY_NAMES = {
    "catalog-live-controls-qualification.yml": "Catalog live controls qualification",
    "catalog-controller-policy-check.yml": "Catalog controller policy",
    "catalog-controller-qualification.yml": (
        "AURORA catalog controller synthetic qualification"
    ),
    "catalog-capacity-calibration.yml": "Catalog capacity calibration",
    "catalog-artifact-keeper.yml": "Catalog artifact keeper",
}


def _fake_qualification_api_run(
    run_id: int,
    step_name: str,
    *,
    protected_commit_sha: str = COMMIT,
) -> dict[str, object]:
    workflow = bootstrap_runner._QUALIFICATION_STEP_WORKFLOWS[step_name]
    return {
        "id": run_id,
        "head_sha": protected_commit_sha,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-08-25T10:00:01Z",
        "html_url": f"https://example.test/runs/{run_id}",
        "path": f".github/workflows/{workflow}",
    }


def _fake_qualification_view(run: dict[str, object], workflow: str) -> str:
    return json.dumps({**run, "path": f".github/workflows/{workflow}"})


@pytest.mark.parametrize(
    "step_name",
    tuple(bootstrap_runner._QUALIFICATION_STEP_WORKFLOWS),
)
def test_dispatch_intent_recovers_accepted_run_without_redispatch(
    step_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hasattr(bootstrap_runner, "_run_qualification_workflow_step"), (
        "qualification dispatch needs persistent intent reconciliation"
    )
    root = tmp_path / "installed"
    root.mkdir()
    workflow = bootstrap_runner._QUALIFICATION_STEP_WORKFLOWS[step_name]
    run = _fake_qualification_api_run(7001, step_name)
    runs: list[dict[str, object]] = []
    dispatch_calls = 0

    def fake_run(args: list[str], **_kwargs: object) -> str:
        nonlocal dispatch_calls
        if args[:4] == ["gh", "api", "--paginate", "--slurp"]:
            return json.dumps([{"workflow_runs": list(runs)}])
        if args[:3] == ["gh", "workflow", "run"]:
            dispatch_calls += 1
            runs.append(run)
            raise RuntimeError("FAULT_AFTER_WORKFLOW_DISPATCH_ACCEPTED")
        if args[:2] == ["gh", "api"] and args[2].endswith(
            f"/actions/runs/{run['id']}"
        ):
            return _fake_qualification_view(run, workflow)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(
        bootstrap_runner.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )

    with pytest.raises(RuntimeError, match="DISPATCH_ACCEPTED"):
        bootstrap_runner._run_qualification_workflow_step(root, step_name, COMMIT)

    intent_path = bootstrap_runner._qualification_dispatch_intent_path(
        root, step_name
    )
    intent_bytes = intent_path.read_bytes()
    intent = json.loads(intent_bytes)
    assert intent_bytes == bootstrap_runner._canonical(intent) + b"\n"
    unsigned = {**intent, "correlation_key_sha256": "0" * 64}
    assert intent["correlation_key_sha256"] == hashlib.sha256(
        bootstrap_runner._canonical(unsigned)
    ).hexdigest()

    observed = bootstrap_runner._run_qualification_workflow_step(
        root, step_name, COMMIT
    )

    assert observed["databaseId"] == run["id"]
    assert dispatch_calls == 1
    assert intent_path.read_bytes() == intent_bytes


def test_runtime_upgrade_dispatch_uses_commit_scoped_intent_after_prior_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "installed"
    root.mkdir()
    step_name = "github_controls_runtime_upgrade_live_1"
    workflow = "catalog-live-controls-qualification.yml"
    prior_commit = "e238a50ee4fd25a5c2c97f6edac21201bf71a3c0"
    legacy_intent = {
        "baseline_run_ids": [101],
        "campaign_key": "controller-bootstrap-qualification-v1",
        "correlation_key_sha256": (
            "fe5877741f6df6fcb8a8f7c1e29c598f17f5ca11f8829450187623961ab31ab0"
        ),
        "protected_commit_sha": prior_commit,
        "schema_version": "1",
        "step_name": step_name,
        "workflow": workflow,
    }
    legacy_path = root / f"qualification-dispatch-{step_name}-v1.intent.json"
    legacy_bytes = bootstrap_runner._canonical(legacy_intent) + b"\n"
    legacy_path.write_bytes(legacy_bytes)
    dispatches: list[tuple[str, str, set[int] | None]] = []
    expected_run = {
        "databaseId": 202,
        "headSha": COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "url": "https://example.test/runs/202",
    }

    monkeypatch.setattr(
        bootstrap_runner,
        "_list_workflow_runs",
        lambda _workflow: [{"databaseId": 101}],
    )

    def fake_dispatch(
        observed_workflow: str,
        observed_commit: str,
        *,
        baseline_run_ids: set[int] | None = None,
    ) -> dict[str, object]:
        dispatches.append((observed_workflow, observed_commit, baseline_run_ids))
        return dict(expected_run)

    monkeypatch.setattr(bootstrap_runner, "_dispatch_workflow", fake_dispatch)

    observed = bootstrap_runner._run_qualification_workflow_step(
        root, step_name, COMMIT
    )

    current_path = (
        root / f"qualification-dispatch-{step_name}-{COMMIT}-v1.intent.json"
    )
    current_intent = json.loads(current_path.read_bytes())
    assert observed == expected_run
    assert legacy_path.read_bytes() == legacy_bytes
    assert current_intent["protected_commit_sha"] == COMMIT
    assert current_intent["baseline_run_ids"] == [101]
    assert dispatches == [(workflow, COMMIT, {101})]

    monkeypatch.setattr(
        bootstrap_runner,
        "_reconcile_qualification_dispatch_intent",
        lambda _intent: dict(expected_run),
    )
    observed_again = bootstrap_runner._run_qualification_workflow_step(
        root, step_name, COMMIT
    )

    assert observed_again == expected_run
    assert dispatches == [(workflow, COMMIT, {101})]


def test_runtime_upgrade_dispatch_reconciles_same_commit_legacy_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "installed"
    root.mkdir()
    step_name = "github_controls_runtime_upgrade_live_1"
    workflow = "catalog-live-controls-qualification.yml"
    legacy_intent = {
        "baseline_run_ids": [101],
        "campaign_key": "controller-bootstrap-qualification-v1",
        "correlation_key_sha256": (
            "ad774a80561db6f20b1c4764b04a759f392f3cd1d85a07b2389df4faf32f860a"
        ),
        "protected_commit_sha": COMMIT,
        "schema_version": "1",
        "step_name": step_name,
        "workflow": workflow,
    }
    legacy_path = root / f"qualification-dispatch-{step_name}-v1.intent.json"
    legacy_bytes = bootstrap_runner._canonical(legacy_intent) + b"\n"
    legacy_path.write_bytes(legacy_bytes)
    expected_run = {
        "databaseId": 202,
        "headSha": COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "url": "https://example.test/runs/202",
    }

    monkeypatch.setattr(
        bootstrap_runner,
        "_reconcile_qualification_dispatch_intent",
        lambda intent: dict(expected_run)
        if intent == legacy_intent
        else pytest.fail("unexpected intent"),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_list_workflow_runs",
        lambda _workflow: pytest.fail("same-commit legacy intent was ignored"),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_dispatch_workflow",
        lambda *_args, **_kwargs: pytest.fail("same-commit legacy intent redispatched"),
    )

    observed = bootstrap_runner._run_qualification_workflow_step(
        root, step_name, COMMIT
    )

    assert observed == expected_run
    assert legacy_path.read_bytes() == legacy_bytes
    assert not (
        root / f"qualification-dispatch-{step_name}-{COMMIT}-v1.intent.json"
    ).exists()


@pytest.mark.parametrize(
    ("scenario", "expected"),
    (
        ("zero", "QUALIFICATION_RUN_NOT_FOUND"),
        ("multiple", "QUALIFICATION_RUN_AMBIGUOUS"),
        ("wrong_identity", "QUALIFICATION_RUN_IDENTITY_AMBIGUOUS"),
    ),
)
def test_dispatch_intent_fails_closed_when_reconciliation_is_not_unique(
    scenario: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hasattr(bootstrap_runner, "_run_qualification_workflow_step"), (
        "qualification dispatch needs persistent intent reconciliation"
    )
    root = tmp_path / "installed"
    root.mkdir()
    step_name = "policy_1"
    exact = _fake_qualification_api_run(7101, step_name)
    wrong = _fake_qualification_api_run(
        7102, step_name, protected_commit_sha="b" * 40
    )
    runs: list[dict[str, object]] = []
    dispatch_calls = 0

    def fake_run(args: list[str], **_kwargs: object) -> str:
        nonlocal dispatch_calls
        if args[:4] == ["gh", "api", "--paginate", "--slurp"]:
            return json.dumps([{"workflow_runs": list(runs)}])
        if args[:3] == ["gh", "workflow", "run"]:
            dispatch_calls += 1
            if scenario == "multiple":
                runs.extend((exact, {**exact, "id": 7103}))
            elif scenario == "wrong_identity":
                runs.append(wrong)
            raise RuntimeError("FAULT_AFTER_WORKFLOW_DISPATCH_ACCEPTED")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    with pytest.raises(RuntimeError, match="DISPATCH_ACCEPTED"):
        bootstrap_runner._run_qualification_workflow_step(root, step_name, COMMIT)

    if scenario == "zero":
        clock = iter((0.0, 0.0, 301.0))
        monkeypatch.setattr(bootstrap_runner.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(bootstrap_runner.time, "sleep", lambda _seconds: None)

    with pytest.raises(ValueError, match=expected):
        bootstrap_runner._run_qualification_workflow_step(root, step_name, COMMIT)
    assert dispatch_calls == 1


def test_qualification_reentry_does_not_redispatch_a_checkpointed_step(
    tmp_path: Path, monkeypatch
) -> None:
    root = _qualification_pending_root(tmp_path)
    source = tmp_path / "source"
    dispatched: list[str] = []
    requester_calls = 0
    live_calls = 0

    def fake_live(
        _root: Path, _commit: str, *, step_name: str | None = None
    ) -> dict[str, object]:
        nonlocal live_calls
        assert step_name in {"live_2", "live_3"}
        live_calls += 1
        return _fake_live_receipt(100 + live_calls)

    def fake_dispatch(
        workflow: str,
        _commit: str,
        *,
        baseline_run_ids: set[int] | None = None,
    ) -> dict[str, object]:
        assert baseline_run_ids == set()
        dispatched.append(workflow)
        run_id = 200 + len(dispatched)
        return {
            "databaseId": run_id,
            "headSha": COMMIT,
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "url": f"https://example.test/runs/{run_id}",
        }

    def fake_requester(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal requester_calls
        requester_calls += 1
        return {
            "issue_number": 777,
            "submission_key_sha256": "1" * 64,
            "request_sha256": "2" * 64,
            "request_id": "018f47a2-6e91-7c34-8000-000000000001",
            "launch_ticket_sha256": "3" * 64,
            "status_sha256": "4" * 64,
            "requester_receipt_sha256": "5" * 64,
            "requester_receipt_file_sha256": "6" * 64,
            "issue_identity_sha256": "7" * 64,
            "issue_sha256": "8" * 64,
            "controller_receipt_sha256": "9" * 64,
            "bootstrap_seal_sha256": "a" * 64,
            "duplicate_call_proof_sha256": "3" * 64,
        }

    monkeypatch.setattr(bootstrap_runner, "_runtime_commit", lambda _root: COMMIT)
    monkeypatch.setattr(
        bootstrap_runner,
        "_context",
        lambda _root: {
            "repository": bootstrap_runner.REPOSITORY,
            "source_commit_sha": COMMIT,
            "source_root": str(source),
        },
    )
    monkeypatch.setattr(bootstrap_runner, "_run_live_qualification", fake_live)
    monkeypatch.setattr(bootstrap_runner, "_dispatch_workflow", fake_dispatch)
    monkeypatch.setattr(bootstrap_runner, "_list_workflow_runs", lambda _workflow: [])
    monkeypatch.setattr(bootstrap_runner, "_run_requester_qualification", fake_requester)
    monkeypatch.setattr(
        bootstrap_runner,
        "_github_activity_snapshot",
        lambda: {"request_issue_numbers": [777], "heavy_run_ids": []},
    )
    monkeypatch.setattr(bootstrap_runner, "_advance", lambda *_args: None)
    monkeypatch.setattr(
        bootstrap_runner,
        "_revalidate_qualification_step",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    original_writer = bootstrap_runner._write_exact_canonical_checkpoint
    faulted = False

    def fail_after_live_2(path: Path, value: object) -> str:
        nonlocal faulted
        digest = original_writer(path, value)
        if (
            not faulted
            and path.name == bootstrap_runner.QUALIFICATION_CHECKPOINT_FILENAME
            and isinstance(value, dict)
            and value.get("steps", [{}])[-1].get("name") == "live_2"
        ):
            faulted = True
            raise RuntimeError("FAULT_AFTER_CHECKPOINT_WRITE")
        return digest

    monkeypatch.setattr(
        bootstrap_runner, "_write_exact_canonical_checkpoint", fail_after_live_2
    )
    with pytest.raises(RuntimeError, match="FAULT_AFTER_CHECKPOINT_WRITE"):
        bootstrap_runner.run_qualifications(root)

    monkeypatch.setattr(
        bootstrap_runner,
        "_write_exact_canonical_checkpoint",
        original_writer,
    )
    bootstrap_runner.run_qualifications(root)

    assert live_calls == 2
    assert requester_calls == 1
    assert dispatched.count("catalog-controller-policy-check.yml") == 3
    assert dispatched.count("catalog-controller-qualification.yml") == 3
    assert dispatched.count("catalog-capacity-calibration.yml") == 1
    assert dispatched.count("catalog-artifact-keeper.yml") == 1


def test_corrupt_qualification_checkpoint_blocks_before_any_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    root = _qualification_pending_root(tmp_path)
    checkpoint_path = root / bootstrap_runner.QUALIFICATION_CHECKPOINT_FILENAME
    checkpoint_path.write_bytes(b'{"schema_version":"1"')
    original = checkpoint_path.read_bytes()
    monkeypatch.setattr(bootstrap_runner, "_runtime_commit", lambda _root: COMMIT)
    monkeypatch.setattr(
        bootstrap_runner,
        "_context",
        lambda _root: {
            "repository": bootstrap_runner.REPOSITORY,
            "source_commit_sha": COMMIT,
            "source_root": str(tmp_path / "source"),
        },
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_run_live_qualification",
        lambda *_args: pytest.fail("dispatch must not follow a corrupt checkpoint"),
    )

    with pytest.raises(ValueError, match="QUALIFICATION_CHECKPOINT_INVALID"):
        bootstrap_runner.run_qualifications(root)
    assert checkpoint_path.read_bytes() == original


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("commit", "QUALIFICATION_RUN_INVALID"),
        ("conclusion", "QUALIFICATION_RUN_INVALID"),
    ),
)
def test_stored_workflow_receipt_must_bind_exact_commit_and_success(
    mutation: str, expected: str, tmp_path: Path
) -> None:
    receipt = {
        "databaseId": 901,
        "headSha": "b" * 40 if mutation == "commit" else COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "failure" if mutation == "conclusion" else "success",
        "url": "https://example.test/runs/901",
    }
    entry: dict[str, object] = {
        "name": "policy_1",
        "receipt": receipt,
        "receipt_sha256": hashlib.sha256(
            bootstrap_runner._canonical(receipt)
        ).hexdigest(),
    }
    with pytest.raises(ValueError, match=expected):
        bootstrap_runner._revalidate_qualification_step(
            tmp_path,
            entry,
            protected_commit_sha=COMMIT,
        )


def test_stored_workflow_receipt_rejects_wrong_workflow_path(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = {
        "databaseId": 902,
        "headSha": COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "url": "https://example.test/runs/902",
    }
    monkeypatch.setattr(
        bootstrap_runner,
        "_list_workflow_runs",
        lambda _workflow: pytest.fail("revalidation must not list the latest 50 runs"),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda *_args, **_kwargs: json.dumps(
            {
                "id": receipt["databaseId"],
                "head_sha": receipt["headSha"],
                "event": receipt["event"],
                "status": receipt["status"],
                "conclusion": receipt["conclusion"],
                "html_url": receipt["url"],
                "path": ".github/workflows/other.yml",
            }
        ),
    )
    with pytest.raises(ValueError, match="QUALIFICATION_RUN_INVALID"):
        bootstrap_runner._revalidate_qualification_step(
            tmp_path,
            {
                "name": "policy_1",
                "receipt": receipt,
                "receipt_sha256": hashlib.sha256(
                    bootstrap_runner._canonical(receipt)
                ).hexdigest(),
            },
            protected_commit_sha=COMMIT,
        )


def test_stored_workflow_run_is_revalidated_directly_by_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = {
        "databaseId": 904,
        "headSha": COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "url": "https://example.test/runs/904",
    }
    commands: list[list[str]] = []
    monkeypatch.setattr(
        bootstrap_runner,
        "_list_workflow_runs",
        lambda _workflow: pytest.fail("revalidation must not list the latest 50 runs"),
    )

    def fake_run(args: list[str], **_kwargs: object) -> str:
        commands.append(args)
        return json.dumps(
            {
                "id": receipt["databaseId"],
                "head_sha": receipt["headSha"],
                "event": receipt["event"],
                "status": receipt["status"],
                "conclusion": receipt["conclusion"],
                "html_url": receipt["url"],
                "path": ".github/workflows/catalog-controller-policy-check.yml",
            }
        )

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)

    observed = bootstrap_runner._read_stored_workflow_run(
        "catalog-controller-policy-check.yml",
        receipt,
        protected_commit_sha=COMMIT,
    )

    assert observed == receipt
    assert len(commands) == 1
    assert commands == [
        [
            "gh",
            "api",
            f"/repos/{bootstrap_runner.REPOSITORY}/actions/runs/904",
        ]
    ]


def test_stored_live_receipt_rejects_changed_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    receipt = _fake_live_receipt(903)
    entry: dict[str, object] = {
        "name": "live_2",
        "receipt": receipt,
        "receipt_sha256": hashlib.sha256(
            bootstrap_runner._canonical(receipt)
        ).hexdigest(),
    }
    run = {
        "databaseId": 903,
        "headSha": COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "url": receipt["run_url"],
    }
    monkeypatch.setattr(
        bootstrap_runner,
        "_read_stored_workflow_run",
        lambda *_args, **_kwargs: run,
    )
    changed = {**receipt, "file_sha256": "e" * 64}
    monkeypatch.setattr(
        bootstrap_runner,
        "_download_live_qualification",
        lambda *_args, **_kwargs: changed,
    )
    with pytest.raises(ValueError, match="LIVE_RECEIPT_CHANGED"):
        bootstrap_runner._revalidate_qualification_step(
            tmp_path,
            entry,
            protected_commit_sha=COMMIT,
        )


def _requester_recovery_fixture(tmp_path: Path) -> _RequesterRecoveryFixture:
    broker_root = tmp_path / "requester-broker"
    (broker_root / "campaign-status").mkdir(parents=True)
    (broker_root / "receipts").mkdir(parents=True)
    root = tmp_path / "requester-installed"
    root.mkdir()
    request_id = "018f47a2-6e91-7c34-8000-000000000001"
    request_payload = {
        "schema_version": "1",
        "request_id": request_id,
        "campaign_key": "controller-bootstrap-qualification-v1",
        "launch_generation": 1,
        "launch_ticket_sha256": "3" * 64,
        "previous_terminal_request_sha256": None,
        "campaign_definition_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        "free_resources_only": True,
        "automatic_recovery": True,
        "max_same_failure_count": 3,
        "requester_public_key_sha256": "c" * 64,
        "requester_attestation_algorithm": "rsa-pss-sha256-v1",
        "requester_attestation_b64": "A" * 300,
    }
    request_sha256 = hashlib.sha256(
        bootstrap_runner._canonical(request_payload)
    ).hexdigest()
    status = {
        "schema_version": "1",
        "campaign_key": "controller-bootstrap-qualification-v1",
        "state": "terminal",
        "launch_generation": 1,
        "launch_ticket_sha256": "3" * 64,
        "submission_key_sha256": "1" * 64,
        "request_id": request_id,
        "request_sha256": request_sha256,
        "issue_number": 123,
        "last_github_checked_at": "2026-08-25T10:00:00Z",
        "updated_at": "2026-08-25T10:00:00Z",
        "status_sha256": "0" * 64,
    }
    status["status_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(status)
    ).hexdigest()
    (broker_root / "campaign-status/controller-bootstrap-qualification-v1.status.json").write_bytes(
        bootstrap_runner._canonical(status) + b"\n"
    )
    (root / "requester-public-v1.json").write_bytes(
        bootstrap_runner._canonical(
            {
                "app_slug": "aurora-catalog-request-f10c7b40e1",
                "public_key_sha256": "c" * 64,
            }
        )
        + b"\n"
    )
    first = {
        "schema_version": "1",
        "status": "existing",
        "reason_code": "REQUEST_ALREADY_EXISTS",
        "submission_key_sha256": "1" * 64,
        "request_id": request_id,
        "campaign_key": "controller-bootstrap-qualification-v1",
        "launch_generation": 1,
        "issue_number": 123,
        "request_sha256": request_sha256,
        "observed_at": "2026-08-25T10:01:00Z",
        "receipt_sha256": "0" * 64,
    }
    first["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(first)
    ).hexdigest()
    (broker_root / "receipts" / ("1" * 64 + ".receipt.json")).write_bytes(
        bootstrap_runner._canonical(first) + b"\n"
    )
    issue = {
        "number": 123,
        "state": "closed",
        "state_reason": "completed",
        "html_url": f"https://github.com/{bootstrap_runner.REPOSITORY}/issues/123",
        "title": f"[AURORA CATALOG RUN REQUEST] {request_id}",
        "body": "```json\n"
        + bootstrap_runner._canonical(request_payload).decode()
        + "\n```\n",
        "user": {"login": "aurora-catalog-request-f10c7b40e1[bot]"},
        "closed_by": {"login": "github-actions[bot]"},
    }
    controller = {
        "schema_version": "1",
        "issue_number": 123,
        "state": "BLOCKED",
        "reason_code": "CATALOG_CONTROLLER_DISABLED",
        "writer_job_id": "report_nonexecuting_decision",
        "request_sha256": request_sha256,
        "receipt_sha256": "0" * 64,
    }
    controller["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(
            {key: value for key, value in controller.items() if key != "receipt_sha256"}
        )
    ).hexdigest()
    return {
        "root": root,
        "broker_root": broker_root,
        "source": tmp_path / "source",
        "first": first,
        "status": status,
        "issue": issue,
        "controller": controller,
    }


def _patch_requester_recovery_fakes(
    fixture: _RequesterRecoveryFixture, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, object]]:
    root = fixture["root"]
    broker_root = fixture["broker_root"]
    source = fixture["source"]
    first = fixture["first"]
    issue = fixture["issue"]
    controller = fixture["controller"]
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(bootstrap_runner, "BROKER_ROOT", broker_root)
    monkeypatch.setattr(
        bootstrap_runner,
        "_context",
        lambda _root: {
            "repository": bootstrap_runner.REPOSITORY,
            "source_commit_sha": COMMIT,
            "source_root": str(source),
        },
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_invoke_bootstrap_request",
        lambda _source: _append_then_return(calls, dict(first), dict(first)),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_parse_terminal_controller_receipt",
        lambda _issue: dict(controller),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda args, **_kwargs: json.dumps(issue)
        if args[:2] == ["gh", "api"]
        and args[2] == f"/repos/{bootstrap_runner.REPOSITORY}/issues/123"
        else pytest.fail(f"unexpected command: {args}"),
    )
    return calls


def _reseal_complete_checkpoint(value: dict[str, object]) -> dict[str, object]:
    terminal = {
        key: item
        for key, item in value.items()
        if key != "complete_checkpoint_sha256"
    }
    terminal["terminal_checkpoint_sha256"] = "0" * 64
    terminal["terminal_checkpoint_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(terminal)
    ).hexdigest()
    complete = {**terminal, "complete_checkpoint_sha256": "0" * 64}
    complete["complete_checkpoint_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(complete)
    ).hexdigest()
    return complete


def test_requester_checkpoints_bind_all_cross_identity_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]

    bootstrap_runner._run_requester_qualification(root, fixture["source"])

    for filename in (
        bootstrap_runner.REQUESTER_TERMINAL_CHECKPOINT_FILENAME,
        bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME,
    ):
        checkpoint = json.loads((root / filename).read_bytes())
        status = checkpoint["status"]
        receipt = checkpoint["requester_receipt"]
        for field in (
            "request_id",
            "request_sha256",
            "submission_key_sha256",
            "issue_number",
        ):
            assert checkpoint[field] == status[field] == receipt[field]


@pytest.mark.parametrize(
    ("field", "different"),
    (
        ("request_id", "018f47a2-6e91-7c34-8000-000000000002"),
        ("request_sha256", "d" * 64),
        ("submission_key_sha256", "e" * 64),
        ("issue_number", 999),
    ),
)
def test_requester_complete_rejects_cross_identity_mismatch_without_local_receipt(
    field: str,
    different: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    calls = _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    bootstrap_runner._run_requester_qualification(root, fixture["source"])
    complete_path = root / bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME
    complete = json.loads(complete_path.read_bytes())
    receipt = dict(complete["requester_receipt"])
    receipt[field] = different
    receipt["receipt_sha256"] = "0" * 64
    receipt["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(receipt)
    ).hexdigest()
    receipt_file_sha256 = hashlib.sha256(
        bootstrap_runner._canonical(receipt) + b"\n"
    ).hexdigest()
    complete["requester_receipt"] = receipt
    complete["requester_receipt_sha256"] = receipt["receipt_sha256"]
    complete["requester_receipt_file_sha256"] = receipt_file_sha256
    qualification = dict(complete["requester_qualification"])
    qualification["requester_receipt_sha256"] = receipt["receipt_sha256"]
    qualification["requester_receipt_file_sha256"] = receipt_file_sha256
    complete["requester_qualification"] = qualification
    complete = _reseal_complete_checkpoint(complete)
    complete_path.write_bytes(bootstrap_runner._canonical(complete) + b"\n")
    local_receipt = (
        fixture["broker_root"]
        / "receipts"
        / (str(fixture["status"]["submission_key_sha256"]) + ".receipt.json")
    )
    local_receipt.unlink()
    calls.clear()

    with pytest.raises(ValueError, match="REQUESTER_EVIDENCE_IDENTITY_MISMATCH"):
        bootstrap_runner._run_requester_qualification(root, fixture["source"], COMMIT)
    assert calls == []


def test_requester_checkpoint_protected_commit_must_match_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    bootstrap_runner._run_requester_qualification(root, fixture["source"], COMMIT)
    complete_path = root / bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME
    complete = json.loads(complete_path.read_bytes())
    complete["protected_commit_sha"] = "b" * 40
    complete = _reseal_complete_checkpoint(complete)
    complete_path.write_bytes(bootstrap_runner._canonical(complete) + b"\n")

    with pytest.raises(ValueError, match="REQUESTER_PROTECTED_COMMIT_MISMATCH"):
        bootstrap_runner._run_requester_qualification(root, fixture["source"], COMMIT)


def test_requester_complete_recovers_missing_local_receipt_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    calls = _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    source = fixture["source"]
    first_result = bootstrap_runner._run_requester_qualification(root, source, COMMIT)
    receipt_path = (
        fixture["broker_root"] / "receipts" / ("1" * 64 + ".receipt.json")
    )
    receipt_bytes = receipt_path.read_bytes()
    receipt_path.unlink()
    calls.clear()

    def recover(_source: Path) -> dict[str, object]:
        calls.append(dict(fixture["first"]))
        receipt_path.write_bytes(receipt_bytes)
        return dict(fixture["first"])

    monkeypatch.setattr(bootstrap_runner, "_invoke_bootstrap_request", recover)

    recovered = bootstrap_runner._run_requester_qualification(root, source, COMMIT)

    assert recovered == first_result
    assert calls == [fixture["first"]]
    assert receipt_path.read_bytes() == receipt_bytes


def test_requester_complete_restores_receipt_from_authoritative_client_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    calls = _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    source = fixture["source"]
    first_result = bootstrap_runner._run_requester_qualification(root, source, COMMIT)
    receipt_path = (
        fixture["broker_root"] / "receipts" / ("1" * 64 + ".receipt.json")
    )
    receipt_path.unlink()
    calls.clear()

    recovered = bootstrap_runner._run_requester_qualification(root, source, COMMIT)
    assert recovered == first_result
    assert calls == [fixture["first"]]
    assert json.loads(receipt_path.read_bytes()) == fixture["first"]


def test_requester_complete_checkpoint_revalidates_without_new_client_call(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    calls = _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    source = fixture["source"]

    first_result = bootstrap_runner._run_requester_qualification(root, source)
    complete_bytes = (
        root / bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME
    ).read_bytes()
    calls.clear()
    second_result = bootstrap_runner._run_requester_qualification(root, source)

    assert second_result == first_result
    assert calls == []
    assert (
        root / bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME
    ).read_bytes() == complete_bytes


@pytest.mark.parametrize(
    "step_name",
    (
        "github_controls_live_1",
        "github_controls_runtime_upgrade_live_1",
        "final_pre_enable_live",
        "final_post_enable_live",
    ),
)
def test_all_one_shot_live_qualifications_use_persistent_dispatch_intents(
    step_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = {
        "databaseId": 999,
        "headSha": COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "url": "https://example.test/runs/999",
    }
    calls: list[str] = []
    monkeypatch.setattr(
        bootstrap_runner,
        "_run_qualification_workflow_step",
        lambda _root, observed_step, _commit: _append_then_return(
            calls, observed_step, run
        ),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_download_live_qualification",
        lambda *_args: {"run_id": 999},
    )

    observed = bootstrap_runner._run_live_qualification(
        tmp_path, COMMIT, step_name=step_name
    )

    assert observed == {"run_id": 999}
    assert calls == [step_name]


def test_live_call_sites_bind_distinct_persistent_intent_names() -> None:
    apply_source = inspect.getsource(bootstrap_runner.apply_github_controls)
    final_source = inspect.getsource(bootstrap_runner.perform_final_audit)

    assert 'step_name="github_controls_live_1"' in apply_source
    assert 'step_name="final_pre_enable_live"' in final_source
    assert 'step_name="final_post_enable_live"' in final_source


def test_dispatch_guard_serializes_two_concurrent_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "installed"
    root.mkdir()
    entered = threading.Event()
    release = threading.Event()
    run = {
        "databaseId": 1201,
        "headSha": COMMIT,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "url": "https://example.test/runs/1201",
    }
    dispatch_count = 0
    results: list[dict[str, object]] = []
    errors: list[BaseException] = []

    monkeypatch.setattr(bootstrap_runner, "_list_workflow_runs", lambda _workflow: [])
    monkeypatch.setattr(
        bootstrap_runner,
        "_reconcile_qualification_dispatch_intent",
        lambda _intent: dict(run),
    )

    def fake_dispatch(
        _workflow: str,
        _commit: str,
        *,
        baseline_run_ids: set[int] | None = None,
    ) -> dict[str, object]:
        nonlocal dispatch_count
        assert baseline_run_ids == set()
        dispatch_count += 1
        entered.set()
        assert release.wait(timeout=5)
        return dict(run)

    monkeypatch.setattr(bootstrap_runner, "_dispatch_workflow", fake_dispatch)

    def invoke() -> None:
        try:
            results.append(
                bootstrap_runner._run_qualification_workflow_step(
                    root, "policy_1", COMMIT
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below.
            errors.append(exc)

    first = threading.Thread(target=invoke)
    second = threading.Thread(target=invoke)
    first.start()
    assert entered.wait(timeout=5)
    second.start()
    time.sleep(0.1)
    assert dispatch_count == 1
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert results == [run, run]
    assert dispatch_count == 1


def test_requester_initial_response_rejects_cross_identity_before_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    calls = _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    receipt_path = (
        fixture["broker_root"] / "receipts" / ("1" * 64 + ".receipt.json")
    )
    receipt_path.unlink()
    mismatched = dict(fixture["first"])
    mismatched["request_id"] = "018f47a2-6e91-7c34-8000-000000000002"
    mismatched["receipt_sha256"] = "0" * 64
    mismatched["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(mismatched)
    ).hexdigest()
    monkeypatch.setattr(
        bootstrap_runner,
        "_invoke_bootstrap_request",
        lambda _source: _append_then_return(calls, mismatched, mismatched),
    )

    with pytest.raises(ValueError, match="QUALIFICATION_NOT_TERMINAL"):
        bootstrap_runner._run_requester_qualification(
            root, fixture["source"], COMMIT
        )
    assert not (
        root / bootstrap_runner.REQUESTER_TERMINAL_CHECKPOINT_FILENAME
    ).exists()


def test_requester_initial_response_restores_missing_local_receipt_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    _patch_requester_recovery_fakes(fixture, monkeypatch)
    receipt_path = (
        fixture["broker_root"] / "receipts" / ("1" * 64 + ".receipt.json")
    )
    receipt_path.unlink()

    bootstrap_runner._run_requester_qualification(
        fixture["root"], fixture["source"], COMMIT
    )

    assert receipt_path.read_bytes() == (
        bootstrap_runner._canonical(fixture["first"]) + b"\n"
    )


def test_requester_blocked_receipt_preserves_exact_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocked = {
        "schema_version": "1",
        "status": "blocked",
        "reason_code": "REQUESTER_PRODUCTION_SEAL_MISSING",
        "submission_key_sha256": "1" * 64,
        "request_id": "018f47a2-6e91-7c34-8000-000000000001",
        "campaign_key": "controller-bootstrap-qualification-v1",
        "launch_generation": 1,
        "issue_number": None,
        "request_sha256": None,
        "observed_at": "2026-08-25T10:01:00Z",
        "receipt_sha256": "0" * 64,
    }
    blocked["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(blocked)
    ).hexdigest()
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda *_args, **_kwargs: json.dumps(blocked),
    )

    with pytest.raises(
        ValueError,
        match="REQUESTER_BLOCKED:REQUESTER_PRODUCTION_SEAL_MISSING",
    ):
        bootstrap_runner._invoke_bootstrap_request(tmp_path)


def test_windows_checkpoint_publication_requests_write_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if bootstrap_runner.os.name != "nt":
        pytest.skip("Windows durability contract")
    temporary = tmp_path / "temporary"
    destination = tmp_path / "destination"
    temporary.write_bytes(b"sealed")
    observed_flags: list[int] = []

    class FakeMove:
        argtypes: object = None
        restype: object = None

        def __call__(self, source: str, target: str, flags: int) -> int:
            observed_flags.append(flags)
            bootstrap_runner.os.replace(source, target)
            return 1

    fake_move = FakeMove()
    monkeypatch.setattr(
        bootstrap_runner.ctypes,
        "WinDLL",
        lambda *_args, **_kwargs: SimpleNamespace(MoveFileExW=fake_move),
    )

    bootstrap_runner._publish_checkpoint_temp(
        temporary, destination, replace_existing=False
    )

    assert destination.read_bytes() == b"sealed"
    assert observed_flags == [0x8]


def test_existing_seal_without_complete_reuses_bytes_and_performs_one_replay(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    calls = _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    source = fixture["source"]
    bootstrap_runner._run_requester_qualification(root, source)
    seal_path = fixture["broker_root"] / "config/bootstrap-qualified-v1.seal.json"
    seal_bytes = seal_path.read_bytes()
    (root / bootstrap_runner.REQUESTER_TERMINAL_CHECKPOINT_FILENAME).unlink()
    (root / bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME).unlink()
    calls.clear()

    bootstrap_runner._run_requester_qualification(root, source)

    assert len(calls) == 1
    assert seal_path.read_bytes() == seal_bytes


@pytest.mark.parametrize(
    ("fault_file", "expected_replay_calls"),
    (
        (bootstrap_runner.REQUESTER_TERMINAL_CHECKPOINT_FILENAME, 0),
        (bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME, 0),
        ("bootstrap-qualified-v1.seal.json", 1),
    ),
)
def test_requester_reentry_after_checkpoint_write_does_not_replay(
    fault_file: str,
    expected_replay_calls: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    calls = _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    source = fixture["source"]
    original = bootstrap_runner._write_exact_canonical_checkpoint
    faulted = False

    def fail_after_write(path: Path, value: object) -> str:
        nonlocal faulted
        digest = original(path, value)
        if not faulted and path.name == fault_file:
            faulted = True
            raise RuntimeError("FAULT_AFTER_REQUESTER_CHECKPOINT_WRITE")
        return digest

    monkeypatch.setattr(
        bootstrap_runner, "_write_exact_canonical_checkpoint", fail_after_write
    )
    with pytest.raises(RuntimeError, match="FAULT_AFTER_REQUESTER_CHECKPOINT_WRITE"):
        bootstrap_runner._run_requester_qualification(root, source)
    monkeypatch.setattr(
        bootstrap_runner, "_write_exact_canonical_checkpoint", original
    )
    calls.clear()
    bootstrap_runner._run_requester_qualification(root, source)

    assert len(calls) == expected_replay_calls
    assert (
        root / bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME
    ).is_file()


def test_second_requester_receipt_with_any_field_difference_blocks(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    calls = _patch_requester_recovery_fakes(fixture, monkeypatch)
    root = fixture["root"]
    source = fixture["source"]
    first = fixture["first"]
    different = {**first, "reason_code": "REQUEST_DIFFERENT"}
    different["receipt_sha256"] = "0" * 64
    different["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(different)
    ).hexdigest()
    responses = iter((dict(first), different))
    monkeypatch.setattr(
        bootstrap_runner,
        "_invoke_bootstrap_request",
        lambda _source: _append_and_get_last(calls, dict(next(responses))),
    )

    with pytest.raises(ValueError, match="REQUESTER_REPLAY_INVALID"):
        bootstrap_runner._run_requester_qualification(root, source)
    assert not (
        root / bootstrap_runner.REQUESTER_COMPLETE_CHECKPOINT_FILENAME
    ).exists()


def test_controller_receipt_request_hash_mismatch_blocks(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _requester_recovery_fixture(tmp_path)
    _patch_requester_recovery_fakes(fixture, monkeypatch)
    bad = {**fixture["controller"], "request_sha256": "d" * 64}
    bad["receipt_sha256"] = hashlib.sha256(
        bootstrap_runner._canonical(
            {key: value for key, value in bad.items() if key != "receipt_sha256"}
        )
    ).hexdigest()
    monkeypatch.setattr(
        bootstrap_runner,
        "_parse_terminal_controller_receipt",
        lambda _issue: bad,
    )

    with pytest.raises(ValueError, match="CONTROLLER_RECEIPT_INVALID"):
        bootstrap_runner._run_requester_qualification(
            fixture["root"], fixture["source"]
        )


@pytest.mark.parametrize(
    ("remote", "expected"),
    (
        ("https://github.com/trading-optimizer-lab-org/aurora.git", True),
        ("git@github.com:trading-optimizer-lab-org/aurora.git", True),
        ("ssh://git@github.com/trading-optimizer-lab-org/aurora.git", True),
        ("https://evil.example/trading-optimizer-lab-org/aurora.git", False),
        ("https://github.com/other/aurora.git", False),
        ("https://user@github.com/trading-optimizer-lab-org/aurora.git", False),
    ),
)
def test_repository_remote_identity_is_exact(remote: str, expected: bool) -> None:
    assert bootstrap_runner._repository_remote_is_exact(remote) is expected


def test_nontransient_block_never_auto_resumes(tmp_path: Path) -> None:
    root = tmp_path / "protected"
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json", _blocked_merge_state()
    )
    (root / "receipts").mkdir(parents=True)
    receipt = {
        "controller_enabled_readback": False,
        "phase": "MERGE_PENDING",
        "reason_code": "REQUIRED_CHECK_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(receipt) + b"\n"
    )

    assert bootstrap_runner._resume_transient_merge_block(root) is False
    assert load_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json"
    ).phase == "BLOCKED"


def test_merge_recovery_rejects_a_matching_receipt_at_the_wrong_sequence(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    source = tmp_path / "source"
    source.mkdir(parents=True)
    persist_bootstrap_state(
        root / "state/catalog-bootstrap-state-v1.json",
        _blocked_local_install_state(),
    )
    (root / "receipts").mkdir(parents=True)
    receipt = {
        "controller_enabled_readback": False,
        "phase": "MERGE_PENDING",
        "reason_code": "BOOTSTRAP_PR_NOT_READY",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        bootstrap_runner._canonical(receipt) + b"\n"
    )
    context = {
        "repository": bootstrap_runner.REPOSITORY,
        "source_commit_sha": COMMIT,
        "source_root": str(source),
    }
    (root / "install-context-v1.json").write_bytes(
        bootstrap_runner._canonical(context) + b"\n"
    )
    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("external command must not run"),
    )

    assert bootstrap_runner._resume_transient_merge_block(root) is False


def test_recover_exact_merge_block_without_replaying_prior_phases(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "protected"
    source = tmp_path / "source"
    source.mkdir(parents=True)
    current_commit = "b" * 40
    binding_commit = "c" * 40
    branch = "catalog/bootstrap-binding-123456789abc"
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    persist_bootstrap_state(state_path, _blocked_merge_state())
    (root / "receipts").mkdir(parents=True)
    (root / "receipts/controller-bootstrap-blocked-v1.json").write_bytes(
        (
            json.dumps(
                {
                    "controller_enabled_readback": False,
                    "phase": "MERGE_PENDING",
                    "reason_code": "BOOTSTRAP_PR_NOT_READY",
                    "result": "BLOCKED",
                    "schema_version": "1",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    (root / "install-context-v1.json").write_text(
        json.dumps(
            {
                "repository": bootstrap_runner.REPOSITORY,
                "source_commit_sha": current_commit,
                "source_root": str(source),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    rounds = []
    for number in range(1, 4):
        value = {
            "round": number,
            "staged_tree_sha": "d" * 40,
            "changed_paths": list(PUBLIC_BINDING_PATHS),
            "material_problems_found": [],
        }
        value["round_sha256"] = bootstrap_runner.hashlib.sha256(
            bootstrap_runner._canonical(value)
        ).hexdigest()
        rounds.append(value)
    review = {"staged_tree_sha": "d" * 40, "rounds": rounds}
    (root / "binding-review-rounds-v1.json").write_bytes(
        (json.dumps(review, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    operation = {
        "binding_commit_sha": binding_commit,
        "branch": branch,
        "pr_number": 163,
        "review_rounds_sha256": bootstrap_runner.hashlib.sha256(
            bootstrap_runner._canonical(review)
        ).hexdigest(),
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        (
            json.dumps(operation, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    )
    baseline: dict[str, list[int]] = {
        "heavy_run_ids": [],
        "request_issue_numbers": [],
    }
    (root / "github-activity-baseline-v1.json").write_text(
        json.dumps(baseline, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    def fake_fixed_run(args: list[str], **_kwargs: object) -> str:
        if args[:3] == ["gh", "variable", "set"]:
            assert args[3] in {
                bootstrap_runner.ARMED_VARIABLE,
                bootstrap_runner.CONTROLLER_VARIABLE,
            }
            assert args[4:6] == ["--body", "false"]
            return ""
        if args[:3] == ["git", "status", "--porcelain=v1"]:
            return ""
        if args == ["git", "rev-parse", "HEAD"]:
            return current_commit
        if args == ["git", "rev-parse", "origin/main"]:
            return current_commit
        if args == ["git", "remote", "get-url", "origin"]:
            return "https://github.com/trading-optimizer-lab-org/aurora.git"
        if args == ["git", "branch", "--show-current"]:
            return "main"
        if args[:3] == ["git", "fetch", "origin"]:
            return ""
        if args[:3] == ["gh", "variable", "get"]:
            return "false"
        if args[:3] == ["gh", "pr", "view"]:
            return json.dumps(
                {
                    "baseRefName": "main",
                    "headRefName": branch,
                    "headRefOid": binding_commit,
                    "state": "OPEN",
                }
            )
        if args[:3] == ["gh", "pr", "diff"]:
            return "\n".join(PUBLIC_BINDING_PATHS)
        raise AssertionError(f"unexpected command: {args}")

    def fake_process(args: list[str], **_kwargs: object):
        assert args[:3] == ["git", "merge-base", "--is-ancestor"]
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr(bootstrap_runner, "EXPECTED_ROOT", root)
    monkeypatch.setattr(bootstrap_runner, "_run", fake_fixed_run)
    monkeypatch.setattr(bootstrap_runner.subprocess, "run", fake_process)
    monkeypatch.setattr(
        bootstrap_runner,
        "_wait_for_required_checks",
        lambda *_args, **_kwargs: (
            {
                "bucket": "pass",
                "name": "GTBI V7 stage-two required",
                "state": "SUCCESS",
            },
        ),
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_verify_existing_installations",
        lambda _root: {"auditor": 2, "requester": 1},
    )
    monkeypatch.setattr(bootstrap_runner, "_github_activity_snapshot", lambda: baseline)

    assert bootstrap_runner._resume_transient_merge_block(root) is True
    resumed = load_bootstrap_state(state_path)
    assert resumed.phase == "MERGE_PENDING"
    assert resumed.sequence == 8
    recovery = json.loads(
        (root / "receipts/controller-bootstrap-merge-retry-v1.json").read_text("utf-8")
    )
    assert recovery["binding_commit_sha"] == binding_commit
    assert recovery["source_commit_sha"] == current_commit


def test_merge_is_pinned_to_the_revalidated_head(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "protected"
    source = tmp_path / "source"
    source.mkdir(parents=True)
    state_path = root / "state/catalog-bootstrap-state-v1.json"
    persist_bootstrap_state(
        state_path,
        advance_bootstrap_state(
            _blocked_merge_state(),
            event("merge_retry_authorized", 8),
        ),
    )
    (root / "receipts").mkdir(parents=True)
    binding_commit = "b" * 40
    expected_head = "c" * 40
    merge_commit = "d" * 40
    operation = {
        "binding_commit_sha": binding_commit,
        "branch": "catalog/bootstrap-binding-123456789abc",
        "pr_number": 163,
        "review_rounds_sha256": "e" * 64,
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        bootstrap_runner._canonical(operation) + b"\n"
    )
    retry = {
        "binding_commit_sha": binding_commit,
        "blocked_state_sha256": "f" * 64,
        "head_commit_sha": expected_head,
        "installations": {"auditor": 2, "requester": 1},
        "pr_number": 163,
        "required_checks": [],
        "review_rounds_sha256": "e" * 64,
        "source_commit_sha": "1" * 40,
    }
    (root / "receipts/controller-bootstrap-merge-retry-v1.json").write_bytes(
        bootstrap_runner._canonical(retry) + b"\n"
    )
    (root / "install-context-v1.json").write_bytes(
        bootstrap_runner._canonical(
            {
                "repository": bootstrap_runner.REPOSITORY,
                "source_commit_sha": "1" * 40,
                "source_root": str(source),
            }
        )
        + b"\n"
    )
    commands: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> str:
        commands.append(args)
        if args[:3] == ["gh", "pr", "view"] and "baseRefName" in args[-1]:
            return json.dumps(
                {
                    "baseRefName": "main",
                    "headRefOid": expected_head,
                    "state": "OPEN",
                }
            )
        if args[:3] == ["gh", "pr", "merge"]:
            return ""
        if args[:3] == ["gh", "pr", "view"]:
            return json.dumps(
                {"state": "MERGED", "mergeCommit": {"oid": merge_commit}}
            )
        if args[:3] == ["git", "fetch", "origin"]:
            return ""
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(bootstrap_runner, "_run", fake_run)
    monkeypatch.setattr(
        bootstrap_runner,
        "_wait_for_required_checks",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        bootstrap_runner.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args=args, returncode=0),
    )

    bootstrap_runner.merge_public_binding(root)

    merge_commands = [args for args in commands if args[:3] == ["gh", "pr", "merge"]]
    assert merge_commands == [
        [
            "gh",
            "pr",
            "merge",
            "163",
            "--repo",
            bootstrap_runner.REPOSITORY,
            "--merge",
            "--match-head-commit",
            expected_head,
        ]
    ]
    assert load_bootstrap_state(state_path).phase == "LOCAL_INSTALL_PENDING"


def test_same_observation_is_idempotent() -> None:
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    observed = event("precheck_passed", 1)
    first = advance_bootstrap_state(state, observed)
    second = advance_bootstrap_state(first, observed)
    assert canonical_state_bytes(first) == canonical_state_bytes(second)


def test_rejects_changed_identity_commit_or_sequence() -> None:
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    with pytest.raises(ValueError, match="BOOTSTRAP_ID_CHANGED"):
        advance_bootstrap_state(state, event("precheck_passed", 1, bootstrap_id="other"))
    changed_commit = event("precheck_passed", 1).model_copy(
        update={"protected_commit_sha": "b" * 40}
    )
    with pytest.raises(ValueError, match="PROTECTED_COMMIT_CHANGED"):
        advance_bootstrap_state(state, changed_commit)
    with pytest.raises(ValueError, match="EVENT_SEQUENCE_INVALID"):
        advance_bootstrap_state(state, event("precheck_passed", 2))


def test_state_contract_cannot_contain_secret_fields() -> None:
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    fields = set(state.model_fields)
    forbidden = {"key", "token", "password", "pem", "jwt", "secret", "cookie", "session"}
    assert not any(part in field.lower() for field in fields for part in forbidden)
    assert not any(part in canonical_state_bytes(state).decode().lower() for part in forbidden)


def test_persistence_is_canonical_and_rejects_rollback(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    persisted = persist_bootstrap_state(target, state)
    assert persisted == load_bootstrap_state(target)
    assert target.read_bytes() == canonical_state_bytes(state) + b"\n"

    advanced = advance_bootstrap_state(state, event("precheck_passed", 1))
    persist_bootstrap_state(target, advanced)
    with pytest.raises(ValueError, match="STATE_ROLLBACK"):
        persist_bootstrap_state(target, state)


def test_load_rejects_noncanonical_json_and_links(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    state = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    target.write_text(json.dumps(state.model_dump(mode="json"), indent=2), "utf-8")
    with pytest.raises(ValueError, match="STATE_NONCANONICAL"):
        load_bootstrap_state(target)

    real = tmp_path / "real.json"
    persist_bootstrap_state(real, state)
    link = tmp_path / "link.json"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="STATE_LINK_FORBIDDEN"):
        load_bootstrap_state(link)


def test_controller_double_shutdown_is_ordered_and_attempts_enabled_after_armed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_set(name: str, value: str) -> None:
        calls.append((name, value))
        if name == bootstrap_runner.ARMED_VARIABLE:
            raise ValueError("armed readback failed")

    monkeypatch.setattr(bootstrap_runner, "_set_repository_variable", fake_set)

    with pytest.raises(bootstrap_runner.CatalogControllerShutdownError) as raised:
        bootstrap_runner._disable_controller()

    assert calls == [
        (bootstrap_runner.ARMED_VARIABLE, "false"),
        (bootstrap_runner.CONTROLLER_VARIABLE, "false"),
    ]
    assert [str(error) for error in raised.value.exceptions] == [
        "armed readback failed"
    ]


def test_controller_double_shutdown_aggregates_failures_in_fixed_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_set(name: str, _value: str) -> None:
        calls.append(name)
        raise ValueError(f"failure:{name}")

    monkeypatch.setattr(bootstrap_runner, "_set_repository_variable", fake_set)

    with pytest.raises(bootstrap_runner.CatalogControllerShutdownError) as raised:
        bootstrap_runner._disable_controller()

    assert calls == [bootstrap_runner.ARMED_VARIABLE, bootstrap_runner.CONTROLLER_VARIABLE]
    assert [str(error) for error in raised.value.exceptions] == [
        f"failure:{bootstrap_runner.ARMED_VARIABLE}",
        f"failure:{bootstrap_runner.CONTROLLER_VARIABLE}",
    ]


def test_failed_shutdown_writes_truthful_emergency_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        bootstrap_runner,
        "_disable_controller",
        lambda: (_ for _ in ()).throw(ValueError("secret must not escape")),
    )

    assert (
        bootstrap_runner._disable_controller_for_failure_receipt(
            tmp_path,
            phase="FINAL_AUDIT_PENDING",
        )
        is False
    )
    receipt = json.loads(
        (
            tmp_path / "receipts/controller-bootstrap-shutdown-failed-v1.json"
        ).read_text("utf-8")
    )
    assert receipt == {
        "controller_enabled_readback": True,
        "phase": "FINAL_AUDIT_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_CONTROLLER_SHUTDOWN_FAILED",
        "result": "FAILED",
        "schema_version": "1",
    }


@pytest.mark.parametrize("armed", ("", "TRUE", " true ", "yes", None))
def test_controller_ready_is_fail_closed_for_missing_or_malformed_values(
    armed: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = {
        bootstrap_runner.CONTROLLER_VARIABLE: "true",
        bootstrap_runner.ARMED_VARIABLE: armed,
    }
    monkeypatch.setattr(
        bootstrap_runner,
        "_read_repository_variable",
        lambda name: values[name],
    )

    assert bootstrap_runner._controller_is_ready() is False


def test_final_activation_sequence_is_exactly_ordered() -> None:
    source = inspect.getsource(bootstrap_runner.perform_final_audit)
    ordered_markers = (
        '_set_repository_variable(ARMED_VARIABLE, "false")',
        'pre_enable = _run_live_qualification',
        '_set_repository_variable(CONTROLLER_VARIABLE, "true")',
        'post_enable = _run_live_qualification',
        '_write_canonical(ready_path, ready.model_dump(mode="json"))',
        'if ready_path.read_bytes() != ready_bytes:',
        'seal = _production_seal',
        'deadline = time.monotonic() + 300',
        'self_audit.get("status") != "production_sealed"',
        '_set_repository_variable(ARMED_VARIABLE, "true")',
        'if not _controller_is_ready():',
        'final_activity = _github_activity_snapshot()',
        '"controller_armed_readback": True',
    )
    positions = [source.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)
