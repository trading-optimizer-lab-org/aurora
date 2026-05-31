"""ResearchFactory -- automated hypothesis -> review-queue pipeline.

The factory accepts a :class:`StrategySpec`, runs it through IS / WF /
OOS_DEV gates, and either promotes it to the review queue (for human
sign-off) or archives it with a categorical
:class:`~aurora.research.factory.outcomes.RejectionReason`.

Hard guarantees
---------------
* No path inside the factory ever touches the OOS_LOCKED or FORWARD
  tiers. All data reads go through
  :func:`aurora.core.data_tiers.load_up_to_tier` capped at
  ``OOS_DEV`` so even a malformed spec cannot leak the lockbox.
* Every candidate -- promoted or archived -- is appended to a JSONL
  archive (or review queue) via atomic file appends so concurrent
  submitters never interleave bytes.
* Every submission is logged in the
  :class:`~aurora.registry.experiments.ExperimentTracker`, which
  this module aliases as the "ExperimentRegistry" for naming
  consistency with the parent task spec.
* The optional auditor injection point uses a duck-typed protocol so
  the factory does not import any P1.B code at module load time.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd

from aurora.core.protocol_policy import ProtocolPolicy
from aurora.research.factory.factory._config import ResearchPipelineConfig
from aurora.research.factory.factory._helpers import (
    _atomic_jsonl_append,
    _AuditorProtocol,
    _default_backtest,
    _default_walk_forward,
    _FILE_LOCK,
    _import_path,
    _read_jsonl,
)
from aurora.research.factory.factory._ingest import _IngestMixin
from aurora.research.factory.factory._promote import _PromoteMixin
from aurora.research.factory.factory._triage import _TriageMixin
from aurora.research.factory.factory._validate import _ValidateMixin


class ResearchFactory(_IngestMixin, _ValidateMixin, _TriageMixin, _PromoteMixin):
    """Hypothesis -> review-queue automation pipeline.

    Constructor injects the only dependencies the factory needs from the
    rest of the system: a :class:`ProtocolPolicy`, the experiment registry
    (an :class:`~aurora.registry.experiments.ExperimentTracker`), and
    optionally an auditor. Tests can pass a fake auditor and a custom
    ``backtest_fn`` / ``walk_forward_fn`` to keep the factory unit
    independent of the engine.
    """

    # Class-level guard: data loads inside ``submit`` MUST cap at OOS_DEV.
    # Any code path requesting OOS_LOCKED or FORWARD must raise immediately.
    _MAX_TIER: str = "OOS_DEV"

    def __init__(
        self,
        config: ResearchPipelineConfig,
        policy: ProtocolPolicy,
        registry: Any,  # ExperimentTracker (a.k.a. ExperimentRegistry)
        auditor: Optional[_AuditorProtocol] = None,
        *,
        backtest_fn: Optional[Callable[..., dict]] = None,
        walk_forward_fn: Optional[Callable[..., dict]] = None,
        data_loader: Optional[Callable[..., pd.Series]] = None,
        triage_engine: Any = None,  # aurora.triage.TriageEngine
    ) -> None:
        self.config = config
        self.policy = policy
        self.registry = registry
        self.auditor = auditor
        self._backtest_fn = backtest_fn or _default_backtest
        self._walk_forward_fn = walk_forward_fn or _default_walk_forward
        self._data_loader = data_loader or self._default_data_loader
        # P2.A: optional triage engine for bulk pre-screening. Accepts any
        # object exposing a ``triage_batch`` method so tests can inject a
        # stub without importing the real engine.
        self.triage_engine = triage_engine


__all__ = [
    "ResearchFactory",
    "ResearchPipelineConfig",
]
