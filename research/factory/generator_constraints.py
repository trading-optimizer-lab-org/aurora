"""Generator pre-acceptance constraints (R111).

Filter generated candidates on cheap pre-acceptance metrics before
they enter the validation pipeline. Avoids burning compute on
candidates that will obviously fail downstream.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PreAcceptanceConstraints:
    """Bounds applied to a candidate's quick-look metrics."""

    max_trades_per_day: Optional[float] = None
    target_mdd_min: Optional[float] = None  # most-negative acceptable MDD
    target_mdd_max: Optional[float] = None  # least-negative acceptable MDD
    target_win_rate_min: Optional[float] = None
    target_win_rate_max: Optional[float] = None
    max_turnover: Optional[float] = None


@dataclass(frozen=True)
class PreAcceptanceVerdict:
    """Outcome of applying constraints."""

    passed: bool
    reasons: list[str]


def evaluate(
    *,
    trades_per_day: float,
    mdd: float,
    win_rate: float,
    turnover: float,
    constraints: PreAcceptanceConstraints,
) -> PreAcceptanceVerdict:
    """Apply ``constraints`` to a candidate's quick-look metrics."""
    reasons: list[str] = []
    c = constraints
    if c.max_trades_per_day is not None and trades_per_day > c.max_trades_per_day:
        reasons.append(f"trades/day={trades_per_day:.2f} > {c.max_trades_per_day}")
    if c.target_mdd_min is not None and mdd < c.target_mdd_min:
        reasons.append(f"mdd={mdd:.4f} < target_min={c.target_mdd_min}")
    if c.target_mdd_max is not None and mdd > c.target_mdd_max:
        reasons.append(f"mdd={mdd:.4f} > target_max={c.target_mdd_max}")
    if c.target_win_rate_min is not None and win_rate < c.target_win_rate_min:
        reasons.append(f"win_rate={win_rate:.3f} < {c.target_win_rate_min}")
    if c.target_win_rate_max is not None and win_rate > c.target_win_rate_max:
        reasons.append(f"win_rate={win_rate:.3f} > {c.target_win_rate_max}")
    if c.max_turnover is not None and turnover > c.max_turnover:
        reasons.append(f"turnover={turnover:.2f} > {c.max_turnover}")
    return PreAcceptanceVerdict(passed=not reasons, reasons=reasons)


__all__ = [
    "PreAcceptanceConstraints",
    "PreAcceptanceVerdict",
    "evaluate",
]
