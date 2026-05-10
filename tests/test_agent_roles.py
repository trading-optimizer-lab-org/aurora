"""R176 -- Tests for the bounded reviewer role registry."""
from __future__ import annotations

import pytest

from aurora.agent_gateway.agent_roles import (
    AgentCapability,
    AgentRole,
    AgentRoleRegistry,
    EVIDENCE_SECTIONS,
    ROLE_REGISTRY,
)


def test_six_roles_enumerated():
    """The roadmap names six specialist roles. The enum exposes exactly six."""
    members = set(AgentRole)
    expected = {
        AgentRole.DATA_QUALITY_REVIEWER,
        AgentRole.STRATEGY_SUMMARY_REVIEWER,
        AgentRole.RISK_REVIEWER,
        AgentRole.EXECUTION_COST_REVIEWER,
        AgentRole.REGIME_REVIEWER,
        AgentRole.REPORT_EXPLAINER,
    }
    assert members == expected


def test_unknown_role_string_cannot_be_constructed():
    """An attacker cannot mint a new role string at runtime."""
    with pytest.raises(ValueError):
        AgentRole("super_admin_reviewer")


def test_registry_returns_capability_for_each_role():
    """The singleton registry is populated for all six roles."""
    for role in AgentRole:
        cap = ROLE_REGISTRY.get(role)
        assert isinstance(cap, AgentCapability)
        assert cap.role is role
        assert cap.allowed_sections, (
            f"role {role.value} must have at least one allowed section"
        )


def test_allowed_sections_are_a_subset_of_known_sections():
    """No role can read a section that is not in the canonical universe."""
    for role in AgentRole:
        cap = ROLE_REGISTRY.get(role)
        unknown = cap.allowed_sections - EVIDENCE_SECTIONS
        assert not unknown, (
            f"role {role.value} declares unknown sections {unknown}"
        )


def test_capabilities_are_frozen_after_construction():
    """The registry's underlying mapping is read-only -- mutation raises."""
    reg = AgentRoleRegistry()
    # The internal dict is a MappingProxyType; assignment must fail.
    with pytest.raises(TypeError):
        reg._caps[AgentRole.RISK_REVIEWER] = AgentCapability(  # type: ignore[index]
            role=AgentRole.RISK_REVIEWER,
            allowed_sections=frozenset({"validation_report"}),
        )


def test_capability_allowed_sections_are_frozenset():
    """Allowed sections are a frozenset so callers cannot mutate them."""
    cap = ROLE_REGISTRY.get(AgentRole.DATA_QUALITY_REVIEWER)
    assert isinstance(cap.allowed_sections, frozenset)
    with pytest.raises(AttributeError):
        cap.allowed_sections.add("validation_report")  # type: ignore[attr-defined]


def test_role_capability_does_not_expose_broker_methods():
    """No reviewer surface should expose order/promote methods.

    This is the structural promise the roadmap demands: reviewers may
    never submit, cancel, modify or approve broker orders.
    """
    cap = ROLE_REGISTRY.get(AgentRole.RISK_REVIEWER)
    forbidden = (
        "submit_order", "cancel_order", "modify_order", "approve",
        "promote", "go_live",
    )
    surface = set(dir(cap))
    for name in forbidden:
        assert name not in surface, (
            f"AgentCapability must not expose {name!r}"
        )
