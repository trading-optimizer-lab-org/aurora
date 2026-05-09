"""Tool allowlist for research agents (Phase 7 / Candidate G).

Agents in this layer are explanation / commentary actors only. They may
not submit broker orders, modify code, edit the roadmap, read secrets,
or read locked OOS partitions. The allowlist below is the only source
of truth for what each role may call; everything else fails closed via
:func:`assert_tool_allowed`.

The :class:`AgentRole` enum is defined in
:mod:`quantforge.agent_gateway.research_agents`; we import it lazily
with ``from __future__ import annotations`` to avoid a cycle.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, FrozenSet

from quantforge.agent_gateway.evidence_pack import ForbiddenAccessError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from quantforge.agent_gateway.research_agents import AgentRole


# Tools that are ALWAYS denied, regardless of role. These map to broker
# actions, secrets, locked-data reads, promotion approvals or roadmap edits
# - none of which an explanation-layer agent is allowed to invoke.
FORBIDDEN_TOOLS: FrozenSet[str] = frozenset(
    {
        "submit_order",
        "cancel_order",
        "modify_order",
        "read_secret",
        "read_oos_locked",
        "approve_promotion",
        "edit_roadmap",
    }
)


def _build_allowlist() -> "dict[AgentRole, FrozenSet[str]]":
    """Lazy-build the role -> allowed-tool map.

    Defined as a function so the import of :class:`AgentRole` happens after
    :mod:`research_agents` finishes its own module-init when callers ask
    for the allowlist. The first call materialises the map and caches it
    on the function as ``_cached``.
    """
    cached = getattr(_build_allowlist, "_cached", None)
    if cached is not None:
        return cached

    from quantforge.agent_gateway.research_agents import AgentRole as _AgentRole

    common_read_tools: FrozenSet[str] = frozenset(
        {
            "read_evidence_pack",
            "read_validation_report",
            "read_audit_reference",
            "read_strategy_summary",
        }
    )

    allowlist: "dict[_AgentRole, FrozenSet[str]]" = {
        _AgentRole.DATA_QUALITY: common_read_tools | frozenset(
            {"read_data_contract", "read_snapshot_metadata"}
        ),
        _AgentRole.STRATEGY_SUMMARY: common_read_tools | frozenset(
            {"read_strategy_spec", "read_research_note"}
        ),
        _AgentRole.RISK: common_read_tools | frozenset(
            {"read_risk_report", "read_drawdown_metrics"}
        ),
        _AgentRole.EXECUTION_COST: common_read_tools | frozenset(
            {"read_cost_report", "read_slippage_metrics"}
        ),
        _AgentRole.REGIME: common_read_tools | frozenset(
            {"read_regime_report", "read_macro_features"}
        ),
        _AgentRole.REPORT_EXPLAINER: common_read_tools | frozenset(
            {"read_explanation_pack", "read_research_archive"}
        ),
    }

    _build_allowlist._cached = allowlist  # type: ignore[attr-defined]
    return allowlist


def is_tool_allowed(role: "AgentRole", tool_name: str) -> bool:
    """Return ``True`` only if ``role`` may invoke ``tool_name``.

    The forbidden list always wins: a tool name in :data:`FORBIDDEN_TOOLS`
    is denied even if a role mistakenly lists it.
    """
    if tool_name in FORBIDDEN_TOOLS:
        return False
    allowlist = _build_allowlist()
    allowed = allowlist.get(role, frozenset())
    return tool_name in allowed


def assert_tool_allowed(role: "AgentRole", tool_name: str) -> None:
    """Raise :class:`ForbiddenAccessError` if ``role`` may not call ``tool_name``."""
    if not is_tool_allowed(role, tool_name):
        raise ForbiddenAccessError(
            f"role {role!r} is not allowed to invoke tool {tool_name!r}"
        )


# Public attribute: the allowlist itself. Lazy-computed on first access via
# ``__getattr__`` so importers can write
# ``from quantforge.agent_gateway.agent_roles import AGENT_TOOL_ALLOWLIST``.
def __getattr__(name: str) -> object:
    if name == "AGENT_TOOL_ALLOWLIST":
        return _build_allowlist()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AGENT_TOOL_ALLOWLIST",
    "FORBIDDEN_TOOLS",
    "is_tool_allowed",
    "assert_tool_allowed",
]
