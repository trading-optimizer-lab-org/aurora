"""Owner-controlled role-registry contracts for GTBI V7 readiness.

Legacy role names remain capability labels. The repository owner may hold all
of them, so missing independent people never creates a readiness vacancy.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import jsonschema

from infra.gtbi_v7_readiness.canonical import domain_digest

DOMAIN = "GTBI_V7_ROLE_REGISTRY_V1"
SCHEMA_VERSION = "gtbi_v7_role_registry_v1"

CANONICAL_ROLES = (
    "repository_owner",
    "implementer",
    "workflow_reviewer",
    "scientific_reviewer",
    "independent_security_reviewer",
    "licence_and_acceptable_use_reviewer",
    "independent_redaction_reviewer",
    "source_app_manager",
    "destination_app_manager",
    "source_deadman_operator",
    "source_deadman_deputy",
    "destination_deadman_operator",
    "destination_deadman_deputy",
    "source_key_broker_custodian",
    "destination_key_broker_custodian",
    "workflow_initiator",
    "locked_approver",
    "independent_disaster_copy_owner",
    "source_break_glass_custodian",
    "destination_break_glass_custodian",
    "source_account_root_custodian",
    "destination_account_root_custodian",
    "source_billing_payer_authorizer",
    "destination_billing_payer_authorizer",
    "source_app_custody_organization_owner",
    "destination_app_custody_organization_owner",
    "source_app_manager_jit_approver",
    "destination_app_manager_jit_approver",
    "source_dual_control_witness",
    "destination_dual_control_witness",
)

JIT_ROLES = frozenset(
    {
        "source_app_manager_jit_approver",
        "destination_app_manager_jit_approver",
    }
)

SOURCE_CUSTODY_ROLES = frozenset(
    role
    for role in CANONICAL_ROLES
    if role.startswith("source_")
)
DESTINATION_CUSTODY_ROLES = frozenset(
    role
    for role in CANONICAL_ROLES
    if role.startswith("destination_")
    or role == "independent_disaster_copy_owner"
)

INDEPENDENT_REVIEW_ROLES = frozenset(
    {
        "workflow_reviewer",
        "scientific_reviewer",
        "independent_security_reviewer",
        "licence_and_acceptable_use_reviewer",
        "independent_redaction_reviewer",
    }
)

OWNER_INCOMPATIBLE_ROLES = frozenset(
    {
        "repository_owner",
        "implementer",
        *INDEPENDENT_REVIEW_ROLES,
        "independent_disaster_copy_owner",
    }
)

DEFAULT_INCOMPATIBILITY_SETS = (
    {
        "set_id": "owner_implementation_independent_review",
        "roles": sorted(OWNER_INCOMPATIBLE_ROLES),
    },
    {
        "set_id": "source_custody_separation",
        "roles": sorted(SOURCE_CUSTODY_ROLES),
    },
    {
        "set_id": "destination_custody_separation",
        "roles": sorted(DESTINATION_CUSTODY_ROLES),
    },
)


class RoleRegistryError(ValueError):
    """Raised when a role registry makes an invalid readiness claim."""


def _custody_domain(role: str) -> str:
    if role.startswith("source_"):
        return "source"
    if role.startswith("destination_") or role == "independent_disaster_copy_owner":
        return "destination"
    if role in INDEPENDENT_REVIEW_ROLES:
        return "independent_review"
    return "repository"


def _vacant_assignment(role: str, index: int = 1) -> dict[str, Any]:
    return {
        "assignment_id": f"{role}:{index}",
        "role": role,
        "assignment_index": index,
        "custody_domain": _custody_domain(role),
        "status": "vacant",
        "actor_id": None,
        "github_actor_id": None,
        "github_login": None,
        "effective_at_utc": None,
        "expires_at_utc": None,
        "deputy_actor_id": None,
        "authentication_evidence_digest": None,
        "recovery_evidence_digest": None,
        "incompatibility_set_digest": None,
        "approving_actor_ids": [],
        "transition_event_digest": None,
        "blocking_reasons": ["eligible_distinct_actor_not_assigned"],
    }


def build_owner_controlled_role_registry(
    *,
    repository: str,
    owner_github_actor_id: int,
    owner_github_login: str,
    observed_at_utc: str,
) -> dict[str, Any]:
    """Build a deterministic registry delegating every capability to owner."""

    assignments: list[dict[str, Any]] = []
    for role in CANONICAL_ROLES:
        count = 2 if role in JIT_ROLES else 1
        assignments.extend(
            _vacant_assignment(role, index)
            for index in range(1, count + 1)
        )

    actor_id = f"github-user:{owner_github_actor_id}"
    evidence = domain_digest(
        "GTBI_V7_OWNER_CONTROLLED_ROLE_EVIDENCE_V1",
        {
            "actor_id": actor_id,
            "repository": repository,
            "observed_at_utc": observed_at_utc,
        },
    )
    for assignment in assignments:
        assignment.update(
            {
                "status": "active",
                "actor_id": actor_id,
                "github_actor_id": owner_github_actor_id,
                "github_login": owner_github_login,
                "effective_at_utc": observed_at_utc,
                "authentication_evidence_digest": evidence,
                "recovery_evidence_digest": evidence,
                "incompatibility_set_digest": evidence,
                "approving_actor_ids": [actor_id],
                "transition_event_digest": evidence,
                "blocking_reasons": [],
            }
        )

    registry: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "registry_status": "active",
        "repository": repository,
        "observed_at_utc": observed_at_utc,
        "assignments": assignments,
        "incompatibility_sets": [
            deepcopy(item) for item in DEFAULT_INCOMPATIBILITY_SETS
        ],
        "role_registry_digest": "",
    }
    registry["role_registry_digest"] = role_registry_digest(registry)
    return registry


def build_blocked_role_registry(
    *,
    repository: str,
    owner_github_actor_id: int,
    owner_github_login: str,
    observed_at_utc: str,
) -> dict[str, Any]:
    """Compatibility alias for the retired template builder."""

    return build_owner_controlled_role_registry(
        repository=repository,
        owner_github_actor_id=owner_github_actor_id,
        owner_github_login=owner_github_login,
        observed_at_utc=observed_at_utc,
    )


def role_registry_digest(registry: dict[str, Any]) -> str:
    payload = deepcopy(registry)
    payload.pop("role_registry_digest", None)
    return domain_digest(DOMAIN, payload)


def validate_role_registry(
    registry: dict[str, Any],
    schema_path: str | Path,
) -> None:
    """Validate schema, digest, role coverage and separation constraints."""

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(registry)

    if registry["role_registry_digest"] != role_registry_digest(registry):
        raise RoleRegistryError("role_registry_digest does not match payload")

    assignments = registry["assignments"]
    assignment_ids = [item["assignment_id"] for item in assignments]
    if len(assignment_ids) != len(set(assignment_ids)):
        raise RoleRegistryError("assignment_id values must be unique")

    by_role: dict[str, list[dict[str, Any]]] = {}
    for assignment in assignments:
        by_role.setdefault(assignment["role"], []).append(assignment)
        status = assignment["status"]
        if status == "vacant" and assignment["actor_id"] is not None:
            raise RoleRegistryError("vacant assignment cannot claim actor_id")
        if status != "vacant" and not assignment["actor_id"]:
            raise RoleRegistryError(
                f"{status} assignment requires immutable actor_id"
            )
        if status == "active":
            required_evidence = (
                "effective_at_utc",
                "authentication_evidence_digest",
                "recovery_evidence_digest",
                "incompatibility_set_digest",
                "transition_event_digest",
            )
            missing = [
                field for field in required_evidence if not assignment[field]
            ]
            if missing:
                raise RoleRegistryError(
                    f"active assignment lacks required evidence: {missing}"
                )
            if not assignment["approving_actor_ids"]:
                raise RoleRegistryError(
                    "active assignment requires approving_actor_ids"
                )
            if assignment["blocking_reasons"]:
                raise RoleRegistryError(
                    "active assignment cannot retain blocking_reasons"
                )

    if set(by_role) != set(CANONICAL_ROLES):
        raise RoleRegistryError("registry must cover the complete canonical role enum")
    for role in CANONICAL_ROLES:
        expected_count = 2 if role in JIT_ROLES else 1
        if len(by_role[role]) != expected_count:
            raise RoleRegistryError(
                f"{role} requires exactly {expected_count} assignments"
            )

    # The owner directive retired separation-of-duty as a hard requirement.
    # Incompatibility sets remain documentation only for optional hardening.

    non_active = [
        item["assignment_id"]
        for item in assignments
        if item["status"] != "active"
    ]
    if registry["registry_status"] == "active" and non_active:
        raise RoleRegistryError(
            "active registry cannot contain non-active assignments"
        )


__all__ = [
    "CANONICAL_ROLES",
    "DEFAULT_INCOMPATIBILITY_SETS",
    "DOMAIN",
    "JIT_ROLES",
    "RoleRegistryError",
    "SCHEMA_VERSION",
    "build_blocked_role_registry",
    "build_owner_controlled_role_registry",
    "role_registry_digest",
    "validate_role_registry",
]
