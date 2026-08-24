"""Fail-closed, resumable public state for the catalog bootstrap assistant."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from .catalog_request_contract import FrozenModel, Sha256


BootstrapPhase = Literal[
    "PRECHECK",
    "REQUESTER_CREATE_PENDING",
    "REQUESTER_INSTALL_PENDING",
    "AUDITOR_CREATE_PENDING",
    "AUDITOR_INSTALL_PENDING",
    "PUBLIC_BINDING_PENDING",
    "MERGE_PENDING",
    "LOCAL_INSTALL_PENDING",
    "GITHUB_CONTROLS_PENDING",
    "QUALIFICATION_PENDING",
    "AGENT_RESTART_PENDING",
    "FINAL_AUDIT_PENDING",
    "READY",
    "BLOCKED",
]

EventName = Literal[
    "precheck_passed",
    "requester_created",
    "requester_installed",
    "auditor_created",
    "auditor_installed",
    "public_binding_committed",
    "merge_retry_authorized",
    "protected_merge_observed",
    "local_install_retry_authorized",
    "github_controls_retry_authorized",
    "local_install_verified",
    "github_controls_verified",
    "qualification_passed",
    "agent_restart_verified",
    "final_audit_passed",
    "blocked",
]


class CatalogBootstrapEventV1(FrozenModel):
    schema_version: Literal["1"]
    bootstrap_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    sequence: int = Field(ge=1)
    name: EventName
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    observed_at: str = Field(min_length=20, max_length=40)
    evidence_sha256: Sha256

    @property
    def idempotency_sha256(self) -> str:
        return hashlib.sha256(_canonical_model_bytes(self)).hexdigest()


class CatalogBootstrapStateV1(FrozenModel):
    schema_version: Literal["1"]
    bootstrap_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    phase: BootstrapPhase
    sequence: int = Field(ge=0)
    applied_event_sha256s: tuple[Sha256, ...]
    last_observed_at: str | None
    reason_codes: tuple[str, ...]


_TRANSITIONS: dict[tuple[str, str], BootstrapPhase] = {
    ("PRECHECK", "precheck_passed"): "REQUESTER_CREATE_PENDING",
    ("REQUESTER_CREATE_PENDING", "requester_created"): "REQUESTER_INSTALL_PENDING",
    ("REQUESTER_INSTALL_PENDING", "requester_installed"): "AUDITOR_CREATE_PENDING",
    ("AUDITOR_CREATE_PENDING", "auditor_created"): "AUDITOR_INSTALL_PENDING",
    ("AUDITOR_INSTALL_PENDING", "auditor_installed"): "PUBLIC_BINDING_PENDING",
    ("PUBLIC_BINDING_PENDING", "public_binding_committed"): "MERGE_PENDING",
    ("BLOCKED", "merge_retry_authorized"): "MERGE_PENDING",
    ("MERGE_PENDING", "protected_merge_observed"): "LOCAL_INSTALL_PENDING",
    ("BLOCKED", "local_install_retry_authorized"): "LOCAL_INSTALL_PENDING",
    ("BLOCKED", "github_controls_retry_authorized"): "GITHUB_CONTROLS_PENDING",
    ("LOCAL_INSTALL_PENDING", "local_install_verified"): "GITHUB_CONTROLS_PENDING",
    ("GITHUB_CONTROLS_PENDING", "github_controls_verified"): "QUALIFICATION_PENDING",
    ("QUALIFICATION_PENDING", "qualification_passed"): "AGENT_RESTART_PENDING",
    ("AGENT_RESTART_PENDING", "agent_restart_verified"): "FINAL_AUDIT_PENDING",
    ("FINAL_AUDIT_PENDING", "final_audit_passed"): "READY",
}


def _canonical_model_bytes(value: FrozenModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_state_bytes(value: CatalogBootstrapStateV1) -> bytes:
    return _canonical_model_bytes(value)


def initial_bootstrap_state(
    bootstrap_id: str,
    protected_commit_sha: str,
) -> CatalogBootstrapStateV1:
    return CatalogBootstrapStateV1(
        schema_version="1",
        bootstrap_id=bootstrap_id,
        protected_commit_sha=protected_commit_sha,
        phase="PRECHECK",
        sequence=0,
        applied_event_sha256s=(),
        last_observed_at=None,
        reason_codes=(),
    )


def advance_bootstrap_state(
    state: CatalogBootstrapStateV1,
    event: CatalogBootstrapEventV1,
) -> CatalogBootstrapStateV1:
    if event.bootstrap_id != state.bootstrap_id:
        raise ValueError("BOOTSTRAP_ID_CHANGED")
    if event.protected_commit_sha != state.protected_commit_sha:
        raise ValueError("PROTECTED_COMMIT_CHANGED")
    event_hash = event.idempotency_sha256
    if event_hash in state.applied_event_sha256s:
        return state
    if event.sequence != state.sequence + 1:
        raise ValueError("EVENT_SEQUENCE_INVALID")
    if event.name == "blocked" and state.phase not in {"READY", "BLOCKED"}:
        next_phase: BootstrapPhase = "BLOCKED"
    else:
        next_phase = _TRANSITIONS.get((state.phase, event.name))  # type: ignore[assignment]
        if next_phase is None:
            raise ValueError("TRANSITION_INVALID")
    return state.model_copy(
        update={
            "phase": next_phase,
            "sequence": event.sequence,
            "applied_event_sha256s": (*state.applied_event_sha256s, event_hash),
            "last_observed_at": event.observed_at,
        }
    )


def _anchor_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.anchor")


def _reject_link(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("STATE_LINK_FORBIDDEN")


def _decode_canonical_state(data: bytes) -> CatalogBootstrapStateV1:
    if not data.endswith(b"\n") or data.count(b"\n") != 1:
        raise ValueError("STATE_NONCANONICAL")
    try:
        state = CatalogBootstrapStateV1.model_validate_json(data[:-1])
    except Exception as exc:
        raise ValueError("STATE_INVALID") from exc
    if data != canonical_state_bytes(state) + b"\n":
        raise ValueError("STATE_NONCANONICAL")
    return state


def _canonical_anchor_bytes(state: CatalogBootstrapStateV1) -> bytes:
    payload = {
        "bootstrap_id": state.bootstrap_id,
        "protected_commit_sha": state.protected_commit_sha,
        "sequence": state.sequence,
        "state_sha256": hashlib.sha256(canonical_state_bytes(state)).hexdigest(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def load_bootstrap_state(path: Path) -> CatalogBootstrapStateV1:
    path = Path(path)
    _reject_link(path)
    state = _decode_canonical_state(path.read_bytes())
    anchor = _anchor_path(path)
    if anchor.exists():
        _reject_link(anchor)
        anchor_data = anchor.read_bytes()
        try:
            parsed = json.loads(anchor_data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("STATE_ANCHOR_INVALID") from exc
        if anchor_data != _canonical_anchor_bytes(state):
            if isinstance(parsed, dict) and parsed.get("sequence", -1) > state.sequence:
                raise ValueError("STATE_ROLLBACK")
            raise ValueError("STATE_ANCHOR_MISMATCH")
    return state


def _atomic_write_new(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".new",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.is_symlink():
            raise ValueError("STATE_LINK_FORBIDDEN")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def persist_bootstrap_state(
    path: Path,
    state: CatalogBootstrapStateV1,
) -> CatalogBootstrapStateV1:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_link(path)
    anchor = _anchor_path(path)
    _reject_link(anchor)
    lock = path.with_name(f"{path.name}.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("STATE_WRITER_LOCKED") from exc
    try:
        os.close(descriptor)
        if path.exists():
            current = load_bootstrap_state(path)
            if current.bootstrap_id != state.bootstrap_id:
                raise ValueError("BOOTSTRAP_ID_CHANGED")
            if current.protected_commit_sha != state.protected_commit_sha:
                raise ValueError("PROTECTED_COMMIT_CHANGED")
            if state.sequence < current.sequence:
                raise ValueError("STATE_ROLLBACK")
        state_data = canonical_state_bytes(state) + b"\n"
        _atomic_write_new(anchor, _canonical_anchor_bytes(state))
        _atomic_write_new(path, state_data)
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(state_data).digest():
            raise ValueError("STATE_READBACK_MISMATCH")
        return load_bootstrap_state(path)
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
