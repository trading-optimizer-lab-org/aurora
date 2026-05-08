"""Corporate-action correctness audit (R150).

Test fixture set covering splits, dividends, mergers, spinoffs,
ticker changes. The functions here verify that price + position
adjustments match expected behaviour after the action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, List, Optional


class ActionKind(str, Enum):
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    DIVIDEND_CASH = "dividend_cash"
    DIVIDEND_STOCK = "dividend_stock"
    MERGER = "merger"
    SPINOFF = "spinoff"
    TICKER_CHANGE = "ticker_change"


@dataclass(frozen=True)
class CorporateAction:
    """Frozen description of one corporate action."""

    ticker: str
    when: date
    kind: ActionKind
    ratio: float = 1.0  # split / reverse-split ratio (e.g. 2.0 for 2-for-1)
    cash_amount: float = 0.0  # for cash dividends
    new_ticker: Optional[str] = None  # for ticker changes / mergers


@dataclass(frozen=True)
class AdjustmentVerdict:
    """Did the post-action price + position match expectation?"""

    ticker: str
    when: date
    kind: ActionKind
    price_correct: bool
    position_correct: bool
    detail: str = ""


def expected_post_split_price(pre_price: float, ratio: float) -> float:
    if ratio <= 0:
        raise ValueError("split ratio must be > 0")
    return pre_price / ratio


def expected_post_split_position(pre_position: float, ratio: float) -> float:
    return pre_position * ratio


def verify_split(
    action: CorporateAction,
    pre_price: float,
    pre_position: float,
    post_price: float,
    post_position: float,
    *,
    tol: float = 1e-6,
) -> AdjustmentVerdict:
    """Verify a split was applied correctly to price + position."""
    expected_p = expected_post_split_price(pre_price, action.ratio)
    expected_pos = expected_post_split_position(pre_position, action.ratio)
    p_ok = abs(post_price - expected_p) <= tol * max(1.0, abs(expected_p))
    pos_ok = abs(post_position - expected_pos) <= tol * max(1.0, abs(expected_pos))
    detail = ""
    if not p_ok:
        detail += f"price expected {expected_p}, got {post_price}; "
    if not pos_ok:
        detail += f"position expected {expected_pos}, got {post_position}; "
    return AdjustmentVerdict(
        ticker=action.ticker, when=action.when, kind=action.kind,
        price_correct=p_ok, position_correct=pos_ok, detail=detail.strip(),
    )


def verify_cash_dividend(
    action: CorporateAction,
    pre_price: float,
    pre_position: float,
    post_price: float,
    cash_balance_delta: float,
    *,
    tol: float = 1e-6,
) -> AdjustmentVerdict:
    """Verify a cash dividend: price drops by amount, cash receives amount * position."""
    expected_p = pre_price - action.cash_amount
    expected_cash = action.cash_amount * pre_position
    p_ok = abs(post_price - expected_p) <= tol * max(1.0, abs(expected_p))
    cash_ok = abs(cash_balance_delta - expected_cash) <= tol * max(1.0, abs(expected_cash))
    detail = ""
    if not p_ok:
        detail += f"price expected {expected_p}, got {post_price}; "
    if not cash_ok:
        detail += f"cash delta expected {expected_cash}, got {cash_balance_delta}; "
    return AdjustmentVerdict(
        ticker=action.ticker, when=action.when, kind=action.kind,
        price_correct=p_ok, position_correct=cash_ok, detail=detail.strip(),
    )


__all__ = [
    "ActionKind",
    "CorporateAction",
    "AdjustmentVerdict",
    "expected_post_split_price",
    "expected_post_split_position",
    "verify_split",
    "verify_cash_dividend",
]
