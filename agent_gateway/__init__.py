"""Secure agent gateway for non-human actors.

P1.A architectural hardening: any LLM, scheduled job, external API, or
other automated actor that wants to query, propose, or execute against
QuantForge must hold a scoped, signed token. Live trading requires
explicit ceremony plus a human counter-signature. Every action is
audit-logged in append-only hash-chained JSONL.

Stage / commit / push pattern:

* ``stage(token, action)`` validates the request and records an audit
  entry. Returns a :class:`StagedAction`.
* ``commit(staged_id, human_signature)`` requires a counter-signature
  from a human operator. For paper actions the policy may allow
  auto-commit; live actions always require a fresh human sig.
* ``push(committed)`` is the only call that actually executes.
"""
from __future__ import annotations

from quantforge.agent_gateway.tokens import (
    AgentToken,
    TokenScope,
    issue_token,
    sign_payload,
)
from quantforge.agent_gateway.audit import AgentAudit, AgentAuditConfig
from quantforge.agent_gateway.gateway import (
    ActionRequest,
    ActionStatus,
    AgentGateway,
    CommittedAction,
    ExecutionResult,
    GatewayPolicy,
    StagedAction,
)


__all__ = [
    "AgentGateway",
    "AgentToken",
    "TokenScope",
    "ActionRequest",
    "ActionStatus",
    "GatewayPolicy",
    "StagedAction",
    "CommittedAction",
    "ExecutionResult",
    "AgentAudit",
    "AgentAuditConfig",
    "issue_token",
    "sign_payload",
]
