"""Tests for the owner-controlled GTBI V7 role registry."""
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
from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_g1b_role_contract import (
    MANIFEST,
    RECEIPT,
    REGISTRY,
    build_manifest,
    build_receipt,
    build_registry,
)
from scripts.generate_gtbi_v7_role_registry_template import generate

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/plans/gtbi-v7-master-plan.md"
SCHEMA = ROOT / "config/gtbi/schemas/readiness/role_registry_v1.schema.json"
FIXTURE = (
    ROOT
    / "config/gtbi/fixtures/v7/governance/role_registry_v1.owner_controlled.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _activate(assignment: dict, actor_suffix: str) -> None:
    assignment.update(
        {
            "status": "active",
            "actor_id": f"test-actor:{actor_suffix}",
            "github_actor_id": None,
            "github_login": None,
            "effective_at_utc": "2026-07-29T00:00:00Z",
            "authentication_evidence_digest": "sha256:" + ("1" * 64),
            "recovery_evidence_digest": "sha256:" + ("2" * 64),
            "incompatibility_set_digest": "sha256:" + ("3" * 64),
            "approving_actor_ids": ["test-approver:1"],
            "transition_event_digest": "sha256:" + ("4" * 64),
            "blocking_reasons": [],
        }
    )


def test_role_enum_matches_master_plan_normative_block() -> None:
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("repository_owner\n", text.index("The canonical role enum"))
    end = text.index("\n```", start)
    plan_roles = tuple(text[start:end].splitlines())

    assert plan_roles == CANONICAL_ROLES


def test_owner_controlled_fixture_is_active_and_has_no_vacancies() -> None:
    registry = _fixture()
    validate_role_registry(registry, SCHEMA)

    vacant = [
        item for item in registry["assignments"] if item["status"] == "vacant"
    ]
    assert registry["registry_status"] == "active"
    assert not vacant
    assert {item["github_actor_id"] for item in registry["assignments"]} == {
        271768688
    }
    assert {item["github_login"] for item in registry["assignments"]} == {
        "gomez5757"
    }


def test_active_registry_cannot_hide_vacancies() -> None:
    registry = _fixture()
    registry["assignments"][0]["status"] = "observed_unverified"
    registry["registry_status"] = "active"
    registry["role_registry_digest"] = role_registry_digest(registry)

    with pytest.raises(RoleRegistryError, match="non-active assignments"):
        validate_role_registry(registry, SCHEMA)


def test_active_assignment_requires_current_evidence() -> None:
    registry = _fixture()
    owner = next(
        item
        for item in registry["assignments"]
        if item["role"] == "repository_owner"
    )
    owner["authentication_evidence_digest"] = None
    registry["role_registry_digest"] = role_registry_digest(registry)

    with pytest.raises(RoleRegistryError, match="required evidence"):
        validate_role_registry(registry, SCHEMA)


def test_same_owner_can_hold_legacy_capability_roles() -> None:
    registry = _fixture()
    owner = next(
        item for item in registry["assignments"]
        if item["role"] == "repository_owner"
    )
    implementer = next(
        item for item in registry["assignments"]
        if item["role"] == "implementer"
    )
    _activate(owner, "same")
    _activate(implementer, "same")
    registry["role_registry_digest"] = role_registry_digest(registry)

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
    assert b"\r\n" not in output.read_bytes()


def test_owner_registry_is_authoritative_for_current_model() -> None:
    registry = _fixture()
    assert registry["registry_status"] == "active"


def test_operational_registry_matches_owner_controlled_fixture() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert REGISTRY.read_bytes() == canonical_bytes(registry) + b"\n"
    assert registry == build_registry()
    assert registry == _fixture()
    validate_role_registry(registry, SCHEMA)
    assert all(item["status"] == "active" for item in registry["assignments"])
    assert {item["actor_id"] for item in registry["assignments"]} == {
        "github-user:271768688"
    }


def test_g1b_role_registry_receipt_is_exact_and_owner_controlled() -> None:
    registry = build_registry()
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert receipt == build_receipt(registry)
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_G1B_ROLE_REGISTRY_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["registry"]["vacant_assignment_count"] == 0
    assert receipt["registry"]["unique_actor_ids"] == [
        "github-user:271768688"
    ]
    assert receipt["verified_properties"] == {
        "all_legacy_capability_labels_assigned": True,
        "all_assignments_active": True,
        "additional_people_required": False,
        "incompatibility_sets_enforced": False,
        "incompatibility_sets_documentation_only": True,
        "locked_data_accessed": False,
        "owner_controlled": True,
        "scientific_work_performed": False,
    }


def test_g1b_transition_manifest_closes_only_role_registry_task() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert manifest == build_manifest()
    validate_transition_manifest(manifest)
    assert [action["task_id"] for action in manifest["task_actions"]] == [
        "PREV7-0201"
    ]
    assert manifest["gate_actions"] == [
        {
            "gate_id": "G1B",
            "target_status": "green",
            "selected_branch_id_or_null": None,
            "inventory_snapshot_digest": manifest["gate_actions"][0][
                "inventory_snapshot_digest"
            ],
            "evidence_bundle_digest": manifest["gate_actions"][0][
                "evidence_bundle_digest"
            ],
        }
    ]
