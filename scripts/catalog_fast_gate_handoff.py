"""Private, single-use evidence between protected steps of one gate job.

The checksum detects corruption, not authorship. Trust comes from the same-job
producer and fixed private RUNNER_TEMP directory; this is never an artifact or
cache input. Mutable authority editions and source state are still read live.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import (
    CheckpointRecoveryOwnerAuthenticationV1, _read_signed_request,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1, verify_checkpoint_failure_owner,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CheckpointRecoveryProfileV1, load_checkpoint_recovery_profile,
)
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_authority_github import _edition, _LOCATOR
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1, parse_catalog_terminal_receipt
from aurora.infra.sp500_megarun.catalog_fast_reservation import (
    FastGateOwnerEvidence, load_owner_terminal_receipt,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1

_ERROR = "CATALOG_FAST_GATE_HANDOFF_INVALID"
_DIRECTORY = ".catalog-fast-gate-handoff"
_MAX_BYTES = 2 * 1024 * 1024


def _execution(commit: str) -> dict[str, str]:
    names = ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")
    values = {name: os.environ.get(name, "") for name in names}
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or values["GITHUB_REPOSITORY"] != "trading-optimizer-lab-org/aurora"
            or values["GITHUB_JOB"] != "gate"
            or any(re.fullmatch(r"[1-9][0-9]*", values[name]) is None
                   for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
            or re.fullmatch(r"[0-9a-f]{40}", commit) is None
            or os.environ.get("CATALOG_PROTECTED_COMMIT_SHA") != commit):
        raise ValueError(_ERROR)
    return {**values, "protected_commit_sha": commit}


def _directory(*, create: bool = False) -> Path:
    raw = os.environ.get("RUNNER_TEMP", "")
    temp = Path(raw)
    if not raw or temp.is_symlink() or not temp.is_dir():
        raise ValueError(_ERROR)
    directory = temp.resolve(strict=True) / _DIRECTORY
    if create:
        directory.mkdir(mode=0o700, exist_ok=False)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(_ERROR)
    if os.name == "posix" and directory.stat().st_mode & 0o077:
        raise ValueError(_ERROR)
    return directory


def _write(name: str, payload: Mapping[str, Any]) -> None:
    document = dict(payload)
    document["content_sha256"] = canonical_sha256(document)
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > _MAX_BYTES:
        raise ValueError(_ERROR)
    path = _directory() / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def _read(name: str, *, commit: str) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(_ERROR)
            result[key] = value
        return result

    path = _directory() / name
    if (path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode)
            or not 0 < path.stat().st_size <= _MAX_BYTES
            or (os.name == "posix" and path.stat().st_mode & 0o077)):
        raise ValueError(_ERROR)
    document = json.loads(path.read_bytes(), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError(_ERROR)))
    if (not isinstance(document, dict) or document.get("schema_version") != "1"
            or document.get("execution") != _execution(commit)
            or document.get("content_sha256") != canonical_sha256(
                {key: value for key, value in document.items() if key != "content_sha256"})):
        raise ValueError(_ERROR)
    return document


def stage_authority(*, state: FastAuthorityStateV1, edit: Mapping[str, Any],
                    anchor: Mapping[str, Any], commit: str) -> None:
    """Called only after the production authority reader authenticates this edit."""
    execution = _execution(commit)
    edition = _edition(edit, anchor)
    locator = _LOCATOR.search(edition[0])
    if locator is None or edition[0][:locator.start()] != state.to_body():
        raise ValueError(_ERROR)
    _directory(create=True)
    _write("authority.json", {"schema_version": "1", "execution": execution,
        "anchor_sha256": canonical_sha256(anchor), "edition": list(edition),
        "state": state.model_dump(mode="json")})


def _authority(*, anchor: Mapping[str, Any], commit: str):
    document = _read("authority.json", commit=commit)
    state = FastAuthorityStateV1.model_validate(document["state"])
    edition = document.get("edition")
    if (document.get("anchor_sha256") != canonical_sha256(anchor)
            or not isinstance(edition, list) or len(edition) != 3
            or any(not isinstance(item, str) or not item for item in edition)):
        raise ValueError(_ERROR)
    locator = _LOCATOR.search(edition[0])
    if locator is None or edition[0][:locator.start()] != state.to_body():
        raise ValueError(_ERROR)
    return document, state, tuple(edition)


def stage_admission(*, anchor: Mapping[str, Any], commit: str,
                    authority: FastAuthorityStateV1, context: Mapping[str, Any],
                    decision: CatalogFastLaunchDecisionV1,
                    authenticated: CheckpointRecoveryOwnerAuthenticationV1 | None,
                    profile: CheckpointRecoveryProfileV1 | None = None) -> None:
    """Called only after admission and plan materialization have succeeded."""
    document, current, _ = _authority(anchor=anchor, commit=commit)
    request = CatalogRunRequestV1.model_validate(context["request"])
    if (current != authority or not decision.launch_required or decision.existing_run_id is not None
            or decision.request_sha256 != request.request_sha256
            or context.get("protected_commit_sha") != commit
            or context.get("content_sha256") != canonical_sha256(
                {key: value for key, value in context.items() if key != "content_sha256"})):
        raise ValueError(_ERROR)
    recovery = None
    if profile is not None:
        if authenticated is None or verify_checkpoint_failure_owner(
                profile=profile, owner=authenticated.owner, terminal=authenticated.terminal) != authenticated.proof:
            raise ValueError(_ERROR)
        owner = authenticated.owner
        recovery = {"profile_sha256": profile.profile_sha256,
            "proof": asdict(authenticated.proof), "owner": {
                "run_id": owner.run_id, "run": dict(owner.run),
                "decision": owner.decision.model_dump(mode="json"),
                "jobs": [job for job in owner.jobs if job.get("id") == authenticated.proof.source_finalizer_job_id]}}
        if authenticated.terminal is not None:
            recovery["terminal"] = authenticated.terminal.model_dump(mode="json")
    elif authenticated is not None:
        raise ValueError(_ERROR)
    _write("admission.json", {"schema_version": "1", "execution": _execution(commit),
        "authority_sha256": document["content_sha256"],
        "context_sha256": canonical_sha256(context), "issue_number": context["issue_number"],
        "request_sha256": request.request_sha256, "decision_sha256": decision.decision_sha256,
        "recovery": recovery})


def consume_admission(*, root: Path, anchor: Mapping[str, Any], commit: str,
                      context: Mapping[str, Any], decision: CatalogFastLaunchDecisionV1,
                      client: CatalogGitHubReadOnlyClient,
                      read_edit: Callable[[], dict[str, Any]],
                      download_archive: Callable[[int], bytes]
                      ) -> tuple[FastAuthorityStateV1, str, CheckpointRecoveryOwnerProofV1 | None]:
    document, current, edition = _authority(anchor=anchor, commit=commit)
    admitted = _read("admission.json", commit=commit)
    request = CatalogRunRequestV1.model_validate(context["request"])
    if (admitted.get("authority_sha256") != document["content_sha256"]
            or admitted.get("context_sha256") != canonical_sha256(context)
            or admitted.get("issue_number") != context["issue_number"]
            or admitted.get("request_sha256") != request.request_sha256
            or admitted.get("decision_sha256") != decision.decision_sha256
            or not decision.launch_required or decision.existing_run_id is not None):
        raise ValueError(_ERROR)
    # Exclusive marker prevents replay even if a subsequent live check fails.
    _write("consumed.json", {"schema_version": "1", "execution": _execution(commit),
                            "admission_sha256": admitted["content_sha256"]})
    if _edition(read_edit(), anchor) != edition:
        raise ValueError("CATALOG_FAST_AUTHORITY_WRITE_CONFLICT")
    profile = load_checkpoint_recovery_profile(root, request.campaign_key, request.launch_generation)
    recovery = admitted.get("recovery")
    proof = None
    if profile is None:
        if recovery is not None:
            raise ValueError(_ERROR)
    else:
        if not isinstance(recovery, dict) or recovery.get("profile_sha256") != profile.profile_sha256:
            raise ValueError(_ERROR)
        proof = CheckpointRecoveryOwnerProofV1(**recovery["proof"])
        cached = recovery["owner"]
        cached_owner = FastGateOwnerEvidence(cached["run_id"], cached["run"],
            CatalogFastLaunchDecisionV1.model_validate(cached["decision"]), tuple(cached["jobs"]))
        cached_terminal = parse_catalog_terminal_receipt(recovery["terminal"]) if "terminal" in recovery else None
        if verify_checkpoint_failure_owner(profile=profile, owner=cached_owner, terminal=cached_terminal) != proof:
            raise ValueError(_ERROR)
        # Recheck the signed source and mutable state; reuse historical job provenance.
        _read_signed_request(client, root, profile)
        path = f"/repos/{client.repository}/actions/runs/{profile.source_run_id}"
        run, _ = client.get_json(path)
        if not isinstance(run, dict):
            raise ValueError(_ERROR)
        for key in ("id", "run_attempt", "head_sha", "head_branch", "status", "conclusion", "path", "repository"):
            if run.get(key) != cached_owner.run.get(key):
                raise ValueError(_ERROR)
        owner = FastGateOwnerEvidence(cached_owner.run_id, run, cached_owner.decision, cached_owner.jobs)
        terminal = load_owner_terminal_receipt(client=client, owner=owner,
            issue_number=profile.source_issue_number, download_archive=download_archive)
        if terminal != cached_terminal or verify_checkpoint_failure_owner(
                profile=profile, owner=owner, terminal=terminal) != proof:
            raise ValueError(_ERROR)
        after, _ = client.get_json(path)
        if not isinstance(after, dict) or any(after.get(key) != run.get(key) for key in (
                "id", "run_attempt", "head_sha", "head_branch", "status", "conclusion", "path", "repository")):
            raise ValueError(_ERROR)
    return current, edition[1], proof
