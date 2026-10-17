"""One-shot locked-period evaluation of the pre-registered candidate.

Candidate, benchmark and pass criteria are fixed here before any data from
2021-01-01 onward is seen. The workflow that runs this refuses to run twice.
"""
from __future__ import annotations

import pandas as pd

from aurora.research import multiasset_baselines as mab

CANDIDATE = "blend_aw_vaa"
BENCHMARK = mab.BENCHMARK
COST_BPS = mab.COST_BPS
TARGET_MONTHLY_SORTINO = 2.0
CRITERIA = (
    "monthly Sortino >= 2.0",
    "monthly Sortino above the SPY benchmark",
    "max drawdown smaller in magnitude than the SPY benchmark",
)


def _annual_returns(returns: pd.Series) -> dict[str, float]:
    yearly = (1 + returns).groupby(returns.index.year).prod() - 1
    return {str(y): float(v) for y, v in yearly.items()}


MAX_DATA_AGE_DAYS = 7


def last_complete_month_end(index: pd.DatetimeIndex) -> pd.Timestamp:
    """Last trading day of the last calendar month that ``index`` fully covers."""
    last = index.max()
    if last >= last + pd.offsets.BMonthEnd(0):
        return last
    previous = index[index < last.replace(day=1)]
    return previous.max()


def _drawdown_from_start(returns: pd.Series) -> float:
    """Max drawdown with the equity curve seeded at the starting capital, so a
    loss on the first locked day is counted."""
    equity = pd.concat([pd.Series([1.0]), (1 + returns).cumprod().reset_index(drop=True)])
    return float((equity / equity.cummax() - 1).min())


def check_data_complete(prices: pd.DataFrame, today: pd.Timestamp) -> None:
    if prices.index.max() < mab.LOCKED_START:
        raise ValueError("no locked-period data to evaluate")
    age = (today.normalize() - prices.index.max()).days
    if age > MAX_DATA_AGE_DAYS:
        raise ValueError(f"price data ends {age} days before the run; refusing a partial window")
    locked = prices.loc[mab.LOCKED_START:]
    needed = ["SPY", "TLT", "IEF", "GLD", "DBC", "EFA", "EEM", "AGG", "LQD", "SHY", "CASH"]
    gaps = [a for a in needed if locked[a].isna().any()]
    if gaps:
        raise ValueError(f"missing locked-period prices for {gaps}")


def evaluate_locked(prices: pd.DataFrame, today: pd.Timestamp | None = None) -> dict:
    """Simulate on the full history (signals need pre-2021 data) and report the
    complete calendar months from ``mab.LOCKED_START`` onward only."""
    check_data_complete(prices, pd.Timestamp.today() if today is None else today)
    end = last_complete_month_end(prices.index)
    prices = prices.loc[:end]
    cash = prices["CASH"].pct_change(fill_method=None)
    out: dict = {"candidate": CANDIDATE, "benchmark": BENCHMARK, "cost_bps": COST_BPS,
                 "criteria": list(CRITERIA), "evaluated_through": str(end.date())}
    for name in (CANDIDATE, BENCHMARK):
        weights = mab.target_weights(prices, mab.ALL_STRATEGIES[name])
        returns, _ = mab.simulate(prices, weights, COST_BPS)
        locked = returns.loc[mab.LOCKED_START:]
        out[name] = {**mab.metrics(locked, cash),
                     "max_drawdown": _drawdown_from_start(locked),
                     "annual_returns": _annual_returns(locked)}
    cand, bench = out[CANDIDATE], out[BENCHMARK]
    checks = [
        cand["sortino_monthly"] >= TARGET_MONTHLY_SORTINO,
        cand["sortino_monthly"] > bench["sortino_monthly"],
        abs(cand["max_drawdown"]) < abs(bench["max_drawdown"]),
    ]
    out["checks"] = dict(zip(CRITERIA, checks))
    out["passed"] = all(checks)
    return out
