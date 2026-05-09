"""Governance package: strategy risk register, lifecycle, and approvals.

Public re-exports for ``from aurora.governance import ...``:

* :class:`StrategyRiskRecord`, :class:`RiskRegister`, :class:`ApprovalStatus`
  -- model-risk records and JSONL persistence.
* :class:`LifecycleState`, :class:`LifecycleTransition`,
  :class:`LifecycleError`, :func:`transition`, :func:`legal_transitions`
  -- explicit lifecycle state machine.
* :class:`MakerCheckerFlow`, :class:`ApprovalEvent`,
  :class:`ApprovalError`, :func:`gate_promotion` -- maker-checker
  workflow and promotion gate.

This is Candidate D / Phase 6 of the QuantForge roadmap.
"""
from aurora.governance.approvals import (
    ApprovalError,
    ApprovalEvent,
    MakerCheckerFlow,
    gate_promotion,
)
from aurora.governance.lifecycle import (
    LifecycleError,
    LifecycleState,
    LifecycleTransition,
    legal_transitions,
    transition,
)
from aurora.governance.risk_register import (
    ApprovalStatus,
    RiskRegister,
    StrategyRiskRecord,
    risk_register_path,
)

__all__ = [
    "ApprovalError",
    "ApprovalEvent",
    "ApprovalStatus",
    "LifecycleError",
    "LifecycleState",
    "LifecycleTransition",
    "MakerCheckerFlow",
    "RiskRegister",
    "StrategyRiskRecord",
    "gate_promotion",
    "legal_transitions",
    "risk_register_path",
    "transition",
]
