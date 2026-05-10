"""R176 -- Bounded specialist agent roles.

Each role names which sections of an :class:`aurora.reporting.evidence_pack.EvidencePack`
it may read. The mapping is hard-coded and frozen so an operator (or a
prompt-injected LLM) cannot widen the surface at runtime.

Roles are reviewers only:

* They never authorise broker orders.
* They never widen scope past the evidence sections enumerated below.
* They cannot read locked OOS / FORWARD data because the underlying
  :class:`EvidencePack` only carries what was approved into the pack.

The capability set is intentionally narrow: every role gets the
``policy_hash``/``snapshot_hash`` provenance pair plus the small subset
of pack fields its job requires. Role-to-section mapping lives here so
tests can introspect it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import FrozenSet, Mapping


class AgentRole(str, Enum):
    """The six bounded reviewer roles defined by R176."""

    DATA_QUALITY_REVIEWER = "data_quality_reviewer"
    STRATEGY_SUMMARY_REVIEWER = "strategy_summary_reviewer"
    RISK_REVIEWER = "risk_reviewer"
    EXECUTION_COST_REVIEWER = "execution_cost_reviewer"
    REGIME_REVIEWER = "regime_reviewer"
    REPORT_EXPLAINER = "report_explainer"


# All evidence sections that may ever be exposed to a reviewer.
# Anything not in this universe is forbidden by construction.
EVIDENCE_SECTIONS: FrozenSet[str] = frozenset({
    "pack_id",
    "pack_kind",
    "subject_id",
    "generated_at",
    "policy_hash",
    "snapshot_hash",
    "pack_hash",
    "manifest",
    "requested_vs_persisted",
    "provider_provenance",
    "data_contract_results",
    "quality_decisions",
    "identity_status",
    "corporate_action_status",
    "snapshots",
    "validation_report",
    "benchmark_pack",
    "research_ledger_excerpt",
    "warnings",
    "overrides",
    "reproduce_commands",
    "artefacts",
})

# Provenance fields every role needs to cite outputs.
_PROVENANCE_CORE: FrozenSet[str] = frozenset({
    "pack_id",
    "pack_kind",
    "subject_id",
    "policy_hash",
    "snapshot_hash",
    "pack_hash",
})

# Hard-coded role -> allowed sections mapping.
_ROLE_CAPABILITIES: Mapping[AgentRole, FrozenSet[str]] = MappingProxyType({
    AgentRole.DATA_QUALITY_REVIEWER: frozenset(_PROVENANCE_CORE | {
        "manifest",
        "requested_vs_persisted",
        "provider_provenance",
        "data_contract_results",
        "quality_decisions",
        "identity_status",
        "corporate_action_status",
        "warnings",
        "overrides",
    }),
    AgentRole.STRATEGY_SUMMARY_REVIEWER: frozenset(_PROVENANCE_CORE | {
        "manifest",
        "validation_report",
        "benchmark_pack",
        "research_ledger_excerpt",
        "warnings",
    }),
    AgentRole.RISK_REVIEWER: frozenset(_PROVENANCE_CORE | {
        "validation_report",
        "benchmark_pack",
        "warnings",
        "overrides",
    }),
    AgentRole.EXECUTION_COST_REVIEWER: frozenset(_PROVENANCE_CORE | {
        "validation_report",
        "benchmark_pack",
        "warnings",
    }),
    AgentRole.REGIME_REVIEWER: frozenset(_PROVENANCE_CORE | {
        "manifest",
        "validation_report",
        "benchmark_pack",
        "warnings",
    }),
    AgentRole.REPORT_EXPLAINER: frozenset(_PROVENANCE_CORE | {
        "manifest",
        "requested_vs_persisted",
        "validation_report",
        "benchmark_pack",
        "warnings",
        "overrides",
        "reproduce_commands",
    }),
})


@dataclass(frozen=True)
class AgentCapability:
    """Frozen capability descriptor for a role.

    ``allowed_sections`` is a frozenset of evidence-pack field names a
    role may read. The reviewer surface is intentionally read-only:
    there are no write/promote/submit capabilities.
    """

    role: AgentRole
    allowed_sections: FrozenSet[str]

    def can_read(self, section: str) -> bool:
        """Return True iff ``section`` is in the role's allowlist."""
        return section in self.allowed_sections


class AgentRoleRegistry:
    """Frozen registry of role capabilities.

    Constructed once at import time. There is no public mutator; trying
    to add or replace a capability raises :class:`TypeError` because the
    underlying mapping is a :class:`types.MappingProxyType`.
    """

    def __init__(self) -> None:
        self._caps: Mapping[AgentRole, AgentCapability] = MappingProxyType({
            role: AgentCapability(role=role, allowed_sections=sections)
            for role, sections in _ROLE_CAPABILITIES.items()
        })

    def get(self, role: AgentRole) -> AgentCapability:
        """Return the capability for ``role`` or raise :class:`KeyError`.

        Construction with an unknown role string is impossible because
        :class:`AgentRole` is a closed enum: ``AgentRole("foo")`` raises
        ``ValueError`` before this method is ever called.
        """
        try:
            return self._caps[role]
        except KeyError as exc:
            raise KeyError(f"unknown agent role: {role!r}") from exc

    def roles(self) -> FrozenSet[AgentRole]:
        """All registered roles."""
        return frozenset(self._caps.keys())

    def __contains__(self, role: object) -> bool:
        return role in self._caps


# A singleton registry. The whole point is that a role's capability set
# is fixed at import time; tests can verify by identity.
ROLE_REGISTRY = AgentRoleRegistry()


__all__ = [
    "AgentRole",
    "AgentCapability",
    "AgentRoleRegistry",
    "ROLE_REGISTRY",
    "EVIDENCE_SECTIONS",
]
