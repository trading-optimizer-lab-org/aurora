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


def evaluate_locked(prices: pd.DataFrame) -> dict:
    """Simulate on the full history (signals need pre-2021 data) and report the
    period from ``mab.LOCKED_START`` onward only."""
    if prices.index.max() < mab.LOCKED_START:
        raise ValueError("no locked-period data to evaluate")
    cash = prices["CASH"].pct_change(fill_method=None)
    out: dict = {"candidate": CANDIDATE, "benchmark": BENCHMARK, "cost_bps": COST_BPS,
                 "criteria": list(CRITERIA)}
    for name in (CANDIDATE, BENCHMARK):
        weights = mab.target_weights(prices, mab.ALL_STRATEGIES[name])
        returns, _ = mab.simulate(prices, weights, COST_BPS)
        locked = returns.loc[mab.LOCKED_START:]
        out[name] = {**mab.metrics(locked, cash), "annual_returns": _annual_returns(locked)}
    cand, bench = out[CANDIDATE], out[BENCHMARK]
    checks = [
        cand["sortino_monthly"] >= TARGET_MONTHLY_SORTINO,
        cand["sortino_monthly"] > bench["sortino_monthly"],
        abs(cand["max_drawdown"]) < abs(bench["max_drawdown"]),
    ]
    out["checks"] = dict(zip(CRITERIA, checks))
    out["passed"] = all(checks)
    return out
