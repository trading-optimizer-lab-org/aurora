"""Corporate-action records and adjustment verifiers.

A :class:`CorporateActionRecord` describes a single action affecting an
instrument: split / reverse split, cash dividend, special dividend,
merger, spin-off, symbol change, etc. The verifiers in this module check
whether prices around the action have been adjusted in a way that is
*consistent* with the action -- they do NOT recompute the adjustment.

They return a small descriptor with a boolean ``passed`` flag plus a
human-readable reason so the caller (validator, factory, audit pipeline)
can record the decision. Tolerances are configurable so the verifiers
work both for clean vendor data and for slightly messier broker fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_type
from typing import Optional, Sequence


# Action types we know how to reason about. Other values are accepted
# (round-tripping through the validator may still record them) but the
# verifiers below only treat these explicitly.
KNOWN_ACTION_TYPES = (
    "split",
    "reverse_split",
    "cash_dividend",
    "special_dividend",
    "merger",
    "spin_off",
    "symbol_change",
    "delisting",
    "suspension",
    "adr_ratio_change",
)


@dataclass(frozen=True)
class CorporateActionRecord:
    """One corporate action affecting one instrument.

    Attributes:
        symbol: internal symbol from the Security Master.
        action_type: one of :data:`KNOWN_ACTION_TYPES` (other values are
            tolerated but verifiers treat them as no-ops).
        effective_date: action effective date.
        factor: split factor (e.g. ``2.0`` for a 2-for-1 split,
            ``0.5`` for a 1-for-2 reverse split). ``None`` for
            non-split actions.
        cash_amount: cash distributed per share (e.g. dividend). ``None``
            for non-cash actions.
    """

    symbol: str
    action_type: str
    effective_date: _date_type
    factor: Optional[float] = None
    cash_amount: Optional[float] = None


@dataclass(frozen=True)
class AdjustmentCheck:
    """Result of running a verifier against a price window."""

    passed: bool
    reason: str = ""


def verify_split_adjustment(
    prices_before: Sequence[float],
    prices_after: Sequence[float],
    action: CorporateActionRecord,
    *,
    tolerance: float = 0.01,
) -> AdjustmentCheck:
    """Verify a split was applied consistently.

    A split with factor ``f`` divides per-share prices by ``f`` going
    forward (e.g. a 2-for-1 split halves prices). If the data is
    *unadjusted*, the bar-to-bar move on the effective date will look
    like a dramatic jump. If the data is *adjusted*, the historical
    prices were already pre-divided so the level should line up.

    The check compares the last pre-action price against the first
    post-action price. ``passed=True`` means the ratio is consistent
    with the recorded factor within ``tolerance`` (relative).
    """
    if action.action_type not in {"split", "reverse_split"}:
        return AdjustmentCheck(False, f"action_type {action.action_type!r} is not a split")
    if action.factor is None or action.factor <= 0:
        return AdjustmentCheck(False, "split factor must be a positive float")
    if not prices_before or not prices_after:
        return AdjustmentCheck(False, "need at least one price on each side")

    last_before = float(prices_before[-1])
    first_after = float(prices_after[0])
    if last_before <= 0 or first_after <= 0:
        return AdjustmentCheck(False, "non-positive prices around action")

    expected_after = last_before / action.factor
    rel_err = abs(first_after - expected_after) / max(expected_after, 1e-12)
    if rel_err <= tolerance:
        return AdjustmentCheck(
            True,
            f"split adjustment consistent: ratio {first_after / last_before:.6f} "
            f"matches 1/factor={1.0 / action.factor:.6f} (rel_err={rel_err:.4f})",
        )
    return AdjustmentCheck(
        False,
        f"split adjustment inconsistent: first_after={first_after:.6f} vs "
        f"expected={expected_after:.6f} (rel_err={rel_err:.4f})",
    )


def verify_dividend_adjustment(
    prices_before: Sequence[float],
    prices_after: Sequence[float],
    action: CorporateActionRecord,
    *,
    tolerance: float = 0.05,
) -> AdjustmentCheck:
    """Verify a cash-dividend adjustment is consistent.

    Cash dividends drop the price by approximately the cash amount on
    the ex-date. The check compares ``last_before - first_after`` to
    the recorded ``cash_amount`` within ``tolerance`` (relative to the
    pre-action price level).
    """
    if action.action_type not in {"cash_dividend", "special_dividend"}:
        return AdjustmentCheck(
            False, f"action_type {action.action_type!r} is not a dividend"
        )
    if action.cash_amount is None or action.cash_amount <= 0:
        return AdjustmentCheck(False, "cash_amount must be a positive float")
    if not prices_before or not prices_after:
        return AdjustmentCheck(False, "need at least one price on each side")

    last_before = float(prices_before[-1])
    first_after = float(prices_after[0])
    if last_before <= 0 or first_after <= 0:
        return AdjustmentCheck(False, "non-positive prices around action")

    drop = last_before - first_after
    expected_drop = float(action.cash_amount)
    rel_err = abs(drop - expected_drop) / max(last_before, 1e-12)
    if rel_err <= tolerance:
        return AdjustmentCheck(
            True,
            f"dividend adjustment consistent: drop={drop:.6f} vs "
            f"cash_amount={expected_drop:.6f} (rel_err={rel_err:.4f})",
        )
    return AdjustmentCheck(
        False,
        f"dividend adjustment inconsistent: drop={drop:.6f} vs "
        f"cash_amount={expected_drop:.6f} (rel_err={rel_err:.4f})",
    )


__all__ = [
    "AdjustmentCheck",
    "CorporateActionRecord",
    "KNOWN_ACTION_TYPES",
    "verify_dividend_adjustment",
    "verify_split_adjustment",
]
