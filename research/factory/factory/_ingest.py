"""Ingest phase: data loading + experiment registry hooks + dedup check.

Module-private mixin. Public API stays at
``aurora.research.factory.factory``.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional, TYPE_CHECKING

import pandas as pd

from aurora.research.factory.factory._helpers import _read_jsonl
from aurora.research.factory.spec import StrategySpec

if TYPE_CHECKING:
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.research.factory.factory._config import ResearchPipelineConfig
    from aurora.research.factory.factory._helpers import _AuditorProtocol

_log = logging.getLogger(__name__)


class _IngestMixin:
    """Data-loading and registry plumbing for the factory."""

    # Attribute declarations so mypy knows these are populated by
    # :class:`ResearchFactory.__init__`.
    config: "ResearchPipelineConfig"
    policy: "ProtocolPolicy"
    registry: Any
    auditor: Optional["_AuditorProtocol"]
    _backtest_fn: Callable[..., dict]
    _walk_forward_fn: Callable[..., dict]
    _data_loader: Callable[..., pd.Series]
    triage_engine: Any
    _MAX_TIER: str

    # ------------------------------------------------------------------
    # data loading -- one place that enforces the OOS_DEV ceiling
    # ------------------------------------------------------------------

    def _default_data_loader(
        self,
        symbol: str,
        max_tier: str = "OOS_DEV",
    ) -> pd.Series:
        """Default loader: ``load_up_to_tier`` capped at OOS_DEV.

        Hard guards against any caller that tries to bypass the ceiling.
        """
        norm = (max_tier or "OOS_DEV").upper()
        if norm not in ("IS_TRAIN", "IS_VALID", "OOS_DEV"):
            raise RuntimeError(
                f"ResearchFactory refuses to load tier {max_tier!r}; "
                "the factory is hard-capped at OOS_DEV. "
                "Use the lockbox ceremony in `forge research promote`."
            )
        from aurora.core.data_tiers import load_up_to_tier
        return load_up_to_tier(symbol, max_tier=norm, source="yfinance")

    def _is_duplicate(self, spec_hash: str) -> bool:
        """True iff ``spec_hash`` appears in the review queue OR archive."""
        for path in (
            self.config.review_queue_path,
            self.config.archive_path,
        ):
            for d in _read_jsonl(path):
                spec = (d.get("spec") or {})
                if spec.get("spec_hash") == spec_hash:
                    return True
        return False

    def _load_full_window(self, spec: StrategySpec) -> pd.Series:
        """Load the OOS_DEV-capped price window for the spec's first symbol.

        The factory currently runs single-asset backtests; multi-asset
        support is a layer above (the universe is preserved on the spec
        but the default backtest runs on ``universe[0]``). This is a
        deliberate scope limit -- the factory's invariants (no OOS_LOCKED)
        do not change for multi-asset, but the engine plumbing does.
        """
        if not spec.universe:
            raise RuntimeError("spec.universe is empty; nothing to backtest")
        symbol = spec.universe[0]
        return self._data_loader(symbol, max_tier=self._MAX_TIER)

    def _open_experiment(self, spec: StrategySpec) -> Optional[str]:
        """Open an experiment in the registry; tolerates a None registry."""
        if self.registry is None:
            return None
        try:
            return self.registry.start_experiment(
                name=f"factory:{spec.name}",
                optimizer="research_factory",
                strategy_class=spec.strategy_class,
                asset=(spec.universe[0] if spec.universe else "UNKNOWN"),
                period_start="IS_TRAIN_START",
                period_end="OOS_DEV_END",
                config={
                    "spec_id": spec.spec_id,
                    "spec_hash": spec.spec_hash,
                    "policy_hash": spec.policy_hash,
                    "params": spec.params,
                    "rebalance": spec.rebalance,
                    "generator": spec.generator,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            _log.debug("start_experiment failed: %s", exc)
            return None

    def _close_experiment(
        self,
        experiment_id: Optional[str],
        *,
        success: bool,
        score: Optional[float] = None,
        notes: str = "",
    ) -> None:
        if experiment_id is None or self.registry is None:
            return
        try:
            self.registry.finish_experiment(
                experiment_id,
                best_score=score,
                notes=notes,
                status="completed" if success else "failed",
            )
        except Exception as exc:  # pragma: no cover - defensive
            _log.debug("finish_experiment failed: %s", exc)
