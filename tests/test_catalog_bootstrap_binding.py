from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra.sp500_megarun.catalog_bootstrap_binding import (
    build_public_binding_patch,
    create_or_verify_authority_anchor,
)
from infra.sp500_megarun.catalog_bootstrap_github import CatalogAppPublicBinding


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PATHS = (
    "config/catalog_authority_anchor_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_auditor_v1.json",
    "config/catalog_requester_public_key_v1.pem",
)


def _binding(kind: str, app_id: int, slug: str, marker: bytes) -> CatalogAppPublicBinding:
    return CatalogAppPublicBinding(
        kind=kind,
        app_id=app_id,
        app_slug=slug,
        public_key_pem=b"-----BEGIN PUBLIC KEY-----\n" + marker + b"\n-----END PUBLIC KEY-----\n",
        public_key_sha256=("a" if kind == "requester" else "b") * 64,
    )


def _authority() -> dict[str, object]:
    return {
        "repository": "trading-optimizer-lab-org/aurora",
        "repository_node_id": "R_repo",
        "number": 123,
        "node_id": "I_issue",
        "title": "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT",
        "creator_login": "gomez5757",
        "created_at": "2026-08-23T12:00:00Z",
    }


def test_binding_changes_only_public_allowlisted_paths() -> None:
    tree = {
        path: (ROOT / path).read_bytes()
        for path in EXPECTED_PATHS
        if (ROOT / path).exists()
    }
    result = build_public_binding_patch(
        _binding("requester", 123, "aurora-catalog-requester", b"REQUESTER"),
        _binding("auditor", 456, "aurora-catalog-auditor", b"AUDITOR"),
        _authority(),
        tree,
    )
    assert result.changed_paths == EXPECTED_PATHS
    joined = b"".join(result.documents.values())
    assert b"PRIVATE KEY" not in joined
    actors = json.loads(result.documents["config/catalog_controller_actors_v1.json"])
    assert actors["production_enabled"] is False
    assert actors["request_actors"] == ["aurora-catalog-requester[bot]"]
    auditor = json.loads(result.documents["config/catalog_github_auditor_v1.json"])
    assert auditor["expected_app_slug"] == "aurora-catalog-auditor"


def test_authority_anchor_is_unique_and_reused() -> None:
    authority = _authority()
    assert create_or_verify_authority_anchor([authority]) == authority
    with pytest.raises(ValueError, match="MULTIPLE_ANCHORS"):
        create_or_verify_authority_anchor([authority, {**authority, "number": 124}])
    with pytest.raises(ValueError, match="AUTHORITY_ANCHOR_MISSING"):
        create_or_verify_authority_anchor([])


def test_binding_rejects_private_or_unexpected_tree_material() -> None:
    tree = {
        "config/catalog_controller_actors_v1.json": b'{"private_key":"no"}',
    }
    with pytest.raises(ValueError, match="PRIVATE_MATERIAL_FORBIDDEN"):
        build_public_binding_patch(
            _binding("requester", 123, "aurora-catalog-requester", b"REQUESTER"),
            _binding("auditor", 456, "aurora-catalog-auditor", b"AUDITOR"),
            _authority(),
            tree,
        )
