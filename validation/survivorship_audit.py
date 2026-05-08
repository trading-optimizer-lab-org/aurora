"""Survivorship-bias audit per backtest (R149).

For every backtest, assert the universe at time T was actually
tradeable then (not selected post-hoc from current S&P 500). Pairs
with R134 (universe rebalance gate).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class SurvivorshipFinding:
    """One ticker / date pair where survivorship-bias was detected."""

    ticker: str
    backtest_date: date
    reason: str  # "not_listed_yet" | "delisted" | "renamed"


def audit_survivorship(
    *,
    backtest_universe: Set[str],
    backtest_window: Tuple[date, date],
    historical_listings: Dict[str, Tuple[date, Optional[date]]],
) -> List[SurvivorshipFinding]:
    """Compare backtest universe against historical listing data.

    Args:
        backtest_universe: tickers used in the backtest.
        backtest_window: (start_date, end_date).
        historical_listings: ``{ticker: (listed_date, delisted_date_or_None)}``.

    Returns:
        Findings for tickers whose listing window did not cover the
        whole backtest window.
    """
    start, end = backtest_window
    findings: List[SurvivorshipFinding] = []
    for ticker in backtest_universe:
        listing = historical_listings.get(ticker)
        if listing is None:
            findings.append(SurvivorshipFinding(
                ticker=ticker, backtest_date=start,
                reason="no_listing_data",
            ))
            continue
        listed, delisted = listing
        if listed > start:
            findings.append(SurvivorshipFinding(
                ticker=ticker, backtest_date=start,
                reason="not_listed_yet",
            ))
        if delisted is not None and delisted < end:
            findings.append(SurvivorshipFinding(
                ticker=ticker, backtest_date=delisted,
                reason="delisted",
            ))
    return findings


__all__ = ["SurvivorshipFinding", "audit_survivorship"]
