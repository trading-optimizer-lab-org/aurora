"""Role-based access control engine.

Implements a minimal RBAC matrix: subjects (users) hold one or more roles,
roles map to a permission set. Permissions are simple string tokens
(typically ``resource:action`` like ``"trades:read"``).

The engine is intentionally storage-agnostic. Persistence and user
management live in higher-level orchestration code. This module provides
the in-memory authorization decision logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class RBACConfig:
    """Static config for the RBAC engine.

    Attributes:
        deny_by_default: when True, missing role grants no permissions.
        wildcard_token: token granting all permissions (use sparingly).
        case_insensitive: if True, role and permission strings are folded.
    """
    deny_by_default: bool = True
    wildcard_token: str = "*"
    case_insensitive: bool = True
    extra_metadata: tuple[str, ...] = field(default_factory=tuple)


class RBACEngine:
    """In-memory RBAC matrix and authorization checks."""

    def __init__(self, config: Optional[RBACConfig] = None) -> None:
        self.config = config or RBACConfig()
        self._roles: dict[str, set[str]] = {}
        self._user_roles: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Public API - role / permission management
    # ------------------------------------------------------------------
    def add_role(self, role: str, permissions: Iterable[str]) -> None:
        """Define a role with the given permission set."""
        self._roles[self._fold(role)] = {self._fold(p) for p in permissions}

    def grant_permission(self, role: str, permission: str) -> None:
        """Add ``permission`` to ``role``. Creates role if missing."""
        r = self._fold(role)
        self._roles.setdefault(r, set()).add(self._fold(permission))

    def revoke_permission(self, role: str, permission: str) -> None:
        """Remove ``permission`` from ``role`` if present."""
        r = self._fold(role)
        self._roles.get(r, set()).discard(self._fold(permission))

    def assign_role(self, user: str, role: str) -> None:
        """Assign ``role`` to ``user``. Creates the assignment if new."""
        self._user_roles.setdefault(self._fold(user), set()).add(self._fold(role))

    def unassign_role(self, user: str, role: str) -> None:
        """Remove ``role`` from ``user`` if present."""
        self._user_roles.get(self._fold(user), set()).discard(self._fold(role))

    # ------------------------------------------------------------------
    # Public API - authorization
    # ------------------------------------------------------------------
    def is_allowed(self, user: str, permission: str) -> bool:
        """Return True iff ``user`` holds ``permission`` via any role."""
        u = self._fold(user)
        p = self._fold(permission)
        wc = self._fold(self.config.wildcard_token)
        roles = self._user_roles.get(u, set())
        if not roles:
            return False if self.config.deny_by_default else True
        for role in roles:
            perms = self._roles.get(role, set())
            if wc in perms or p in perms:
                return True
        return False

    def permissions_of(self, user: str) -> set[str]:
        """Return the union of permissions across all of ``user``'s roles."""
        u = self._fold(user)
        out: set[str] = set()
        for role in self._user_roles.get(u, set()):
            out |= self._roles.get(role, set())
        return out

    def roles_of(self, user: str) -> set[str]:
        """Return the set of roles assigned to ``user``."""
        return set(self._user_roles.get(self._fold(user), set()))

    def all_roles(self) -> dict[str, set[str]]:
        """Return a copy of the role -> permission mapping."""
        return {r: set(p) for r, p in self._roles.items()}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _fold(self, value: str) -> str:
        return value.lower() if self.config.case_insensitive else value
