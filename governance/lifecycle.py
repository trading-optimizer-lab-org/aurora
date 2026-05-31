"""Strategy lifecycle state machine.

Strategies move through a small set of explicit states. The transition
graph below is the *only* legal set of edges; anything else raises
:class:`LifecycleError`. The graph is intentionally narrow so the
governance gate (see :mod:`aurora.governance.approvals`) can refuse
illegal moves before any consumer code touches a paper or live capital
path.

States (one record per strategy-version):

* ``DRAFT``         -- the spec exists but no work has started.
* ``RESEARCHING``   -- under active research; may still be rejected.
* ``REJECTED``      -- explicitly rejected; terminal until a *new* record
  resurrects the strategy.
* ``QUARANTINED``   -- temporarily blocked (e.g. data-contract drift);
  must return to ``RESEARCHING`` to escape.
* ``VALIDATED``     -- passed the in-sample validation pipeline.
* ``OOS_APPROVED``  -- passed locked-OOS evaluation.
* ``SHADOW``        -- runs alongside the book without sending orders.
* ``PAPER``         -- runs against a paper broker.
* ``CANARY``        -- live with capped capital.
* ``LIVE``          -- live at full size.
* ``DEGRADED``      -- live but flagged; no scaling, may be retired.
* ``RETIRED``       -- decommissioned cleanly.
* ``GRAVEYARD``     -- hard-archived; no resurrection without a new
  record.

The transition table also records:

* ``required_approval`` -- the minimum
  :class:`~aurora.governance.risk_register.ApprovalStatus` the
  strategy's risk record must hold before this edge can fire.
  ``None`` means "no record check at this edge". The promotion gate
  layered above still does its own checks.
* ``requires_evidence`` -- when True, the caller must pass a non-None
  ``record`` so the transition function can verify the approval status.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from aurora.governance.risk_register import ApprovalStatus, StrategyRiskRecord


class LifecycleState(str, Enum):
    """Explicit lifecycle states. Strings are stable on-disk."""

    DRAFT = "draft"
    RESEARCHING = "researching"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    VALIDATED = "validated"
    OOS_APPROVED = "oos_approved"
    SHADOW = "shadow"
    PAPER = "paper"
    CANARY = "canary"
    LIVE = "live"
    DEGRADED = "degraded"
    RETIRED = "retired"
    GRAVEYARD = "graveyard"


class LifecycleError(ValueError):
    """Raised when an illegal lifecycle transition is attempted."""


@dataclass(frozen=True)
class LifecycleTransition:
    """A single legal edge in the lifecycle graph."""

    from_state: LifecycleState
    to_state: LifecycleState
    required_approval: Optional[ApprovalStatus]
    requires_evidence: bool


# ---------------------------------------------------------------------------
# Transition graph
# ---------------------------------------------------------------------------
# Edges are deliberately conservative. Adding new edges requires a code
# change so reviewers can spot them in diff.
_TRANSITIONS: Tuple[LifecycleTransition, ...] = (
    # Research progression.
    LifecycleTransition(LifecycleState.DRAFT, LifecycleState.RESEARCHING, None, False),
    LifecycleTransition(LifecycleState.RESEARCHING, LifecycleState.REJECTED, None, False),
    LifecycleTransition(LifecycleState.RESEARCHING, LifecycleState.QUARANTINED, None, False),
    LifecycleTransition(LifecycleState.QUARANTINED, LifecycleState.RESEARCHING, None, False),
    LifecycleTransition(LifecycleState.RESEARCHING, LifecycleState.VALIDATED, None, False),

    # Pre-deployment.
    LifecycleTransition(LifecycleState.VALIDATED, LifecycleState.OOS_APPROVED, None, False),
    LifecycleTransition(
        LifecycleState.OOS_APPROVED, LifecycleState.SHADOW, ApprovalStatus.REVIEWED, True,
    ),
    LifecycleTransition(
        LifecycleState.SHADOW, LifecycleState.PAPER, ApprovalStatus.RISK_APPROVED, True,
    ),
    LifecycleTransition(
        LifecycleState.PAPER, LifecycleState.CANARY,
        ApprovalStatus.OPERATOR_APPROVED, True,
    ),
    LifecycleTransition(
        LifecycleState.CANARY, LifecycleState.LIVE,
        ApprovalStatus.OPERATOR_APPROVED, True,
    ),

    # Live degradation / decommissioning.
    LifecycleTransition(LifecycleState.LIVE, LifecycleState.DEGRADED, None, False),
    LifecycleTransition(LifecycleState.DEGRADED, LifecycleState.RETIRED, None, False),
    LifecycleTransition(LifecycleState.LIVE, LifecycleState.RETIRED, None, False),
    LifecycleTransition(LifecycleState.RETIRED, LifecycleState.GRAVEYARD, None, False),

    # Allow a degraded strategy to be re-promoted to live only via a
    # CANARY redeploy. Adding DEGRADED -> CANARY directly would skip the
    # canary stage and is intentionally disallowed.
    LifecycleTransition(
        LifecycleState.DEGRADED, LifecycleState.CANARY,
        ApprovalStatus.OPERATOR_APPROVED, True,
    ),
)


_TRANSITION_INDEX = {(t.from_state, t.to_state): t for t in _TRANSITIONS}


def legal_transitions() -> Tuple[LifecycleTransition, ...]:
    """Return the full transition table for inspection / docs."""
    return _TRANSITIONS


def transition(
    current: LifecycleState,
    target: LifecycleState,
    record: Optional[StrategyRiskRecord] = None,
) -> LifecycleState:
    """Validate and return the new state.

    Raises :class:`LifecycleError` if:

    * the ``(current, target)`` edge is not in the graph;
    * the edge requires evidence but ``record`` is ``None``;
    * the record's approval status is below the required level.

    The required-status check uses the rank order
    ``DRAFT < PROPOSED < REVIEWED < RISK_APPROVED < OPERATOR_APPROVED``;
    ``REJECTED`` and ``EXPIRED`` always block.
    """
    edge = _TRANSITION_INDEX.get((current, target))
    if edge is None:
        raise LifecycleError(
            f"illegal lifecycle transition: {current.value} -> {target.value}"
        )
    if edge.requires_evidence and record is None:
        raise LifecycleError(
            f"transition {current.value} -> {target.value} requires a risk record"
        )
    if edge.required_approval is not None:
        if record is None:
            raise LifecycleError(
                f"transition {current.value} -> {target.value} requires approval "
                f">= {edge.required_approval.value} but no record was supplied"
            )
        if not _approval_at_least(record.approval_status, edge.required_approval):
            raise LifecycleError(
                f"transition {current.value} -> {target.value} requires approval "
                f">= {edge.required_approval.value}, got {record.approval_status.value}"
            )
    return target


_APPROVAL_RANK = {
    ApprovalStatus.DRAFT: 0,
    ApprovalStatus.PROPOSED: 1,
    ApprovalStatus.REVIEWED: 2,
    ApprovalStatus.RISK_APPROVED: 3,
    ApprovalStatus.OPERATOR_APPROVED: 4,
}


def _approval_at_least(current: ApprovalStatus, minimum: ApprovalStatus) -> bool:
    """Return True iff ``current`` is at least ``minimum`` on the maker-checker scale.

    ``REJECTED`` and ``EXPIRED`` always return False regardless of
    ``minimum``.
    """
    if current in (ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED):
        return False
    return _APPROVAL_RANK.get(current, -1) >= _APPROVAL_RANK.get(minimum, 999)


__all__ = [
    "LifecycleError",
    "LifecycleState",
    "LifecycleTransition",
    "legal_transitions",
    "transition",
]
