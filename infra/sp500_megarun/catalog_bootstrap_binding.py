"""Build the closed public identity binding for catalog bootstrap."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from .catalog_bootstrap_github import CatalogAppPublicBinding


REPOSITORY = "trading-optimizer-lab-org/aurora"
AUTHORITY_TITLE = "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT"
PUBLIC_BINDING_PATHS = (
    "config/catalog_authority_anchor_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_auditor_v1.json",
    "config/catalog_requester_public_key_v1.pem",
)
_PRIVATE_PEM_MARKER = b"-----BEGIN " + b"PRIVATE KEY-----"


@dataclass(frozen=True, slots=True)
class CatalogPublicBindingPatch:
    changed_paths: tuple[str, ...]
    documents: dict[str, bytes]


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _load_document(tree: Mapping[str, bytes], path: str) -> dict[str, object]:
    data = tree.get(path)
    if data is None:
        raise ValueError(f"PUBLIC_BINDING_SOURCE_MISSING:{path}")
    if _PRIVATE_PEM_MARKER in data:
        raise ValueError("PRIVATE_MATERIAL_FORBIDDEN")
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"PUBLIC_BINDING_SOURCE_INVALID:{path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"PUBLIC_BINDING_SOURCE_INVALID:{path}")
    forbidden = {"private_key", "pem", "token", "client_secret", "webhook_secret", "password"}
    if any(key.casefold() in forbidden for key in value):
        raise ValueError("PRIVATE_MATERIAL_FORBIDDEN")
    return value


def create_or_verify_authority_anchor(
    candidates: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    exact = [
        candidate
        for candidate in candidates
        if candidate.get("repository") == REPOSITORY
        and candidate.get("title") == AUTHORITY_TITLE
    ]
    if not exact:
        raise ValueError("AUTHORITY_ANCHOR_MISSING")
    if len(exact) != 1:
        raise ValueError("MULTIPLE_ANCHORS")
    candidate = exact[0]
    required = {
        "repository_node_id": str,
        "number": int,
        "node_id": str,
        "creator_login": str,
        "created_at": str,
    }
    if any(
        not isinstance(candidate.get(name), expected_type)
        for name, expected_type in required.items()
    ):
        raise ValueError("AUTHORITY_ANCHOR_INVALID")
    return candidate


def build_public_binding_patch(
    requester: CatalogAppPublicBinding,
    auditor: CatalogAppPublicBinding,
    authority: Mapping[str, object],
    tree: Mapping[str, bytes],
) -> CatalogPublicBindingPatch:
    if requester.kind != "requester" or auditor.kind != "auditor":
        raise ValueError("PUBLIC_BINDING_ROLE_INVALID")
    if _PRIVATE_PEM_MARKER in requester.public_key_pem:
        raise ValueError("PRIVATE_MATERIAL_FORBIDDEN")
    checked_authority = create_or_verify_authority_anchor([authority])
    actors = _load_document(tree, "config/catalog_controller_actors_v1.json")
    auditor_config = _load_document(tree, "config/catalog_github_auditor_v1.json")
    actors.update(
        {
            "production_enabled": False,
            "request_actors": [f"{requester.app_slug}[bot]"],
            "requester_public_key_path": "config/catalog_requester_public_key_v1.pem",
            "requester_public_key_sha256": requester.public_key_sha256,
        }
    )
    auditor_config.update(
        {
            "expected_app_slug": auditor.app_slug,
            "public_key_sha256": auditor.public_key_sha256,
        }
    )
    anchor = {
        "schema_version": "1",
        "production_enabled": False,
        "repository": REPOSITORY,
        "repository_node_id": checked_authority["repository_node_id"],
        "issue_number": checked_authority["number"],
        "issue_node_id": checked_authority["node_id"],
        "exact_title": AUTHORITY_TITLE,
        "creator_login": checked_authority["creator_login"],
        "created_at": checked_authority["created_at"],
    }
    documents = {
        "config/catalog_authority_anchor_v1.json": _canonical_json(anchor),
        "config/catalog_controller_actors_v1.json": _canonical_json(actors),
        "config/catalog_github_auditor_v1.json": _canonical_json(auditor_config),
        "config/catalog_requester_public_key_v1.pem": requester.public_key_pem,
    }
    return CatalogPublicBindingPatch(
        changed_paths=PUBLIC_BINDING_PATHS,
        documents=documents,
    )


def open_or_reuse_bootstrap_pr(*, matching_prs: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
    if len(matching_prs) > 1:
        raise ValueError("MULTIPLE_BOOTSTRAP_PRS")
    if not matching_prs:
        raise ValueError("BOOTSTRAP_PR_CREATION_REQUIRED")
    return matching_prs[0]


def merge_verified_bootstrap_pr(
    *,
    pull_request: Mapping[str, object],
    expected_head_sha: str,
) -> str:
    if pull_request.get("head_sha") != expected_head_sha:
        raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
    if pull_request.get("checks") != "success" or pull_request.get("mergeable") is not True:
        raise ValueError("BOOTSTRAP_PR_NOT_READY")
    merge_sha = pull_request.get("merge_commit_sha")
    if not isinstance(merge_sha, str) or len(merge_sha) != 40:
        raise ValueError("BOOTSTRAP_PR_MERGE_UNVERIFIED")
    return merge_sha
