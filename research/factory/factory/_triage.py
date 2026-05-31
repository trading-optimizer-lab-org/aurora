"""Triage phase: bulk pre-screening of specs before the full pipeline.

Module-private mixin. Public API stays at
``aurora.research.factory.factory``.
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Iterable, Optional, TYPE_CHECKING

import pandas as pd

from aurora.research.factory.outcomes import (
    RejectionReason,
    ResearchOutcome,
    ResearchStage,
)
from aurora.research.factory.spec import StrategySpec

if TYPE_CHECKING:
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.research.factory.factory._config import ResearchPipelineConfig
    from aurora.research.factory.factory._helpers import _AuditorProtocol


class _TriageMixin:
    """Bulk submission helpers."""

    # Attribute declarations so mypy can resolve attribute access.
    config: "ResearchPipelineConfig"
    policy: "ProtocolPolicy"
    registry: Any
    auditor: Optional["_AuditorProtocol"]
    _backtest_fn: Callable[..., dict]
    _walk_forward_fn: Callable[..., dict]
    _data_loader: Callable[..., pd.Series]
    triage_engine: Any
    _MAX_TIER: str

    if TYPE_CHECKING:
        # Method signatures provided by sibling mixins. Declared here so
        # mypy can resolve cross-mixin attribute access without runtime
        # impact.
        def submit(self, spec: StrategySpec) -> ResearchOutcome: ...
        def _archive(
            self,
            *,
            candidate_id: str,
            spec: StrategySpec,
            stage: ResearchStage,
            rejection: RejectionReason,
            detail: str,
            started_at: pd.Timestamp,
            t0: float,
            is_metrics: Optional[dict] = None,
            wf_metrics: Optional[dict] = None,
            oos_dev_metrics: Optional[dict] = None,
            auditor_report_hash: Optional[str] = None,
            experiment_id: Optional[str] = None,
        ) -> ResearchOutcome: ...

    def submit_with_triage(
        self,
        specs: Iterable[StrategySpec],
        *,
        prices: Optional[pd.DataFrame] = None,
    ) -> list[ResearchOutcome]:
        """Pre-screen specs through the triage engine before the full pipeline.

        When :attr:`triage_engine` is None, this method falls back to
        :meth:`submit_batch` (no pre-screening). Otherwise, it converts
        each spec to a :class:`~aurora.triage.variants.StrategyVariant`,
        runs them through the triage engine in a single batch, and only
        passes the *promising* hits to the full IS / WF / OOS_DEV
        pipeline. Triage hits that fail the simple thresholds are
        archived with :data:`RejectionReason.IS_SHARPE_TOO_LOW` (the
        most-common triage failure mode) so the existing CLI list
        commands work unchanged.

        Triage results are NEVER promotable on their own; this method
        only uses the triage layer as a *filter*, never as a verdict.

        Args:
            specs: iterable of :class:`StrategySpec` proposals.
            prices: optional DataFrame fed straight to the triage engine.
                When None, the factory uses its data loader on the
                first symbol of each spec to assemble a univariate
                DataFrame. The ``triage_tier_only`` setting on the
                triage engine is honored.

        Returns:
            List of :class:`ResearchOutcome` aligned with the input
            specs. Triage-rejected specs return an archived outcome with
            :data:`RejectionReason.IS_SHARPE_TOO_LOW`.
        """
        specs = list(specs)
        if self.triage_engine is None or not specs:
            return [self.submit(s) for s in specs]
        # Build variants from specs.
        from aurora.triage.variants import StrategyVariant
        variants = [
            StrategyVariant.make(
                strategy_class=s.strategy_class,
                params=s.params,
                universe=s.universe,
                rebalance=s.rebalance,
            )
            for s in specs
        ]
        # Resolve prices via the engine's first universe entry if not given.
        if prices is None:
            symbol = specs[0].universe[0] if specs[0].universe else "SPY"
            tier = getattr(
                self.triage_engine.config, "triage_tier_only", "IS_TRAIN"
            )
            from aurora.core.data_tiers import load_tier
            ser = load_tier(symbol, tier=tier)
            prices = ser.to_frame(name=symbol)
        triage_batch = self.triage_engine.triage_batch(prices, variants)
        # Index per variant_id for quick lookup.
        by_id = {r.variant_id: r for r in triage_batch.results}
        outcomes: list[ResearchOutcome] = []
        for spec, variant in zip(specs, variants):
            tr = by_id.get(variant.variant_id)
            if tr is not None and tr.promising:
                outcomes.append(self.submit(spec))
            else:
                started = pd.Timestamp.utcnow().tz_localize(None)
                t0 = time.perf_counter()
                detail = (
                    f"triage rejected: {tr.rejection_reason}"
                    if tr is not None
                    else "triage failed to score variant"
                )
                outcomes.append(self._archive(
                    candidate_id=uuid.uuid4().hex[:12],
                    spec=spec.with_policy_hash(self.policy.policy_hash),
                    stage=ResearchStage.PROPOSED,
                    rejection=RejectionReason.IS_SHARPE_TOO_LOW,
                    detail=detail,
                    started_at=started,
                    t0=t0,
                ))
        return outcomes

    def submit_batch(self, specs: Iterable[StrategySpec]) -> list[ResearchOutcome]:
        """Submit many specs.

        Uses ``self.config.parallel_workers`` workers via
        ``concurrent.futures.ThreadPoolExecutor`` when > 1. Threads are
        safe here because the factory's data load and JSONL appends are
        explicitly serialized (``_FILE_LOCK``); the strategy backtest
        itself releases the GIL only sporadically, so the speedup is
        modest but the API matches what callers expect.
        """
        specs = list(specs)
        if self.config.parallel_workers <= 1 or len(specs) <= 1:
            return [self.submit(s) for s in specs]
        with ThreadPoolExecutor(max_workers=self.config.parallel_workers) as ex:
            return list(ex.map(self.submit, specs))
