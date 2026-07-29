"""Tests for the non-fabricated GTBI V7 role-registry template."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from infra.gtbi_v7_readiness.roles import (
    CANONICAL_ROLES,
    RoleRegistryError,
    role_registry_digest,
    validate_role_registry,
)
from scripts.generate_gtbi_v7_role_registry_template import generate

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/plans/gtbi-v7-master-plan.md"
SCHEMA = ROOT / "config/gtbi/schemas/readiness/role_registry_v1.schema.json"
FIXTURE = (
    ROOT
    / "config/gtbi/fixtures/v7/governance/role_registry_v1.blocked.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_role_enum_matches_master_plan_normative_block() -> None:
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("repository_owner\n", text.index("The canonical role enum"))
    end = text.index("\n```", start)
    plan_roles = tuple(text[start:end].splitlines())

    assert plan_roles == CANONICAL_ROLES


def test_blocked_fixture_is_valid_and_does_not_invent_actors() -> None:
    registry = _fixture()
    validate_role_registry(registry, SCHEMA)

    active = [
        item for item in registry["assignments"] if item["status"] == "active"
    ]
    vacant = [
        item for item in registry["assignments"] if item["status"] == "vacant"
    ]
    assert registry["registry_status"] == "blocked_vacancies"
    assert len(active) == 1
    assert active[0]["role"] == "repository_owner"
    assert active[0]["github_actor_id"] == 271768688
    assert len(vacant) == 31
    assert all(item["actor_id"] is None for item in vacant)


def test_active_registry_cannot_hide_vacancies() -> None:
    registry = _fixture()
    registry["registry_status"] = "active"
    registry["role_registry_digest"] = role_registry_digest(registry)

    with pytest.raises(RoleRegistryError, match="cannot contain vacancies"):
        validate_role_registry(registry, SCHEMA)


def test_same_actor_cannot_hold_incompatible_active_roles() -> None:
    registry = _fixture()
    owner = next(
        item for item in registry["assignments"]
        if item["role"] == "repository_owner"
    )
    implementer = next(
        item for item in registry["assignments"]
        if item["role"] == "implementer"
    )
    implementer.update(
        {
            "status": "active",
            "actor_id": owner["actor_id"],
            "github_actor_id": owner["github_actor_id"],
            "github_login": owner["github_login"],
            "effective_at_utc": owner["effective_at_utc"],
            "blocking_reasons": [],
        }
    )
    registry["role_registry_digest"] = role_registry_digest(registry)

    with pytest.raises(RoleRegistryError, match="incompatible active"):
        validate_role_registry(registry, SCHEMA)


def test_tampered_registry_digest_is_rejected() -> None:
    registry = deepcopy(_fixture())
    registry["repository"] = "someone/else"

    with pytest.raises(RoleRegistryError, match="digest"):
        validate_role_registry(registry, SCHEMA)


def test_checked_fixture_matches_deterministic_generator(tmp_path: Path) -> None:
    output = tmp_path / "role_registry.json"
    generated = generate(output_path=output)

    assert generated == _fixture()
    assert json.loads(output.read_text(encoding="utf-8")) == generated


def test_no_authoritative_registry_is_claimed_before_real_assignments() -> None:
    assert not (
        ROOT / "config/gtbi/governance/role_registry.json"
    ).exists()
