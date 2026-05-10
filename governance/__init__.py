"""Governance: solo-operator approvals, risk records, lifecycle.

Adapted from the Candidate D maker-checker workflow for AURORA's
single-operator model. The roles are minimal: the operator drafts the
record, reviews it themselves, and approves promotion stage by stage.
No second human is required by default; multi-reviewer fields exist for
forward compatibility but are off the critical path.
"""
from __future__ import annotations

from aurora.governance.approvals import (
    LifecycleStage,
    PromotionBlocked,
    StrategyRiskRecord,
    StrategyRiskRegistry,
    StrategyOverride,
)

__all__ = [
    "LifecycleStage",
    "PromotionBlocked",
    "StrategyOverride",
    "StrategyRiskRecord",
    "StrategyRiskRegistry",
]
