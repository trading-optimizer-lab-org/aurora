"""Live discipline modes (R135 + R136 + R137 + R138 + R139).

Five distinct primitives that ship safety on the way to live:

- :class:`ShadowMode` (R135) -- run in parallel without sending orders.
- :class:`DryRunMode` (R136) -- full live wrapper with the broker
  call intercepted at the boundary.
- :func:`pre_deploy_freshness_check` (R137) -- assert recent
  validation data.
- :class:`DataQualityMonitor` (R138) -- auto-pause on data gaps /
  stale ticks.
- :class:`LiveAnomalyDetector` (R139) -- alert when realised metrics
  diverge from expected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import numpy as np


# --------------------------------------------------------------------------
# R135 shadow mode
# --------------------------------------------------------------------------


@dataclass
class ShadowMode:
    """Run a strategy in parallel to live without sending orders.

    The shadow runner records the orders the strategy WOULD have
    placed; an operator inspects the journal to confirm the rule
    behaves as expected.
    """

    strategy_id: str
    journal: List[Dict[str, Any]] = field(default_factory=list)

    def record_intended_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        timestamp: datetime,
        rationale: str = "",
    ) -> None:
        self.journal.append({
            "strategy_id": self.strategy_id,
            "symbol": symbol,
            "side": side,
            "quantity": float(quantity),
            "timestamp": timestamp.isoformat(),
            "rationale": rationale,
            "executed": False,
        })

    def diff_against(self, real_orders: List[Dict[str, Any]]) -> Dict[str, int]:
        """Compare shadow journal against the live journal.

        Returns counts: ``shadow_only`` (intended but not placed live),
        ``live_only`` (placed live but not by shadow), ``matched``.
        """
        shadow_keys = {
            (o["symbol"], o["side"], o["timestamp"]) for o in self.journal
        }
        live_keys = {
            (o["symbol"], o["side"], o["timestamp"]) for o in real_orders
        }
        return {
            "shadow_only": len(shadow_keys - live_keys),
            "live_only": len(live_keys - shadow_keys),
            "matched": len(shadow_keys & live_keys),
        }


# --------------------------------------------------------------------------
# R136 dry-run mode
# --------------------------------------------------------------------------


@dataclass
class DryRunMode:
    """Full live wrapper invocation with broker calls intercepted.

    The broker boundary is replaced by ``record_call``: every order
    submission is logged + dropped instead of executed. Used to verify
    triple-gate, kill switch, audit chain, rate-limiter.
    """

    journal: List[Dict[str, Any]] = field(default_factory=list)

    def record_call(self, name: str, **kwargs: Any) -> Dict[str, Any]:
        entry = {
            "name": name,
            "timestamp": datetime.utcnow().isoformat(),
            "kwargs": dict(kwargs),
            "intercepted": True,
        }
        self.journal.append(entry)
        return entry

    def assert_gate_fired(self, name: str) -> bool:
        return any(e["name"] == name for e in self.journal)


# --------------------------------------------------------------------------
# R137 pre-deploy freshness check
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FreshnessCheckResult:
    fresh: bool
    last_validation_date: Optional[date]
    age_days: Optional[int]
    reason: str = ""


def pre_deploy_freshness_check(
    last_validation_date: Optional[date],
    *,
    max_age_days: int = 14,
    today: Optional[date] = None,
) -> FreshnessCheckResult:
    today = today or date.today()
    if last_validation_date is None:
        return FreshnessCheckResult(
            fresh=False, last_validation_date=None, age_days=None,
            reason="no validation marker found",
        )
    age = (today - last_validation_date).days
    if age > max_age_days:
        return FreshnessCheckResult(
            fresh=False,
            last_validation_date=last_validation_date,
            age_days=age,
            reason=f"validation marker is {age}d old > {max_age_days}d",
        )
    return FreshnessCheckResult(
        fresh=True,
        last_validation_date=last_validation_date,
        age_days=age,
        reason="ok",
    )


# --------------------------------------------------------------------------
# R138 data quality monitor
# --------------------------------------------------------------------------


@dataclass
class DataQualityMonitor:
    """Track per-symbol data feed health and flag pause conditions."""

    max_gap_seconds: float = 300.0
    repeated_bar_threshold: int = 5
    last_seen: Dict[str, datetime] = field(default_factory=dict)
    last_price: Dict[str, float] = field(default_factory=dict)
    repeat_count: Dict[str, int] = field(default_factory=dict)

    def observe(self, symbol: str, timestamp: datetime, price: float) -> Optional[str]:
        """Record a bar; return a problem reason or None."""
        problem: Optional[str] = None
        prev_ts = self.last_seen.get(symbol)
        if prev_ts is not None:
            gap = (timestamp - prev_ts).total_seconds()
            if gap > self.max_gap_seconds:
                problem = f"gap of {gap:.0f}s (limit {self.max_gap_seconds}s)"
        if self.last_price.get(symbol) == price:
            self.repeat_count[symbol] = self.repeat_count.get(symbol, 0) + 1
            if self.repeat_count[symbol] >= self.repeated_bar_threshold:
                problem = problem or (
                    f"repeated price {price} for {self.repeat_count[symbol]} bars"
                )
        else:
            self.repeat_count[symbol] = 0
        self.last_seen[symbol] = timestamp
        self.last_price[symbol] = price
        return problem


# --------------------------------------------------------------------------
# R139 live anomaly detector
# --------------------------------------------------------------------------


@dataclass
class LiveAnomalyDetector:
    """Compare rolling realised metrics against expected bands.

    Operator-supplied expected bands come from the backtest baseline
    plus the R104 bootstrap CI.
    """

    expected_sharpe_low: float
    expected_sharpe_high: float
    expected_win_rate_low: float
    expected_win_rate_high: float

    def evaluate(
        self,
        *,
        realised_sharpe: float,
        realised_win_rate: float,
    ) -> Optional[str]:
        if not (self.expected_sharpe_low <= realised_sharpe <= self.expected_sharpe_high):
            return (
                f"realised sharpe {realised_sharpe:.3f} outside band "
                f"[{self.expected_sharpe_low:.3f}, {self.expected_sharpe_high:.3f}]"
            )
        if not (self.expected_win_rate_low <= realised_win_rate <= self.expected_win_rate_high):
            return (
                f"realised win-rate {realised_win_rate:.3f} outside band "
                f"[{self.expected_win_rate_low:.3f}, {self.expected_win_rate_high:.3f}]"
            )
        return None


__all__ = [
    "ShadowMode",
    "DryRunMode",
    "FreshnessCheckResult",
    "pre_deploy_freshness_check",
    "DataQualityMonitor",
    "LiveAnomalyDetector",
]
