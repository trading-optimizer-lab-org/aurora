"""Per-role caps for the agent gateway (R43).

The gateway today treats every actor symmetrically. This module ships
the minimum role schema for a multi-operator team:

- ``junior_ops``: paper-only. Can submit research, run paper backtests,
  inspect audit. Cannot promote, kill-switch, or edit policy.
- ``senior_ops``: paper + live. Can countersign promotions, place live
  orders within rate limits, hit the kill switch.
- ``admin``: senior_ops + policy / key rotation / RBAC management.

Built on the existing :class:`compliance.rbac.RBACEngine` skeleton so
the storage / persistence side is reused.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from quantforge.compliance.rbac import RBACConfig, RBACEngine


# Permission tokens used by the gateway. resource:action grammar.
PAPER_TRADE = "trade:paper"
LIVE_TRADE = "trade:live"
PROMOTE_STRATEGY = "strategy:promote"
ARCHIVE_STRATEGY = "strategy:archive"
RUN_BACKTEST = "backtest:run"
RUN_RESEARCH = "research:submit"
READ_AUDIT = "audit:read"
KILL_SWITCH = "live:kill"
ROTATE_KEYS = "keys:rotate"
EDIT_POLICY = "policy:edit"
MANAGE_RBAC = "rbac:manage"


_ROLE_PERMISSIONS = {
    "junior_ops": {
        PAPER_TRADE,
        RUN_BACKTEST,
        RUN_RESEARCH,
        READ_AUDIT,
    },
    "senior_ops": {
        PAPER_TRADE,
        LIVE_TRADE,
        PROMOTE_STRATEGY,
        ARCHIVE_STRATEGY,
        RUN_BACKTEST,
        RUN_RESEARCH,
        READ_AUDIT,
        KILL_SWITCH,
    },
    "admin": {
        PAPER_TRADE,
        LIVE_TRADE,
        PROMOTE_STRATEGY,
        ARCHIVE_STRATEGY,
        RUN_BACKTEST,
        RUN_RESEARCH,
        READ_AUDIT,
        KILL_SWITCH,
        ROTATE_KEYS,
        EDIT_POLICY,
        MANAGE_RBAC,
    },
}


@dataclass
class GatewayRBAC:
    """RBAC engine pre-loaded with the standard gateway role schema."""

    engine: RBACEngine

    @classmethod
    def standard(cls) -> "GatewayRBAC":
        engine = RBACEngine(RBACConfig(deny_by_default=True))
        for role, perms in _ROLE_PERMISSIONS.items():
            engine.add_role(role, perms)
        return cls(engine=engine)

    def assign(self, user: str, role: str) -> None:
        if role not in _ROLE_PERMISSIONS:
            raise KeyError(f"unknown role: {role}")
        self.engine.assign_role(user, role)

    def authorise(self, user: str, permission: str) -> bool:
        return self.engine.is_allowed(user, permission)

    def require(self, user: str, permission: str) -> None:
        if not self.authorise(user, permission):
            raise PermissionError(
                f"user '{user}' missing permission '{permission}'"
            )

    def list_roles(self) -> List[str]:
        return list(_ROLE_PERMISSIONS.keys())

    def permissions_for(self, role: str) -> set[str]:
        if role not in _ROLE_PERMISSIONS:
            raise KeyError(f"unknown role: {role}")
        return set(_ROLE_PERMISSIONS[role])


__all__ = [
    "GatewayRBAC",
    "PAPER_TRADE",
    "LIVE_TRADE",
    "PROMOTE_STRATEGY",
    "ARCHIVE_STRATEGY",
    "RUN_BACKTEST",
    "RUN_RESEARCH",
    "READ_AUDIT",
    "KILL_SWITCH",
    "ROTATE_KEYS",
    "EDIT_POLICY",
    "MANAGE_RBAC",
]
