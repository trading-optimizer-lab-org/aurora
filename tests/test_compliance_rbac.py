"""Tests for aurora.compliance.rbac."""
from __future__ import annotations

import pytest

from aurora.compliance.rbac import RBACConfig, RBACEngine


@pytest.fixture
def engine() -> RBACEngine:
    e = RBACEngine()
    e.add_role("trader", ["trades:read", "trades:execute"])
    e.add_role("compliance", ["audit:read", "trades:read"])
    e.add_role("admin", ["*"])
    return e


def test_assign_role_grants_permissions(engine):
    engine.assign_role("alice", "trader")
    assert engine.is_allowed("alice", "trades:read") is True
    assert engine.is_allowed("alice", "trades:execute") is True


def test_unassigned_user_denied_by_default(engine):
    assert engine.is_allowed("nobody", "trades:read") is False


def test_unassigned_user_allowed_when_default_allow():
    e = RBACEngine(RBACConfig(deny_by_default=False))
    assert e.is_allowed("anybody", "anything") is True


def test_user_outside_role_denied(engine):
    engine.assign_role("alice", "trader")
    assert engine.is_allowed("alice", "audit:read") is False


def test_admin_wildcard_grants_all(engine):
    engine.assign_role("root", "admin")
    assert engine.is_allowed("root", "trades:read") is True
    assert engine.is_allowed("root", "anything:goes") is True


def test_revoke_permission_blocks_access(engine):
    engine.assign_role("alice", "trader")
    engine.revoke_permission("trader", "trades:execute")
    assert engine.is_allowed("alice", "trades:execute") is False


def test_unassign_role_blocks_access(engine):
    engine.assign_role("alice", "trader")
    engine.unassign_role("alice", "trader")
    assert engine.is_allowed("alice", "trades:read") is False


def test_permissions_of_unions_roles(engine):
    engine.assign_role("bob", "trader")
    engine.assign_role("bob", "compliance")
    perms = engine.permissions_of("bob")
    assert "trades:read" in perms
    assert "trades:execute" in perms
    assert "audit:read" in perms


def test_roles_of_returns_assignments(engine):
    engine.assign_role("alice", "trader")
    engine.assign_role("alice", "compliance")
    assert engine.roles_of("alice") == {"trader", "compliance"}


def test_case_insensitive_default(engine):
    engine.assign_role("ALICE", "TRADER")
    assert engine.is_allowed("alice", "trades:read") is True
    assert engine.is_allowed("ALICE", "TRADES:READ") is True


def test_case_sensitive_when_configured():
    e = RBACEngine(RBACConfig(case_insensitive=False))
    e.add_role("Trader", ["trades:read"])
    e.assign_role("alice", "Trader")
    assert e.is_allowed("alice", "trades:read") is True
    assert e.is_allowed("alice", "TRADES:READ") is False


def test_grant_permission_creates_role():
    e = RBACEngine()
    e.grant_permission("new_role", "thing:do")
    e.assign_role("u", "new_role")
    assert e.is_allowed("u", "thing:do") is True
