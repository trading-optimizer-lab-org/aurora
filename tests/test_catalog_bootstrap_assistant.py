from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import run_catalog_bootstrap_assistant as bootstrap_runner

from infra.sp500_megarun.catalog_bootstrap_state import (
    CatalogBootstrapEventV1,
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


def event(name: str, sequence: int, *, bootstrap_id: str = BOOTSTRAP_ID):
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
    names = (
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
    names = (
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


def test_only_exact_merge_retry_can_leave_terminal_blocked_state() -> None:
    blocked = _blocked_merge_state()
    assert blocked.phase == "BLOCKED"

    resumed = advance_bootstrap_state(blocked, event("merge_retry_authorized", 8))
    assert resumed.phase == "MERGE_PENDING"
    assert resumed.sequence == 8

    precheck = initial_bootstrap_state(BOOTSTRAP_ID, COMMIT)
    with pytest.raises(ValueError, match="TRANSITION_INVALID"):
        advance_bootstrap_state(precheck, event("merge_retry_authorized", 1))


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


def test_second_local_install_block_enters_protected_recovery(
    tmp_path: Path, monkeypatch
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
    tmp_path: Path, monkeypatch
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
    tmp_path: Path, monkeypatch
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
    tmp_path: Path, monkeypatch
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
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("external command must not run"),
    )

    with pytest.raises(ValueError, match="LOCAL_RETRY_CONTEXT_INVALID"):
        bootstrap_runner._resume_transient_local_install_block(root)


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
    baseline = {"heavy_run_ids": [], "request_issue_numbers": []}
    (root / "github-activity-baseline-v1.json").write_bytes(
        bootstrap_runner._canonical(baseline) + b"\n"
    )
    (root / "secrets").mkdir()
    (root / "secrets/requester-pending.pem").write_bytes(b"test-pending-key")

    calls: list[list[str]] = []

    def fake_fixed_run(args: list[str], **_kwargs: object) -> str:
        calls.append(args)
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
    monkeypatch.setattr(
        bootstrap_runner,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("external command must not run"),
    )

    with pytest.raises(ValueError, match="LOCAL_RETRY_PARTIAL_INSTALL"):
        bootstrap_runner._resume_transient_local_install_block(root)


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


def test_post_repair_phases_all_use_the_runtime_commit() -> None:
    for handler in (
        bootstrap_runner.install_local_components,
        bootstrap_runner.apply_github_controls,
        bootstrap_runner.run_qualifications,
        bootstrap_runner.perform_final_audit,
    ):
        assert "_runtime_commit" in handler.__code__.co_names


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
        "_resume_transient_merge_block",
        lambda _root: recoveries.append("merge") or False,
    )
    monkeypatch.setattr(
        bootstrap_runner,
        "_resume_transient_local_install_block",
        lambda _root: recoveries.append("local") or True,
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
    baseline = {"heavy_run_ids": [], "request_issue_numbers": []}
    (root / "github-activity-baseline-v1.json").write_text(
        json.dumps(baseline, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    def fake_fixed_run(args: list[str], **_kwargs: object) -> str:
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
