"""Closed transition-manifest policy for the readiness state controller."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest

MANIFEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TASK_ID_RE = re.compile(r"^PREV7-[0-9]{4}$")
GATE_ID_RE = re.compile(r"^G(?:0|1A|1B|2|3A|3B|4|5|6|7|8|9|9X|10)$")
TRANSACTION_ID_RE = re.compile(
    r"^G(?:0|1A|1B|2|3A|3B|4|5|6|7|8|9|9X|10)_CLOSE-[1-9][0-9]*$"
)

READINESS_PREFIX = "docs/readiness/gtbi-v7/"
TRANSITION_MANIFEST_DIR = (
    "docs/readiness/gtbi-v7/transition_manifests"
)
ALLOWED_TARGET_STATUSES = {"done", "cancelled"}
MANIFEST_FIELDS = {
    "schema_version",
    "manifest_id",
    "transaction_id",
    "requested_at_utc",
    "actor_id",
    "actor_role",
    "expected_base_ref",
    "expected_base_sha_mode",
    "task_actions",
    "branch_actions",
    "gate_actions",
    "owner_directive_digest",
    "manifest_digest",
}
TASK_ACTION_FIELDS = {
    "task_id",
    "target_status",
    "evidence_paths",
    "evidence_sha256",
    "terminal_reason",
    "notes",
    "files_touched",
    "expected_result",
    "alternative_completion_receipt_set_digest_or_null",
}
BRANCH_ACTION_FIELDS = {
    "branch_id",
    "task_id",
    "selected_successor",
    "predicate_evidence_digest",
    "decision_receipt_digest",
}
GATE_ACTION_FIELDS = {
    "gate_id",
    "target_status",
    "selected_branch_id_or_null",
    "inventory_snapshot_digest",
    "evidence_bundle_digest",
}


class StateControllerError(ValueError):
    """Raised when a controller request is outside the reviewed contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StateControllerError(message)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _validate_path(value: Any) -> str:
    _require(isinstance(value, str), "evidence path must be text")
    _require(value.startswith(READINESS_PREFIX),
             "evidence path is outside readiness")
    _require("\\" not in value, "evidence path contains a backslash")
    _require(".." not in Path(value).parts, "evidence path traverses parents")
    _require(not Path(value).is_absolute(),
             "evidence path must be repository-relative")
    return value


def _validate_task_action(action: Any) -> None:
    _require(isinstance(action, dict), "task action must be an object")
    _require(set(action) == TASK_ACTION_FIELDS,
             "task action field set mismatch")
    _require(bool(TASK_ID_RE.fullmatch(str(action["task_id"]))),
             "invalid task id")
    _require(action["target_status"] in ALLOWED_TARGET_STATUSES,
             "invalid task target status")
    paths = action["evidence_paths"]
    digests = action["evidence_sha256"]
    _require(isinstance(paths, list) and bool(paths),
             "task evidence paths must be non-empty")
    _require(isinstance(digests, list) and len(digests) == len(paths),
             "task evidence digest count mismatch")
    for path in paths:
        _validate_path(path)
    _require(all(_is_digest(value) for value in digests),
             "invalid task evidence digest")
    _require(len(paths) == len(set(paths)), "duplicate task evidence path")
    files_touched = action["files_touched"]
    _require(isinstance(files_touched, list),
             "files_touched must be a list")
    for path in files_touched:
        _validate_path(path)
    alternative = action[
        "alternative_completion_receipt_set_digest_or_null"
    ]
    _require(alternative is None or _is_digest(alternative),
             "invalid alternative-completion digest")
    _require(isinstance(action["terminal_reason"], str)
             and bool(action["terminal_reason"]),
             "terminal reason is required")
    _require(isinstance(action["notes"], str), "notes must be text")
    _require(isinstance(action["expected_result"], str)
             and bool(action["expected_result"]),
             "expected result is required")


def _validate_branch_action(action: Any) -> None:
    _require(isinstance(action, dict), "branch action must be an object")
    _require(set(action) == BRANCH_ACTION_FIELDS,
             "branch action field set mismatch")
    _require(isinstance(action["branch_id"], str)
             and bool(action["branch_id"]),
             "branch id is required")
    _require(bool(TASK_ID_RE.fullmatch(str(action["task_id"]))),
             "invalid branch task id")
    _require(isinstance(action["selected_successor"], str)
             and bool(action["selected_successor"]),
             "selected successor is required")
    _require(_is_digest(action["predicate_evidence_digest"]),
             "invalid branch predicate evidence digest")
    _require(_is_digest(action["decision_receipt_digest"]),
             "invalid branch decision receipt digest")


def _validate_gate_action(action: Any) -> None:
    _require(isinstance(action, dict), "gate action must be an object")
    _require(set(action) == GATE_ACTION_FIELDS,
             "gate action field set mismatch")
    _require(bool(GATE_ID_RE.fullmatch(str(action["gate_id"]))),
             "invalid gate id")
    _require(action["target_status"] in {"green", "not_applicable"},
             "invalid gate target status")
    selected = action["selected_branch_id_or_null"]
    _require(selected is None or isinstance(selected, str),
             "invalid selected gate branch")
    _require(_is_digest(action["inventory_snapshot_digest"]),
             "invalid inventory snapshot digest")
    _require(_is_digest(action["evidence_bundle_digest"]),
             "invalid gate evidence bundle digest")


def validate_transition_manifest(manifest: dict[str, Any]) -> None:
    """Validate an exact reviewed transition manifest without touching state."""

    _require(set(manifest) == MANIFEST_FIELDS,
             "transition manifest field set mismatch")
    _require(
        manifest["schema_version"]
        == "gtbi_v7_readiness_transition_manifest_v1",
        "transition manifest schema mismatch",
    )
    _require(bool(MANIFEST_ID_RE.fullmatch(str(manifest["manifest_id"]))),
             "invalid manifest id")
    _require(
        bool(TRANSACTION_ID_RE.fullmatch(str(manifest["transaction_id"]))),
        "invalid transaction id",
    )
    _require(manifest["expected_base_ref"] == "refs/heads/main",
             "controller base ref must be main")
    _require(
        manifest["expected_base_sha_mode"]
        == "runtime_default_branch_head",
        "controller base SHA mode mismatch",
    )
    _require(isinstance(manifest["actor_id"], str)
             and bool(manifest["actor_id"]),
             "actor id is required")
    _require(manifest["actor_role"] == "repository_owner",
             "only the owner-controlled role is allowed")
    _require(_is_digest(manifest["owner_directive_digest"]),
             "invalid owner directive digest")

    tasks = manifest["task_actions"]
    branches = manifest["branch_actions"]
    gates = manifest["gate_actions"]
    _require(isinstance(tasks, list) and bool(tasks),
             "at least one task action is required")
    _require(isinstance(branches, list), "branch actions must be a list")
    _require(isinstance(gates, list), "gate actions must be a list")
    for action in tasks:
        _validate_task_action(action)
    for action in branches:
        _validate_branch_action(action)
    for action in gates:
        _validate_gate_action(action)
    task_ids = [action["task_id"] for action in tasks]
    _require(len(task_ids) == len(set(task_ids)),
             "duplicate task action")
    gate_ids = [action["gate_id"] for action in gates]
    _require(len(gate_ids) == len(set(gate_ids)),
             "duplicate gate action")
    branch_keys = [
        (action["branch_id"], action["task_id"]) for action in branches
    ]
    _require(len(branch_keys) == len(set(branch_keys)),
             "duplicate branch action")

    expected_digest = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    _require(manifest["manifest_digest"] == expected_digest,
             "transition manifest digest mismatch")


def load_transition_manifest(
    repository_root: Path,
    manifest_id: str,
) -> dict[str, Any]:
    """Load a manifest by closed identifier, never by caller-provided path."""

    _require(bool(MANIFEST_ID_RE.fullmatch(manifest_id)),
             "invalid manifest id")
    root = repository_root.resolve()
    path = root / TRANSITION_MANIFEST_DIR / f"{manifest_id}.json"
    _require(path.is_file(), "reviewed transition manifest not found")
    _require(not path.is_symlink(), "transition manifest cannot be a symlink")
    raw = path.read_bytes()
    value = json.loads(raw)
    _require(isinstance(value, dict),
             "transition manifest must be an object")
    _require(raw == canonical_bytes(value) + b"\n",
             "transition manifest is not canonical")
    manifest = dict(value)
    _require(manifest.get("manifest_id") == manifest_id,
             "manifest id does not match filename")
    validate_transition_manifest(manifest)
    return manifest
