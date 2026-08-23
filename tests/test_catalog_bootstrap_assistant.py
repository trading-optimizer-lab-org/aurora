from __future__ import annotations

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
