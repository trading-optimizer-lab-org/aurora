"""Vectorized triage backend for QuantForge.

Triage is a fast screening layer for thousands of strategy variants.
It is **not** a substitute for the official engine: anything that
passes triage thresholds gets re-run on
:func:`quantforge.core.engine.run_backtest` (or whatever the caller
passes as ``official_runner``) under full QuantForge ceremony --
costs, slippage, snapshots, OOSGuard, protocol enforcement.

Public API::

    from aurora.triage import (
        TriageEngine, TriageResult, TriageBatch, TriageConfig,
        StrategyVariant, variant_grid, variant_random_sample,
    )

Hard guarantees:

* The engine refuses to operate on data crossing the OOS_LOCKED or
  FORWARD tier boundaries (read directly from the active
  :class:`~quantforge.core.protocol_policy.ProtocolPolicy`).
* ``TriageResult.promising`` means *eligible to re-run on the official
  engine*, never *promotable*. Promotion is single-use through
  :meth:`TriageEngine.promote_to_official`.
"""
from aurora.triage.engine import (
    TriageBatch,
    TriageConfig,
    TriageEngine,
    TriageResult,
)
from aurora.triage.variants import (
    StrategyVariant,
    variant_grid,
    variant_random_sample,
)

__all__ = [
    "StrategyVariant",
    "TriageBatch",
    "TriageConfig",
    "TriageEngine",
    "TriageResult",
    "variant_grid",
    "variant_random_sample",
]
